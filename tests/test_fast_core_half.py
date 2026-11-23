"""Plan 0104: ``fast-v4``, the default fast subset: a seeded random half of every core family
but the two safety ones, with the strict ATI subset whole (``scripts/fast_cut_core_half.py``)."""

import dataclasses
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import write_jsonl, write_sidecar
from summary_fakes import FakeLLM

from wsbench import fast, mc, nyt, readplan, reads, registry, tiers
from wsbench.baselines import text_inversion as ti
from wsbench.cli import fast_header, main
from wsbench.results import FamilyResult, macro, read_results, write_results

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/fast_cut_core_half.py"
V4, SEED = "fast-v4", 20261121
V4_SHA256 = "e5fba03e6ac2037ced69ed1ee8a581d737f08a878a866dd6cf01cffe23c723ef"
SAFETY = ("agentic_misalignment", "jailbreak_recognition")
STRICT_ATI = (  # ati-subset-v2 (plan 0085, tests/test_ati_freeze.py): 350 ids
    "conjunctive_association",
    "introspection",
    "knowledge_cutoff",
    "model_multihop",
    "model_specific_directed_modulation",
    "moral_rationale",
    "poetry",
    "wrong_intermediate",
)
# family -> (scored units, strict-ATI units, random units, fast units, read items)
TABLE = {
    "arithmetic_intermediates": (480, 0, 240, 240, 240),
    "buggy_code": (64, 0, 32, 32, 64),
    "chain_intermediates": (120, 0, 60, 60, 60),
    "conjunctive_association": (100, 26, 24, 50, 50),
    "hinted_cutoff": (118, 0, 59, 59, 118),
    "introspection": (125, 124, 0, 124, 250),
    "knowledge_cutoff": (147, 39, 35, 74, 74),
    "model_multihop": (283, 22, 120, 142, 142),
    "model_specific_directed_modulation": (98, 25, 24, 49, 49),
    "moral_rationale": (195, 56, 42, 98, 98),
    "multi_concept_directed_modulation": (114, 0, 57, 57, 57),
    "nyt_connections": (89, 0, 45, 45, 43),
    "poetry": (100, 16, 34, 50, 50),
    "relational_multihop": (100, 0, 50, 50, 50),
    "role_bound_association": (46, 0, 23, 23, 46),
    "wrong_intermediate": (100, 42, 8, 50, 50),
}

# The plan_sha every FAST fast-v4 readouts file declares (`reads.fast_plan_sha`): the family's
# full plan rows restricted to the frozen read ids. The manifest check sets a re-selected
# version's rows aside (nothing in the golden to compare them with), so they are pinned here: a
# change to how a fast row is built or hashed moves one of these. nyt_connections and
# knowledge_cutoff render their text from pinned sources that the test stubs replace
# (`tests/conftest.py`), so their two values are the stubbed plans', not a real producer's.
V4_FAST_PLAN_SHA = {
    "arithmetic_intermediates": "4da43ebd6549b034ef7e1094debd2728be2cac6dd0a5d1ae3d808a4ad9723a52",
    "buggy_code": "80b2e31300ac80c2d877d48c0c9c4c53c4f33750d10bfc1c67a73a645a010925",
    "chain_intermediates": "b54d3ae62619a39039175c262f78a4599d8927e51c11be9ce3689a1150e240f2",
    "conjunctive_association": "e8c15120aefc24db6a09527bc4b369c482856b93a5fafbb16b6ad065c3f48b90",
    "hinted_cutoff": "e48e0125b1c590bd89deeceac98274c1294aab2b3315883ab4e12f52a6dece77",
    "introspection": "921f22d46a1ae0eae0217da24ab24be5dfb924bf34597c518a81445a8ce1c2ec",
    "knowledge_cutoff": "7029d6bdac3ea26c50c6be00a739aba4d69156386c5784b183547c9d14e844b0",
    "model_multihop": "8d203247fa8f65eb86ec81af65c665fb158501c402023e956f05c27f6e9c9cca",
    "model_specific_directed_modulation": (
        "a45584fd645d3fe294d738f6a7726fc96d607fed852495230532565ef12e2170"
    ),
    "moral_rationale": "3ceb319bc4b87d7d376857526d40ec6859ce0813732ba17e672dc9d6b6f7aeb8",
    "multi_concept_directed_modulation": (
        "88cfb1cdde90452dc0ec4b5c19399e439d048a5a48d4fb3f54f48c2c3096b46a"
    ),
    "nyt_connections": "280e424644366487ff10adfc727babccd2c2ea7901b935b08acfbdbd95453843",
    "poetry": "a553bc9707f626f281c05e3ac9cc4139f112d008b47281d24f9382d39946b526",
    "relational_multihop": "97ddc2b1eb1e8cc565df0786858e57593cfa83e7da5823450ec966ce10209039",
    "role_bound_association": "f9d5c9d1035d857b83630663b0ead770d45cb8da2229bb7a88329352f135b59c",
    "wrong_intermediate": "327553081a9f690d175896ef10ebc8f16a80ee528a86a3ac3e61c41f1f3fb2d6",
}


