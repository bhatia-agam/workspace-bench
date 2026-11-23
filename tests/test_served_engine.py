"""The served engine on the CPU against a fake server: the sampler filter equals HF's two
warpers, the token bank, and `SGLangEngine.decode` (no sglang, no GPU, no network)."""

import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("safetensors")

from safetensors.torch import load_file  # noqa: E402
from served_fakes import DIM, EMBED, EOS, VOCAB, Tok, meta, snapshot  # noqa: E402

from wsbench.produce.served import bank, bundle, engine  # noqa: E402
from wsbench.produce.served.sampling import SamplingPlan, hf_top_k_top_p  # noqa: E402
from wsbench.produce.store import Cell  # noqa: E402

# ---------------------------------------------------------------- sampling


def hf_reference(scores, top_k, top_p):
    """transformers' TopKLogitsWarper followed by TopPLogitsWarper (min_tokens_to_keep=1)."""
    scores = scores.clone()
    k = min(top_k, scores.size(-1))
    remove = scores < torch.topk(scores, k)[0][..., -1, None]
    scores = scores.masked_fill(remove, float("-inf"))
    sorted_logits, sorted_indices = torch.sort(scores, descending=False)
    cumulative = sorted_logits.softmax(dim=-1).cumsum(dim=-1)
    sorted_remove = cumulative <= (1 - top_p)
    sorted_remove[..., -1:] = 0
    remove = sorted_remove.scatter(1, sorted_indices, sorted_remove)
    return scores.masked_fill(remove, float("-inf"))


def test_same_kept_set_as_hf():
    torch.manual_seed(0)
    for scale in (0.5, 2.0, 6.0):  # flat to peaked distributions
        logits = torch.randn(64, 5000) * scale
        want = hf_reference(logits, 64, 0.95)
        got = hf_top_k_top_p(logits.clone(), 64, 0.95)
        assert torch.equal(torch.isfinite(got), torch.isfinite(want))
        assert torch.equal(got[torch.isfinite(got)], want[torch.isfinite(want)])
        kept = torch.isfinite(got).sum(-1)
        assert int(kept.min()) >= 1 and int(kept.max()) <= 64


def test_the_transformers_warpers_agree_when_installed():
    warpers = pytest.importorskip("transformers.generation.logits_process")
    torch.manual_seed(1)
    logits = torch.randn(8, 500) * 3
    want = warpers.TopPLogitsWarper(0.9)(None, warpers.TopKLogitsWarper(20)(None, logits.clone()))
    got = hf_top_k_top_p(logits.clone(), 20, 0.9)
    assert torch.equal(torch.isfinite(got), torch.isfinite(want))


def test_hf_order_cuts_inside_the_top_k_when_their_mass_is_small():
    # a flat distribution: the top-64 hold little mass, so a nucleus on the FULL distribution
    # never cuts inside them, while HF's renormalised nucleus does
    logits = torch.zeros(1, 5000)
    logits[0, :64] = torch.linspace(1.0, 0.0, 64)
    assert int(torch.isfinite(hf_top_k_top_p(logits.clone(), 64, 0.95)).sum()) < 64


def test_sampling_plan_renders_for_sglang_with_and_without_the_ban(tmp_path):
    plain = SamplingPlan.of(bundle.Bundle(tmp_path, meta())).sglang()
    assert plain == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "max_new_tokens": 8,
        "stop_token_ids": [EOS, 9],
        "skip_special_tokens": True,
    }
    banned = bundle.Bundle(tmp_path, meta(ban_ids=[1, 2], ban_min_new=24))
    sg = SamplingPlan.of(banned).sglang()
    assert sg["logit_bias"] == {"1": -1e9, "2": -1e9}
    assert sg["min_new_tokens"] == 8  # the hold never exceeds the length limit
    greedy = SamplingPlan.of(banned, greedy=True).sglang()
    assert (greedy["temperature"], greedy["top_k"], greedy["top_p"]) == (0.0, 1, 1.0)


# ---------------------------------------------------------------- the bank


