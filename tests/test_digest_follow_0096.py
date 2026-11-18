"""Plan 0096 part 2: the summarizer follows a non-Claude override judge, a non-Claude digest
model runs as plan 0059 Arm B ran (no reasoning field, no family-default fallback), and
``summ_context``. Ported from the plan-0059 branch's digest tests where they exist."""

import dataclasses
import json
from pathlib import Path

import pytest
from conftest import native_args
from test_fallback_0096 import ALL, Run

from wsbench import digest, llm, mcjudge, registry, runner
from wsbench.cache import Cache
from wsbench.cli import main
from wsbench.judge_config import JudgeConfig, ResolvedJudge, resolve
from wsbench.llm import Spend
from wsbench.readouts import Cell
from wsbench.registry import EvalSpec, JudgeArgs, register
from wsbench.results import FamilyResult

FAM = "test_follow_family"
LUNA = "openai/gpt-6-luna"
OR_MODEL = "deepseek/deepseek-v4-flash"
OPUS55, SONNET, SONNET55, OPUS5 = (
    "claude-opus-5-5",
    "claude-sonnet-5",
    "claude-sonnet-5-5",
    "claude-opus-5",
)
PINNED = resolve(JudgeConfig(prompt_version="t"))


def _args(tmp_path: Path, judge: ResolvedJudge | None = PINNED, **extra: str) -> JudgeArgs:
    return native_args(
        readouts=tmp_path / "r.jsonl",
        out=tmp_path / "out",
        judge=judge,
        layers=None,
        items=None,
        limit=0,
        allow_missing=False,
        concurrency=1,
        rpm=1.0,
        dry_run=False,
        extra={"aggregate": "summary", **extra},
    )


def _family_args(tmp_path: Path, family: str, flag: str | None = None, **extra: str) -> JudgeArgs:
    """The JudgeArgs ``runner.judge_family`` builds for a real family under ``judge_model=``."""
    spec = registry.FAMILIES[family]
    args = _args(tmp_path, judge=resolve(spec.judge, flag=flag, env={}), **extra)
    return dataclasses.replace(args, aux_models=spec.judge.aux_models)


# ---------------------------------------------------------------- digest_reasoning / settings


def test_digest_reasoning_table(monkeypatch):
    for model in (OPUS55, SONNET):
        for effort in digest.EFFORTS:
            assert digest.digest_reasoning(model, effort) == {"anthropic_effort": effort}
    for model in (LUNA, OR_MODEL):
        assert digest.digest_reasoning(model, "default") is None
        for effort in ("low", "medium", "high"):
            assert digest.digest_reasoning(model, effort) == {"effort": effort}
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "wif")  # the openai route: as OpenRouter
    assert digest.digest_reasoning(LUNA, "default") is None
    assert digest.digest_reasoning(LUNA, "low") == {"effort": "low"}
    assert digest.digest_reasoning(OPUS55, "low") == {"anthropic_effort": "low"}


def test_claude_digest_settings_and_fingerprint_inputs_are_unchanged(tmp_path, real_families):
    s = digest.settings(_args(tmp_path))
    assert s.model == OPUS55 and s.reasoning == {"anthropic_effort": "default"}
    assert digest.settings(_args(tmp_path, summ_effort="low")).reasoning == {
        "anthropic_effort": "low"
    }
    # nothing new reaches to_json (the digest fingerprint and config.summarizer) by default
    assert "context" not in s.to_json() and "effort" not in s.to_json()
    assert digest.pinned(_args(tmp_path))
    for fam in ("agentic_misalignment", "jailbreak_recognition"):
        s = digest.settings(_family_args(tmp_path, fam), fam)
        assert (s.model, s.fallback) == (SONNET, f"none+{OPUS5}")
        assert s.reasoning == {"anthropic_effort": "default"}
    s = digest.settings(_family_args(tmp_path, "introspection"), "introspection")
    assert (s.model, s.fallback) == (OPUS55, f"default+{SONNET55}")


def test_non_claude_digest_runs_as_arm_b(tmp_path):
    s = digest.settings(_args(tmp_path, summ_model=OR_MODEL))
    assert s.reasoning is None and s.fallback == "none"
    for level in ("low", "medium", "high"):
        s = digest.settings(_args(tmp_path, summ_model=OR_MODEL, summ_effort=level))
        assert s.reasoning == {"effort": level}
    assert not digest.pinned(_args(tmp_path, summ_model=OR_MODEL))


