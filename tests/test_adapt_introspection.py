"""Offline tests for ``wsbench.adapt.introspection`` (plan 0060 Phase E): the subject's renders,
the job, the measure loop on a fake engine, the calibration rule, the adapted bank and the read
plan it yields, and the stage plumbing. No GPU, no tokenizer download, no API call."""

import functools
import hashlib
import json
import re
from contextlib import contextmanager

import numpy as np
import pytest

from wsbench import readplan, registry
from wsbench.adapt import __main__ as adapt_main
from wsbench.adapt import families as fams
from wsbench.adapt import introspection as ii
from wsbench.adapt import store, subjects
from wsbench.adapt.subjects import Subject

REAL_GAUSSIAN_ROWS = ii.gaussian_rows  # before the autouse stand-in replaces it

TOKEN = re.compile(r"<\|[a-z_]+\|>|</?think>|\s?[A-Za-z]+|\d+|\s+|.", re.S)


class FakeTok:
    """A ChatML-shaped tokenizer: one token per word / special marker / punctuation mark, with
    character offsets (the subject-render contract ``encode`` relies on)."""

    def __init__(self):
        self.vocab: dict[str, int] = {}
        self.inv: dict[int, str] = {}

    def _id(self, t: str) -> int:
        if t not in self.vocab:
            self.vocab[t] = len(self.vocab) + 1
            self.inv[self.vocab[t]] = t
        return self.vocab[t]

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        ms = list(TOKEN.finditer(text))
        out = {"input_ids": [self._id(m.group()) for m in ms]}
        if return_offsets_mapping:
            out["offset_mapping"] = [m.span() for m in ms]
        return out

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **_):
        s = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
        if add_generation_prompt:
            s += "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        return self(s)["input_ids"] if tokenize else s

    def decode(self, ids, skip_special_tokens=False):
        return "".join(self.inv[i] for i in ids)


@pytest.fixture
def tok():
    return FakeTok()


@pytest.fixture(scope="module")
def bank():
    return ii.registered_bank()  # read once: tests never mutate it (one asserts so)


@pytest.fixture(autouse=True)
def _cached_bank(bank, monkeypatch):
    monkeypatch.setattr(ii, "registered_bank", lambda: bank)


@pytest.fixture(autouse=True)
def _numpy_gaussians(monkeypatch):
    """The recipe's gaussian rows need torch (not in the dev env): ingestion re-draws them with
    the same stand-in the fake results were drawn with."""
    monkeypatch.setattr(ii, "gaussian_rows", _randn)


@pytest.fixture(scope="module")
def subject():
    s = Subject("fake-32l", "org/Fake-32L", "Fake-32L", 32, "fake", "abc123")
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(subjects.SUBJECTS, s.key, s)
        yield s


@pytest.fixture
def adapted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / model)
    return tmp_path


# ---------------------------------------------------------------- renders


def test_protocol_sites_follow_the_source_rules(tok, bank):
    r = ii.protocol_render(tok, bank["prompts"], 3)
    toks = r["tokens"]
    span = "".join(toks[i] for i in r["inject_span"])
    assert span.strip() == bank["prompts"]["protocol"]["trial_turn"].format(trial=3)
    assert toks[r["echo"][0]] == "," and r["echo"][0] in r["inject_span"]
    assert r["grid"] == list(range(r["inject_span"][-1] + 1, r["n_tokens"]))
    assert r["null"] == [r["inject_span"][0] - 2, r["inject_span"][0] - 1]
    assert r["lite"] == [r["n_tokens"] - 1] and toks[-1] == '"'
    assert r["tokens"][r["grid"][0]] == "<|im_end|>"


def test_neutral_sites_and_lite(tok, bank):
    prompt = bank["prompts"]["neutral"]["meeting_note"]
    r = ii.neutral_render(tok, prompt)
    assert "".join(r["tokens"][i] for i in r["inject_span"]).strip() == prompt
    assert r["echo"] == [r["inject_span"][-1]]
    # the ChatML-shaped fake has Qwen's 9-token tail: <|im_end|> \n <|im_start|> ... \n\n
    assert len(r["grid"]) == 9 and r["lite"] == [r["grid"][1]]
    assert r["tokens"][r["lite"][0]] == "\n"


def test_registered_renders_check(tok, bank):
    renders = ii.subject_renders(tok, bank)
    assert set(renders) == set(bank["renders"])
    fake = {**bank, "renders": {k: {s: r[s] for s in ii.SITE_KEYS} for k, r in renders.items()}}
    assert ii.check_against_registered(renders, fake) == []
    fake["renders"]["protocol:trial1"]["grid"] = [0]
    assert ii.check_against_registered(renders, fake) == ["protocol:trial1.grid"]
    # the fake tokenizer is not Qwen's: against the real bank every render differs
    assert ii.check_against_registered(renders, bank)


