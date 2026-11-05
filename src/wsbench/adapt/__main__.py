"""``python -m wsbench.adapt <cmd> model=<key> [families=a,b] [k=v ...]``

profile   gate the original banks on the subject   [limit= regate=true draws= temperature= llm=]
generate  deterministic candidates at a tier              family= tier= n= [seed=]
author    Opus-authored candidates at a tier              family= tier= n= [steer= wave=]
gate      lint + gate pending (regate=true: passing new items; regate=all: failed too)
          [draws= temperature= llm= regate=]
regrade   re-grade stored answers (no resampling)         llm=<claude id> [workers=16 legs=a,b]
auto      generate+gate down the ladder until full / ooc  family=
freeze    write adapted/<model>/<family>.json + report.json  [families= allow_untried=<reason>]
          (with families=, refuses a short family never refilled: plan 0066 §1.3)
refill    refill until target / ooc (plan 0066)  families= [waves=8 claude_budget= gpu_minutes=
          pilot=true llm=]
note      status + reason (+ macro exclusion)   family= [status=] [text=] [exclude_from_macro=]
drop      audited drop: ids leave the bank (reason recorded)  family= ids=a,b reason=
patch     audited field fix on one item of the adapted copy   family= id= set='{json}' note=
status    one line per family
native_langs  the subject's native languages, which freeze needs   [stage=measure card=en,..
          thinking=on|off (default: on with a thinking mode, plan 0054 R6's trace measure)
          readouts=<J-lens readouts dir> (the readout criterion; none = trace only)]
          | stage=readouts readouts=<dir> (add the J-lens criterion to a measured record)
          | langs=en,.. evidence= [thinking=off] | stage=upgrade [families=] (A1.10 / A2 rebuild)
moral     moral_rationale: elicit, distil, re-gate          [stage=]
          v3 on a subject: stage=rekey_readrender step=<s> [variant=system_one_word] [out=],
          then stage=options [bank=], then stage=adopt [bank=]
poetry    poetry v5: stage=gate|tier_a|mc|opus_gate|all     [regate=true]
agentic   agentic_misalignment: rollouts, commitment judge, keep  [stage=] [twins=true]
fill      author+gate an authored family until full / ooc       families= [waves=8]
carry     verify + copy jailbreak / multi_concept_dm to the subject [families=] [screen=true]
floors    prompt-only floors: stock subject summaries, Claude judge   [stage=] [judge=]
mc        MC options for adapted-only candidates (the repo's builders, --bank)   families=
          [stage=build|subject]  (subject: basic_readout's post-gate subject fields)
introspection  the subject's own vectors, dose, detection baseline  [stage=] [result=]
               [coherence=off] [llm=]
msdm      model_specific_directed_modulation re-derived on the subject (plan 0060 Phase E)
          [stage=elicit|canon|units|build|all] [llm=<claude id>|none] [limit=] [regate=] [pool=]
kcutoff   knowledge_cutoff re-derived on the subject (plan 0060 Phase E)
          [stage=elicit|canon|verify|units|build|all] [llm=] [cutoff=YYYY-MM] [limit=] [regate=]
          [pool=]
wrong_intermediate    the subject's own wrong-intermediate errors (plan 0060 Phase E)
                stage=screen|grade|gate|adjudicate|bank|all pool=<dir> [limit= resolve= llm=]
multihop_mt_v2  staged subject gate incl. the shortcut leg (plan 0060 Phase E) [limit= regate=]
nyt_connections the subject's own groupings, labels and stability (plan 0060 Phase E)
                [stage=solve|stability|options|build|all] [limit=] [llm=<claude id>|none]
                [regate=] [herrings=<pilot alt file>]
"""

import json
import sys

from wsbench.registry import LEGACY_FAMILY_NAMES, canonical

from . import families as fams
from . import run

USAGE = __doc__


def _pool_arg(v: str) -> bool | str:
    """``pool=`` for msdm / kcutoff: a boolean as before, or a mode name (plan 0066: ``ext``)."""
    low = v.lower()
    if low in ("1", "true", "yes"):
        return True
    if low in ("0", "false", "no"):
        return False
    return low


def _args(argv: list[str]) -> dict[str, str]:
    out = {}
    for a in argv:
        if "=" not in a:
            raise SystemExit(f"bad argument {a!r}\n{USAGE}")
        k, v = a.split("=", 1)
        out[k] = v
    return out