@pytest.fixture(scope="module")
def cut():
    spec = importlib.util.spec_from_file_location("fast_cut_core_half", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc():
    return json.loads(fast.VERSIONS[V4].read_text(encoding="utf-8"))


def test_fast_v4_is_the_default_and_the_only_selectable_subset():
    assert fast.DEFAULT == V4 == fast.VERSION and fast.VARIANTS == {"": V4}
    assert fast.KEY_ERA[V4] == "0101" and fast.VERSIONS[V4].name == "fast_v4.json"
    assert fast.families() == sorted(TABLE) == tiers.families("fast")
    assert set(TABLE) == set(tiers.CORE) - set(SAFETY) and len(TABLE) == 16
    for fam in SAFETY:  # the owner's ruling: out of the fast tier
        with pytest.raises(fast.NotInFast) as e:
            fast.entry(fam)
        assert e.value.code == f"{fam}: not in fast-v4"


def test_the_file_is_frozen_and_the_cut_is_reproducible(cut, doc, tmp_path):
    raw = fast.VERSIONS[V4].read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V4_SHA256
    assert (doc["version"], doc["seed"], doc["subject"]) == (V4, SEED, "Qwen3.6-27B")
    assert doc["excluded_families"] == list(cut.EXCLUDED) == sorted(SAFETY)
    assert "ati_only" not in doc and list(doc["families"]) == sorted(TABLE) == list(doc["cut"])
    # two builds are the same bytes; --check passes on the frozen file and fails on another seed
    assert cut.build(V4, SEED) == cut.build(V4, SEED) == raw.decode()
    assert cut.build(V4, SEED + 1) != raw.decode()
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--version", V4, "--seed", str(SEED), "--check"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert r.returncode == 0 and "is up to date" in r.stderr
    with pytest.raises(SystemExit, match="exists: a frozen file is never edited"):
        cut.main(["--version", V4, "--seed", str(SEED)])
    out = tmp_path / "other.json"
    assert cut.main(["--version", V4, "--seed", str(SEED + 1), "--out", str(out)]) == 0
    assert cut.main(["--version", V4, "--seed", str(SEED), "--out", str(out), "--check"]) == 1


@pytest.mark.parametrize("fam", sorted(TABLE))
def test_the_fast_plan_sha_of_every_family_is_pinned(fam):
    assert set(V4_FAST_PLAN_SHA) == set(TABLE)
    rows = [s.row() for s in readplan.plan(fam, fast=True)]
    assert reads.plan_sha_rows(rows) == reads.fast_plan_sha(fam) == V4_FAST_PLAN_SHA[fam]
    assert reads.fast_plan_sha(fam, declared=V4) == V4_FAST_PLAN_SHA[fam]
    assert reads.fast_plan_sha(fam) != reads.plan_sha_rows([s.row() for s in readplan.plan(fam)])


def test_the_frozen_pins_check_runs_this_file():
    """``wsbench check frozen_pins`` covers the default subset's pins, not only its
    predecessors' (``tests/test_fast_subset.py`` runs on fast-v3)."""
    import inspect

    from wsbench import checks

    assert f'"tests/{Path(__file__).name}"' in inspect.getsource(checks.frozen_pins)


@pytest.mark.parametrize(
    "var",
    ["WSB_BANK_ROOT", "WSB_NO_NYT", "WSB_NO_NOCOT", "WSB_BANK_FILE_POETRY",
     "WSB_BANK_FILE_NYT_CONNECTIONS"],
)  # fmt: skip
def test_the_cut_refuses_another_bank_or_a_plan_with_rows_dropped(cut, var, monkeypatch):
    """Up front, by name: under one of these the units would come from another bank, or from a
    read plan without nyt_connections' / the nocot rows."""
    monkeypatch.setenv(var, "adapted/glm-5.3" if var == "WSB_BANK_ROOT" else "1")
    with pytest.raises(SystemExit, match=f"fast_cut_core_half: unset {var} "):
        cut.build(V4, SEED)
    with pytest.raises(SystemExit, match=f"unset {var} "):
        cut.main(["--version", V4, "--seed", str(SEED), "--check"])
    monkeypatch.delenv(var)
    monkeypatch.setenv("WSB_BANK_FILE_TYPO", "x")  # a family outside the cut: not its concern
    assert cut.build(V4, SEED) == fast.VERSIONS[V4].read_text(encoding="utf-8")


def test_the_cut_reads_ati_ids_through_the_staleness_check(cut, monkeypatch):
    """A registered ATI entry gated on another bank or instrument is refused at cut time
    (``text_inversion.subset_entry``), never forced into the units as it stands."""
    real = ti.subset_entry
    asked = []

    def entry(family, dst=None, **kw):
        asked.append((family, dst))
        return real(family, dst, **kw)

    monkeypatch.setattr(ti, "subset_entry", entry)
    assert cut.build(V4, SEED) == fast.VERSIONS[V4].read_text(encoding="utf-8")
    assert sorted(asked) == sorted((f, ti.FROZEN) for f in STRICT_ATI)
    monkeypatch.setattr(ti, "subset_entry", real)
    fingerprint = ti.bank_fingerprint
    monkeypatch.setattr(
        ti, "bank_fingerprint", lambda f: "moved" if f == "poetry" else fingerprint(f)
    )
    with pytest.raises(SystemExit, match=r"poetry: .* gated on a different bank"):
        cut.build(V4, SEED)


@pytest.mark.parametrize("fam", sorted(TABLE))
def test_each_family_is_half_its_units_with_the_ati_units_first(fam, cut, doc):
    n, n_ati, n_random, n_total, n_read = TABLE[fam]
    rec, entry = doc["cut"][fam], doc["families"][fam]
    assert (rec["n_units"], rec["n_ati"], rec["n_random"], rec["n_total"]) == (
        n, n_ati, n_random, n_total,
    )  # fmt: skip
    assert n_total == max(math.ceil(n / 2), n_ati) == n_ati + n_random
    units, key = cut.units_of(fam)
    ids = [u for u, _s, _r in units]
    chosen = entry["units"]["all"]
    assert len(ids) == n and chosen == sorted(chosen) and set(chosen) <= set(ids)
    assert list(entry) == ["bank_sha", "units", "read_ids"] and len(chosen) == n_total
    assert entry["bank_sha"] == fast.bank_sha(fam) and rec["stratum_key"] == key
    # the strict ATI ids are all there (2): never sampled
    ati = set(ti.subset_entry(fam, ti.FROZEN)["ids"]) if fam in STRICT_ATI else set()
    assert len(ati) == n_ati and ati <= set(chosen) and (bool(ati) == (fam in STRICT_ATI))
    # read ids: the plan rows the chosen units read, in plan order, every position (no rule)
    plan = [s.id for s in readplan.plan(fam)]
    want = {r for u, _s, rs in units if u in set(chosen) for r in rs}
    assert entry["read_ids"] == [i for i in plan if i in want] and len(want) == n_read
    assert (
        "positions" not in entry
        and [s.id for s in readplan.plan(fam, fast=True)] == (entry["read_ids"])
    )
    # strata: the totals add up, and the random part follows the largest-remainder split of
    # the non-ATI units
    strata = rec["strata"]
    assert sum(s["n"] for s in strata.values()) == n
    assert sum(s["n_fast"] for s in strata.values()) == n_total
    rest = {k: s["n"] - s["n_ati"] for k, s in strata.items()}
    quota = cut.largest_remainder(n_random, rest)
    assert {k: s["n_fast"] - s["n_ati"] for k, s in strata.items()} == quota


def test_totals_and_the_strict_ati_subset(doc):
    assert sum(len(e["units"]["all"]) for e in doc["families"].values()) == 1203
    assert sum(len(e["read_ids"]) for e in doc["families"].values()) == 1441
    assert ti.SUBSET_VERSION == "ati-subset-v2"
    ati = {f: ti.subset_entry(f, ti.FROZEN)["ids"] for f in STRICT_ATI}
    assert sum(len(v) for v in ati.values()) == 350 and len(ati["conjunctive_association"]) == 26
    for fam, ids in ati.items():
        e = fast.subset(V4)[fam]
        assert set(ids) <= set(e["units"]["all"]) and set(ids) <= set(e["read_ids"])


def test_stratum_keys(doc, cut):
    keys = {f: c["stratum_key"] for f, c in doc["cut"].items() if c["stratum_key"] != "none"}
    assert keys == {
        "arithmetic_intermediates": "expression shape",
        "knowledge_cutoff": "frozen / nocot",
        "model_multihop": "invented / cutoff",
        "moral_rationale": "committed / deliberative",
        "multi_concept_directed_modulation": "bank stratum (concept count / relation)",
    }
    assert set(doc["cut"]["model_multihop"]["strata"]) == {"invented", "cutoff"}
    assert set(doc["cut"]["knowledge_cutoff"]["strata"]) == {"frozen", "nocot"}
    assert set(doc["cut"]["moral_rationale"]["strata"]) == {"committed", "deliberative"}
    assert len(doc["cut"]["arithmetic_intermediates"]["strata"]) == 13
    assert cut.largest_remainder(5, {"a": 3, "b": 3, "c": 4}) == {"a": 2, "b": 1, "c": 2}
    assert cut.largest_remainder(0, {"a": 3}) == {"a": 0}
    with pytest.raises(ValueError):
        cut.largest_remainder(4, {"a": 3})


def test_a_familys_draw_depends_on_nothing_but_itself(cut, doc, monkeypatch):
    """Independence: the draw is ``random.Random(f"{seed}|{pre-0101 name}")`` over the family's
    own sorted units, never the version. So a later version cut with the same seed after one
    family's bank changed holds every OTHER family's units unchanged (their fast results stay
    valid by ``fast.compatible``), and a family joining or leaving moves no one else."""
    units, _ = cut.units_of("poetry")
    ati = set(ti.subset_entry("poetry", ti.FROZEN)["ids"])
    base = cut.draw(SEED, "poetry", units, ati)[0]
    assert base == doc["families"]["poetry"]["units"]["all"]
    assert cut.draw(SEED, "poetry", list(reversed(units)), ati)[0] == base  # order-free
    assert cut.draw(SEED + 1, "poetry", units, ati)[0] != base
    assert cut.draw(SEED, "poetry", units[:-1], ati - {units[-1][0]})[0] != base
    # the stream is keyed by the seed and the pre-0101 name alone: multihop was multihop_mt
    assert registry.frozen_name("multihop") == "multihop_mt"
    seen = []
    real = cut.random.Random

    def spy(key):
        seen.append(key)
        return real(key)

    monkeypatch.setattr(cut.random, "Random", spy)
    cut.draw(SEED, "multihop", [("a", "all", ("a",)), ("b", "all", ("b",))], set())
    assert seen == [f"{SEED}|multihop_mt"]
    monkeypatch.undo()
    # THE re-cut: the next version, same seed, after ONE family's bank changed (here poetry
    # loses a unit). Every other family's entry is byte-identical to fast-v4's; only poetry's
    # units move, and the file differs otherwise in `version` alone
    real_units = cut.units_of

    def changed(family):
        us, key = real_units(family)
        return (us[:-1], key) if family == "poetry" else (us, key)

    monkeypatch.setattr(cut, "units_of", changed)
    monkeypatch.setattr(cut, "_ati_ids", lambda frozen, fam, strict: (
        set(frozen[fam]["ids"]) - {real_units("poetry")[0][-1][0]} if fam in strict else set()
    ))  # fmt: skip
    nxt = json.loads(cut.build("fast-v5", SEED))
    assert nxt["version"] == "fast-v5" and nxt["seed"] == SEED
    for fam in TABLE:
        same = nxt["families"][fam] == doc["families"][fam]
        assert same == (fam != "poetry"), fam
        assert (nxt["cut"][fam] == doc["cut"][fam]) == (fam != "poetry"), fam
    assert json.dumps(
        {k: v for k, v in nxt.items() if k not in ("version", "families", "cut")}
    ) == (json.dumps({k: v for k, v in doc.items() if k not in ("version", "families", "cut")}))
    monkeypatch.undo()
    # a family added to core: every other family's entry is byte-identical
    core = tiers.core()  # the module the script reads is this one: capture before patching
    monkeypatch.setattr(cut.tiers, "core", lambda: sorted([*core, "user_modeling"]))
    wider = json.loads(cut.build(V4, SEED))
    assert set(wider["families"]) == {*TABLE, "user_modeling"}
    for fam in TABLE:
        assert wider["families"][fam] == doc["families"][fam], fam
    # a strict-ATI family outside the family list is refused (the ATI subset stays whole)
    monkeypatch.setattr(cut.tiers, "core", lambda: [f for f in core if f != "poetry"])
    with pytest.raises(SystemExit, match="strict-ATI families outside the fast family list"):
        cut.build(V4, SEED)


def test_units_follow_the_families_own_headline_conventions(cut, doc):
    """The unit of each special family is what its headline averages, and the read ids are
    what the older fast files held for the same units (pairs: both members; introspection: the
    headline row and the rows its twins read; nyt: the slot's puzzle)."""
    old = fast.subset("fast-v3")
    for fam in ("buggy_code", "hinted_cutoff", "role_bound_association", "introspection",
                "nyt_connections"):  # fmt: skip
        units = {u: rs for u, _s, rs in cut.units_of(fam)[0]}
        e = old[fam]
        assert set(e["units"]["all"]) <= set(units), fam
        assert {r for u in e["units"]["all"] for r in units[u]} == set(e["read_ids"]), fam
    assert all(len(rs) == 2 for _u, _s, rs in cut.units_of("buggy_code")[0])
    assert all(u.count("|") == 1 for u, _s, _r in cut.units_of("nyt_connections")[0])
    mcdm = {u for u, _s, _r in cut.units_of("multi_concept_directed_modulation")[0]}
    assert not {"b-none", "d-none"} & mcdm  # the two control items are never scored


def _row(family: str, version: str = V4, value: float = 0.5) -> FamilyResult:
    return FamilyResult(
        family=family, metric="pass_rate", value=value, ci95=None, n_items=30,
        higher_is_better=True, chance=None, chance_label=None, complete=True,
        pinned_instrument=True, config={"scope": fast.SCOPE, "fast_subset": version}, counts={},
    )  # fmt: skip


def test_macro_and_report_under_the_new_default_and_for_old_directories(tmp_path, capsys):
    rows = [_row("poetry"), _row("chain_intermediates", value=0.3), _row("poetry", "fast-v3")]
    m = macro(rows[:2])
    assert m["fast_subset"] == V4 and m["families"] == ["poetry", "chain_intermediates"]
    assert m["value"] == pytest.approx(0.4)
    # every older version's row is stale under fast-v4: no entry is identical
    for old in ("fast-v1", "fast-v2", "fast-v3", "fast-safety-v1", "fast-safety-v2"):
        assert not any(fast.compatible(old, f) for f in fast.subset(old))
        assert macro([_row("poetry", old)])["excluded"] == [
            {"family": "poetry", "reason": f"stale fast subset ({old})"}
        ]
    head = "scope: fast subset fast-v4 (16 families; not comparable with full-bench numbers)"
    assert fast_header() == head + "; rows of other subsets are excluded"
    assert fast_header([_row("poetry", "fast-v3")]).endswith(
        "\n1 row(s) are fast-v3 rows; pass fast_version=fast-v3 for that subset's macro"
    )
    # an old fast-v3 directory: stale under the default, reported whole with fast_version=
    old_dir = tmp_path / "old"
    for fam in ("poetry", "basic_readout_st"):
        write_results(old_dir / fam, _row(fam, "fast-v3"))
    assert main(["report", f"dir={old_dir}", "json=True"]) == 0
    m = json.loads(capsys.readouterr().out)["macro"]
    assert m["fast_subset"] == V4 and m["families"] == [] and len(m["excluded"]) == 2
    assert main(["report", f"dir={old_dir}", "fast_version=fast-v3", "json=True"]) == 0
    m = json.loads(capsys.readouterr().out)["macro"]
    assert m["fast_subset"] == "fast-v3" and sorted(m["families"]) == ["basic_readout_st", "poetry"]
    assert m["excluded"] == [] and fast.VERSION == "fast-v3"
    fast.VERSION = fast.DEFAULT
    # an old --fast-safety directory, under the version that made it
    safe_dir = tmp_path / "safe"
    write_results(
        safe_dir / "jailbreak_recognition", _row("jailbreak_recognition", "fast-safety-v2")
    )
    assert main(["report", f"dir={safe_dir}", "fast_version=fast-safety-v2"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("scope: fast subset fast-safety-v2 (24 families;")
    assert "stale fast subset" not in text


def test_fast_safety_is_retired_with_a_message(capsys, tmp_path):
    for argv in (["plan", "--fast-safety"], ["run", "--fast-safety", "readouts_root=r", "out=o"],
                 ["report", f"dir={tmp_path}", "fast=safety"]):  # fmt: skip
        assert main(argv) == 2
        err = capsys.readouterr().err
        assert "--fast-safety is retired (plan 0104)" in err and "fast_version=" in err
    with pytest.raises(ValueError, match="retired"):
        fast.select("safety")
    assert set(fast.VERSIONS) >= {"fast-safety-v1", "fast-safety-v2"}  # frozen, still readable


def test_plan_judge_run_report_smoke_on_fast_v4(tmp_path, capsys, mk_args):
    """``plan --fast`` writes the 16 families' fast rows; a FULL readouts file is narrowed to
    the fast read ids by ``reads.load``; a FAST file needs every fast read id."""
    assert main(["plan", "--fast", f"out={tmp_path / 'plan'}"]) == 0
    files = sorted(p.stem for p in (tmp_path / "plan").glob("*.jsonl"))
    assert files == sorted(TABLE)
    n = sum(len(p.read_text().splitlines()) for p in (tmp_path / "plan").glob("*.jsonl"))
    assert n == 1441
    capsys.readouterr()
    assert main(["plan", "--fast", "families=jailbreak_recognition", f"out={tmp_path / 'x'}"]) == 2
    assert "jailbreak_recognition: not in fast-v4" in capsys.readouterr().err
    # reads: a full poetry file (every plan id) is restricted to the 50 fast ids
    e = fast.entry("poetry")
    ids = [s.id for s in readplan.plan("poetry")]
    rows = [{"id": i, "layer": 20, "pos": p, "token": "x", "samples": ["r"]} for i in ids
            for p in (7, 8)]  # fmt: skip
    full = write_jsonl(tmp_path / "poetry.jsonl", rows)
    cells, _rep = reads.load(mk_args(full, scope=fast.SCOPE, layers=[20], items=e["read_ids"]),
                             "poetry")  # fmt: skip
    assert {c.id for c in cells} == set(e["read_ids"]) and len(e["read_ids"]) == 50
    # a FAST file of an older version holds other ids: refused (it reads other items)
    old = fast.subset("fast-v3")["poetry"]["read_ids"]
    assert set(old) != set(e["read_ids"]) and not fast.same_reads("fast-v3", "poetry")
    stale = write_jsonl(tmp_path / "old_poetry.jsonl", [r for r in rows if r["id"] in set(old)])
    write_sidecar(stale, fast="fast-v3", layers=[20])
    with pytest.raises(SystemExit):
        reads.load(mk_args(stale, scope=fast.SCOPE, layers=[20], items=e["read_ids"]), "poetry")
    assert "poetry reads other items or positions there" in capsys.readouterr().err
    # run --fast over an empty readouts root: the 16 families are skipped (no file), the two
    # safety families are not fast families, and the report header names fast-v4
    out = tmp_path / "out"
    root = tmp_path / "root"
    root.mkdir()
    assert main(["run", "--fast", f"readouts_root={root}", f"out={out}"]) in (0, 2)
    run = json.loads((out / "run.json").read_text())
    out_of_fast = {f for f, v in run["families"].items() if v.get("error") == "not in fast-v4"}
    assert set(run["families"]) - out_of_fast == set(TABLE) and set(SAFETY) <= out_of_fast
    assert {v["status"] for v in run["families"].values()} == {"skipped"}


def test_judge_fast_of_a_pair_family_end_to_end(tmp_path, monkeypatch, capsys):
    """``wsbench judge family=buggy_code --fast`` under the default subset, the two stages
    scripted: only the 64 members of the 32 fast pairs are digested and judged, the value is
    the pair rate over the fast pairs, and the row is stamped fast-v4 and enters its macro."""
    from wsbench.evals.computational.buggy_code.judge import load_bank

    assert fast.VERSION == fast.DEFAULT == V4
    header, items = load_bank(registry.frozen_bank_path("buggy_code"))
    e = fast.subset(V4)["buggy_code"]
    units = e["units"]["all"]
    buggy_of = {it["twin"]: it["id"] for it in items if it.get("src") == "buggy" and it.get("twin")}
    outside = sorted(set(buggy_of) - set(units))
    assert len(units) == 32 and len(e["read_ids"]) == 64 and len(outside) == 32
    # the readouts flag the bug in 10 fast pairs and in one pair outside the subset
    hit = {buggy_of[u] for u in [*units[:10], outside[0]]}
    rows = [
        {"id": it["id"], "layer": header["read_cells"][it["lang_group"]]["layer"], "pos": 7,
         "samples": [("FLAGGED " if it["id"] in hit else "") + f"readout about {it['id']}"]}
        for it in items
    ]  # fmt: skip
    path = write_jsonl(tmp_path / "buggy_code.jsonl", rows)  # a FULL file: every bank item

    def judge_(system, user, schema):
        if schema["name"] == "inferred_bug":
            flagged = "FLAGGED" in user
            return {"claim": "bug" if flagged else "none", "inferred": "x" if flagged else "",
                    "quote": "FLAGGED" if flagged else ""}  # fmt: skip
        return {"score": 9, "why": ""}

    fake = FakeLLM.install(monkeypatch, judge_)
    out = tmp_path / "o"
    assert main(["judge", "family=buggy_code", f"readouts={path}", f"out={out}", "--fast"]) == 0
    r = read_results(out)
    assert fake.n("digest") == 64 and fake.n("inferred_bug") == 64 * 3  # the fast read ids only
    assert {x["id"] for x in r.rows} == set(e["read_ids"]) == set(r.config["items"])
    assert r.config["scope"] == fast.SCOPE and r.config["fast_subset"] == V4
    assert r.config["aggregate"] == "summary" and "+fast-" not in r.config["prompt_version"]
    assert r.complete and r.pinned_instrument and r.n_items == 32
    assert r.value == pytest.approx(10 / 32) and r.ci95 is not None
    assert r.extras["fast_n_units"] == 32 and r.extras["fast_n_scored"] == 32
    assert r.extras["fast_units_missing"] == [] and "fast_rescore_mismatch" not in r.extras
    assert r.extras["fast_family_value"] == pytest.approx(10 / 32)  # the pairs that were read
    m = macro([r])
    assert m["families"] == ["buggy_code"] and m["fast_subset"] == V4 and m["excluded"] == []
    assert "pass_rate=0.3125 n=32" in capsys.readouterr().out


def test_judge_fast_of_nyt_connections_end_to_end(tmp_path, monkeypatch):
    """``wsbench judge family=nyt_connections --fast`` under the default subset (the synthetic
    puzzles of the test stubs): the 43 puzzles of the 45 fast slots are read, every stable slot
    of those puzzles gets a row, and the fast value counts the 45 fast slots only."""
    from wsbench.evals.logical_processing.nyt_connections import judge

    assert fast.VERSION == fast.DEFAULT == V4
    _header, items = nyt.bank_items()
    e = fast.subset(V4)["nyt_connections"]
    units, read = e["units"]["all"], set(e["read_ids"])
    assert len(units) == 45 and len(read) == 43 and {u.split("|")[0] for u in units} == read
    stable = judge.stable_slots([it for it in items if it["id"] in read])
    riders = sorted(set(stable) - set(units))  # stable slots of a read puzzle outside the subset
    assert len(stable) == 50 and len(riders) == 5
    won = {*units[:5], riders[0]}
    gold = {}  # the listing a slot's judge call shows -> (slot id, the Qwen option's position)
    for it in items:
        for s in it["mc"]:
            o = judge.slot_options(it, s)
            gold[mc.listing(judge.shown(o))] = (
                judge.slot_id(it["id"], s["slot"]),
                judge.gold_pos(o),
            )
    rows = [
        {"id": it["id"], "layer": ly, "pos": 100 + p,
         "samples": [f"grouping note {it['id']} L{ly} p{p}"]}
        for it in items for ly in (20, 24) for p in range(2)
    ]  # fmt: skip
    path = write_jsonl(tmp_path / "nyt_connections.jsonl", rows)  # a FULL file: every puzzle

    def judge_(system, user, schema):
        listing = user.split("Candidate connections:\n", 1)[1].split("\n\n", 1)[0]
        slot, pos = gold[listing]
        lines = [ln for ln in user.splitlines() if "grouping note" in ln]
        if slot in won and lines:  # the gold with a quote the digest holds; else cannot tell
            return {"choice": pos, "quote": lines[0].split("] ", 1)[-1].removeprefix("- ")}
        return {"choice": len(listing.splitlines()), "quote": ""}

    fake = FakeLLM.install(monkeypatch, judge_)
    out = tmp_path / "o"
    assert (
        main(["judge", "family=nyt_connections", f"readouts={path}", f"out={out}", "--fast"]) == 0
    )
    r = read_results(out)
    assert fake.n("digest") == 43 * 2  # one digest per read puzzle and layer, no other puzzle
    assert [x["id"] for x in r.rows] == stable and {x["puzzle"] for x in r.rows} == read
    assert {x["id"] for x in r.rows if x["pass"]} == won
    assert r.config["scope"] == fast.SCOPE and r.config["fast_subset"] == V4
    assert r.config["aggregate"] == "summary" and "+fast-" not in r.config["prompt_version"]
    assert r.complete and r.pinned_instrument and r.n_items == 45
    assert r.value == pytest.approx(5 / 45) and r.ci95 is not None
    assert r.extras["fast_n_units"] == 45 and r.extras["fast_n_scored"] == 45
    assert r.extras["fast_units_missing"] == [] and "fast_rescore_mismatch" not in r.extras
    assert r.extras["fast_family_value"] == pytest.approx(6 / 50)  # every stable slot read
    m = macro([r])
    assert m["families"] == ["nyt_connections"] and m["fast_subset"] == V4 and m["excluded"] == []


def _item_rows(fam: str, ids: list[str]) -> list[dict]:
    """Synthetic per-item rows: every third id passes; introspection rows are headline rows."""
    extra = {"role": "headline"} if fam == "introspection" else {}
    return [{"id": i, "pass": k % 3 == 0, **extra} for k, i in enumerate(ids)]


def test_the_strict_ati_macro_from_a_fast_run(tmp_path, capsys):
    """``report --fast anti_text_inversion=True``: each fast row becomes its family's ATI row,
    the fast units restricted to the gated ids (``fast.ati_view``), and the macro applies its
    ATI rules. The value is the one a result holding ONLY the gated ids' rows gives under the
    family's own unit rule: what an ``anti_text_inversion=True`` run over the same readouts
    scores, a unit's verdict not depending on which other items are judged."""
    fams = [f for f in STRICT_ATI if f != "moral_rationale"]  # its rows need the judge's shape
    made = {}
    for fam in [*fams, "arithmetic_intermediates"]:
        ids = fast.subset(V4)[fam]["units"]["all"]
        r = _row(fam)
        r.rows = _item_rows(fam, ids)
        r.value = sum(x["pass"] for x in r.rows) / len(r.rows)
        made[fam] = r
        write_results(tmp_path / fam, r)
    assert fast.ati_view(made["arithmetic_intermediates"]) is None  # not gated: left out
    # the scope guard: a full row or an ATI row is not a fast row, gated family or not
    for scope in (None, "anti_text_inversion"):
        for fam in ("poetry", "arithmetic_intermediates"):
            other = dataclasses.replace(made[fam], config={**made[fam].config, "scope": scope})
            if scope is None:
                del other.config["scope"]
            with pytest.raises(ValueError, match=r"fast\.ati_view reads a fast row"):
                fast.ati_view(other)
    for fam in fams:
        ati = ti.subset_entry(fam, ti.FROZEN)
        view = fast.ati_view(made[fam])
        want = [x["pass"] for x in made[fam].rows if x["id"] in set(ati["ids"])]
        assert len(want) == len(ati["ids"]) == view.n_items
        assert view.value == pytest.approx(sum(want) / len(want))
        # the same rows as an ATI-scoped result: the family's unit rule gives the same value
        scoped = _row(fam)
        scoped.rows = [x for x in made[fam].rows if x["id"] in set(ati["ids"])]
        groups, sign = fast.units(fam, scoped)
        assert fast.value_of(groups, sign) == pytest.approx(view.value)
        assert view.config["scope"] == "anti_text_inversion" and view.complete
        assert view.extras["ati_gate"] == ti.GATE_VERSION == ati["gate"]
        assert view.extras["ati_n_ids"] == len(ati["ids"])
        assert view.extras["ati_subset"] == ti.SUBSET_VERSION
        assert view.extras["ati_from_fast"] == V4 and made[fam].config["scope"] == fast.SCOPE
    # an undecided gated id is out of the value and counted; too many make the row incomplete
    r = _row("poetry")
    ids = fast.subset(V4)["poetry"]["units"]["all"]
    gated = set(ti.subset_entry("poetry", ti.FROZEN)["ids"])
    r.rows = [x for x in _item_rows("poetry", ids) if x["id"] not in sorted(gated)[:3]]
    view = fast.ati_view(r)
    assert view.n_items == 16 and view.extras["n_items_undecided"] == 3 and not view.complete
    # the macro: the n >= 20 families plus the two exceptions (poetry 16, model_multihop 22)
    m = macro([fast.ati_view(made[f]) for f in fams])
    assert sorted(m["families"]) == sorted(fams) and m["ati_subset"] == ti.SUBSET_VERSION
    assert m["excluded"] == []
    # the command; summary.md stays the fast report's (the view writes nothing)
    assert main(["report", f"dir={tmp_path}", "--fast"]) == 0
    before = (tmp_path / "summary.md").read_text()
    capsys.readouterr()
    assert main(["report", f"dir={tmp_path}", "--fast", "anti_text_inversion=True"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("scope: strict ATI view of the fast run (fast-v4)")
    assert (
        "arithmetic_intermediates" not in text and (tmp_path / "summary.md").read_text() == before
    )
    assert (
        main(["report", f"dir={tmp_path}", "--fast", "anti_text_inversion=True", "json=True"]) == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert sorted(out["macro"]["families"]) == sorted(fams)
    assert out["macro"]["value"] == pytest.approx(m["value"])
    assert main(["report", f"dir={tmp_path}", "anti_text_inversion=True"]) == 2
    assert "ATI view of a FAST run: pass --fast" in capsys.readouterr().err
    # rows of an older version are stale under fast-v4: no view of them
    old = _row("poetry", "fast-v3")
    old.rows = _item_rows("poetry", ids)
    write_results(tmp_path / "poetry", old)
    assert (
        main(["report", f"dir={tmp_path}", "--fast", "anti_text_inversion=True", "json=True"]) == 0
    )
    assert "poetry" not in json.loads(capsys.readouterr().out)["macro"]["families"]


def _fast_only_rows(fam: str) -> list[dict]:
    """A readouts file that holds the family's fast read plan and nothing else: every layer of
    every row, at the row's own positions where the plan lists them, else at stand-in ones."""
    token = {"multi_concept_directed_modulation": {"token": "x"}}.get(fam, {})
    rows = []
    for s in readplan.plan(fam, fast=True):
        kind = s.positions["kind"]
        if kind == "positions":
            pos = s.positions["positions"]
        else:  # all_from_end reports negative offsets, -1 the last
            pos = [-2, -1] if kind == "all_from_end" else [7, 8]
        rows += [
            {"id": s.id, "layer": layer, "pos": p, "samples": ["r"], **token}
            for layer in s.layers
            for p in pos
        ]
    return rows


@pytest.mark.parametrize("fam", sorted(fast.subset(fast.DEFAULT)))
def test_a_fast_only_read_holds_every_cell_the_judge_requires(fam, tmp_path, capsys):
    """For every family of the default subset: the judge, given a readouts file of the fast
    read plan alone, finds every cell it requires (a dry run: no call; it counts the missing
    cells it would refuse). A unit, pair member or twin whose row the fast plan does not hold
    shows here as missing cells or as an item without readouts."""
    assert set(fast.subset(fast.DEFAULT)) == set(TABLE)
    path = write_jsonl(tmp_path / f"{fam}.jsonl", _fast_only_rows(fam))
    out = tmp_path / "o"
    argv = ["judge", f"family={fam}", f"readouts={path}", f"out={out}", "--fast", "dry_run=True"]
    assert main(argv) == 0, capsys.readouterr().err[-2000:]
    r = read_results(out)
    assert r.config["scope"] == fast.SCOPE and r.config["fast_subset"] == fast.DEFAULT
    # multi_concept_directed_modulation expects the cells its window tokens place inside the
    # dictated sentence (none of the stand-in ones): the item count below is its check
    assert r.counts["n_expected_cells"] > 0 or fam == "multi_concept_directed_modulation"
    assert r.counts["n_missing_cells"] == 0
    assert r.extras["n_items_without_readouts"] == 0


def test_judge_fast_of_introspection_reads_a_twins_row_without_judging_its_item(
    tmp_path, monkeypatch
):
    """The one non-ATI headline item (``...|oceans``) is no fast unit, but its inject row is a
    fast read: the cross twin of the unit ``...|trees`` reads it. The judge takes that row as
    a readout only, so a FAST file (which has no row of the item's own gaussian twin) is
    judged whole, and gives the fast value a file that also holds that twin gives."""
    from wsbench.evals.model_specific.introspection import judge

    bank = judge.load()
    by = {it["id"]: it for it in bank["items"]}
    e = fast.subset(V4)["introspection"]
    units, read = e["units"]["all"], set(e["read_ids"])
    rider = "inject|protocol:trial1|b4|oceans"
    assert rider in read and rider not in units and by[rider]["headline"]
    assert by[rider]["twins"]["gaussian"] not in read
    assert [u for u in units if by[by[u]["twins"]["cross"]]["readout_of"] == rider] == [
        "inject|protocol:trial1|b4|trees"
    ]
    # the readouts name the concept on 10 units and on the rider; one unit's gaussian twin
    # names it too (a voided hit)
    named = {u: by[u]["concept"] for u in [*units[:10], rider]}
    void = by[units[0]]["twins"]["gaussian"]
    named[void] = by[units[0]]["concept"]
    layer = 56

    def rows_of(ids):
        return [
            {"id": s.id, "layer": layer, "pos": p,
             "samples": [f"MARK {named[s.id]}" if s.id in named else f"plain note {s.id}"]}
            for s in readplan.plan("introspection") if s.id in ids
            for p in s.positions["positions"]
        ]  # fmt: skip

    def judge_(system, user, schema):
        options, rest = user.split("OPTIONS:\n", 1)[1].split("\n\n", 1)
        labels = [ln.split(". ", 1)[1].split(" (", 1)[0] for ln in options.splitlines()]
        for k, lab in enumerate(labels):
            if f"MARK {lab}" in rest:
                return {"choice": k + 1, "quote": f"MARK {lab}"}
        return {"choice": labels.index(judge.NONE_OPTION) + 1, "quote": ""}

    got = {}
    for name, ids in (("fast", read), ("more", read | {by[rider]["twins"]["gaussian"]})):
        path = write_jsonl(tmp_path / f"{name}.jsonl", rows_of(ids))
        FakeLLM.install(monkeypatch, judge_)
        out = tmp_path / name
        argv = ["judge", "family=introspection", f"readouts={path}", f"out={out}", "--fast"]
        assert main([*argv, f"layers={layer}"]) == 0
        got[name] = r = read_results(out)
        assert r.counts["n_missing_cells"] == 0 and r.extras["n_items_without_readouts"] == 0
        head = {x["id"]: x for x in r.rows if x.get("role") == "headline"}
        assert set(head) == set(units) and rider not in {x["id"] for x in r.rows}
        assert {u for u, x in head.items() if x["pass"]} == set(units[1:10])
        assert head[units[0]]["pass"] is False and head[units[0]]["pass_unpaired"] is True
        assert r.n_items == r.extras["fast_n_units"] == r.extras["fast_n_scored"] == 124
        assert r.extras["fast_units_missing"] == [] and "fast_rescore_mismatch" not in r.extras
        assert r.value == pytest.approx(9 / 124)
        assert r.extras["fast_family_value"] == pytest.approx(9 / 124)
    assert got["fast"].value == got["more"].value and got["fast"].ci95 == got["more"].ci95