def test_cont_ids_in_context_and_loose(tok):
    conts, loose = ii.cont_ids(tok, 'about the word "', ["trumpets", "snow"])
    assert loose == 0 and tok.decode(conts["trumpets"]) == "trumpets"

    class Merging(FakeTok):  # a tokenizer that fuses the quote with the word
        def __call__(self, text, **kw):
            return super().__call__(text.replace('"t', "\x00"), **kw)

    m = Merging()
    conts, loose = ii.cont_ids(m, 'word "', ["trumpets"])
    assert loose == 1 and m.decode(conts["trumpets"]) == "trumpets"


# ---------------------------------------------------------------- the job


def test_job_is_the_subjects_own(tok, bank, subject):
    job = ii.build_job(subject.key, tok, bank)
    assert job["inject_layer"] == 6  # the 27B's L12 at the same depth of 32 blocks
    assert len(job["concept_ids"]) == 125 and len(job["baseline_ids"]) == 100
    assert len(job["gaussian_seeds"]) == 500
    seeds = [it["vector"]["seed"] for it in bank["items"] if it["kind"] == "gaussian"]
    assert job["gaussian_seeds"] == seeds
    paper = ii.paper_words(bank)
    assert job["protocol"]["paper_words"] == paper and len(paper) == 50
    assert set(paper) <= set(job["gaussian_row"])
    # the vector render: lowercase word, the subject's template, read at the last token
    ids = job["concept_ids"]["trumpets"]
    assert tok.decode(ids).endswith("Tell me about trumpets<|im_end|>\n<|im_start|>assistant\n"
                                    "<think>\n\n</think>\n\n")  # fmt: skip
    assert tok.decode([job["detect"]["yes"]]) == "Yes" and len(job["detect"]["trials"]) == 8
    assert job["protocol"]["ids"] == job["renders"]["protocol:trial1"]["input_ids"]
    assert set(job["neutral"]) == set(bank["prompts"]["neutral"])
    assert len(job["coherence_words"]) == ii.N_COHERENCE
    json.dumps(job)  # the job ships to Modal as JSON


def test_registered_template_gate_is_the_template_not_the_tokenizer_key(tok, bank, monkeypatch):
    # the qwen3.6 tokenizer key with another template (Qwen3.5 may differ): no exact-match gate
    s = Subject("fake-qwen", "Qwen/Fake", "Fake", 32, "qwen3.6")
    monkeypatch.setitem(subjects.SUBJECTS, s.key, s)
    assert ii.build_job(s.key, tok, bank)["registered_template"] is False
    # the 27B's own render of the protocol, but a site rule that drifted: refused
    fake = {k: {**r, "_text": ""} for k, r in bank["renders"].items()}
    fake["neutral:bike_brake"] = {**fake["neutral:bike_brake"], "lite": [0]}
    monkeypatch.setattr(ii, "subject_renders", lambda t, b: fake)
    with pytest.raises(SystemExit, match="sites differ"):
        ii.build_job(s.key, tok, bank)


def test_unregistered_external_subject_gets_the_runner_guidance(tok, bank, monkeypatch):
    # deepseek-v4-flash is registered since #239; unregister it here so the case still exercises
    # an EXTERNAL subject that has no Subject entry yet
    monkeypatch.delitem(subjects.SUBJECTS, "deepseek-v4-flash", raising=False)
    assert "deepseek-v4-flash" not in subjects.SUBJECTS
    with pytest.raises(SystemExit, match=r"subjects\.py yet.*encode_messages"):
        ii.build_job("deepseek-v4-flash", tok, bank)


class GemmaLikeTok(FakeTok):
    """A non-ChatML template: a template-written BOS, a template-injected system preamble, and a
    tokenizer that fuses a turn's last punctuation mark with the closing marker (one token
    straddling content and template)."""

    PAT = re.compile(r"[.?]<end_of_turn>|<bos>|<[a-z_]+>|\s?[A-Za-z]+|\d+|\s+|.", re.S)

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        ms = list(self.PAT.finditer(text))
        out = {"input_ids": [self._id(m.group()) for m in ms]}
        if return_offsets_mapping:
            out["offset_mapping"] = [m.span() for m in ms]
        return out

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **_):
        s = "<bos><start_of_turn>system\nYou are a helpful model.<end_of_turn>\n"
        for m in messages:
            role = "model" if m["role"] == "assistant" else m["role"]
            s += f"<start_of_turn>{role}\n{m['content']}<end_of_turn>\n"
        if add_generation_prompt:
            s += "<start_of_turn>model\n"
        return self(s)["input_ids"] if tokenize else s