KEYS: dict[str, set[str]] = {
    "profile": {"families", "limit", "regate", "llm", "draws", "temperature"},
    "generate": {"family", "tier", "n", "seed"},
    "author": {"family", "tier", "n", "steer", "wave"},
    "gate": {"families", "llm", "draws", "temperature", "regate"},
    "regrade": {"families", "llm", "workers", "legs"},
    "auto": {"family"},
    "fill": {"families", "llm", "waves"},
    "freeze": {"families", "allow_untried"},
    "refill": {"families", "waves", "claude_budget", "gpu_minutes", "pilot", "llm"},
    "note": {"family", "status", "text", "exclude_from_macro"},
    "drop": {"family", "ids", "reason"},
    "patch": {"family", "id", "set", "note"},
    "status": set(),
    "native_langs": {"stage", "langs", "evidence", "thinking", "families", "card", "readouts"},
    "moral": {"stage", "step", "out", "limit", "variant", "bank"},
    "poetry": {"stage", "regate"},
    "agentic": {"stage", "twins"},
    "carry": {"families", "screen"},
    "floors": {"stage", "judge"},
    "introspection": {"stage", "result", "coherence", "llm"},
    # plan 0060 Phase E: self-answer families re-derived on the subject
    "msdm": {"stage", "llm", "limit", "regate", "pool"},
    "kcutoff": {"stage", "llm", "cutoff", "limit", "regate", "pool"},
    # plan 0060 Phase E (wrong_intermediate.py, mhmt2.py)
    "wrong_intermediate": {"stage", "pool", "limit", "resolve", "llm"},
    "multihop_mt_v2": {"stage", "limit", "regate"},
    "mc": {"families", "stage"},
    "nyt_connections": {"stage", "limit", "llm", "regate", "herrings"},  # nyt_connections.py
}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in LEGACY_FAMILY_NAMES:  # `adapt wrong_bridge` (renamed in v1.2.0)
        print(f"note: family {argv[0]!r} was renamed to {canonical(argv[0])!r}", file=sys.stderr)
        argv = [canonical(argv[0]), *argv[1:]]
    if not argv or argv[0] not in KEYS:
        raise SystemExit(USAGE)
    cmd, a = argv[0], _args(argv[1:])
    # strict: an unknown key is an error, never silently ignored (`gate family=x` used to gate
    # EVERY family; the skill audit)
    if bad := sorted(set(a) - KEYS[cmd] - {"model"}):
        raise SystemExit(f"{cmd}: unknown argument(s) {bad}; allowed: {sorted(KEYS[cmd])}\n{USAGE}")
    model = a.pop("model", None) or sys.exit("model= is required")
    if "family" in a:
        a["family"] = canonical(a["family"])
    families = a.pop("families", "")
    names = [canonical(f) for f in families.split(",") if f] or sorted(fams.FAMILIES)
    common = {k: a[k] for k in ("llm",) if k in a}
    for k in ("draws",):
        if k in a:
            common[k] = int(a[k])
    if "temperature" in a:
        common["temperature"] = float(a["temperature"])
    if cmd == "profile":  # profile regate re-asks every original, so "all" is the same as true
        regate = a.get("regate", "").lower() in ("1", "true", "yes", "all")
        run.profile(model, names, limit=int(a.get("limit", 0)), regate=regate, **common)
    elif cmd == "generate":
        run.generate(model, a["family"], a["tier"], int(a["n"]), int(a.get("seed", 0)))
    elif cmd == "author":
        from .author import author

        steer = a.get("steer", "")
        author(model, a["family"], a["tier"], int(a["n"]), steer, int(a.get("wave", 0)))
    elif cmd == "gate":
        rg = a.get("regate", "").lower()
        regate: bool | str = "all" if rg == "all" else rg in ("1", "true", "yes")
        run.gate(model, names, regate=regate, **common)
    elif cmd == "regrade":
        llm = a.get("llm") or sys.exit("regrade needs llm=<claude id>")
        legs = [x for x in a.get("legs", "").split(",") if x] or None
        run.regrade(model, names, llm, workers=int(a.get("workers", 16)), legs=legs)
    elif cmd == "floors":
        from . import floors

        floors.run(model, a.get("stage", "all"), a.get("judge", "claude-opus-5-5"))
    elif cmd == "carry":
        from . import carry

        screen = a.get("screen", "true").lower() in ("1", "true", "yes")  # plan 0060 A2
        carry.carry(model, [f for f in families.split(",") if f] or None, screen=screen)
    elif cmd == "fill":
        runner = run._runner(model)  # one vLLM load for every family
        for fam in names:
            print(fam, run.fill(model, fam, a.get("llm", "claude-opus-5-5"),
                                int(a.get("waves", 8)), runner=runner))  # fmt: skip
    elif cmd == "agentic":
        from . import agentic

        twins = a.get("twins", "true").lower() in ("1", "true", "yes")  # plan 0060 D5
        agentic.run(model, a.get("stage", "all"), twins=twins)
    elif cmd == "moral":
        from . import moral

        extra = {k: a[k] for k in ("step", "out", "limit", "variant", "bank") if k in a}
        moral.run(model, a.get("stage", "all"), **extra)
    elif cmd == "poetry":
        from . import poetry

        regate = a.get("regate", "").lower() in ("1", "true", "yes")
        poetry.run(model, a.get("stage", "all"), regate=regate)
    elif cmd == "introspection":
        from . import introspection

        introspection.run(model, a.get("stage", "all"), a.get("result"),
                          a.get("coherence", "on"), a.get("llm", "claude-opus-5-5"))  # fmt: skip
    elif cmd in ("msdm", "kcutoff"):  # plan 0060 Phase E
        from . import kcutoff, msdm

        mod = msdm if cmd == "msdm" else kcutoff
        extra = {"cutoff": a["cutoff"]} if "cutoff" in a else {}
        mod.run(model, a.get("stage", "all"), llm=a.get("llm", "claude-opus-5-5"),
                limit=int(a.get("limit", 0)),
                regate=a.get("regate", "").lower() in ("1", "true", "yes"),
                pool=_pool_arg(a.get("pool", "true")), **extra)  # fmt: skip
    elif cmd == "wrong_intermediate":  # plan 0060 Phase E
        from . import wrong_intermediate

        wrong_intermediate.run(model, a.get("stage", "all"), pool=a.get("pool"),
                         limit=int(a.get("limit", 0)), llm=a.get("llm", "claude-opus-5-5"),
                         resolve=a.get("resolve", "local"))  # fmt: skip
    elif cmd == "multihop_mt_v2":  # plan 0060 Phase E
        from . import mhmt2

        regate = a.get("regate", "").lower() in ("1", "true", "yes")
        mhmt2.run(model, a.get("stage", "gate"), limit=int(a.get("limit", 0)), regate=regate)
    elif cmd == "mc":
        from . import mcstage

        if not families:
            raise SystemExit(f"mc: families= is required ({', '.join(mcstage.FAMILIES)})")
        mcstage.run(model, names, a.get("stage", "build"))
    elif cmd == "nyt_connections":  # plan 0060 Phase E
        from . import nyt_connections

        nyt_connections.run(model, a.get("stage", "all"), llm=a.get("llm", "claude-opus-5-5"),
                            limit=int(a.get("limit", 0)),
                            regate=a.get("regate", "").lower() in ("1", "true", "yes"),
                            herrings_src=a.get("herrings"))  # fmt: skip
    elif cmd == "auto":
        print(a["family"], run.auto(model, a["family"]))
    elif cmd == "note":
        ex = a.get("exclude_from_macro")
        run.note(model, a["family"], a.get("status"), a.get("text"),
                 None if ex is None else ex.lower() in ("1", "true", "yes"))  # fmt: skip
    elif cmd == "drop":
        run.drop(model, a["family"], [i for i in a["ids"].split(",") if i], a["reason"])
    elif cmd == "patch":
        run.patch(model, a["family"], a["id"], json.loads(a["set"]), a["note"])
    elif cmd == "native_langs":
        from . import native_langs as nl

        if a.get("stage") == "measure":
            card = [x for x in a.get("card", "").split(",") if x] or None
            print(nl.measure(model, a.get("thinking"), card_langs=card,  # None: default_thinking
                             readouts=a.get("readouts")))  # fmt: skip
        elif a.get("stage") == "readouts":  # the J-lens criterion added to a measured record
            print(nl.add_readouts(model, a["readouts"]))
        elif a.get("stage") == "upgrade":  # plan 0060 A2: the multilingual rows, rebuilt
            from . import ml_native

            ml_native.upgrade(model, [f for f in families.split(",") if f] or None)
        elif "langs" in a:
            langs = [x for x in a["langs"].split(",") if x]
            print(nl.record(model, langs, a.get("evidence", ""), a.get("thinking")))
        else:
            print(nl.load(model) or f"{model}: not measured ({nl.path(model)})")
    elif cmd == "freeze":
        au = a.get("allow_untried", "")
        allow: bool | str = au if au.lower() not in ("", "0", "false", "no", "1", "true", "yes") \
            else au.lower() in ("1", "true", "yes")  # fmt: skip
        run.freeze(model, names if families else None, strict=True, allow_untried=allow)
        run.status(model)
    elif cmd == "refill":  # plan 0066
        from . import refill

        if not families:
            raise SystemExit(f"refill: families= is required ({', '.join(refill.POLICY)})")
        refill.refill(
            model, names, waves=int(a.get("waves", 8)),
            claude_budget=int(a["claude_budget"]) if "claude_budget" in a else None,
            gpu_minutes=float(a["gpu_minutes"]) if "gpu_minutes" in a else None,
            pilot=a.get("pilot", "").lower() in ("1", "true", "yes"),
            llm=a.get("llm", "claude-opus-5-5"),
        )  # fmt: skip
    else:
        run.status(model)


if __name__ == "__main__":
    main()