def test_family_default_fallback_is_off_for_a_non_claude_digest(tmp_path):
    for fam in ("jailbreak_recognition", "agentic_misalignment", "introspection"):
        assert "+" in digest.FAMILY_DEFAULTS[fam]["summ_fallback"]
        a = _args(tmp_path, summ_model=LUNA)
        s = digest.settings(a, fam)
        assert s.fallback == "none" and s.refusal_model is None and s.server_fallback is None
        assert digest.config(a, "prose", family=fam)["summarizer"]["fallback"] == "none"
        # a Claude digest keeps the family's refusal rescue
        assert (
            digest.settings(_args(tmp_path), fam).fallback
            == digest.FAMILY_DEFAULTS[fam]["summ_fallback"]
        )


def test_explicit_fallback_with_a_non_claude_digest(tmp_path, capsys):
    for fb in ("default", f"default+{SONNET}", f"default+{OR_MODEL}"):
        for fam in (None, "jailbreak_recognition"):
            with pytest.raises(SystemExit) as e:
                digest.settings(_args(tmp_path, summ_model=LUNA, summ_fallback=fb), fam)
            assert e.value.code == 2
        with pytest.raises(SystemExit):
            runner.parse_opts([f"summ_model={LUNA}", f"summ_fallback={fb}"])
    assert "needs a claude-* digest model" in capsys.readouterr().err
    # an explicit none / none+<model> is honoured, on either route, family default or not
    for fam in (None, "jailbreak_recognition"):
        for fb, want in (("none", None), (f"none+{OPUS5}", OPUS5), (f"none+{OR_MODEL}", OR_MODEL)):
            s = digest.settings(_args(tmp_path, summ_model=LUNA, summ_fallback=fb), fam)
            assert s.fallback == fb and s.refusal_model == want and s.server_fallback is None
    # an explicit value equal to the family default is explicit: kept
    fam = "jailbreak_recognition"
    explicit = digest.FAMILY_DEFAULTS[fam]["summ_fallback"]
    s = digest.settings(_args(tmp_path, summ_model=LUNA, summ_fallback=explicit), fam)
    assert s.fallback == explicit


def test_reasoning_on_is_digest_reasoning_at_the_runs_effort(tmp_path):
    """R9: every client-side re-run sends ``digest_reasoning(<its model>, summ_effort)``."""
    s = digest.settings(_args(tmp_path))  # a Claude digest at the default effort
    assert s.reasoning_on(SONNET55) == s.reasoning == {"anthropic_effort": "default"}
    assert s.reasoning_on(LUNA) is None
    s = digest.settings(_args(tmp_path, summ_effort="low"))
    assert s.reasoning_on(SONNET55) == {"anthropic_effort": "low"}
    assert s.reasoning_on(LUNA) == {"effort": "low"}
    s = digest.settings(_args(tmp_path, summ_model=LUNA))  # a non-Claude digest
    assert s.reasoning is None
    assert s.reasoning_on(OPUS5) == {"anthropic_effort": "default"}
    assert s.reasoning_on(OR_MODEL) is None
    s = digest.settings(_args(tmp_path, summ_model=LUNA, summ_effort="high"))
    assert s.reasoning_on(OPUS5) == {"anthropic_effort": "high"}
    assert s.reasoning_on(OR_MODEL) == {"effort": "high"}


# ---------------------------------------------------------------- summ_context


def test_summ_context(tmp_path):
    assert (digest.CONTEXT_WINDOW, digest.MIN_CONTEXT) == (1_000_000, 128_000)
    s = digest.settings(_args(tmp_path, summ_context="200000"))
    assert s.context == 200_000 and s.to_json()["context"] == 200_000
    assert digest.settings(_args(tmp_path)).context == digest.CONTEXT_WINDOW
    assert "context" not in digest.settings(_args(tmp_path, summ_context="1000000")).to_json()
    assert digest.settings(_args(tmp_path, summ_context=str(digest.MIN_CONTEXT))).context
    assert digest.settings(_args(tmp_path, summ_context="1050000")).context == 1_050_000
    for bad in ("127999", "0", "x"):
        with pytest.raises(SystemExit) as e:
            digest.settings(_args(tmp_path, summ_context=bad))
        assert e.value.code == 2
    assert "summ_context" in digest.KNOWN_KEYS
    assert runner.parse_opts(["summ_context=200000"])["summ_context"] == "200000"