def cells():
    return [
        Cell("a", 0, 3, "t", torch.tensor([3.0, 4.0, 0.0, 0.0])),
        Cell("b", 1, -1, "u", torch.tensor([0.0, 0.0, 0.0, 2.0])),
        Cell("c", 0, 5, "v", torch.tensor([1.0, 0.0, 0.0, 0.0])),
    ]


def test_slot_rows_are_norm_times_unit_vector():
    rows = bank.slot_rows(meta(), cells(), "cpu", chunk=1)
    assert rows.dtype == torch.bfloat16 and rows.shape == (3, DIM)
    want = torch.tensor([[1.2, 1.6, 0, 0], [0, 0, 0, 10.0], [2.0, 0, 0, 0]])
    assert torch.allclose(rows.float(), want, atol=1e-2)
    assert bank.slot_rows(meta(), [], "cpu").shape[0] == 0


@pytest.fixture
def made(tmp_path):
    """A bundle of the fake snapshot (no adapter: nothing to fold in)."""
    out = tmp_path / "bundle"
    bundle.merge(snapshot(tmp_path / "snap"), out, {}, 1.0, meta())
    return bundle.load(out)


def test_build_bank_appends_rows_and_links_the_rest(made, tmp_path):
    vectors = bank.slot_rows(made.meta, cells(), "cpu")
    out = tmp_path / "bank"
    (tmp_path / "bank").mkdir()
    (tmp_path / "bank" / "stale").write_text("from an earlier bank")
    assert bank.build_bank(made.path, out, vectors) == VOCAB
    first, second = (load_file(str(p)) for p in sorted(out.glob("*.safetensors")))
    before = load_file(str(made.path / "model-00002-of-00002.safetensors"))
    assert first[EMBED].shape == (VOCAB + 3, DIM) and first[EMBED].dtype == torch.bfloat16
    assert torch.equal(first[EMBED][VOCAB:], vectors)
    head = second["lm_head.weight"]
    assert head.shape == (VOCAB + 3, DIM) and torch.equal(head[:VOCAB], before["lm_head.weight"])
    row = bank.head_row(before["lm_head.weight"])
    assert all(torch.equal(head[VOCAB + j], row) for j in range(3))
    assert torch.allclose(
        row.float(), -4.0 * before["lm_head.weight"][256:].float().mean(0), atol=0.05
    )
    assert json.loads((out / "config.json").read_text())["text_config"]["vocab_size"] == VOCAB + 3
    index = json.loads((out / bundle.INDEX).read_text())
    assert index["metadata"]["total_size"] == 100 + 2 * 3 * DIM * 2
    assert (out / "tokenizer.json").is_symlink() and (out / "tokenizer.json").read_text() == "{}"
    assert not (out / "model-00001-of-00002.safetensors").is_symlink()
    assert not any((out / name).exists() for name in ("stale", bundle.DONE, bundle.META))