def test_non_chatml_template_sites(bank):
    t = GemmaLikeTok()
    prompt = bank["prompts"]["neutral"]["meeting_note"]
    r = ii.neutral_render(t, prompt)
    toks = r["tokens"]
    assert toks[0] == "<bos>" and 0 not in r["inject_span"] and min(r["null"]) > 0
    # the straddling ".<end_of_turn>" overlaps the content: it is steered (the echo), never read
    assert toks[r["echo"][0]] == ".<end_of_turn>" and r["echo"] == [r["inject_span"][-1]]
    assert "".join(toks[i] for i in r["inject_span"]).startswith("\nWrite")
    assert r["grid"] == list(range(r["inject_span"][-1] + 1, r["n_tokens"]))
    # Gemma-shaped tail: 4 read positions (< the 27B's 9; the bank records it, reads honours it)
    assert [toks[i] for i in r["grid"]] == ["\n", "<start_of_turn>", "model", "\n"]
    assert r["lite"] == [r["grid"][1]]
    p = ii.protocol_render(t, bank["prompts"], 2)
    ptoks = p["tokens"]
    trial = bank["prompts"]["protocol"]["trial_turn"].format(trial=2)
    span = "".join(ptoks[i] for i in p["inject_span"])
    assert trial[:-1] in span and span.endswith("?<end_of_turn>")  # straddle kept in the span
    assert "You are a helpful model" not in span and ptoks[p["echo"][0]] == ","
    assert ptoks[-1] == '"' and p["lite"] == [p["n_tokens"] - 1]


def test_real_qwen36_tokenizer_reproduces_the_registered_renders(bank):
    tf = pytest.importorskip("transformers")
    try:
        t = tf.AutoTokenizer.from_pretrained(bank["model"], local_files_only=True)
    except Exception:  # not cached on this box: never download in a unit test
        pytest.skip(f"{bank['model']} tokenizer not in the local HF cache")
    renders = ii.subject_renders(t, bank)
    assert ii.check_against_registered(renders, bank) == []


def test_zero_layers_refused(tok, bank, monkeypatch):
    s = Subject("fake-0", "Org/Fake", "Fake", 0, "fake")
    monkeypatch.setitem(subjects.SUBJECTS, s.key, s)
    with pytest.raises(SystemExit, match="n_layers"):
        ii.build_job(s.key, tok, bank)


# ---------------------------------------------------------------- measure on a fake engine


class FakeEngine:
    """Concept c's residual is E[c] (+ a constant every baseline word shares), so the subject's
    vector is E[c] exactly. A steer with vector v at dose b scores word w by b * cos(v, E[w]) plus
    a fixed per-word prior; replies degrade at b >= 6; P(Yes) rises with any steer at b >= 2."""

    def __init__(self, job, d=24, seed=0):
        rng = np.random.default_rng(seed)
        self.E = {w: rng.standard_normal(d) for w in job["words"]}
        self.c0 = rng.standard_normal(d)
        self.word_of = {tuple(i): w for w, i in job["concept_ids"].items()}
        self.cont_word = {tuple(c): w for w, c in job["protocol"]["cont_ids"].items()}
        self.prior = {w: float(rng.uniform(0, 3)) for w in job["protocol"]["paper_words"]}
        self.yes, self.no = job["detect"]["yes"], job["detect"]["no"]
        self.cur = None
        self.calls = {"steer": 0}

    def last_hidden(self, ids, layer):
        w = self.word_of.get(tuple(ids))
        return self.c0 + (self.E[w] if w else 0.0)

    @contextmanager
    def steer(self, layer, positions, vector, beta):
        assert layer == 6 and list(positions) == sorted(positions)
        self.calls["steer"] += 1
        self.cur = (np.asarray(vector, float), float(beta))
        try:
            yield
        finally:
            self.cur = None

    def cont_logprobs(self, prefix, conts):
        out = []
        for c in conts:
            w = self.cont_word[tuple(c)]
            s = self.prior[w]
            if self.cur is not None:
                v, b = self.cur
                e = self.E[w]
                s += b * float(v @ e / (np.linalg.norm(v) * np.linalg.norm(e)))
            out.append(s)
        return out

    def next_logprobs(self, ids, token_ids):
        assert token_ids == [self.yes, self.no]
        on = self.cur is not None and self.cur[1] >= 2
        return [np.log(0.9), np.log(0.1)] if on else [np.log(0.1), np.log(0.9)]

    def greedy(self, ids, n):
        return "zzz zzz zzz" if self.cur is not None and self.cur[1] >= 6 else "A fine reply."


def _randn(seeds, d):
    return np.stack([np.random.default_rng(s).standard_normal(d) for s in seeds])


def _rate(prompt, reply):
    return 2.0 if "zzz" in reply else 9.0