class Fake:
    """count_tokens: ``tpc`` x len(user); stream_json answers the first two bundle lines."""

    def __init__(self, monkeypatch, tpc: float):
        self.calls: list[dict] = []
        self.tpc = tpc
        monkeypatch.setattr(llm, "count_tokens", self.count_tokens)
        monkeypatch.setattr(llm, "stream_json", self.stream_json)

    def count_tokens(self, model, prompts, concurrency=8):
        return [int(len(u) * self.tpc) for _s, u in prompts]

    def stream_json(self, prompts, *, on_result, **kw):
        for i, (_s, user) in enumerate(prompts):
            self.calls.append({"user": user, **kw})
            lines = [ln[2:] for ln in user.splitlines() if ln.startswith("- ")]
            items = [{"statement": "s", "key": "", "where": "", "evidence": ln} for ln in lines[:2]]
            on_result(i, {"items": items})
        return Spend()


def _cells(item: str, n_layers: int) -> list[Cell]:
    return [
        Cell(item, 20 + 4 * L, p, (f"word {item} L{L} p{p} " + "x" * 40,), None, None, None)
        for L in range(n_layers)
        for p in range(3)
    ]


def _collapse(tmp_path, cells_by_item, judge: ResolvedJudge | None = PINNED, **extra):
    tmp_path.mkdir(parents=True, exist_ok=True)
    with Cache(tmp_path / "c.jsonl") as cache:
        return digest.collapse(
            FAM,
            cells_by_item,
            args=_args(tmp_path, judge=judge, **extra),
            cache=cache,
            spend=Spend(),
            preflight=None,
            task_note="",
        )


@pytest.fixture
def fam(monkeypatch):
    monkeypatch.setitem(
        digest.FAMILY_DEFAULTS,
        FAM,
        {"summ_overflow": "hierarchical", "summ_max": "5", "summ_layers": "joint"},
    )


def test_summ_context_sets_the_hierarchical_budget(tmp_path, fam, monkeypatch, capsys):
    # one ~60k-token bundle: one call at the default 1M context; chunks at summ_context=128k
    # (budget 128 000 - 32 000 - 64 000 = 32 000)
    monkeypatch.setattr(digest, "COUNT_TOKENS_ABOVE", 0.0)
    fake = Fake(monkeypatch, tpc=60.0)
    cells = {"a": _cells("a", 6)}
    col = _collapse(tmp_path / "big", cells)
    assert not col.chunks and len(fake.calls) == 1
    col = _collapse(tmp_path / "small", cells, summ_context=str(digest.MIN_CONTEXT))
    assert "budget 32000 tokens" in capsys.readouterr().out
    assert col.chunks.get("a", 0) >= 2


# ---------------------------------------------------------------- the follow rule


def test_digest_model_order(tmp_path, monkeypatch):
    aux = {digest.AUX_ROLE: SONNET}
    luna = resolve(JudgeConfig(), flag=LUNA, env={})
    assert not luna.pinned
    for with_aux in (False, True):
        pin = aux[digest.AUX_ROLE] if with_aux else digest.DEFAULT_MODEL

        def model(judge, with_aux=with_aux, **extra):
            a = _args(tmp_path, judge=judge, **extra)
            if with_aux:
                a = dataclasses.replace(a, aux_models=aux)
            return digest.settings(a).model

        assert model(luna) == LUNA  # a non-Claude override: the summarizer follows the judge
        assert model(luna, summ_model=OPUS55) == OPUS55  # summ_model= wins (Arm A)
        assert model(luna, summ_model=OR_MODEL) == OR_MODEL
        assert model(PINNED) == pin  # a pinned judge keeps today's digest
        assert model(resolve(JudgeConfig(), flag=OPUS5, env={})) == pin  # a Claude override too
        assert model(None) == pin  # a probe without a judge (validate, resolve_layer_mode)
        # a family PINNED on a non-Claude judge is not an override: no follow
        assert model(resolve(JudgeConfig(model=OR_MODEL), env={})) == pin
        # ... but judge_effort= unpins it, so its digest follows it
        assert model(resolve(JudgeConfig(model=OR_MODEL), env={}, effort="low")) == OR_MODEL
    assert digest.follows_judge(_args(tmp_path, judge=luna))
    assert not digest.follows_judge(_args(tmp_path, judge=luna, summ_model=OPUS55))
    assert not digest.follows_judge(_args(tmp_path)) and not digest.follows_judge(
        _args(tmp_path, judge=None)
    )
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "wif")  # the openai route is non-Anthropic too
    assert llm.route(luna.model) == "openai"
    assert digest.settings(_args(tmp_path, judge=luna)).model == LUNA


