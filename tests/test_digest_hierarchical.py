"""digest hierarchical overflow (plan 0021): real-token fit, chunks + final union, persisted
fallback on refusal / too long, cached counts, dry run without network."""

from pathlib import Path

import pytest
from conftest import native_args

from wsbench import digest, llm
from wsbench.cache import Cache
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.llm import Spend
from wsbench.readouts import Cell
from wsbench.registry import JudgeArgs

FAM = "test_hier_family"


def _args(tmp_path: Path, dry: bool = False, **extra: str) -> JudgeArgs:
    return native_args(
        readouts=tmp_path / "r.jsonl",
        out=tmp_path / "out",
        judge=resolve(JudgeConfig(prompt_version="t")),
        layers=None,
        items=None,
        limit=0,
        allow_missing=False,
        concurrency=1,
        rpm=1.0,
        dry_run=dry,
        extra={"aggregate": "summary", **extra},
    )


@pytest.fixture
def fam(monkeypatch):
    # these tests pin the real-count path: count every bundle (plan 0032 counts only estimates
    # above 60% of the cap)
    monkeypatch.setattr(digest, "COUNT_TOKENS_ABOVE", 0.0)
    monkeypatch.setitem(
        digest.FAMILY_DEFAULTS,
        FAM,
        # summ_layers=joint: these tests drive the chunk / halving machinery with multi-layer
        # bundles; under the per-layer default (audit F1) each layer is its own small bundle and
        # never chunks (the per-layer path: tests/test_digest_union.py)
        {
            "summ_overflow": "hierarchical",
            "summ_token_cap": "1000",
            "summ_max": "5",
            "summ_layers": "joint",
        },
    )


class Fake:
    """count_tokens returns ``tokens_per_char`` x len(user); stream_json picks the first bundle
    line of each prompt (or a scripted marker by substring)."""

    def __init__(self, monkeypatch, tokens_per_char: float = 1.0):
        self.counts: list[int] = []
        self.calls: list[str] = []
        self.script: dict[str, object] = {}  # substring -> result
        self.exact: dict[str, object] = {}  # whole user prompt -> result
        self.tpc = tokens_per_char
        monkeypatch.setattr(llm, "count_tokens", self.count_tokens)
        monkeypatch.setattr(llm, "stream_json", self.stream_json)

    def count_tokens(self, model, prompts, concurrency=8):
        self.counts.append(len(prompts))
        return [int(len(u) * self.tpc) for _s, u in prompts]

    def stream_json(self, prompts, *, on_result, **kw):
        assert kw.get("mark_refusals") is True and kw.get("attempts") == digest.DIGEST_ATTEMPTS
        for i, (_s, user) in enumerate(prompts):
            self.calls.append(user)
            hit = self.exact.get(user)
            if hit is None:
                hit = next((v for k, v in self.script.items() if k in user), None)
            if hit is not None:
                on_result(i, hit)
                continue
            lines = [ln[2:] for ln in user.splitlines() if ln.startswith("- ")]
            on_result(
                i,
                {
                    "items": [
                        {"statement": "s", "key": "", "where": "", "evidence": ln}
                        for ln in lines[:2]
                    ]
                },
            )
        return Spend()


def _cells(item: str, n_layers: int, text: str = "word") -> list[Cell]:
    return [
        Cell(item, 20 + 4 * L, p, (f"{text} {item} L{L} p{p} " + "x" * 40,), None, None, None)
        for L in range(n_layers)
        for p in range(3)
    ]


def _run(tmp_path, cells_by_item, **kw):
    with Cache(tmp_path / "c.jsonl") as cache:
        return digest.collapse(
            FAM,
            cells_by_item,
            args=_args(tmp_path, **kw),
            cache=cache,
            spend=Spend(),
            preflight=None,
            task_note="",
        )


def test_fits_is_one_call_and_counts_are_cached(tmp_path, fam, monkeypatch):
    fake = Fake(monkeypatch, tokens_per_char=0.5)
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert len(fake.calls) == 1 and not col.chunks and col.summaries["a"]
    assert col.row("a")["summary_hierarchical"] is False
    _run(tmp_path, {"a": _cells("a", 2)})
    assert fake.counts == [1] and len(fake.calls) == 1  # rerun: count and digest cached


def test_over_budget_chunks_at_layer_boundaries_then_final(tmp_path, fam, monkeypatch):
    fake = Fake(monkeypatch, tokens_per_char=1.0)
    col = _run(tmp_path, {"a": _cells("a", 6)})
    n = col.chunks["a"]
    assert n >= 2 and len(fake.calls) == n + 1  # n chunk calls + 1 final
    final = fake.calls[-1]
    assert "(support:" in final and "[L20 pos 0]" in final
    assert col.row("a")["summary_hierarchical"] is True and col.row("a")["summary_chunks"] == n
    # every chunk is a run of whole layers (the bundle has 3 positions per layer)
    for user in fake.calls[:-1]:
        heads = [ln for ln in user.splitlines() if ln.startswith("[L")]
        assert len(heads) % 3 == 0
    # evidence is verbatim original samples
    assert all("x" * 40 in e.text for e in col.evidence["a"])


def test_refused_single_falls_back_to_chunks_and_is_persisted(tmp_path, fam, monkeypatch):
    fake = Fake(monkeypatch, tokens_per_char=0.3)
    cells = {"a": _cells("a", 4)}
    first_user = digest.render_user(digest._render([digest._group(c) for c in cells["a"]]))
    fake.exact[first_user] = llm.REFUSED_JSON  # only the whole-bundle call is refused
    col = _run(tmp_path, cells)
    # recovered through chunks: one fallback event, no item lost to a refusal
    assert col.diag["n_fallback_events"] == 1 and col.diag["n_digest_refused"] == 0
    assert col.chunks.get("a", 0) >= 2
    assert col.summaries["a"]
    n_before = len(fake.calls)
    _run(tmp_path, cells)
    rerun_users = fake.calls[n_before:]
    assert first_user not in rerun_users  # the known-refused single call is never re-sent