def test_the_processors_mask_bank_ids_and_filter_in_hf_order(monkeypatch):
    import importlib
    import sys
    import types

    fake = types.ModuleType("sglang.srt.sampling.custom_logit_processor")
    fake.CustomLogitProcessor = object
    for name in ("sglang", "sglang.srt", "sglang.srt.sampling"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.delitem(sys.modules, "wsbench.produce.served.processors", raising=False)
    processors = importlib.import_module("wsbench.produce.served.processors")
    logits = torch.arange(12.0).reshape(2, 6)
    masked = processors.BankMask()(logits.clone(), [{"base_vocab": 4}])
    assert torch.isinf(masked[:, 4:]).all() and torch.equal(masked[:, :4], logits[:, :4])
    params = [{"base_vocab": 4, "hf_top_k": 2, "hf_top_p": 1.0}]
    kept = torch.isfinite(processors.HFOrderSampler()(logits.clone(), params))
    assert kept.tolist() == [[False, False, True, True, False, False]] * 2
    monkeypatch.delitem(sys.modules, "wsbench.produce.served.processors")


# ---------------------------------------------------------------- the engine, a fake server


class Reply:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


class Server:
    """Stands in for the HTTP client and the server: each row's readout is [layer marker, the
    bank row's number, EOS]; ``leak(row, attempt)`` makes a row sample a bank id instead."""

    def __init__(self, work, leak=lambda row, attempt: False, first=None):
        self.work, self.leak, self.first = work, leak, first
        self.bodies, self.asked, self.events = [], {}, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.events.append("client closed")

    async def get(self, url):
        return Reply({"version": "fake-1"})

    async def post(self, url, json):
        assert url == "http://fake/generate"
        assert (self.work / "bank" / "config.json").exists()  # the bank is there while serving
        self.bodies.append(json)
        out = []
        for ids in json["input_ids"]:
            (row,) = [t - VOCAB for t in ids if t >= VOCAB]
            attempt = self.asked[row] = self.asked.get(row, 0) + 1
            first = self.first if self.first is not None else len(ids)
            out.append(
                {"output_ids": [VOCAB + 1] if self.leak(row, attempt) else [first, row, EOS]}
            )
        return Reply(out)


@pytest.fixture
def fake(made, tmp_path, monkeypatch):
    """`start(**options)` -> (engine, server) with every outside call replaced."""

    def start(leak=lambda row, attempt: False, first=None, lens=made, **options):
        work = tmp_path / "work"
        server = Server(work, leak, first)
        monkeypatch.setattr(
            engine,
            "start_server",
            lambda model, log, **kw: (server.events.append(kw), "http://fake"),
        )
        monkeypatch.setattr(engine, "stop_server", lambda proc: server.events.append("stopped"))
        monkeypatch.setattr(engine, "http_client", lambda: server)
        monkeypatch.setattr(engine, "processor", lambda hf_order: "HF" if hf_order else "MASK")
        monkeypatch.setattr(engine, "load_tokenizer", lambda path: Tok())
        return engine.load("sglang", lens, work=work, device="cpu", **options), server

    return start


def test_decode_puts_each_cells_bank_id_at_the_slot_and_returns_k_rows_per_cell(fake, made):
    eng, server = fake(post_rows=4)
    texts = eng.decode(cells())
    # k = 2 readouts per cell, in cell order: "<prompt length of the layer> <bank row>"
    assert texts == [["4 0 7", "4 0 7"], ["5 1 7", "5 1 7"], ["4 2 7", "4 2 7"]]
    sent = [ids for body in server.bodies for ids in body["input_ids"]]
    assert len(sent) == 6 and [len(b["input_ids"]) for b in server.bodies] == [4, 2]
    for ids in sent:
        (row,) = [t - VOCAB for t in ids if t >= VOCAB]
        prompt = made.meta["prompts"][str(cells()[row].layer)]
        assert ids.index(VOCAB + row) == prompt["slot"]
        assert [t for t in ids if t < VOCAB] == [t for i, t in enumerate(prompt["ids"]) if i != 2]
    assert [len(ids) for ids in sent] == [4, 4, 4, 4, 5, 5]  # rows of one layer are neighbours
    body = server.bodies[0]
    assert body["custom_logit_processor"] == "HF"
    params = body["sampling_params"]
    assert params["custom_params"] == {"base_vocab": VOCAB, "hf_top_k": 64, "hf_top_p": 0.95}
    assert (params["top_k"], params["top_p"], params["max_new_tokens"]) == (1 << 30, 1.0, 8)
    started = server.events[0]
    assert started["extra"] == ["--enable-custom-logit-processor", *engine.DEFAULT_SERVER_ARGS]
    assert server.events[1:] == ["client closed", "stopped"]
    assert eng.tokens == [[4, 0, 7], [4, 0, 7], [5, 1, 7], [5, 1, 7], [4, 2, 7], [4, 2, 7]]
    stats = eng.stats.as_dict()
    assert (stats["rows"], stats["tokens"], stats["bank_leaks_resampled"]) == (6, 18, 0)
    assert eng.checks["length_max"] == 2 and eng.version == "fake-1"
    eng.close()
    assert not (eng.work / "bank").exists()


def test_a_new_bank_and_server_per_max_bank_cells(fake):
    eng, server = fake(max_bank=2, server_args=["--max-running-requests", "8"], sampler="native")
    assert eng.decode(cells()) == [["4 0 7"] * 2, ["5 1 7"] * 2, ["4 0 7"] * 2]
    assert server.events.count("stopped") == 2
    assert server.events[0]["extra"] == [
        "--enable-custom-logit-processor",
        "--max-running-requests",
        "8",
    ]
    params = server.bodies[0]["sampling_params"]
    assert server.bodies[0]["custom_logit_processor"] == "MASK"
    assert (params["top_k"], params["top_p"], params["custom_params"]) == (
        64,
        0.95,
        {"base_vocab": VOCAB},
    )
    assert eng.decode([]) == [] and eng.tokens == []


def test_a_sampled_bank_id_is_asked_again_and_never_kept(fake):
    eng, server = fake(leak=lambda row, attempt: row == 1 and attempt <= 2, post_rows=3)
    texts = eng.decode(cells())
    assert texts[1] == ["5 1 7", "5 1 7"]
    assert all(t < VOCAB for row in eng.tokens for t in row)
    assert eng.leaks == 2 and eng.stats.extra["bank_leaks_resampled"] == 2
    assert server.asked == {0: 2, 1: 4, 2: 2}  # only the leaked rows were sent again


def test_four_leaks_in_a_row_is_an_error_and_the_server_is_stopped(fake):
    eng, server = fake(leak=lambda row, attempt: row == 2)
    with pytest.raises(RuntimeError, match="sampled a bank id 4 times in a row"):
        eng.decode(cells())
    assert server.events[-1] == "stopped"


def test_token_checks_and_the_ban(fake, made, tmp_path):
    rows = [[5, 6, EOS], [5, 6, 7, 8, 9], [1, 5], [EOS]]
    plain = engine.token_checks(rows, meta())
    assert plain == {"length_mean": 2.0, "length_p50": 2, "length_p90": 4, "length_max": 4}
    assert engine.token_checks([], meta()) == {}
    engine.enforce_ban(plain)
    checks = engine.token_checks(rows, meta(ban_ids=[1], ban_min_new=2))
    assert (checks["rows_with_banned_token"], checks["rows_stopped_before_hold"]) == (1, 1)
    with pytest.raises(RuntimeError, match="ban was violated"):
        engine.enforce_ban(checks)
    banned = bundle.Bundle(made.path, meta(ban_ids=[4], ban_min_new=2))
    eng, server = fake(lens=banned)
    with pytest.raises(RuntimeError, match="ban was violated"):  # layer-0 rows start with id 4
        eng.decode(cells())
    assert server.bodies[0]["sampling_params"]["logit_bias"] == {"4": -1e9}
    eng, _ = fake(lens=banned, first=20)
    assert eng.decode(cells())[0] == ["20 0 7", "20 0 7"]
    assert eng.checks["rows_with_banned_token"] == 0


def test_engine_usage_errors(fake, made):
    with pytest.raises(ValueError, match="To add one"):
        engine.load("vllm", made)
    with pytest.raises(ValueError, match="sampler is one of"):
        fake(sampler="joint")
    eng, server = fake()
    with pytest.raises(ValueError, match=r"no prompt for layers \[7\]"):
        eng.decode([Cell("x", 7, 0, "t", torch.ones(DIM))])
    assert server.events == []  # refused before any bank or server
    hot = bundle.Bundle(made.path, meta(sampling=meta()["sampling"] | {"temperature": 0.7}))
    eng, server = fake(lens=hot)
    with pytest.raises(NotImplementedError, match="needs temperature"):
        eng.decode(cells())
    assert server.events[-1] == "stopped"
    eng, server = fake(lens=hot, greedy=True)
    assert len(eng.decode(cells())) == 3
    assert server.bodies[0]["sampling_params"]["temperature"] == 0.0
    grown = bundle.Bundle(made.path, meta(base_vocab=VOCAB + 1))
    with pytest.raises(RuntimeError, match="base_vocab"):
        fake(lens=grown)[0].decode(cells())