@pytest.mark.parametrize("fam_name", ["poetry", "agentic_misalignment", "jailbreak_recognition"])
def test_a_luna_judge_digests_on_luna(tmp_path, real_families, fam_name):
    """A family with no digest pin, and the two Sonnet-digest families: Luna override -> Luna
    digest with no reasoning and no family-default fallback; ``summ_model=`` wins; a Claude
    override and the pinned judge keep today's digest."""
    today = digest.settings(_family_args(tmp_path, fam_name), fam_name)
    want = SONNET if fam_name != "poetry" else OPUS55
    assert today.model == want and today.reasoning == {"anthropic_effort": "default"}
    args = _family_args(tmp_path, fam_name, flag=LUNA)
    s = digest.settings(args, fam_name)
    assert (s.model, s.reasoning, s.fallback) == (LUNA, None, "none")
    cfg = digest.config(args, "prose", family=fam_name)["summarizer"]
    assert (cfg["model"], cfg["reasoning"], cfg["fallback"]) == (LUNA, None, "none")
    sj = digest.summarizer_judge(args, fam_name)
    assert (sj.model, sj.reasoning, sj.pinned) == (LUNA, None, False)
    assert not digest.pinned(args, fam_name)
    # the digest's own explicit refusal re-run is still available under a followed digest
    s = digest.settings(_family_args(tmp_path, fam_name, flag=LUNA, summ_fallback=f"none+{OPUS5}"))
    assert (s.model, s.refusal_model) == (LUNA, OPUS5)
    # Arm A: the Luna judge on Claude digests, with the family's own fallback again
    arm_a = digest.settings(_family_args(tmp_path, fam_name, flag=LUNA, summ_model=want), fam_name)
    assert arm_a.to_json() == today.to_json()
    # a Claude override keeps the digest it has today
    claude = digest.settings(_family_args(tmp_path, fam_name, flag=OPUS5), fam_name)
    assert claude.to_json() == today.to_json()


def test_preflight_judge_follows_only_with_a_judge(tmp_path):
    luna = resolve(JudgeConfig(), flag=LUNA, env={})
    aux = {digest.AUX_ROLE: SONNET}
    extra = {"aggregate": "summary"}
    two_args = digest.preflight_judge(extra, aux)  # the pre-0096 call: no follow
    assert two_args.model == SONNET and two_args.reasoning == {"anthropic_effort": "default"}
    assert digest.preflight_judge(extra, aux, None) == two_args
    assert digest.preflight_judge(extra, aux, PINNED) == two_args
    followed = digest.preflight_judge(extra, aux, luna)
    assert (followed.model, followed.reasoning, followed.pinned) == (LUNA, None, False)
    assert digest.preflight_judge({**extra, "summ_model": OPUS55}, aux, luna).model == OPUS55
    with pytest.raises(SystemExit) as e:  # R5: an explicit default fallback on a followed digest
        digest.preflight_judge({**extra, "summ_fallback": "default"}, aux, luna)
    assert e.value.code == 2
    assert digest.preflight_judge({**extra, "summ_fallback": "default"}, aux).model == SONNET


def _spec(name: str, calls: list, model: str = OPUS55, aux: dict | None = None) -> EvalSpec:
    def run(args: JudgeArgs) -> FamilyResult:
        s = digest.settings(args, name)
        calls.append((args.judge.model, s.model))
        return FamilyResult(
            family=name,
            metric="pass_rate",
            value=0.5,
            ci95=(0.0, 1.0),
            n_items=1,
            higher_is_better=True,
            chance=None,
            chance_label=None,
            complete=True,
            pinned_instrument=args.judge.pinned,
            config={"judge_model": args.judge.model, **digest.config(args, "prose", family=name)},
            counts=mcjudge.base_counts(
                n_expected=1, n_unjudged=0, n_empty=0, skipped_rows=0, spend=Spend()
            ),
        )

    return register(
        EvalSpec(
            name=name,
            title=name,
            group="logic",
            bank=Path(f"evals/{name}/items.json"),
            judge=JudgeConfig(model=model, aux_models=aux or {}),
            metric="pass_rate",
            higher_is_better=True,
            run=run,
        )
    )


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.delenv("WSBENCH_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(llm, "_make_client", lambda r, k: pytest.fail("no client in tests"))
    seen: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: seen.append((model, reasoning)))
    registry.FAMILIES.clear()
    return seen


def _run(tmp_path: Path, out: str, *extra: str) -> list[str]:
    root = tmp_path / "r"
    root.mkdir(parents=True, exist_ok=True)
    row = json.dumps({"id": "a", "layer": 36, "pos": 1, "samples": ["x"]}) + "\n"
    for n in ("plain", "pinned_digest"):
        (root / f"{n}.jsonl").write_text(row)
    families = "families=plain,pinned_digest"
    return ["run", families, f"readouts_root={root}", f"out={tmp_path / out}", *extra]