def test_chunk_outcomes(tmp_path, fam, monkeypatch):
    fake = Fake(monkeypatch, tokens_per_char=1.0)
    fake.script["word"] = {"items": []}  # every chunk reports nothing
    col = _run(tmp_path, {"a": _cells("a", 6)})
    assert "a" in col.empty
    fake2_dir = tmp_path / "b"
    fake2_dir.mkdir()
    fake.script = {
        "word": {"items": [{"statement": "s", "key": "", "where": "", "evidence": "not there"}]}
    }
    col = _run(fake2_dir, {"a": _cells("a", 6)})
    assert "a" in col.unsummarized


def test_dry_run_makes_no_network_call(tmp_path, fam, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network in dry run")

    monkeypatch.setattr(llm, "count_tokens", boom)
    monkeypatch.setattr(llm, "stream_json", boom)
    col = _run(tmp_path, {"a": _cells("a", 6)}, dry=True)
    assert col.unsummarized == {"a"}


def test_family_defaults_reach_settings_and_config(tmp_path, fam):
    a = _args(tmp_path)
    s = digest.settings(a, FAM)
    assert (s.overflow, s.token_cap, s.max_items) == ("hierarchical", 1000, 5)
    assert digest.config(a, "prose", family=FAM)["summarizer"]["overflow"] == "hierarchical"
    # plan 0032 §2.2.1: hierarchical is the global default (stride is the stamped ablation)
    assert digest.settings(a).overflow == "hierarchical"
    override = _args(tmp_path, summ_max="7")
    assert digest.settings(override, FAM).max_items == 7  # opts beat family defaults


def test_refused_at_every_level_is_unsummarized_and_counts_are_rerun_stable(
    tmp_path, fam, monkeypatch
):
    fake = Fake(monkeypatch, tokens_per_char=1.0)
    fake.script["word"] = llm.REFUSED_JSON  # every chunk at every level is refused
    col = _run(tmp_path, {"a": _cells("a", 6)})
    assert "a" in col.unsummarized and col.diag["n_digest_refused"] == 1
    n = len(fake.calls)
    col = _run(tmp_path, {"a": _cells("a", 6)})
    assert len(fake.calls) == n  # out of halvings: nothing re-sent
    assert "a" in col.unsummarized and col.diag["n_digest_refused"] == 1


def test_too_long_marker_falls_back(tmp_path, fam, monkeypatch):
    fake = Fake(monkeypatch, tokens_per_char=0.3)
    cells = {"a": _cells("a", 4)}
    first_user = digest.render_user(digest._render([digest._group(c) for c in cells["a"]]))
    fake.exact[first_user] = llm.TOO_LONG_JSON
    col = _run(tmp_path, cells)
    assert col.chunks.get("a", 0) >= 2 and col.summaries["a"]
    assert col.diag["n_fallback_events"] == 1 and col.diag["n_digest_too_long"] == 0


def test_refused_final_moves_down_a_level(tmp_path, fam, monkeypatch):
    fake = Fake(monkeypatch, tokens_per_char=1.0)
    fake.script["(support:"] = llm.REFUSED_JSON  # finals are refused, chunks are not
    col = _run(tmp_path, {"a": _cells("a", 6)})
    # audit F3: out of halvings, the item is judged on its (served) chunk digests directly
    # instead of being given up; nothing is unserved, so it is neither refused nor partial
    assert col.diag["n_fallback_events"] >= 1
    assert "a" not in col.unsummarized and col.summaries["a"]
    assert col.diag["n_items_chunk_direct"] == 1 and "a" not in col.partial
    assert col.diag["n_digest_refused"] + col.diag["n_digest_too_long"] == 0


def test_all_dropped_final_is_reasked_on_rerun(tmp_path, fam, monkeypatch):
    fake = Fake(monkeypatch, tokens_per_char=0.3)
    bad = {"items": [{"statement": "s", "key": "", "where": "", "evidence": "nowhere at all"}]}
    fake.script["word"] = bad
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert "a" in col.unsummarized
    n = len(fake.calls)
    fake.script.clear()
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert len(fake.calls) == n + 1 and col.summaries["a"]  # the failed digest was re-asked


def test_stride_path_all_dropped_is_reasked_on_rerun(tmp_path, monkeypatch):
    seen: list[str] = []
    replies = {"r": {"items": [{"statement": "s", "key": "", "where": "", "evidence": "nope"}]}}

    def fake_stream_json(prompts, *, on_result, **_kw):
        for i, (_s, user) in enumerate(prompts):
            seen.append(user)
            on_result(i, replies["r"])
        return Spend()

    monkeypatch.setattr(llm, "stream_json", fake_stream_json)
    cells = {"a": [Cell("a", 20, 1, ("alpha",), None, None, None)]}
    with Cache(tmp_path / "c.jsonl") as cache:
        col = digest.collapse(
            "basic_readout_st",
            cells,
            args=_args(tmp_path),
            cache=cache,
            spend=Spend(),
            preflight=None,
            task_note="",
        )
    assert "a" in col.unsummarized
    replies["r"] = {"items": [{"statement": "s", "key": "", "where": "", "evidence": "alpha"}]}
    with Cache(tmp_path / "c.jsonl") as cache:
        col = digest.collapse(
            "basic_readout_st",
            cells,
            args=_args(tmp_path),
            cache=cache,
            spend=Spend(),
            preflight=None,
            task_note="",
        )
    assert len(seen) == 2 and col.summaries["a"]


def test_plan_0020_fingerprint_unchanged():
    # the digest fingerprint fields, frozen (the v4 freeze, plan 0032: the task variant,
    # hierarchical overflow and one 920k cap by default; plan 0022 added max_rare and numbers;
    # the audit-fix digest PR bumped the version to digest-v5, per-claim counts): a change here
    # re-bills every cached digest
    args = _args(Path("/tmp"))
    s = digest.settings(args, "basic_readout_st")
    assert (s.overflow, s.concurrency, s.timeout) == ("hierarchical", None, None)
    from wsbench.cache import fingerprint

    expected = digest._digest_fp(s, "", "TEXT")
    assert expected == fingerprint(
        "digest-v5",
        "claude-opus-5-5",
        {"anthropic_effort": "default"},
        "task",
        10,
        15,
        0,
        920000,
        True,
        "",
        "TEXT",
    )


def test_refusal_fallback_is_passed_and_served_model_recorded(tmp_path, fam, monkeypatch):
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default")
    seen_kw: list[dict] = []

    def count_tokens(model, prompts, concurrency=8):
        return [10 for _ in prompts]

    def stream_json(prompts, *, on_result, **kw):
        seen_kw.append(kw)
        for i, (_s, user) in enumerate(prompts):
            line = next(ln[2:] for ln in user.splitlines() if ln.startswith("- "))
            on_result(
                i,
                {
                    "items": [{"statement": "s", "key": "", "where": "", "evidence": line}],
                    llm.SERVED_BY: "claude-opus-4-8",
                },
            )
        return Spend()

    monkeypatch.setattr(llm, "count_tokens", count_tokens)
    monkeypatch.setattr(llm, "stream_json", stream_json)
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert seen_kw[0]["fallbacks"] == "default"
    assert col.row("a")["summary_served_by"] == "claude-opus-4-8"
    assert col.diag["n_fallback_served_items"] == 1
    col = _run(tmp_path, {"a": _cells("a", 2)})  # cached: provenance survives a rerun
    assert col.row("a")["summary_served_by"] == "claude-opus-4-8"


def _refusing_on(models_refusing: set[str], seen: list[str]):
    """A stream_json fake: ``REFUSED_JSON`` for calls on a model in ``models_refusing``, else
    the first bundle line as evidence."""

    def stream_json(prompts, *, on_result, **kw):
        assert kw.get("mark_refusals") is True
        for i, (_s, user) in enumerate(prompts):
            seen.append(kw["model"])
            if kw["model"] in models_refusing:
                on_result(i, llm.REFUSED_JSON)
                continue
            line = next(ln[2:] for ln in user.splitlines() if ln.startswith("- "))
            on_result(i, {"items": [{"statement": "s", "key": "", "where": "", "evidence": line}]})
        return Spend()

    return stream_json


def test_refusal_model_serves_a_still_declined_digest(tmp_path, fam, monkeypatch):
    """plan 0037 J10: ``summ_fallback=default+<model>`` re-runs a call still declined after the
    server-side fallback on <model>, at the same level (no halving), and records it as served."""
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default+claude-sonnet-5")
    monkeypatch.setattr(
        llm, "count_tokens", lambda model, prompts, concurrency=8: [10] * len(prompts)
    )
    seen: list[str] = []
    monkeypatch.setattr(llm, "stream_json", _refusing_on({"claude-opus-5-5"}, seen))
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert seen == ["claude-opus-5-5", "claude-sonnet-5"]
    assert col.summaries["a"] and "a" not in col.unsummarized
    assert col.row("a")["summary_served_by"] == "claude-sonnet-5"
    assert col.extras()["digest_served_by"] == {"claude-sonnet-5": 1}
    assert col.diag["n_refusal_model_calls"] == 1 and col.diag["max_halvings"] == 0
    seen.clear()
    col = _run(tmp_path, {"a": _cells("a", 2)})  # cached: no call, provenance survives
    assert seen == [] and col.row("a")["summary_served_by"] == "claude-sonnet-5"


def test_refusal_model_declines_too_halves_as_before(tmp_path, fam, monkeypatch):
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default+claude-sonnet-5")
    monkeypatch.setattr(
        llm, "count_tokens", lambda model, prompts, concurrency=8: [10] * len(prompts)
    )
    seen: list[str] = []
    monkeypatch.setattr(
        llm, "stream_json", _refusing_on({"claude-opus-5-5", "claude-sonnet-5"}, seen)
    )
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert "a" in col.unsummarized and col.diag["n_digest_refused"] == 1
    assert seen[:2] == ["claude-opus-5-5", "claude-sonnet-5"]  # every level tries both


def test_no_refusal_model_no_retry(tmp_path, fam, monkeypatch):
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default")
    monkeypatch.setattr(
        llm, "count_tokens", lambda model, prompts, concurrency=8: [10] * len(prompts)
    )
    seen: list[str] = []
    monkeypatch.setattr(llm, "stream_json", _refusing_on({"claude-opus-5-5"}, seen))
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert "a" in col.unsummarized and set(seen) == {"claude-opus-5-5"}


@pytest.mark.parametrize("bad", ["sonnet", "default+", "none+"])
def test_summ_fallback_values(tmp_path, bad):
    s = digest.settings(_args(tmp_path, summ_fallback="default+claude-sonnet-5"))
    assert (s.server_fallback, s.refusal_model) == ("default", "claude-sonnet-5")
    s = digest.settings(_args(tmp_path, summ_fallback="default"))
    assert (s.server_fallback, s.refusal_model) == ("default", None)
    s = digest.settings(_args(tmp_path))
    assert (s.server_fallback, s.refusal_model) == (None, None)
    # the client-side re-run alone (no server-side ``fallbacks`` parameter)
    s = digest.settings(_args(tmp_path, summ_fallback="none+claude-opus-5"))
    assert (s.server_fallback, s.refusal_model) == (None, "claude-opus-5")
    with pytest.raises(SystemExit):
        digest.settings(_args(tmp_path, summ_fallback=bad))


def test_count_tokens_unavailable_falls_back_to_estimate(tmp_path, fam, monkeypatch):
    def no_count(model, prompts, concurrency=8):
        raise llm.JudgeConfigError("count_tokens needs an Anthropic model")

    fake = Fake(monkeypatch, tokens_per_char=0.1)
    monkeypatch.setattr(llm, "count_tokens", no_count)
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert col.summaries["a"] and fake.calls  # estimated size, still digested


def test_union_too_large_is_judged_on_the_chunks(tmp_path, fam, monkeypatch):
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_max", "25")
    fake = Fake(monkeypatch, tokens_per_char=1.0)

    def every_line(user):
        lines = [ln[2:] for ln in user.splitlines() if ln.startswith("- ")]
        return {
            "items": [{"statement": "s", "key": "", "where": "", "evidence": ln} for ln in lines]
        }

    fake.stream_json_orig = fake.stream_json

    def sj(prompts, *, on_result, **kw):
        for i, (_s, user) in enumerate(prompts):
            fake.calls.append(user)
            on_result(i, every_line(user))
        return Spend()

    monkeypatch.setattr(llm, "stream_json", sj)
    col = _run(tmp_path, {"a": _cells("a", 6)})
    # audit F3 (was: unsummarized, counted too long): a union too large for the final call is
    # judged on its chunk digests directly, every chunk claim kept
    assert "a" not in col.unsummarized and col.diag["n_items_chunk_direct"] == 1
    assert col.diag["n_digest_too_long"] == 0
    assert len(col.evidence["a"]) == len(_cells("a", 6))


def test_refusal_model_also_serves_under_stride(tmp_path, fam, monkeypatch):
    """Review r2: the stride ablation honours ``summ_fallback=default+<model>`` too (it was a
    silent no-op there): a declined digest is re-run on <model>, recorded as served, cached."""
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_overflow", "stride")
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default+claude-sonnet-5")
    seen: list[str] = []
    monkeypatch.setattr(llm, "stream_json", _refusing_on({"claude-opus-5-5"}, seen))
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert seen == ["claude-opus-5-5", "claude-sonnet-5"]
    assert col.summaries["a"] and "a" not in col.unsummarized
    assert col.row("a")["summary_served_by"] == "claude-sonnet-5"
    assert col.extras()["digest_served_by"] == {"claude-sonnet-5": 1}
    assert col.diag["n_refusal_model_calls"] == 1
    seen.clear()
    col = _run(tmp_path, {"a": _cells("a", 2)})  # cached: no call, provenance survives
    assert seen == [] and col.row("a")["summary_served_by"] == "claude-sonnet-5"


def test_stride_declined_twice_stays_unsummarized(tmp_path, fam, monkeypatch):
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_overflow", "stride")
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default+claude-sonnet-5")
    seen: list[str] = []
    monkeypatch.setattr(
        llm, "stream_json", _refusing_on({"claude-opus-5-5", "claude-sonnet-5"}, seen)
    )
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert "a" in col.unsummarized and seen == ["claude-opus-5-5", "claude-sonnet-5"]
    seen.clear()
    col = _run(tmp_path, {"a": _cells("a", 2)})  # a refusal is never cached: re-asked
    assert seen == ["claude-opus-5-5", "claude-sonnet-5"]


# ------------------------------------------------- Sonnet 5.5 fallback switch (Camila 2026-11-01)

LEGACY_VIA = "\x00pre_switch_rows_carry_no_served_via"


def test_default_refusal_model_is_sonnet_5_5_and_sonnet_5_is_retired():
    assert digest.REFUSAL_MODEL == "claude-sonnet-5-5"
    assert set(digest.RETIRED_REFUSAL_MODELS) == {"claude-sonnet-5"}
    assert digest.REFUSAL_MODEL not in digest.RETIRED_REFUSAL_MODELS


def test_stale_fallback_rule_both_ways():
    sb, via = llm.SERVED_BY, digest.SERVED_VIA
    stale = digest._stale_fallback
    # stale: a pre-switch Sonnet 5 row; a client row of another model; a client row, no fallback
    assert stale({"items": [], sb: "claude-sonnet-5"}, "claude-sonnet-5-5")
    assert stale({"items": [], sb: "claude-sonnet-5", via: "client"}, "claude-sonnet-5-5")
    assert stale({"items": [], sb: "claude-sonnet-5-5", via: "client"}, None)
    # kept: the run's own client model; server-side rows (tagged or pre-switch); unserved rows
    assert not stale({"items": [], sb: "claude-sonnet-5-5", via: "client"}, "claude-sonnet-5-5")
    assert not stale({"items": [], sb: "claude-sonnet-5", via: "client"}, "claude-sonnet-5")
    assert not stale({"items": [], sb: "claude-opus-4-8", via: "server"}, "claude-sonnet-5-5")
    assert not stale({"items": [], sb: "claude-opus-4-8"}, "claude-sonnet-5-5")
    assert not stale({"items": []}, "claude-sonnet-5-5") and not stale(None, None)


@pytest.mark.parametrize("overflow", ["hierarchical", "stride"])
def test_retired_sonnet5_digest_is_a_cache_miss_rerun_on_sonnet55(
    tmp_path, fam, monkeypatch, overflow
):
    """A digest Sonnet 5 served before the switch (no SERVED_VIA) is re-asked under the Sonnet
    5.5 default, served by Sonnet 5.5 and cached; a rerun then hits the cache."""
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_overflow", overflow)
    monkeypatch.setattr(
        llm, "count_tokens", lambda model, prompts, concurrency=8: [10] * len(prompts)
    )
    seen: list[str] = []
    monkeypatch.setattr(llm, "stream_json", _refusing_on({"claude-opus-5-5"}, seen))
    # the pre-switch run: Sonnet 5 serves, the row carries no SERVED_VIA
    real_via = digest.SERVED_VIA
    monkeypatch.setattr(digest, "SERVED_VIA", LEGACY_VIA)
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default+claude-sonnet-5")
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert seen == ["claude-opus-5-5", "claude-sonnet-5"]
    assert col.row("a")["summary_served_by"] == "claude-sonnet-5"
    # after the switch: the family default names Sonnet 5.5
    monkeypatch.setattr(digest, "SERVED_VIA", real_via)
    monkeypatch.setitem(
        digest.FAMILY_DEFAULTS[FAM], "summ_fallback", f"default+{digest.REFUSAL_MODEL}"
    )
    seen.clear()
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert seen == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert col.row("a")["summary_served_by"] == "claude-sonnet-5-5"
    assert col.extras()["digest_served_by"] == {"claude-sonnet-5-5": 1}
    seen.clear()
    col = _run(tmp_path, {"a": _cells("a", 2)})  # the Sonnet 5.5 row is a hit
    assert seen == [] and col.row("a")["summary_served_by"] == "claude-sonnet-5-5"
    # ... and a run that asks for Sonnet 5 explicitly does not reuse the Sonnet 5.5 row
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default+claude-sonnet-5")
    col = _run(tmp_path, {"a": _cells("a", 2)})
    assert seen == ["claude-opus-5-5", "claude-sonnet-5"]


@pytest.mark.parametrize("overflow", ["hierarchical", "stride"])
def test_pre_switch_server_served_and_unserved_digests_stay_cached(
    tmp_path, fam, monkeypatch, overflow
):
    """The other direction: a pre-switch row the SERVER-side fallback served (no SERVED_VIA,
    SERVED_BY not retired) and a row no fallback served are reused after the switch."""
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_overflow", overflow)
    monkeypatch.setattr(
        llm, "count_tokens", lambda model, prompts, concurrency=8: [10] * len(prompts)
    )

    def served(prompts, *, on_result, **kw):
        for i, (_s, user) in enumerate(prompts):
            line = next(ln[2:] for ln in user.splitlines() if ln.startswith("- "))
            item = {"statement": "s", "key": "", "where": "", "evidence": line}
            res: dict = {"items": [item]}
            if "item a" in user or " a L" in user:
                res[llm.SERVED_BY] = "claude-opus-4-8"
            on_result(i, res)
        return Spend()

    monkeypatch.setattr(digest, "SERVED_VIA", LEGACY_VIA)
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_fallback", "default+claude-sonnet-5")
    monkeypatch.setattr(llm, "stream_json", served)
    cells = {"a": _cells("a", 2), "b": _cells("b", 2)}
    col = _run(tmp_path, cells)
    assert col.row("a")["summary_served_by"] == "claude-opus-4-8"
    monkeypatch.undo()  # back to the real SERVED_VIA and the default fallback ...
    monkeypatch.setattr(digest, "COUNT_TOKENS_ABOVE", 0.0)
    monkeypatch.setitem(
        digest.FAMILY_DEFAULTS,
        FAM,
        {
            "summ_overflow": overflow,
            "summ_token_cap": "1000",
            "summ_max": "5",
            "summ_layers": "joint",
            "summ_fallback": f"default+{digest.REFUSAL_MODEL}",
        },
    )
    monkeypatch.setattr(
        llm, "count_tokens", lambda model, prompts, concurrency=8: [10] * len(prompts)
    )
    calls: list[str] = []

    def never(prompts, *, on_result, **kw):
        calls.extend(u for _s, u in prompts)
        return Spend()

    monkeypatch.setattr(llm, "stream_json", never)
    col = _run(tmp_path, cells)
    assert calls == []  # ... and neither digest is re-asked
    assert col.row("a")["summary_served_by"] == "claude-opus-4-8"
    assert col.summaries["b"] and not col.row("b").get("summary_served_by")


# ------------------------------------------- plan 0093: a rerun replays the halving levels

FAILED = object()  # a RuleFake rule's "the call failed" (stream_json reports None)


class RuleFake(Fake):
    """``Fake`` whose ``rule(user)`` scripts a call first (``FAILED`` = a failed call, ``None`` =
    no rule); an unscripted call cites its first ``n_lines`` bundle lines."""

    def __init__(self, monkeypatch, rule, tokens_per_char: float = 1.0, n_lines: int = 1):
        super().__init__(monkeypatch, tokens_per_char)
        self.rule = rule
        self.n_lines = n_lines

    def stream_json(self, prompts, *, on_result, **kw):
        assert kw.get("mark_refusals") is True and kw.get("attempts") == digest.DIGEST_ATTEMPTS
        for i, (_s, user) in enumerate(prompts):
            self.calls.append(user)
            hit = self.rule(user)
            if hit is FAILED:
                on_result(i, None)
            elif hit is not None:
                on_result(i, hit)
            else:
                lines = [ln[2:] for ln in user.splitlines() if ln.startswith("- ")]
                on_result(
                    i,
                    {
                        "items": [
                            {"statement": "s", "key": "", "where": "", "evidence": ln}
                            for ln in lines[: self.n_lines]
                        ]
                    },
                )
        return Spend()


def _is_final(user: str) -> bool:
    return "(support:" in user


def _heads(user: str) -> list[str]:
    return [ln.split("]")[0] + "]" for ln in user.splitlines() if ln.startswith("[L")]


def _outcome(col: digest.Collapse) -> dict:
    """What a family judges of a Collapse, plus the counters main already keeps rerun-stable
    (``n_fallback_events`` is asserted apart: main counts 0 on every rerun)."""
    keys = (
        "max_halvings",
        "n_items_chunk_direct",
        "n_digest_refused",
        "n_digest_too_long",
    )
    return {
        "summaries": col.summaries,
        "statements": col.statements,
        "evidence": {i: [(e.where, e.text) for e in ev] for i, ev in col.evidence.items()},
        "reasons": col.reasons,
        "unsummarized": col.unsummarized,
        "empty": col.empty,
        "partial": col.partial,
        "refused_layers": col.refused_layers,
        "served_by": col.served_by,
        "chunks": col.chunks,
        "diag": {k: col.diag[k] for k in keys},
    }


def _n_rows(tmp_path) -> int:
    return len((tmp_path / "c.jsonl").read_text().splitlines())


def _rerun_is_first_pass(tmp_path, fake, cells, first, resent: int = 0, events: bool = True):
    """Run again over the same cache: the same outcome, ``resent`` calls (0: nothing sent and no
    cache row appended) and, with ``events``, the same ``n_fallback_events``."""
    n_calls, n_rows = len(fake.calls), _n_rows(tmp_path)
    again = _run(tmp_path, cells)
    assert _outcome(again) == _outcome(first)
    if events:
        assert again.diag["n_fallback_events"] == first.diag["n_fallback_events"]
    assert len(fake.calls) == n_calls + resent
    if not resent:
        assert _n_rows(tmp_path) == n_rows
    return again


def test_rerun_of_refused_final_moves_down_a_level_scenario(tmp_path, fam, monkeypatch):
    """The scenario of ``test_refused_final_moves_down_a_level``, run twice. A guard that passes
    on main: there the item ends at persisted level 2 (its level-2 union is too large for a final
    call), and that level alone holds its best chunk claims."""
    fake = Fake(monkeypatch, tokens_per_char=1.0)
    fake.script["(support:"] = llm.REFUSED_JSON  # finals are refused, chunks are not
    cells = {"a": _cells("a", 6)}
    col = _run(tmp_path, cells)
    assert "a" not in col.unsummarized and col.diag["n_items_chunk_direct"] == 1
    _rerun_is_first_pass(tmp_path, fake, cells, col, events=False)


def test_rerun_after_a_refused_final_at_every_level(tmp_path, fam, monkeypatch):
    """Fails on main: every final is refused, so the item runs out of halvings (persisted level
    3) and is judged on its level-2 chunk claims; main's rerun skips it (unsummarized, refused)."""
    fake = RuleFake(monkeypatch, lambda u: llm.REFUSED_JSON if _is_final(u) else None)
    cells = {"a": _cells("a", 6)}
    col = _run(tmp_path, cells)
    assert col.diag["max_halvings"] == 3 and col.diag["n_fallback_events"] == 3
    assert col.summaries["a"] and not col.unsummarized and "a" not in col.partial
    assert col.diag["n_items_chunk_direct"] == 1 and len(col.evidence["a"]) == 6
    _rerun_is_first_pass(tmp_path, fake, cells, col)


def test_rerun_after_a_refused_final_at_level_2(tmp_path, fam, monkeypatch):
    """Fails on main: the chunk holding L20 is refused at levels 0 and 1, level 2 serves every
    chunk and its final is refused (persisted level 3): judged on the level-2 claims."""

    def rule(user):
        if _is_final(user):
            return llm.REFUSED_JSON
        if "[L20 pos 0]" in user and len(_heads(user)) > 3:  # the level 0 / level 1 chunk
            return llm.REFUSED_JSON
        return None

    fake = RuleFake(monkeypatch, rule)
    cells = {"a": _cells("a", 6)}
    col = _run(tmp_path, cells)
    assert col.diag["max_halvings"] == 3 and col.summaries["a"] and "a" not in col.partial
    assert len(col.evidence["a"]) == 6  # one claim per level-2 chunk (a layer each)
    _rerun_is_first_pass(tmp_path, fake, cells, col)


def test_rerun_after_a_refused_chunk_at_levels_1_and_2(tmp_path, fam, monkeypatch):
    """Fails on main: level 0 serves every chunk and its final is refused; at levels 1 and 2 the
    chunk holding L20 is refused. The item is judged on the level-0 claims (nothing lost), which
    only a replay of level 0 rebuilds."""

    def rule(user):
        if _is_final(user):
            return llm.REFUSED_JSON
        if "[L20 pos 0]" in user and len(_heads(user)) < 12:  # not the level-0 chunk
            return llm.REFUSED_JSON
        return None

    fake = RuleFake(monkeypatch, rule)
    cells = {"a": _cells("a", 6)}
    col = _run(tmp_path, cells)
    assert col.diag["max_halvings"] == 3 and col.summaries["a"] and "a" not in col.partial
    assert len(col.evidence["a"]) == 2  # the two level-0 chunks' claims
    _rerun_is_first_pass(tmp_path, fake, cells, col)


def test_rerun_out_of_halvings_is_judged_on_the_remembered_chunks(tmp_path, fam, monkeypatch):
    """Fails on main: the chunk holding L20 is refused at EVERY level (out of halvings). Both
    passes judge the item on its remembered chunk claims, L20 partial and refused; main's rerun
    leaves it unsummarized."""
    fake = Fake(monkeypatch, tokens_per_char=1.0)
    fake.script["L0 p"] = llm.REFUSED_JSON
    cells = {"a": _cells("a", 6)}
    col = _run(tmp_path, cells)
    assert col.diag["max_halvings"] == 3 and col.summaries["a"] and not col.unsummarized
    assert col.partial == {"a": [20]} and col.refused_layers == {"a": [20]}
    assert col.diag["n_items_chunk_direct"] == 1 and col.diag["n_digest_refused"] == 0
    again = _rerun_is_first_pass(tmp_path, fake, cells, col)
    assert again.partial == {"a": [20]} and again.diag["n_fallback_events"] == 3
    _rerun_is_first_pass(tmp_path, fake, cells, col)  # and a third pass


def test_rerun_too_long_single_then_served_level_1(tmp_path, fam, monkeypatch):
    """A guard that passes on main: a too-long single call (level 0), then a served level 1."""
    fake = Fake(monkeypatch, tokens_per_char=0.3)
    cells = {"a": _cells("a", 4)}
    first_user = digest.render_user(digest._render([digest._group(c) for c in cells["a"]]))
    fake.exact[first_user] = llm.TOO_LONG_JSON
    col = _run(tmp_path, cells)
    assert col.chunks.get("a", 0) >= 2 and col.diag["n_fallback_events"] == 1
    again = _rerun_is_first_pass(tmp_path, fake, cells, col, events=False)
    assert again.diag["n_digest_too_long"] == 0


def test_rerun_counts_the_fallback_events_of_the_first_pass(tmp_path, fam, monkeypatch):
    """Fails on main (which counts 0 on a rerun): ``n_fallback_events`` is rerun-stable, here
    after a too-long single call and after a refusal at every level."""
    fake = Fake(monkeypatch, tokens_per_char=0.3)
    cells = {"a": _cells("a", 4)}
    first_user = digest.render_user(digest._render([digest._group(c) for c in cells["a"]]))
    fake.exact[first_user] = llm.TOO_LONG_JSON
    col = _run(tmp_path, cells)
    again = _rerun_is_first_pass(tmp_path, fake, cells, col)
    assert again.diag["n_fallback_events"] == 1
    other = tmp_path / "every"
    other.mkdir()
    fake = Fake(monkeypatch, tokens_per_char=1.0)
    fake.script["word"] = llm.REFUSED_JSON
    col = _run(other, {"a": _cells("a", 6)})
    again = _rerun_is_first_pass(other, fake, {"a": _cells("a", 6)}, col)
    assert again.diag["n_fallback_events"] == 3 and again.unsummarized == {"a"}


def test_rerun_too_long_at_every_level_keeps_its_reason(tmp_path, fam, monkeypatch):
    """A guard that passes on main: every call too long, the item unsummarized as too long on
    both passes (the replayed levels carry the persisted kind)."""
    fake = Fake(monkeypatch, tokens_per_char=1.0)
    fake.script["word"] = llm.TOO_LONG_JSON
    cells = {"a": _cells("a", 6)}
    col = _run(tmp_path, cells)
    assert col.unsummarized == {"a"} and col.reasons == {"a": "too_long"}
    assert col.diag["n_digest_too_long"] == 1
    _rerun_is_first_pass(tmp_path, fake, cells, col, events=False)


def test_rerun_after_failed_then_refused_single(tmp_path, fam, monkeypatch):
    """A guard that passes on main (it pins the replay rule: a replayed level never reads its
    single row). Run 1: the single call fails (a ``None`` row). Run 2: the same call is refused
    and level 1 serves. Run 3 equals run 2, sends nothing, appends nothing."""
    cells = {"a": _cells("a", 4)}
    first_user = digest.render_user(digest._render([digest._group(c) for c in cells["a"]]))
    answer: dict[str, object] = {"single": FAILED}
    fake = RuleFake(
        monkeypatch, lambda u: answer["single"] if u == first_user else None, tokens_per_char=0.3
    )
    col1 = _run(tmp_path, cells)
    assert col1.unsummarized == {"a"} and col1.diag["max_halvings"] == 0
    answer["single"] = llm.REFUSED_JSON
    col2 = _run(tmp_path, cells)
    assert col2.summaries["a"] and col2.chunks.get("a", 0) >= 2
    assert col2.diag["max_halvings"] == 1
    _rerun_is_first_pass(tmp_path, fake, cells, col2, events=False)


def test_rerun_after_failed_then_refused_chunk(tmp_path, fam, monkeypatch):
    """A guard that passes on main (the replay rule again: a failed chunk row at a level a later
    pass bumped past is the refusal marker, never the end of the item). Run 1: a level-0 chunk
    fails. Run 2: it is refused and level 1 serves. Run 3 equals run 2 and sends nothing."""
    cells = {"a": _cells("a", 6)}
    answer: dict[str, object] = {"big": FAILED}
    fake = RuleFake(
        monkeypatch, lambda u: answer["big"] if len(_heads(u)) == 12 else None, n_lines=2
    )
    col1 = _run(tmp_path, cells)
    assert col1.partial == {"a": [20, 24, 28, 32]} and col1.diag["max_halvings"] == 0
    answer["big"] = llm.REFUSED_JSON
    col2 = _run(tmp_path, cells)
    assert col2.summaries["a"] and "a" not in col2.partial and col2.chunks == {"a": 3}
    assert col2.diag["max_halvings"] == 1 and col2.diag["n_items_chunk_direct"] == 0
    _rerun_is_first_pass(tmp_path, fake, cells, col2, events=False)


def test_rerun_chunk_direct_through_a_failed_chunk_keeps_the_better_level(
    tmp_path, fam, monkeypatch
):
    """Fails on main: level 0 serves every chunk and its final is refused; at level 1 the chunk
    holding L20 FAILS, so the item ends there (persisted level 1), judged on the level-0 claims
    (nothing lost). Main's rerun starts at level 1 and judges the worse level-1 claims (L20 and
    L24 partial). The failed call is re-sent, as before (one call, one ``None`` row)."""

    def rule(user):
        if _is_final(user):
            return llm.REFUSED_JSON
        if _heads(user)[0] == "[L20 pos 0]" and len(_heads(user)) == 6:  # level 1, chunk 1
            return FAILED
        return None

    fake = RuleFake(monkeypatch, rule, n_lines=2)
    cells = {"a": _cells("a", 6)}
    col = _run(tmp_path, cells)
    assert col.diag["max_halvings"] == 1 and col.diag["n_items_chunk_direct"] == 1
    assert col.summaries["a"] and "a" not in col.partial and len(col.evidence["a"]) == 4
    n_rows = _n_rows(tmp_path)
    again = _rerun_is_first_pass(tmp_path, fake, cells, col, resent=1)
    assert "a" not in again.partial and _n_rows(tmp_path) == n_rows + 1
    assert len(_heads(fake.calls[-1])) == 6 and "[L20 pos 0]" in fake.calls[-1]


def test_rerun_chunk_direct_at_level_2_through_a_failed_chunk(tmp_path, fam, monkeypatch):
    """Fails on main: finals refused at levels 0 and 1, a failed chunk at level 2 (persisted
    level 2). The item is judged on the level-1 claims; main's rerun judges the level-2 ones
    with L20 partial."""

    def rule(user):
        if _is_final(user):
            return llm.REFUSED_JSON
        if _heads(user)[0] == "[L20 pos 0]" and len(_heads(user)) == 3:  # level 2, chunk 1
            return FAILED
        return None

    fake = RuleFake(monkeypatch, rule)
    cells = {"a": _cells("a", 6)}
    col = _run(tmp_path, cells)
    assert col.diag["max_halvings"] == 2 and col.diag["n_items_chunk_direct"] == 1
    assert "a" not in col.partial and len(col.evidence["a"]) == 3  # the three level-1 chunks
    _rerun_is_first_pass(tmp_path, fake, cells, col, resent=1)


def test_rerun_union_with_a_refused_layer_part(tmp_path, fam, monkeypatch):
    """Fails on main (the real failure shape, ``summ_layers=union``): of six layer parts, L40
    is refused at every level (the item's one refused layer) and L24 runs out of halvings on
    refused finals, judged on its chunk claims. Main's rerun loses L24 too: two refused layers of
    six are over ``PARTIAL_UNDECIDED_SHARE``, so the item goes undecided."""
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_layers", "union")
    cells = {
        "a": [
            Cell("a", layer, p, (f"word a L{layer} p{p} " + "x" * 40,), None, None, None)
            for layer in (20, 24, 28, 32, 36, 40)
            for p in range(8)
        ]
    }

    def rule(user):
        if "[L40 " in user:
            return llm.REFUSED_JSON
        if "[L24 " not in user:
            return None
        if _is_final(user) or len(_heads(user)) == 8:  # the L24 single call and every final
            return llm.REFUSED_JSON
        line = next(ln[2:] for ln in user.splitlines() if ln.startswith("- "))
        return {
            "items": [{"statement": "s", "key": "", "where": "", "evidence": line}],
            llm.SERVED_BY: "claude-opus-4-8",
        }

    fake = RuleFake(monkeypatch, rule)
    col = _run(tmp_path, cells)
    assert col.summaries["a"] and not col.unsummarized
    assert col.partial == {"a": [40]} and col.refused_layers == {"a": [40]}
    assert col.served_by == {"a": "claude-opus-4-8"}
    assert any("L24" in e.where for e in col.evidence["a"])
    again = _rerun_is_first_pass(tmp_path, fake, cells, col)
    assert again.partial == {"a": [40]} and again.refused_layers == {"a": [40]}
    assert again.served_by == {"a": "claude-opus-4-8"}


# ---------------------------------------------------------------- plan 0096: any refusal model

LUNA = "openai/gpt-6-luna"


def test_summ_fallback_accepts_any_model_id(tmp_path):
    for v, want in (
        (f"none+{LUNA}", (None, LUNA)),
        (f"default+{LUNA}", ("default", LUNA)),
        ("default+gpt-5", ("default", "gpt-5")),
        ("none+gpt-5", (None, "gpt-5")),
    ):
        s = digest.settings(_args(tmp_path, summ_fallback=v))
        assert (s.server_fallback, s.refusal_model) == want
    with pytest.raises(SystemExit) as e:
        digest.settings(_args(tmp_path, summ_fallback="server+x"))
    assert e.value.code == 2


def _recording(models_refusing: set[str], seen: list[tuple]):
    inner = _refusing_on(models_refusing, [])

    def stream_json(prompts, *, on_result, **kw):
        seen.append((kw["model"], kw["reasoning"], kw["max_tokens"]))
        return inner(prompts, on_result=on_result, **kw)

    return stream_json


@pytest.mark.parametrize("overflow", ["hierarchical", "stride"])
def test_cross_route_refusal_model_sends_its_routes_reasoning(tmp_path, fam, monkeypatch, overflow):
    """The client-side re-run on a model of the other route sends ``digest_reasoning`` of that
    model at the run's effort (plan 0096 R9: no reasoning at the default effort for a non-Claude
    model); one on the digest model's route sends ``s.reasoning`` as before. The cap is kept,
    the fingerprint and the ``SERVED_VIA`` tag do not move."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setitem(digest.FAMILY_DEFAULTS[FAM], "summ_overflow", overflow)
    monkeypatch.setattr(
        llm, "count_tokens", lambda model, prompts, concurrency=8: [10] * len(prompts)
    )
    default = {"anthropic_effort": digest.DEFAULT_EFFORT}
    for fb, want in ((LUNA, None), ("claude-sonnet-5", default)):
        seen: list[tuple] = []
        monkeypatch.setattr(llm, "stream_json", _recording({"claude-opus-5-5"}, seen))
        out = tmp_path / fb.replace("/", "_")
        out.mkdir()
        col = _run(out, {"a": _cells("a", 2)}, summ_fallback=f"none+{fb}")
        assert seen == [
            ("claude-opus-5-5", default, digest.MAX_TOKENS),
            (fb, want, digest.MAX_TOKENS),
        ]
        assert col.row("a")["summary_served_by"] == fb
        with Cache(out / "c.jsonl") as cache:
            results = [r.get("result") for rows in cache._rows.values() for r in rows]
        served = [r for r in results if isinstance(r, dict) and r.get(llm.SERVED_BY)]
        assert [(r[llm.SERVED_BY], r[digest.SERVED_VIA]) for r in served] == [(fb, "client")]
    # the fingerprint does not key the fallback: a run with Sonnet as the refusal model finds
    # the Luna-served row stale (re-asked), exactly as for two Claude refusal models
    seen = []
    monkeypatch.setattr(llm, "stream_json", _recording({"claude-opus-5-5"}, seen))
    col = _run(tmp_path / LUNA.replace("/", "_"), {"a": _cells("a", 2)},
               summ_fallback="none+claude-sonnet-5")  # fmt: skip
    assert [m for m, _r, _c in seen] == ["claude-opus-5-5", "claude-sonnet-5"]


def test_cross_route_refusal_model_needs_its_key_before_the_first_call(tmp_path, fam, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    seen: list[tuple] = []
    monkeypatch.setattr(llm, "stream_json", _recording(set(), seen))
    monkeypatch.setattr(
        llm, "count_tokens", lambda model, prompts, concurrency=8: [10] * len(prompts)
    )
    with pytest.raises(llm.JudgeConfigError, match="OPENROUTER_API_KEY"):
        _run(tmp_path, {"a": _cells("a", 2)}, summ_fallback=f"none+{LUNA}")
    assert seen == []
    _run(
        tmp_path, {"a": _cells("a", 2)}, dry=True, summ_fallback=f"none+{LUNA}"
    )  # never on a dry run
    _run(tmp_path, {"a": _cells("a", 2)}, summ_fallback="none+claude-sonnet-5")  # same route: none
    assert [m for m, _r, _c in seen] == ["claude-opus-5-5"]