@pytest.fixture(scope="module")
def job(bank, subject):
    return ii.build_job(subject.key, FakeTok(), bank)


@pytest.fixture(scope="module")
def result(job):
    return ii.measure(FakeEngine(job), job, randn=_randn, log=lambda s: None)


def test_measure_shapes_and_sweep(job, result):
    assert result["concept"].shape == (125, 24) and result["concept"].dtype == np.float32
    assert result["gaussian"].shape == (500, 24)
    eng = FakeEngine(job)
    np.testing.assert_allclose(result["concept"][0], eng.E["trumpets"], rtol=1e-5)
    sw = result["sweep"]
    assert set(sw["betas"]) == {f"{b:g}" for b in ii.BETA_GRID}
    assert len(sw["beta0"]["rr"]) == 50 and len(sw["beta0"]["top5"]) == 5
    assert all(p < 0.5 for p in sw["beta0"]["p_yes"].values())  # no false alarm at beta 0
    hi = sw["betas"]["8"]
    assert np.median(list(hi["inject"].values())) == 1.0  # the own vector wins at a high dose
    assert np.median(list(hi["cross"].values())) < 0.5
    n = len(job["neutral"]) * (1 + len(ii.BETA_GRID) * ii.N_COHERENCE * 2)
    assert len(sw["neutral"]) == n


def test_result_roundtrip(result):
    back = ii.load_result(ii.save_result(result))
    np.testing.assert_array_equal(back["concept"], result["concept"])
    np.testing.assert_array_equal(back["gaussian"], result["gaussian"].astype(np.float32))
    assert back["sweep"] == json.loads(json.dumps(result["sweep"]))


# ---------------------------------------------------------------- calibration


def _coh(sweep):
    return {ii.coherence_key(n): _rate("", n["reply"]) for n in sweep["neutral"]}


def test_calibrate_picks_the_smallest_coherent_dose(result):
    sw = result["sweep"]
    cal = ii.calibrate(sw, _coh(sw))
    tab = cal["table"]
    assert cal["GO"], cal["why"]
    h = cal["headline_beta"]
    assert tab[f"{h:g}"]["rr_inject"] >= ii.HEAD_RR and h < 6  # beta >= 6 is incoherent
    smaller = [b for b in tab if float(b) < h]
    assert all(tab[b]["rr_inject"] < ii.HEAD_RR for b in smaller)
    assert cal["secondary_beta"] < h
    det = cal["detection_baseline"]
    assert det["false_alarm_rate"] == 0 and len(det["beta0_top5"]) == 5
    assert tab["8"]["coherent_inject"] == 0 and tab["1"]["detect_inject"] == 0


def _sweep(rr_by_beta, b0=0.04, gauss=0.04, cross=0.04):
    words = [f"w{i}" for i in range(5)]

    def same(v):
        return dict.fromkeys(words, v)

    return {
        "beta0": {"rr": same(b0), "top5": words, "p_yes": {"1": 0.1, "2": 0.7}},
        "betas": {
            f"{b:g}": {
                "inject": same(rr),
                "gaussian": same(gauss),
                "cross": same(cross),
                "p_yes_inject": same(0.9),
                "p_yes_gaussian": same(0.2),
            }
            for b, rr in rr_by_beta.items()
        },
        "neutral": [],
    }


def test_calibrate_no_go_and_fallbacks():
    cal = ii.calibrate(_sweep({1: 0.1, 2: 0.2}), None)
    assert not cal["GO"] and cal["headline_beta"] is None and "0.6" in cal["why"]
    assert cal["notes"] == ["coherence clause dropped (coherence=off)"]
    assert cal["detection_baseline"]["false_alarm_rate"] == 0.5
    # an abrupt jump: the first beta reaching 0.35 is the headline itself -> half of it
    cal = ii.calibrate(_sweep({1: 0.1, 2: 0.9}), None)
    assert cal["GO"] and cal["headline_beta"] == 2.0 and cal["secondary_beta"] == 1.0
    # the gaussian control reaches the word too: NO-GO on the margin
    cal = ii.calibrate(_sweep({2: 0.9}, gauss=0.8), None)
    assert not cal["GO"] and "vs gaussian False" in cal["why"]
    # coherence on, but no rating at that dose: never coherent
    cal = ii.calibrate(_sweep({2: 0.9}), {})
    assert not cal["GO"] and cal["headline_beta"] is None


# ---------------------------------------------------------------- the adapted bank


def _bank_from_result(tmp_path, subject, bank, job, result):
    paths = {"concept": tmp_path / "c.npy", "gaussian": tmp_path / "g.npy"}
    np.save(paths["concept"], result["concept"])
    np.save(paths["gaussian"], result["gaussian"].astype(np.float32))
    cal = ii.calibrate(result["sweep"], _coh(result["sweep"]))
    out = ii.build_bank(subject.key, bank, job, cal, result["concept"], paths,
                        result["gaussian"].shape)  # fmt: skip
    return out, cal, paths


