"""Validation gate for math_shortcuts (plan 0065): convert the source's frozen s3d readouts to the
readout contract, check that the native screen and the native render are byte-equal to the
source's, and replay the source's frozen GUESS answers through this family's verdict gate and
headline to the frozen 28 / 18.

    python scripts/math_shortcuts_replay.py --reads <gw>/outputs/shortcuts/v2/confirm_reads \
        --guess <gw>/outputs/shortcuts/v2/confirm/guess.jsonl --out <dir>/math_shortcuts.jsonl

``--reads`` holds one ``<pid>.json`` per problem (``readouts[str(layer)]`` = ``{pos, set, text}``);
only the ``instr`` and ``reply_start`` cells are written, one packed sample per cell
(``prose1``: one 4-bullet generation per activation is ONE sample). ``--toy`` writes the toy
example instead (three items at L44)."""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from wsbench import reads
from wsbench.banks import load_bank
from wsbench.evals.math_shortcuts import judge, prompts, score
from wsbench.readouts import load_readouts, normalize, write_sidecar
from wsbench.registry import bank_path

FROZEN = {"I_flagged": 28, "N_flagged": 18, "n_I": 120, "n_N": 98}
POST = ("instr", "reply_start")
READER = "olens-s3d-space-rl600"  # agu18dec/olens_and_ar:olens_s3d_space_rl600
TOY = ("omni_3559", "omni_2084", "omni_1018")  # I (flagged at L44), N (flagged at L44), I


def last_json(text: str) -> object:
    """gw ``guess._last_json``: the last parseable ``{...}`` of a free-text answer."""
    i = text.rfind("{")
    while i >= 0:
        try:
            return json.loads(text[i : text.rfind("}") + 1])
        except json.JSONDecodeError:
            i = text.rfind("{", 0, i)
    return None


def convert(reads_dir: Path, out: Path, by_id: dict, only: tuple[str, ...] = (),
            layers: tuple[int, ...] = ()) -> list[int]:  # fmt: skip
    seen_layers: set[int] = set()
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for item_id, it in by_id.items():
            if only and item_id not in only:
                continue
            r = json.loads((reads_dir / f"{item_id}.json").read_text(encoding="utf-8"))
            assert r["pid"] == it["name"] and r["n_tokens"] == it["n_tokens"], item_id
            assert r["samples"] == 1, item_id
            for layer in r["layers"]:
                if layers and layer not in layers:
                    continue
                cells = {x["pos"]: x for x in r["readouts"][str(layer)] if x["set"] in POST}
                assert sorted(cells) == it["positions"], (item_id, layer)
                assert cells[it["reply_start"]]["set"] == "reply_start", item_id
                for p in it["positions"]:
                    row = {"id": item_id, "layer": layer, "pos": p, "samples": [cells[p]["text"]]}
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n += 1
                seen_layers.add(layer)
    print(f"wrote {out}: {n} cells")
    return sorted(seen_layers)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reads", required=True)
    ap.add_argument("--guess", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--toy", action="store_true")
    a = ap.parse_args()
    _h, items = load_bank(bank_path("math_shortcuts"))
    by_id = {it["id"]: it for it in items}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if a.toy:
        convert(Path(a.reads), out, by_id, only=TOY, layers=(44,))
        return 0
    layers = convert(Path(a.reads), out, by_id)
    write_sidecar(
        out,
        sampling="prose1",
        reader=READER,
        arm="olens_s3d_space_rl600",
        layers=layers,
        reads="full",
        plan_sha=reads.plan_sha("math_shortcuts"),
    )
    if not a.guess:
        return 0

    cells, _rep = load_readouts(out, ids=list(by_id))
    cells, diag = normalize(cells, "prose1")
    assert not any(diag.values()), diag
    frozen = {}
    for line in Path(a.guess).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        assert r["status"] == "ok", r["rid"]
        frozen[r["rid"]] = r
    screened, n_render_bad, flagged = set(), 0, defaultdict(bool)
    n_gate_diff = 0
    for c in cells:
        raw = judge.readout_text(c)
        if not prompts.SCREEN.search(raw):
            continue
        rid = f"{by_id[c.id]['name']}|L{c.layer}|p{c.pos}"
        screened.add(rid)
        if rid not in frozen:
            continue
        mine = prompts.render(
            prompts.NATIVE, problem=by_id[c.id]["problem"], readout=prompts.clean(raw)
        )
        theirs = prompts.GUESS_PROMPT.format(problem=by_id[c.id]["problem"],
                                             readout=prompts.clean(c.samples[0]))  # fmt: skip
        n_render_bad += mine != theirs
        o = last_json(frozen[rid]["raw"])
        v = score.verdict(o, judge.native_gate(raw))
        assert v is not None, rid
        n_gate_diff += v["guess"] != bool(frozen[rid]["parsed"]["positive"])
        flagged[c.id] |= v["guess"]
    print(f"screen: {len(screened)} cells (source {len(frozen)}), "
          f"same set: {screened == set(frozen)}")  # fmt: skip
    print(f"render: {n_render_bad} native prompts differ from the source")
    print(f"gate: {n_gate_diff} verdicts differ from the source's parse_guess")
    i_f = [flagged[i] for i, it in by_id.items() if it["label"] == "I"]
    n_f = [flagged[i] for i, it in by_id.items() if it["label"] == "N"]
    head = score.headline(i_f, n_f)
    print(json.dumps(head))
    ok = screened == set(frozen) and n_render_bad == 0
    ok &= all(head[k] == v for k, v in FROZEN.items())
    ok &= abs(head["fisher_one_sided_p"] - 0.2342068259869) < 1e-9
    ok &= n_gate_diff == 0  # every cell verdict must equal the source's parse_guess
    print("GATE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