def test_the_runner_preflights_the_followed_digest_model(offline, tmp_path):
    """Under a Luna judge the digest preflight asks Luna, never the family's Claude digest; the
    family sees the same model (one place decides it)."""
    calls: list = []
    _spec("plain", calls)
    _spec("pinned_digest", calls, model=SONNET, aux={digest.AUX_ROLE: SONNET})
    assert main(_run(tmp_path, "pin")) == 0  # the pinned judges: today's digests
    default = {"anthropic_effort": "default"}
    want = [(OPUS55, None), (SONNET, None), (OPUS55, default), (SONNET, default)]
    assert sorted(offline, key=str) == sorted(want, key=str)
    assert sorted(calls) == [(OPUS55, OPUS55), (SONNET, SONNET)]
    offline.clear(), calls.clear(), mcjudge._PREFLIGHTED.clear()
    assert main(_run(tmp_path, "luna", f"judge_model={LUNA}", "judge_effort=low")) == 0
    assert sorted(offline, key=str) == sorted([(LUNA, None), (LUNA, {"effort": "low"})], key=str)
    assert calls == [(LUNA, LUNA), (LUNA, LUNA)]
    for name in ("plain", "pinned_digest"):
        res = json.loads((tmp_path / "luna" / name / "results.json").read_text())
        assert res["config"]["summarizer"]["model"] == LUNA
        assert res["config"]["summarizer"]["reasoning"] is None
        assert res["config"]["summarizer"]["fallback"] == "none"
    offline.clear(), calls.clear(), mcjudge._PREFLIGHTED.clear()
    arm_a = _run(tmp_path, "a", f"judge_model={LUNA}", f"opts=summ_model={OPUS55}")
    assert main(arm_a) == 0  # summ_model= wins: Luna judges Opus digests
    want = [(OPUS55, default), (LUNA, {"effort": "minimal"})]
    assert sorted(offline, key=str) == sorted(want, key=str)
    assert calls == [(LUNA, OPUS55), (LUNA, OPUS55)]
    offline.clear(), calls.clear(), mcjudge._PREFLIGHTED.clear()
    assert main(_run(tmp_path, "c", f"judge_model={OPUS5}")) == 0  # a Claude override
    assert sorted(calls) == [(OPUS5, OPUS55), (OPUS5, SONNET)]
    assert (LUNA, None) not in offline


def test_explicit_default_fallback_on_a_followed_digest_exits_2_before_any_family(
    offline, tmp_path, capsys
):
    calls: list = []
    _spec("plain", calls)
    _spec("pinned_digest", calls, model=SONNET, aux={digest.AUX_ROLE: SONNET})
    argv = _run(tmp_path, "o", f"judge_model={LUNA}", f"opts=summ_fallback=default+{SONNET55}")
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2 and calls == [] and offline == []
    assert "needs a claude-* digest model" in capsys.readouterr().err
    assert main([*argv[:-2], f"opts=summ_fallback=default+{SONNET55}"]) == 0  # Claude digests


# ---------------------------------------------------------------- end to end: no Claude call


@pytest.mark.parametrize("name", ALL)
def test_a_luna_run_without_judge_fallback_makes_no_claude_call(
    name, tmp_path, monkeypatch, real_families
):
    """Section 9's smoke, offline: ``judge_model=openai/gpt-6-luna opts=fallback=none`` on the
    four fallback families, native and summary, sends every digest and judge call to Luna."""
    run = Run(name, tmp_path, monkeypatch)
    res = run(fallback="none")
    assert run.ant.calls == [] and run.orc.calls
    assert {c["model"] for c in run.orc.calls} == {LUNA}
    if name.endswith("/summary"):
        summ = res.config["summarizer"]
        assert (summ["model"], summ["reasoning"], summ["fallback"]) == (LUNA, None, "none")
        digests = [
            c
            for c in run.orc.calls
            if c["messages"][-1]["content"].startswith(("READOUTS:", "LAYER DIGESTS:"))
        ]
        assert digests and all("reasoning" not in c["extra_body"] for c in digests)
    assert not res.pinned_instrument
    # the family's literals stay in a Luna row's stamp (R8); config.summarizer is the record
    if name in ("agentic_misalignment/summary", "jailbreak_recognition/summary"):
        assert "+sonnet-digest" in res.config["prompt_version"]
        assert "+opus5-fb" in res.config["prompt_version"]