def test_build_bank_replaces_every_subject_field(tmp_path, subject, bank, job, result):
    out, cal, paths = _bank_from_result(tmp_path, subject, bank, job, result)
    assert out["model"] == "org/Fake-32L" and out["spec"]["inject_layer"] == 6
    assert out["renders"] == job["renders"]
    assert len(out["items"]) == len(bank["items"]) and out["beta0_rows"] == bank["beta0_rows"]
    for it, orig in zip(out["items"], bank["items"], strict=True):
        assert it["id"] == orig["id"] and it["beta"] == orig["beta"]  # the tier the judge keys on
        assert it.get("twins") == orig.get("twins") and it["inject_layer"] == 6
        want = cal["headline_beta"] if orig["beta"] == 4.0 else cal["secondary_beta"]
        assert it["dose"] == want
    c0 = out["concepts"][0]
    assert "vector_norm_L12" not in c0 and c0["vector_fingerprint"] == ii.fingerprint(
        result["concept"][0]
    )
    assert out["vectors"]["concept"]["shape"] == [125, 24]
    assert (
        out["vectors"]["gaussian"]["sha256"]
        == hashlib.sha256(paths["gaussian"].read_bytes()).hexdigest()
    )
    assert out["reference_27b"]["agam_reproduction"] == bank["agam_reproduction"]
    assert 0 <= out["vector_space_check"]["mean_neighbour_purity"] <= 1
    assert out["calibration"] == cal and out["vector_recipe"]["layer"] == 6
    # the registered bank object is untouched
    assert "dose" not in bank["items"][0] and bank["spec"]["inject_layer"] == 12


def test_plan_of_the_adapted_bank_injects_the_subjects_dose(tmp_path, subject, bank, job, result,
                                                            monkeypatch):  # fmt: skip
    out, cal, paths = _bank_from_result(tmp_path, subject, bank, job, result)
    f = tmp_path / "introspection.json"
    f.write_text(json.dumps(out))
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + "INTROSPECTION", str(f))
    by_id = {s.id: s for s in readplan.plan("introspection")}
    head = by_id["inject|protocol:trial1|b4|trumpets"]
    st = head.extra["steering"]
    assert st["beta"] == cal["headline_beta"] and st["inject_layer"] == 6
    assert st["vector_file"] == str(paths["concept"]) and st["vector_row"] == 0
    r = job["renders"]["protocol:trial1"]
    assert head.extra["input_ids"] == r["input_ids"]
    assert st["token_span"] == [r["inject_span"][0], r["inject_span"][-1]]
    assert head.positions["positions"] == r["grid"]
    assert head.lite_positions["positions"] == r["lite"]
    sec = by_id["gaussian|protocol:trial1|b2|trumpets"].extra["steering"]
    assert sec["beta"] == cal["secondary_beta"] and sec["type"] == "gaussian"
    b0 = next(s for s in by_id.values() if s.id.startswith("beta0|"))
    assert b0.extra["steering"] == {"type": "none", "beta": 0.0}


# ---------------------------------------------------------------- stages and CLI


def test_stages_end_to_end(adapted, tok, subject, job, monkeypatch):
    m = subject.key
    ii.stage_job(m, tok)
    monkeypatch.setattr(ii, "measure", functools.partial(ii.measure, randn=_randn,
                                                         log=lambda s: None))  # fmt: skip
    ii.stage_measure(m, engine=FakeEngine(job))
    paths = ii.vector_paths(m, 6)
    assert np.load(paths["concept"]).shape == (125, 24)
    assert ii.stage_coherence(m, rate=_rate, workers=4) > 0
    assert ii.stage_coherence(m, rate=lambda p, r: pytest.fail("cached"), workers=4) == 0
    cal = ii.stage_calibrate(m)
    assert cal["GO"]
    out = ii.stage_build(m)
    written = json.loads((adapted / m / "introspection.json").read_text())
    assert written["calibration"] == cal and len(written["items"]) == len(out["items"])
    entry = json.loads((adapted / m / "report.json").read_text())["families"]["introspection"]
    assert entry["status"] == "full" and entry["n_items"] == 2250 and entry["target"] == 2250
    assert "freeze_notes" not in entry  # the fake's grids have >= 9 positions, coherence on


