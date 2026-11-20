"""Plan 0096 step 0: the SDK requests and the result ``config`` of the four families on their
pinned judge, with one declined call so the refusal fallback fires, against a golden written on
the tree before the plan's first ``src/`` edit (``tests/golden/README.md``)."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from conftest import native_args, write_jsonl
from summary_fakes import first_lines_digest
from test_jailbreak_recognition import RECOG, _end_cells, _fixture_bank, _item_answer
from test_llm_refusal_rerun import _resp, fake_client_installer, is_digest
from test_summary_mode_agentic import BENIGN, GOOD, RH, _rows

from wsbench import registry
from wsbench.banks import load_bank
from wsbench.evals.model_specific.hinted_cutoff import judge as hc_judge
from wsbench.evals.model_specific.hinted_cutoff import prompts as hc_prompts
from wsbench.judge_config import resolve

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests/golden/pin_requests_0096.json"
WRITE_ENV = "WSB_PIN_0096_WRITE"  # set to 1 to (re)write the golden: only on the pre-0096 tree
MMH_IDS = ["r15iv2891", "r13co0078"]
HC_NEEDLE = "Based on the provided metadata, the answer is X."


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _plain(obj: Any) -> Any:
    """``obj`` as the JSON file holds it (tuples become lists, keys strings)."""
    return json.loads(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str))


def _request(kw: dict[str, Any]) -> dict[str, Any]:
    """One SDK request: ``system`` / ``messages`` as one sha256 each, every other kwarg as sent."""
    out = {k: v for k, v in kw.items() if k not in ("system", "messages")}
    out["system_sha256"] = _sha(kw["system"]) if "system" in kw else None
    out["messages_sha256"] = _sha(kw["messages"])
    return _plain(out)


def _sort_key(kw: dict[str, Any]) -> tuple[str, str]:
    return kw["model"], _sha([kw.get("system"), kw["messages"]])


def _args(family: str, path: Path, out: Path, mode: str, **kw: Any):
    """A run on the family's own pin, as ``runner.judge_family`` builds it, at concurrency 1."""
    spec = registry.FAMILIES[family]
    base: dict[str, Any] = {
        "readouts": path,
        "out": out,
        "judge": resolve(spec.judge, env={}),
        "layers": None,
        "items": None,
        "limit": 0,
        "allow_missing": False,
        "concurrency": 1,
        "rpm": 1e9,
        "dry_run": False,
        "aux_models": dict(spec.judge.aux_models),
        "extra": {"aggregate": mode},
    }
    return native_args(**(base | kw))


def _schema_name(kw: dict[str, Any]) -> str:
    """Which structured call a request is, by its schema's required keys ("" = free text)."""
    fmt = (kw.get("output_config") or {}).get("format")
    return "" if fmt is None else ",".join(fmt["schema"]["required"])


# ---------------------------------------------------------------- the four families


def _agentic(tmp_path: Path, monkeypatch, mode: str):
    from wsbench.evals.safety.agentic_misalignment import judge

    path = write_jsonl(tmp_path / "r.jsonl", _rows([RH, f"{RH}~twin"], positions=(0, 1)))
    pin = registry.FAMILIES["agentic_misalignment"].judge.model

    def answer(model, kw):
        user = kw["messages"][0]["content"]
        if is_digest(kw):
            return _resp(json.dumps(first_lines_digest(user)), model=model)
        if model == pin and f"R:{RH}:" in user and "~twin" not in user:
            return _resp("", "refusal")  # RH's Stage C call: re-run on the refusal model
        return _resp(GOOD if "~twin" not in user else BENIGN, model=model)

    args = _args("agentic_misalignment", path, tmp_path / "o", mode, items=[RH])
    return judge, args, answer


def _jailbreak(tmp_path: Path, monkeypatch, mode: str):
    from wsbench.evals.safety.jailbreak_recognition import judge

    items = _fixture_bank(tmp_path, monkeypatch, 2, 2)
    jb0, jb1 = items[0]["id"], items[1]["id"]
    path = write_jsonl(tmp_path / "r.jsonl", _end_cells(items, {jb0: RECOG, jb1: RECOG}))
    pin = registry.FAMILIES["jailbreak_recognition"].judge.model
    declined = {"n": 0}

    def answer(model, kw):
        user = kw["messages"][0]["content"]
        if is_digest(kw):
            return _resp(json.dumps(first_lines_digest(user)), model=model)
        if model == pin and f"R:{jb1} " in user:
            declined["n"] += 1
            if declined["n"] == 1:  # one draw of jb1 only (the three draws are one request)
                return _resp("", "refusal")
        return _resp(json.dumps(_item_answer(user)), model=model)

    args = _args("jailbreak_recognition", path, tmp_path / "o", mode, allow_missing=True)
    return judge, args, answer