def test_build_blocked_on_no_go(adapted, subject):
    m = subject.key
    (adapted / m / "introspection").mkdir(parents=True)
    store.write_json(adapted / m / "introspection" / "job.json", {"inject_layer": 6})
    store.write_json(adapted / m / "introspection" / "calibration.json",
                     ii.calibrate(_sweep({1: 0.1}), None))  # fmt: skip
    store.write_json(adapted / m / "introspection.json", {"items": ["an earlier GO bank"]})
    assert ii.stage_build(m) is None
    assert not (adapted / m / "introspection.json").exists()
    entry = json.loads((adapted / m / "report.json").read_text())["families"]["introspection"]
    assert entry["status"] == "blocked" and entry["n_items"] == 0 and "NO-GO" in entry["note"]


def test_calibrate_needs_every_reply_rated_unless_off(adapted, subject):
    m = subject.key
    sw = _sweep({2: 0.9})
    sw["neutral"] = [{"beta": 2.0, "kind": "inject", "concept": f"w{i}", "prompt": "p",
                      "reply": f"reply {i}"} for i in range(3)]  # fmt: skip
    store.write_json(adapted / m / "introspection" / "sweep.json", sw)
    with pytest.raises(SystemExit, match="0/3 neutral replies rated"):
        ii.stage_calibrate(m)
    keys = [ii.coherence_key(n) for n in sw["neutral"]]
    store._append_jsonl(adapted / m / "introspection" / "coherence.jsonl",
                        [{"key": k, "score": 9.0} for k in keys[:2]])  # fmt: skip
    with pytest.raises(SystemExit, match="2/3"):
        ii.stage_calibrate(m)
    store._append_jsonl(adapted / m / "introspection" / "coherence.jsonl",
                        [{"key": keys[2], "score": 9.0}])  # fmt: skip
    cal = ii.stage_calibrate(m)
    assert cal["GO"] and cal["coherence_coverage"] == {"rated": 3, "total": 3}
    assert ii.stage_calibrate(m, use_coherence=False)["coherence_coverage"] is None


def test_coherence_key_follows_the_reply():
    n = {"beta": 2.0, "kind": "inject", "concept": "snow", "prompt": "p", "reply": "a"}
    assert ii.coherence_key(n) != ii.coherence_key({**n, "reply": "b"})
    assert ii.coherence_key(n) == ii.coherence_key(dict(n))


def test_remeasure_removes_the_bank_built_from_old_vectors(adapted, subject, job, result):
    m = subject.key
    store.write_json(adapted / m / "introspection" / "job.json", job)
    store.write_json(adapted / m / "introspection" / "calibration.json", {"GO": True})
    store.write_json(adapted / m / "introspection.json", {"items": []})
    f = adapted / "res.npz"
    f.write_bytes(ii.save_result(result))
    ii.stage_measure(m, result=str(f))
    assert not (adapted / m / "introspection.json").exists()
    assert not (adapted / m / "introspection" / "calibration.json").exists()


def test_adapted_bank_lowers_min_full_positions(tmp_path, monkeypatch):
    from wsbench import reads

    monkeypatch.delenv(registry.BANK_ROOT_ENV, raising=False)
    (tmp_path / "introspection.json").write_text(json.dumps({"adapt": {"min_grid_positions": 4}}))
    assert reads.min_full_positions("introspection", 9) == 9  # registered: never consulted
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert reads.min_full_positions("introspection", 9) == 4
    assert reads.min_full_positions("introspection", 3) == 3  # lowers, never raises
    assert reads.min_full_positions("typo", 9) == 9  # no bank there
    (tmp_path / "introspection.json").write_text(json.dumps([{"id": "x"}]))
    assert reads.min_full_positions("introspection", 9) == 9  # a bare-list bank


def test_big_moe_subjects_need_their_own_engine(adapted):
    store.write_json(adapted / "kimi-k2" / "introspection" / "job.json", {"inject_layer": 30})
    with pytest.raises(SystemExit, match="Engine"):
        ii.stage_measure("kimi-k2")


def test_external_result_is_ingested(adapted, subject, job, result):
    m = subject.key
    store.write_json(adapted / m / "introspection" / "job.json", job)
    f = adapted / "res.npz"
    f.write_bytes(ii.save_result(result))
    ii.stage_measure(m, result=str(f))
    assert np.load(ii.vector_paths(m, 6)["gaussian"]).shape == (500, 24)
    bad = {**result, "concept": result["concept"][:3]}
    f.write_bytes(ii.save_result(bad))
    with pytest.raises(SystemExit, match="concept rows"):
        ii.stage_measure(m, result=str(f))
    sw = json.loads(json.dumps(result["sweep"]))
    sw["betas"].pop("8")
    f.write_bytes(ii.save_result({**result, "sweep": sw}))
    with pytest.raises(SystemExit, match="betas"):
        ii.stage_measure(m, result=str(f))
    sw = json.loads(json.dumps(result["sweep"]))
    sw["beta0"]["rr"] = {"other": 1.0}
    f.write_bytes(ii.save_result({**result, "sweep": sw}))
    with pytest.raises(SystemExit, match="paper words"):
        ii.stage_measure(m, result=str(f))


def test_cli_keys_and_family_registry(monkeypatch):
    assert adapt_main.KEYS["introspection"] == {"stage", "result", "coherence", "llm"}
    with pytest.raises(SystemExit, match="unknown argument"):
        adapt_main.main(["introspection", "model=x", "family=introspection"])
    with pytest.raises(SystemExit, match="adapt introspection"):
        fams.get("introspection")
    with pytest.raises(SystemExit, match="unknown stage"):
        ii.run("m", stage="vectors")
    seen = {}
    monkeypatch.setattr(ii, "run", lambda *a: seen.setdefault("a", a))
    adapt_main.main(["introspection", "model=m", "stage=calibrate", "coherence=off"])
    assert seen["a"] == ("m", "calibrate", None, "off", "claude-opus-5-5")


# ---------------------------------------------------------------- round 2: job identity


def test_job_sha_stamps_job_and_sweep(job, result):
    assert job["job_sha"] == ii.job_sha(job) and len(job["job_sha"]) == 16
    assert ii.job_sha({**job, "betas": [1.0]}) != job["job_sha"]
    assert result["sweep"]["job_sha"] == job["job_sha"]


def test_result_of_another_job_refused(adapted, subject, job, result):
    m = subject.key
    store.write_json(adapted / m / "introspection" / "job.json", {**job, "job_sha": "other"})
    f = adapted / "res.npz"
    f.write_bytes(ii.save_result(result))
    with pytest.raises(SystemExit, match="measured on job"):
        ii.stage_measure(m, result=str(f))
    assert not ii.vector_paths(m, 6)["concept"].exists()


def test_build_refuses_a_calibration_of_another_job(adapted, subject):
    m = subject.key
    store.write_json(
        adapted / m / "introspection" / "job.json", {"inject_layer": 6, "job_sha": "a"}
    )
    cal = {**ii.calibrate(_sweep({2: 0.9}), None), "job_sha": "b"}
    store.write_json(adapted / m / "introspection" / "calibration.json", cal)
    with pytest.raises(SystemExit, match="re-run measure and calibrate"):
        ii.stage_build(m)


def test_calibrate_voids_the_built_bank_and_stamps_the_job(adapted, subject):
    m = subject.key
    sw = {**_sweep({2: 0.9}), "job_sha": "abc"}
    store.write_json(adapted / m / "introspection" / "sweep.json", sw)
    store.write_json(adapted / m / "introspection.json", {"items": []})
    cal = ii.stage_calibrate(m, use_coherence=False)
    assert cal["job_sha"] == "abc" and not (adapted / m / "introspection.json").exists()


def test_a_changed_job_voids_everything_downstream(adapted, tok, subject):
    m = subject.key
    w = adapted / m / "introspection"
    downstream = [w / "sweep.json", w / "calibration.json", adapted / m / "introspection.json",
                  w / "vectors" / "concept_vectors_L6.npy"]  # fmt: skip

    def seed():
        for p in downstream:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}")

    ii.stage_job(m, tok)
    seed()
    ii.stage_job(m, tok)  # the same job: nothing removed
    assert all(p.exists() for p in downstream)
    store.write_json(w / "job.json", {"job_sha": "an older job"})
    ii.stage_job(m, tok)
    assert not any(p.exists() for p in downstream)


def test_reads_load_honours_a_short_grid_adapted_bank(tmp_path, bank, monkeypatch):
    import copy

    from conftest import native_args, write_jsonl, write_sidecar

    from wsbench import reads
    from wsbench.judge_config import JudgeConfig, resolve

    item = "inject|neutral:meeting_note|b4|trumpets"
    grid = bank["renders"]["neutral:meeting_note"]["grid"]
    rows = [{"id": item, "layer": 20, "pos": p, "samples": [f"s{p}"]} for p in grid[:4]]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    write_sidecar(path, reader="t", arm="t")

    def args():
        return native_args(readouts=path, out=tmp_path / "o", judge=resolve(JudgeConfig()),
                           layers=[20], items=None, limit=0, allow_missing=False, concurrency=1,
                           rpm=1.0, dry_run=True, extra={})  # fmt: skip

    short = copy.deepcopy(bank)
    f = tmp_path / "introspection.json"
    f.write_text(json.dumps(short))
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + "INTROSPECTION", str(f))
    with pytest.raises(SystemExit):  # an adapted bank without the record: the family's 9
        reads.load(args(), "introspection", ids=[item])
    short["adapt"] = {"min_grid_positions": 4}
    f.write_text(json.dumps(short))
    cells, rep = reads.load(args(), "introspection", ids=[item])
    assert len(cells) == 4 and not rep.partial_ids
    # WSB_BANK_FILE_<F> wins over WSB_BANK_ROOT (registry.bank_path's precedence)
    root = tmp_path / "root"
    root.mkdir()
    (root / "introspection.json").write_text(json.dumps({"adapt": {"min_grid_positions": 2}}))
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(root))
    assert reads.min_full_positions("introspection", 9) == 4
    monkeypatch.delenv(registry.BANK_FILE_ENV_PREFIX + "INTROSPECTION")
    assert reads.min_full_positions("introspection", 9) == 2