def _hinted_cutoff(tmp_path: Path, monkeypatch, mode: str):
    _h, items = load_bank(REPO / "evals/model_specific/hinted_cutoff/items_v2.json")
    pairs = hc_judge.pairs_of(items)[:2]
    keep = [{**p[r], "positions": p[r]["positions"][:20]} for p in pairs for r in ("I", "N")]
    bank = {"family": "hinted_cutoff", "frozen": True, "n_pairs": 2, "items": keep}
    bp = tmp_path / "items.json"
    bp.write_text(json.dumps(bank))
    monkeypatch.setenv("WSB_BANK_FILE_HINTED_CUTOFF", str(bp))
    rows = [
        {
            "id": it["id"],
            "layer": 44,
            "pos": p,
            "samples": [f"- {HC_NEEDLE if it['role'] == 'I' else 'plain line'} R:{it['id']}"],
        }
        for it in keep
        for p in it["positions"]
    ]
    path = write_jsonl(tmp_path / "hinted_cutoff.jsonl", rows)
    pin = registry.FAMILIES["hinted_cutoff"].judge.model
    first = keep[0]["id"]
    declined = {"n": 0}

    def answer(model, kw):
        user = kw["messages"][0]["content"]
        if is_digest(kw):
            return _resp(json.dumps(first_lines_digest(user)), model=model)
        if model == pin and f"R:{first}" in user:
            declined["n"] += 1
            if declined["n"] == 1:  # the first twin's first call: re-asked on the fallback
                return _resp("", "refusal")
        rel = "Based on the provided metadata" in user
        quotes = {f: [] for f in hc_prompts.FLAGS}
        if rel:
            quotes["hint_reliance"] = ["based on the provided metadata"]
        flags = {f: (f == "hint_reliance" and rel) for f in hc_prompts.FLAGS}
        return _resp(json.dumps(flags | {"quotes": quotes}), model=model)

    return hc_judge, _args("hinted_cutoff", path, tmp_path / "o", mode), answer


def _model_multihop(tmp_path: Path, monkeypatch, mode: str):
    from wsbench.evals.model_specific.model_multihop import judge
    from wsbench.readplan import bank_file

    _h, bank = bank_file(REPO / "evals/model_specific/model_multihop/items.json")
    items = {it["id"]: it for it in bank}
    src = (REPO / "examples/readouts/model_multihop.jsonl").read_text().splitlines()
    path = write_jsonl(tmp_path / "model_multihop.jsonl", [json.loads(x) for x in src if x.strip()])
    pin = registry.FAMILIES["model_multihop"].judge.model

    def of(user: str) -> str:
        return MMH_IDS[0] if "Zimbabwe" in user else MMH_IDS[1]

    def answer(model, kw):
        user = kw["messages"][0]["content"]
        if is_digest(kw):
            return _resp(json.dumps(first_lines_digest(user, k=50)), model=model)
        name, iid = _schema_name(kw), of(user)
        # one declined call: the Zimbabwe item's MC call (summary) / summarizer call (native)
        if model == pin and iid == MMH_IDS[0] and name in ("choice,quote", "summary,concepts"):
            return _resp("", "refusal")
        bridge = items[iid]["bridge"]
        if name == "summary,concepts":
            return _resp(json.dumps({"summary": f"S {bridge}", "concepts": [bridge]}), model=model)
        if name == "pick,quote":
            return _resp(json.dumps({"pick": bridge, "quote": f"S {bridge}"}), model=model)
        order = items[iid]["mc"]["order"]
        return _resp(json.dumps({"choice": order.index(bridge) + 1, "quote": bridge}), model=model)

    return judge, _args("model_multihop", path, tmp_path / "o", mode, items=list(MMH_IDS)), answer


SCENARIOS = {
    "agentic_misalignment/summary": (_agentic, "summary"),
    "jailbreak_recognition/summary": (_jailbreak, "summary"),
    "hinted_cutoff/summary": (_hinted_cutoff, "summary"),
    "hinted_cutoff/native": (_hinted_cutoff, "native"),
    "model_multihop/summary": (_model_multihop, "summary"),
    "model_multihop/native": (_model_multihop, "native"),
}


def capture(name: str, tmp_path: Path, monkeypatch) -> dict[str, Any]:
    """Run one scenario through the Anthropic-shaped fake client and return what the golden
    holds: every request sorted by ``(model, sha256 of system + messages)``, and ``config``."""
    build, mode = SCENARIOS[name]
    judge, args, answer = build(tmp_path, monkeypatch, mode)
    fake = fake_client_installer(monkeypatch)(answer)
    result = judge.run(args)
    models = {kw["model"] for kw in fake.calls}
    assert len(models) > 1, f"{name}: no fallback request fired ({models})"
    return {
        "requests": [_request(kw) for kw in sorted(fake.calls, key=_sort_key)],
        "config": _plain(result.config),
    }


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_pinned_requests_and_config_are_unchanged(name, tmp_path, monkeypatch, real_families):
    got = capture(name, tmp_path, monkeypatch)
    if os.environ.get(WRITE_ENV) == "1":
        golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
        golden[name] = got
        text = json.dumps(golden, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        GOLDEN.write_text(text, encoding="utf-8")
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))[name]
    assert got["config"] == want["config"]
    assert len(got["requests"]) == len(want["requests"])
    for g, w in zip(got["requests"], want["requests"], strict=True):
        assert g == w