# ---------------------------------------------------------------- round 3: result integrity


def _ingest(adapted, m, job, res):
    store.write_json(adapted / m / "introspection" / "job.json", job)
    f = adapted / "res.npz"
    f.write_bytes(ii.save_result(res))
    ii.stage_measure(m, result=str(f))


def test_gaussian_rows_off_recipe_refused(adapted, subject, job, result):
    g = result["gaussian"]
    unit = g / np.linalg.norm(g, axis=1, keepdims=True)  # e.g. a runner that ships unit rows
    with pytest.raises(SystemExit, match="gaussian rows are not the recipe"):
        _ingest(adapted, subject.key, job, {**result, "gaussian": unit})
    assert not ii.vector_paths(subject.key, 6)["gaussian"].exists()


@pytest.mark.parametrize("bad", [np.nan, np.inf, 0.0])
def test_non_finite_or_zero_concept_rows_refused(adapted, subject, job, result, bad):
    c = result["concept"].copy()
    c[3] = 0.0 if bad == 0.0 else c[3]
    if bad != 0.0:
        c[3, 1] = bad
    with pytest.raises(SystemExit, match="non-finite or zero-norm"):
        _ingest(adapted, subject.key, job, {**result, "concept": c})


def test_gaussian_recipe_reproduces_the_shipped_27b_rows(bank):
    pytest.importorskip("torch")
    shipped = np.load(registry.REPO_ROOT / bank["vectors"]["gaussian"]["path"], mmap_mode="r")
    seeds = [it["vector"]["seed"] for it in bank["items"] if it["kind"] == "gaussian"][:3]
    np.testing.assert_array_equal(REAL_GAUSSIAN_ROWS(seeds, 5120), np.asarray(shipped[:3]))


def test_adapted_spec_does_not_describe_the_27b(tmp_path, subject, bank, job, result):
    out, _cal, _paths = _bank_from_result(tmp_path, subject, bank, job, result)
    assert "legacy_v1" not in out["spec"]
    assert out["reference_27b"]["spec_legacy_v1"] == bank["spec"]["legacy_v1"]
    assert (
        "subject's width" in out["spec"]["controls"]
        and "org/Fake-32L" in out["spec"]["subject_note"]
    )
    assert "legacy_v1" in bank["spec"]  # the registered bank object is untouched


def test_bare_list_bank_span_from_the_set_report(tmp_path, monkeypatch):
    """GLM-5.3: conjunctive / role_bound banks are bare lists (no ``adapt`` header), so their
    shorter GLM span is recorded in the set's report.json and read from there, under
    WSB_BANK_ROOT only; a header still wins; a file override never reads the root report."""
    from wsbench import reads

    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    (tmp_path / "conjunctive_association.json").write_text(json.dumps([{"id": "q01_c"}]))
    assert reads.min_full_positions("conjunctive_association", 19) == 19  # no record yet
    rep = {"families": {"conjunctive_association": {"min_grid_positions": 13}}}
    (tmp_path / "report.json").write_text(json.dumps(rep))
    assert reads.min_full_positions("conjunctive_association", 19) == 13
    assert reads.min_full_positions("conjunctive_association", 9) == 9  # lowers, never raises
    (tmp_path / "conjunctive_association.json").write_text(
        json.dumps({"adapt": {"min_grid_positions": 15}, "items": []}))  # fmt: skip
    assert reads.min_full_positions("conjunctive_association", 19) == 15  # the header wins
    (tmp_path / "conjunctive_association.json").write_text(json.dumps([{"id": "q01_c"}]))
    for bad in (
        {"families": ["x"]},
        {"families": "x"},
        ["x"],
        {"families": {"conjunctive_association": {"min_grid_positions": True}}},
    ):
        (tmp_path / "report.json").write_text(json.dumps(bad))  # malformed: the default
        assert reads.min_full_positions("conjunctive_association", 19) == 19
    f = tmp_path / "other.json"
    f.write_text(json.dumps([{"id": "q01_c"}]))
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + "CONJUNCTIVE_ASSOCIATION", str(f))
    assert reads.min_full_positions("conjunctive_association", 19) == 19
