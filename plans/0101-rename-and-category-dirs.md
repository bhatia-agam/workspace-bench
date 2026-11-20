# 0101: the multi-token families take the plain keys, family directories move under categories

Camila, 2026-11-20. Follows plan 0098 (which announced these two steps as plans 0099 / 0100;
they ship together here as ONE mechanical PR, because both rewrite the same paths).

This plan changes names and locations only. It changes no bank byte, no judge prompt, no
`prompt_version`, no call key, no option order, no `plan_sha`, no ATI `bank_sha`, no seed, no
floor value, no fast subset file. Every results directory, readouts root, digest store and
adapted set written before it keeps reading as the family it was written for, or is refused
with a message that names this rename. Nothing is ever judged as the other family of a pair.

Revision 2 (after critique 1, `/root/tmp/wsb-0101-critique1.md`): every one of its 15 findings
was checked against the code and is fixed where the affected code is specified; the owner's
rulings on the former open questions are §0.4; §2 is now a complete inventory of the
name-embedding sites; §8 (the migration script) is redesigned around a KEEP list; §11 has the
manifest; §15 is the commit order.

Revision 3 (after critique 2, `/root/tmp/wsb-0101-critique2.md`; all ten items verified and
applied): F14 covers `row_sha` and the cell store, F16 the producer's resume file; §2.3 is the
table of every place code derives something from a family key's SPELLING; the refusal marks
and KEEP patterns of §8 are tightened; the manifest script's imports are stated (§11.1).

## 0. Decisions (the owner's, not open)

### 0.1 Key renames (A)

| key today | key after | title after | superseded |
|---|---|---|---|
| `basic_readout_mt` | `basic_readout` | Basic readout | |
| `multihop_mt` (former `multihop_mt_v2`) | `multihop` | Multihop | |
| `multilingual_mt` | `multilingual` | Multilingual | |
| `typo_mt` | `typo` | Typo | |
| `basic_readout` | `basic_readout_st` | Basic readout (single-token) | |
| `multihop` | `multihop_st` | Multihop (single-token) | |
| `multilingual` | `multilingual_st` | Multilingual (single-token) | |
| `typo` | `typo_st` | Typo (single-token) | `superseded_by="typo"` (was `typo_mt`; carried over) |

Every other key is unchanged, including `multilingual_multihop`, `multilingual_typo`,
`relational_multihop`, `model_multihop`. Four live keys (`basic_readout`, `multihop`,
`multilingual`, `typo`) change MEANING: before this plan they name the single-token family,
after it the multi-token one. Below, "pair" = one row pair of this table, "`_st` family" = its
single-token member, "bare key" = the key both members have held.

### 0.2 Directory layout (B)

`evals/<family>/` becomes `evals/<category>/<family>/`, category = `EvalSpec.group`
(`registry.CATEGORIES`). `evals/baselines/`, `evals/fast/`, `evals/hallucinationbench/` stay.
`adapted/<set>/<family>.json` stays flat (renamed for 0.1 only).

| category dir | families (keys after 0.1) |
|---|---|
| `basic` | association, basic_readout, basic_readout_st, directed_modulation, multi_concept_directed_modulation, multihop, multihop_st, multilingual, multilingual_st, multilingual_multihop, multilingual_typo, poetry, typo, typo_st |
| `computational` | arithmetic_intermediates, buggy_code, chain_intermediates |
| `association` | conjunctive_association, user_modeling |
| `safety` | agentic_misalignment, jailbreak_recognition |
| `anti_bag_of_features` | relational_multihop, role_bound_association |
| `logical_processing` | moral_rationale, nyt_connections |
| `model_specific` | hinted_cutoff, introspection, knowledge_cutoff, model_multihop, model_specific_directed_modulation, wrong_intermediate |
| `precision` | jlens_concept_pr |

### 0.3 The Python packages move too (my choice; the trade-off)

`src/wsbench/evals/<family>/` becomes `src/wsbench/evals/<category>/<family>/`, mirroring the
data tree, with NO compatibility shim (no re-export module at the old dotted path).

- For: (1) the owner's goal, one shape in both trees. (2) Safety of the swap: with flat
  packages, a stale `from wsbench.evals.multihop import prompts` in an unmigrated branch,
  script or notebook would import the OTHER family's module and often keep running (`PROMPTS`,
  `SPEC`, `PROMPT_VERSION` exist in both). With the packages moved, every pre-0101 dotted path
  is a `ModuleNotFoundError`. The move turns a silent hazard into a loud one. (3) The cost is
  mechanical: one regex table rewrites the 615 import lines (109 in `src`, 458 in `tests`, 48
  in `scripts`; 209 files).
- Against: a larger diff; every in-flight branch must run the branch procedure (§8.7); two names need
  care (§2 F8: the family `association` vs the category `association`; `wsbench.evals.basic`
  vs the shared judge package `wsbench.basic`).
- Rejected: packages flat + data categorised (the hazard in (2) stays and the trees disagree);
  packages moved + shims (a shim at `wsbench.evals.multihop` would have to pick one family of
  the pair, which is exactly the silent mis-binding to avoid).

Code that needs a family's module by NAME (`tests/test_prompts_in_readme.py`,
`basic.mcjudge_bank.strings_of`, `baselines.prompt_only`, `registry._spec_for_bank`,
`adapt.run`) goes through one helper, `registry.family_module` (§4), never an f-string.

### 0.4 Rulings on the former open questions (Camila, 2026-11-20)

1. The category directory `association` stays, alongside the family at `basic/association`
   (F8 handles the overlap, including in `repo_path`, §4).
2. Introspection's plan rows keep the legacy string `evals/introspection/vectors/…` (hash
   input, F3); the producer resolves it through `registry.repo_path`.
3. Public artefacts keyed by family are NOT renamed: the pushed adapted sets on HF, viewer /
   atlas exports, HallucinationBench's WSB method names. `README.md` says so, with the key
   table of §0.1, and the code reads both vocabularies.
4. No per-category README.
5. The stderr notice for the four swapped bare keys is removed at the next version tag. Every
   guard (`owner`, `RenamedKey`, the header / id / stamp checks) stays permanently.
6. `tests/golden/` and `tests/fixtures/` files keep their pre-0101 names and bytes.

## 1. Size (measured on origin/main 030dd09b, 8,666 tracked files)

| what | count |
|---|---|
| family data dirs moved (`evals/`) | 32 dirs, 3,770 files (3,595 are `jlens_concept_pr`) |
| family packages moved (`src/wsbench/evals/`) | 32 packages, 111 files; + 8 new category `__init__.py` |
| `adapted/` paths renamed | 157 (125 `<family>.json` in 17 sets; 32 files in 16 `basic_readout_mt/` overlay dirs) |
| `examples/readouts/` renamed | 9 (8 `.jsonl`, 1 `.meta.json`) |
| `evals/baselines/{topics,confusers}/` renamed | 8 |
| test modules renamed | about 20 (§9.1) |
| text files rewritten (keys, paths, imports) | about 460: src 118, tests 212, scripts 68, skills 17, live docs 3, atlas 8, viewer_app 2, root md 4, family READMEs 24, baselines/fast READMEs 2, `adapted/README.md` |
| in-repo JSON with keys renamed IN PLACE | 75: 5 `evals/baselines/*.json`, 8 topics/confusers (inner `"family"` value), 62 under `adapted/` (17 `report.json`, 17 `floors/floors.json`, 16 `floors/prompt_only_summary.json`, 7 `anti_text_inversion*.json`, 5 `lenses/scores.json`) |
| in-repo JSON TRANSLATED AT READ (bytes untouched) | 3 `evals/fast/*.json`, 1 `evals/baselines/archive/*.json`, 2 goldens keyed by family (`plan_sha_pre_0090.json`, `capable_questions.json`) |
| left as history (not rewritten) | `plans/` (75 files), 28 `adapted/*/AUDIT*.md`-style records, 5 results docs under `docs/`, 3 skill audit records, every bank / pool / golden / fixture byte |

## 2. Findings from the code (each is designed around below)

Nothing found makes a hash-neutral rename impossible, but sixteen sites embed a family key or
a family path in a hash, seed, cache key or prompt and WOULD move without the fixes here.

### 2.1 Two frozen-name functions, and why one is not enough

- `registry.hash_name(family)` (exists): the key a family hashes under at the sites converted
  in v1.2.0 (`plan_sha`, ATI `bank_sha`, lucky-guessing seeds, `gate_sampling.seed`,
  `qwen_seed`). For the multi-token multihop family it is `multihop_mt_v2`.
- `registry.frozen_name(family)` (NEW): the key the family had on main just before this plan,
  i.e. the inverse of §0.1 (`multihop` -> `multihop_mt`, `basic_readout` ->
  `basic_readout_mt`, `multilingual` -> `multilingual_mt`, `typo` -> `typo_mt`, `<X>_st` ->
  `<X>`; any other family -> itself). It is what every site that embeds the RAW key today must
  embed afterwards.

The two differ for exactly one family: the multi-token multihop family is `multihop_mt_v2`
under `hash_name` and `multihop_mt` under `frozen_name`, because the 2026-11-04 rename
converted only the v1.2.0 sites and let the raw-key sites move to `multihop_mt`. (Revision 1
of this plan put `hash_name` at F2, F5 and F6; that would have moved those three for the
multi-token multihop family. Corrected below.) Rule: a site already on `hash_name` stays on
it; every site converted by THIS plan uses `frozen_name`. Neither result is ever a lookup key
or a file name (F7), and each is applied once, to a current key.

### 2.2 The complete inventory of name-embedding sites

Method: every `random.Random(`, `hashlib.`, `seed`, `seeded_shuffle`, `seed_int`,
`fingerprint(`, and every f-string or `.format` that interpolates a family variable
(`family`, `fam`, `name`, `spec.name`, `FAMILY`, `NAME`, `row.family`, `cfg.name`) next to
`|`, `:`, `/` or `#`, across `src/`, `scripts/`, `atlas/`, `viewer_app/`,
`.claude/skills/**/*.py`, `tests/conftest.py` and `tests/summary_fakes.py`; plus a scan of
every family's cleaned plan rows for key and path strings. 184 seed / hash lines in `src`
were read; the ones that can see one of the eight families are below. A site that only ever
sees another family (chain_intermediates, directed_modulation, MCDM, role-bound,
user_modeling, wrong_intermediate, poetry, moral, msdm, kcutoff, introspection option / pool
seeds) is out of scope and unchanged.

| # | site | what embeds the name | disposition |
|---|---|---|---|
| F1 | `basic/mcjudge_bank.py:161` `options_of` | option order of the single-token multihop judge: `mc.seeded_shuffle(content, f"{family}\|{item['id']}")`; pinned by `tests/golden/multihop_mc_options{,_v5}.json` | gets `frozen_name(family)` |
| F2 | `split.py:16` `is_dev` | `seed_int(f"{family}:{key}")`, the dev/test split of `extras.layer_protocols` (callers: `basic/family.py:155`, `basic/mcjudge_bank.py:887`, `basic/mcjudge_basic.py:605`, `multitoken/family.py:887`) | gets `frozen_name` inside `is_dev` |
| F3 | `evals/introspection/items_v2.json` `vectors.*.path` -> `readplan.vector_file` -> `extra.steering.vector_file` of 1,750 plan rows | a pre-0101 repo PATH inside `plan_sha` and the ATI `bank_sha` | the row string is kept as written; the producer opens it through `registry.repo_path` (§4; ruling 0.4.2) |
| F4 | `basic/prompts.py:108` `DIGEST_TASK_NOTES_TEXT` | a printed record `"<family>: <note>"`, in `basic.prompts.PROMPTS["DIGEST_TASK_NOTES"]`; hashed only by the pin in `tests/test_basic_prompts.py`; printed in ONE README (`evals/typo/README.md`); never sent to a model as a whole | keys renamed with the families; the pin's sha constant is re-pinned (the one sanctioned sha change, §9.2 V1). `PROMPT_VERSION` stays `bank-2026-10-30b` |
| F5 | `capable/run.py:100,136,148,179` | reply / grade cache keys `f"{family}\|{q.id}\|d{d}"`, `f"{family}\|{q_id}\|g…"` | gets `frozen_name` |
| F6 | `adapt/generate.py:295`, `adapt/author.py:1463` | `random.Random(f"{family}:{tier}:{seed}")`, `random.Random(f"{model}:{family}:{len(pool)}")`: candidate generation of a set that is mid-refill | gets `frozen_name` |
| F11 | `multitoken/options.py:101,126,134` | language-distractor seeds `f"{R4_LANG_SEED}\|{family}\|{gold}"`, `…\|balanced\|{family}`, `…\|balanced\|{family}\|{name}`; live caller `adapt/author.py:83-95`, builders `scripts/build_r4_mc_banks.py:101-122`, `scripts/build_r4b_mc_banks.py:75-109`; pinned against the frozen banks by `tests/test_r4b_mc_banks.py:96` and `tests/test_r4_bridge_ml.py:403,407` | gets `frozen_name` in all three seeds. `R4_LANG_POOLS` (`options.py:68`) keys are renamed (`multilingual` -> `multilingual_st`, `multilingual_mt` -> `multilingual`), values untouched. Both tests must pass with NO value change |
| F12 | `adapt/author.py:1506` | the authoring prompt says "…WorkspaceBench family {family}: …"; authoring calls are cached by a hash of the prompt | gets `frozen_name(family)` in the prompt text, so a mid-refill set re-uses its authoring cache and authors from the same prompt bytes. Not a judge prompt; the manifest pins its sha (§11.1) |
| F13 | `adapt/onecue.py:154,168` | option-order seed and cache key `f"{VERSION}\|{row.family}\|{row.id}\|{row.role}\|…"` (families: single-token multihop, the multi-token basic_readout and multilingual, two unaffected) | gets `frozen_name(row.family)` in both |
| F14 | `scripts/lens_readouts_modal.py`: `row_sha` (101-108), `_job` (617), `store_path` (553), the export (690-722) | `row_sha` is sha256 of the WHOLE plan row, and `ROW_SHA_EXCLUDE` (75) does not drop `family`, whose value is the current key (`_plan_rows`, 545-550). `row_sha` keys the resumable cell store (`stored_shas` 557, 599-601) and is the third component of the `_job` sampling seed `sha256(f"{arm}\|{fam}\|{row_sha}")`. Unfixed, every stored cell of all eight families misses (a full GPU re-read) and the seed moves. `store_path` is `<store>/<subject>/<arm>/<family>.jsonl`, so new multi-token cells would APPEND to an old single-token `multihop.jsonl` | (a) `row_sha` hashes the row with `family` replaced by `frozen_name(family)` (nothing else changes; layers stay hashed). (b) `_job` seeds with `frozen_name(fam)`. (c) Store-path rule, §5.9: reads take every `lookup_names` candidate that content-attributes to the family; writes go only to `<current key>.jsonl` and are refused when that file belongs to the partner. (d) the export writes `<out>/<current key>.jsonl` under the same refusal |
| F15 | `scripts/r4b_mc_refine.py:773`, `scripts/common_confusers_r5.py:198,242,248,538,593` | seeded draw `draw(lists[k], f"{family}\|{k}", rnd)`; gate-row keys and `gate_r5.json` keys `f"{family}\|{id}"` (the gate key also feeds `gate_sampling.seed`). These builders are LIVE for adapted sets (`adapt/mcstage` runs them into `adapted/<m>/mc/<family>/build-<hash>/`). (`r4b_mc_refine.py:369` `f"{family}\|{source_bank(family)}"` is an in-process dict key, not a hash or a stored key: harmless either way, converted too for uniformity) | get `frozen_name(family)` at every listed line |
| F16 | `src/wsbench/produce/producer.py:196-219` `run_family` | resumable by item id: it reads the ids already in `out`, then opens `out` with `"a"`. No row hash and no family in a key (rows are the readout contract: id, layer, pos, token, samples), but `produce family=multihop out=<root>/multihop.jsonl` over a pre-0101 single-token file would append multi-token rows to it and then write a multi-token sidecar over it | before reading `done`: when `out` exists and the family is in a pair, `registry.owner(<bare key>, ids=readouts.ids_in(out))` must not be the partner and must not raise "both"; else `RenamedKey`, nothing opened. A fresh `out` is unaffected |
| — | `reads._clean_row` (`reads.py:98`), `text_inversion._row_dict` (1290), `qwen_seed` (943), `lucky_guessing._rng` (769) and its call keys (1474, 1512), `gate_sampling.seed` (33), `scripts/r4_mc_select.py:245,290` | family in plan_sha / bank_sha / seeds | uses `hash_name` already: unchanged |
| — | `adapt/generate.py:306`, `adapt/author.py:1635` | item ids `f"{family.split('_')[0]}-{tier}-…"`, `…-au-…` | the first `_` segment is the same string before and after for all eight keys: unchanged. Consequence (note 12 of the critique): both members of a pair share the `multihop-au-` / `basic-au-` id prefix, so F10's disjointness is an observed fact, not a structural one; T5 runs over every set and `owner(ids=)` raises on "both" |
| — | `baselines/text_inversion.py:896` `run_key(out)` | hashes the `out` PATH (the Modal answers volume key), not a family | not hash-relevant. A work dir path that contains a family key is the caller's choice |
| — | every other place a plan ROW is hashed or keyed (swept: `row_sha`, `plan_sha_rows`, `.row()`, `json.dumps(row…)` + sha across `src/`, `scripts/`, `atlas/`, skills): `reads.plan_sha_rows` and `fast_plan_sha` (via `_clean_row`), `text_inversion._row_dict`, `scripts/dmo_control_plan.py:28` and `scripts/drop_frac_0083.py:83` (both call `reads.plan_sha_rows`), `readplan.write` (1414, writes rows, hashes nothing), `adapt/run.py:787` (rows for `lineage_step`, which cleans them with `_clean_row`), `scripts/evidence_mh2.py:205` (prints a row) | plan rows | all go through `hash_name` already or hash nothing: unchanged. `scripts/lens_readouts_modal.py` (F14) is the only raw row hash in the repo; no other driver is vendored here (`ati_qwen_modal.py`, `qwen_sample_modal.py`, `adapt_modal.py` key their requests by `gate_sampling.seed` / `qwen_seed`, already on `hash_name`) |
| — | `adapt/mcstage.py:232` `work_dir`, `adapt/mhmt2.py:1808` `_work_dir` | hash of the candidate items / ids; the family is only the parent directory (`family_dir`) | hash unchanged; the directory lookup is §5.5 |
| — | `mcjudge.Call` fingerprint; every cache key of the eight families (`<item id>\|L<layer>[\|<role>]`, `digest:<id>\|<layer>`, `ntok:<id>\|…`); the digest fingerprint (`digest.py:1825`); `mcjudge_basic` option seeds (`<OPTIONS_VERSIONS stamp>\|<id>`); `multitoken/options.py:151-214` (`<MC_SEED>\|<item name>\|<role>`); `adapt/rebuild.py:67`; `scripts/build_multilingual_v2.py:182`, `build_r4_mc_banks.py:74`, `build_multihop_mc.py:661` (item names only) | no family key | not hash-relevant |
| — | every result stamp (§3.2), the task note each family's digest is told (text only), `EvalSpec.title` (read by `wsbench list`, the README tests and the viewer; in no prompt) | no family key | not hash-relevant |
| — | error and log messages (`f"{family}: …"`, `f"{family}/{id}: …"`), `scripts/mc_options_r5.py:1051,1130,1150,1519` lock labels `r5:{cfg.name}:…`, `text_inversion.py:1392` `supersede` keys (CLI input, current keys) | text only | not hash-relevant |
| — | `tests/conftest.py`, `tests/summary_fakes.py` | no seed or hash over a family key (the one family use is the `iter_modules` walk, §4) | not hash-relevant |

The manifest (§11.1) records an output of EVERY row marked "gets" or "already", so the
inventory is checked by a byte comparison, not by trust.

### 2.3 Code that derives something from a family key's SPELLING (prefix, suffix, substring, split, regex)

A rename table preserves IDENTITY uses of a key (`family == "typo_mt"`, membership in a set or
tuple of keys, dict lookups): each literal maps to the same family, so R4 is right there, and
that covers every key set in the repo (`RAW_REGEX_FAMILIES`, `ANCHOR_SUPPORT_FAMILIES`,
`PIN_FAMILIES`, `ALIAS_FAMILIES`, `PREMISE_FAMILIES`, `MC_FAMILIES`, `MC_BANK_FAMILIES`,
`onecue.FAMILIES`, `NOT_GATED`, `ATI_EXCLUDE`, `TOPIC_FAMILIES`, `LITE_*_FAMILIES`,
`viewer.build.GROUPS`, the `capable` and `adapt.families` tables). It does NOT preserve logic
that reads the spelling. Swept: `.startswith(` / `.endswith(` / `.removeprefix(` /
`.removesuffix(` / `.split(` / `.rsplit(` / `.partition(` / `.replace(` on a family-like
variable; `"_mt"`, `"_st"`, `"-mt"`, `"-hard"` literals; `[:-3]`-style slices; `re.*` calls
and `in <string>` tests naming a key; f-strings that build a key from another
(`f"{x}_mt"`); glob patterns on keys; over `src/`, `scripts/`, `atlas/`, `viewer_app/`,
`.claude/skills/`, `tests/conftest.py`, `tests/summary_fakes.py`. Every hit:

| site | today, over the 32 families | after | new code |
|---|---|---|---|
| `adapt/onecue.py:146` `if family.startswith("multilingual"):` | true for the 4 multilingual families (of which onecue's `FAMILIES` holds 3: `multilingual_mt`, `multilingual_typo`, `multilingual_multihop`): the target forms join the gold's banned forms | must stay true for the same families, now keyed `multilingual`, `multilingual_typo`, `multilingual_multihop` (and `multilingual_st`) | UNCHANGED text. All four new keys still start with `multilingual`. R4 would have made it `startswith("multilingual_st")`, true for one family, silently dropping the target forms for the other three. KEEP pattern (§8.2); manifest row (§11.1) |
| `adapt/generate.py:306` `family.split('_')[0]`, `adapt/author.py:1635` same | the first `_` segment as an id prefix: `basic`, `multihop`, `multilingual`, `typo` for the eight; unique segment for the rest | the same four strings (`basic_readout_st` -> `basic`, `multihop_st` -> `multihop`, …) | unchanged; the manifest records the generated ids' prefix per family |
| `multitoken/regex.py:311,318,319` `family.endswith("-mt")`, `family != "multilingual-mt"` | `family` here is the bank HEADER's value (`header.get("family", name)` at `mcrx.py:340`, `family.py:747,1882,2580,2654`), source vocabulary with hyphens; with the registry key as fallback both tests are False / True for all 32 (keys have no hyphen) | identical: header values never change (F9) and no new key ends in `-mt` | unchanged; hyphenated literals are a KEEP pattern |
| `baselines/prompt_only.py:390,408`, `text_inversion.py:1830` `fam.startswith("_")` | skips metadata keys (`_source`, `_not_gated`) of a frozen file | same | unchanged |
| `atlas/build.py:575,625`, `viewer_app/index.py:452,531` `jd.name.endswith("_opus")` / `.replace("_opus", "")` | strips a run-dir suffix, then uses the directory name as the family | the name is a pre- or post-0101 key | §5.8: the family comes from `read_results` / `dir_owner`, not the name |
| `viewer_app/index.py:508` `s, fam = f.stem.split(".", 1)` | family from an exported readouts file stem `<subject>.<family>.jsonl` | stems of old exports are pre-0101 keys | §5.8: `registry.owner(<stem>, ids=readouts.ids_in(f))` for a bare-key stem; unattributable -> skipped with a logged line |
| `atlas/normal_gated.py:98,197,228` gate keys `f"{fam}/{iid}"`, `k.startswith(fam + "/")` | per-item gate map; line 197 loads a PERSISTED map keyed `<family>/<id>` | a persisted map written before 0101 has bare keys meaning the single-token family | the loaded map is re-keyed once on load: `<key>/<id>` -> `<registry.owner(key, ids=[id]) or canonical(key)>/<id>`; the prefix test itself is unchanged (the `/` makes it exact) |
| `scripts/evidence_mh2.py:271` `"multihop" in ln` | a substring filter over listing lines in a dated evidence script | historical script | unchanged (KEEP pattern; not live) |
| `scripts/typo_mt_drop_arith.py:71` `REPO.glob("adapted/*/typo_mt.json")` | a dated one-off migration | historical | R6 rewrites the stem to `typo.json` (an identity use of a file name); nothing else |
| `tests/*` `"<key>" in <collection>` assertions (`test_capable.py:256-257`, `test_readplan.py:185,189`, `test_registry.py:81-82`, `test_tiers.py:80`, `test_text_inversion.py:88-89,887,893`, `test_multihop.py:96,98`) | membership in a dict / list / set of keys | identity | R4 is right (e.g. `"typo_mt" in seen and "typo" not in seen` becomes `"typo" in seen and "typo_st" not in seen`); those in KEEP files are hand-edited |

No code builds one key from another (`+ "_mt"`, `f"{x}_mt"`, `removesuffix("_mt")`, a `[:-3]`
slice on a key) and no regex names a key; `rg` found none. T17 (§9.3) keeps it that way: an
`ast` scan fails on any new `startswith` / `endswith` / `removeprefix` / `removesuffix` /
`split` / `re.*` call whose argument or receiver is one of the 40 current or former keys
outside a small allowlist holding exactly the rows above.

### 2.4 Other facts that shape the design

- F7. `baselines/logit_lens.py:146` uses `registry.HASH_FAMILY_NAMES[family]` as a FILE-NAME
  fallback. After this plan `hash_name("multihop_st") == "multihop"`, another live family's
  key. That line becomes `registry.lookup_names(family)` plus the content rule; a test asserts
  `HASH_FAMILY_NAMES` and `FROZEN_KEY_NAMES` are referenced in `registry.py` only (T9).
- F8. Name collisions between levels: the FAMILY `association` (category `basic`) and the
  CATEGORY `association` (families conjunctive_association, user_modeling). After the move
  `evals/association/` and `wsbench.evals.association` are the category; the family is
  `evals/basic/association/`, `wsbench.evals.basic.association`. Consequences handled below:
  the move order (§8.3), `repo_path` (§4), the script's idempotence (§8.1). Also
  `wsbench.evals.basic` (category) is not `wsbench.basic` (the shared bank judge). Category
  packages export nothing, so a stale `from wsbench.evals.association import judge` fails.
- F9. Every bank file of the eight families, registered (36 files) and adapted (all 125), has
  a header `"family"` value from the SOURCE repo's vocabulary, which never changed with our
  keys and is the reliable content label of a bank:

  | header `"family"` | family (key after) |
  |---|---|
  | `basic-readout` | basic_readout_st |
  | `basic-readout-hard` | basic_readout |
  | `multihop` | multihop_st |
  | `multihop-hard` | multihop |
  | `multilingual` | multilingual_st |
  | `multilingual-hard` | multilingual |
  | `typo` | typo_st |
  | `typo-hard` | typo |

  Trap: three of these values (`multihop`, `multilingual`, `typo`) are spelled like the bare
  keys and mean the `_st` family. They are bank bytes, are never rewritten (the migration
  script's KEEP patterns, §8.2), and are compared only through this table (`Reused.live_header`
  / `other_header`, §3.2), never to a key.
- F10. Within each pair the two families share no item id, over every registered bank version
  AND every in-repo adapted bank (checked: basic_readout 606 vs 1,119 ids, multihop 657 vs 427,
  multilingual 123 vs 615, typo 223 vs 728; overlap 0 in all four). So item ids identify the
  family of a readouts file or a cache today. A test pins it over every set (T5).

## 3. `src/wsbench/registry.py`

### 3.1 Tables

```python
# Former keys that mean exactly ONE current family (pure renames). canonical() is single-step.
LEGACY_FAMILY_NAMES = {
    "introspection_inject": "introspection",
    "cutoff_confab": "knowledge_cutoff",
    "dm_category_default": "model_specific_directed_modulation",
    "directed_modulation_obscure": "model_specific_directed_modulation",
    "wrong_bridge": "wrong_intermediate",
    # plan 0101: the multi-token families took the plain keys
    "multihop_mt_v2": "multihop",  # was -> "multihop_mt" (2026-11-04); single-step, so it
    "multihop_mt": "multihop",  # now points straight at the current key
    "basic_readout_mt": "basic_readout",
    "multilingual_mt": "multilingual",
    "typo_mt": "typo",
}
```

Retained from the 2026-11-04 rename, restated because the entry is rewritten:
`canonical("multihop_mt_v2")` still resolves to the multi-token multihop family in one step
(its key is now `multihop`), and `legacy_names("multihop")` lists `multihop_mt_v2` BEFORE
`multihop_mt` (dict order), so a file under `multihop_mt_v2` still wins over one under
`multihop_mt`, which may be the removed regex family's. The bare keys `basic_readout`,
`multihop`, `multilingual`, `typo` are NOT in this map: on the command line they mean the
multi-token family (§5.6).

```python
# The key a family hashes under in plan_sha / bank_sha / seeds / option orders: frozen.
HASH_FAMILY_NAMES = {
    "wrong_intermediate": "wrong_bridge",
    "multihop": "multihop_mt_v2",  # retained: was HASH_FAMILY_NAMES["multihop_mt"]
    "basic_readout": "basic_readout_mt",
    "multilingual": "multilingual_mt",
    "typo": "typo_mt",
    "basic_readout_st": "basic_readout",
    "multihop_st": "multihop",
    "multilingual_st": "multilingual",
    "typo_st": "typo",
}
```

Retained: every family hashes under exactly the string it hashes under today (the multi-token
multihop family keeps `multihop_mt_v2`, as since 2026-11-04). `hash_name` stays
un-canonicalized. NEW rule in its docstring: a hash name is an opaque hash input, never a
lookup key or a file name (F7); `hash_name` is not idempotent across a pair
(`hash_name("multihop_st") == "multihop"`, `hash_name("multihop") == "multihop_mt_v2"`), so it
is applied once, to a CURRENT key.

```python
# The key each family had on main just before plan 0101: what every site that embedded the RAW
# key then (option orders, the dev split, capable / onecue / builder cache keys, adapt seeds,
# the authoring prompt, the producer's sampling seed; §2.2) embeds now. The inverse of §0.1.
FROZEN_KEY_NAMES = {
    "basic_readout": "basic_readout_mt",
    "multihop": "multihop_mt",
    "multilingual": "multilingual_mt",
    "typo": "typo_mt",
    "basic_readout_st": "basic_readout",
    "multihop_st": "multihop",
    "multilingual_st": "multilingual",
    "typo_st": "typo",
}


def frozen_name(name: str) -> str: ...  # FROZEN_KEY_NAMES.get(name, name); never canonicalized
```

It differs from `hash_name` only for `multihop` (`multihop_mt` here, `multihop_mt_v2` there;
§2.1). An import-time check asserts `FROZEN_KEY_NAMES` is exactly the inverse of
`PRE_0101_KEYS` minus `multihop_mt_v2`.

```python
# The key every family had on main just before plan 0101 -> its key now: the map for files that
# are frozen in the old vocabulary (evals/fast/*.json, the archived floor, goldens) and for
# pre-0101 layout paths (repo_path). Never used for user input.
PRE_0101_KEYS = {
    "basic_readout": "basic_readout_st",
    "basic_readout_mt": "basic_readout",
    "multihop": "multihop_st",
    "multihop_mt": "multihop",
    "multihop_mt_v2": "multihop",
    "multilingual": "multilingual_st",
    "multilingual_mt": "multilingual",
    "typo": "typo_st",
    "typo_mt": "typo",
}


def from_pre_0101(key: str) -> str: ...  # PRE_0101_KEYS.get(key, canonical(key))
def rekey_pre_0101(d: Mapping[str, V]) -> dict[str, V]:
    ...  # keys translated, order kept;
    # two keys landing on one key -> ValueError
```

### 3.2 `REUSED_FAMILY_KEYS`, generalised (one mechanism, five entries)

Today: `{"multihop_mt": ("multihop_mt_regex", (<live stamp prefixes>))}`. It becomes a map from
EVERY key that two families have held to a record of both holders:

```python
@dataclass(frozen=True)
class Reused:
    live: str  # the family the key means when typed today (a current key)
    other: str  # the family that held it before (a current or removed key)
    live_stamps: tuple[str, ...]  # result-stamp prefixes of `live`
    other_stamps: tuple[str, ...] | None  # CLOSED list of the prefixes `other` ever wrote under
    # this key; None = every stamp that is not live's
    live_header: str | None = None  # bank header "family" value of `live`'s banks (F9)
    other_header: str | None = None
    since: str = ""  # for messages: "2026-11-20 (plan 0101)"


REUSED_FAMILY_KEYS: dict[str, Reused] = {
    # 2026-11-04, retained unchanged in behaviour: `other_stamps=None`
    "multihop_mt": Reused(
        "multihop",
        "multihop_mt_regex",
        ("mh2-mc-", "mt-regex-2026-10-30+md+fz"),
        None,
        "multihop-hard",
        None,
        "2026-11-04",
    ),
    # plan 0101
    "basic_readout": Reused(
        "basic_readout",
        "basic_readout_st",
        ("mc-brmt-", "mt-regex-", "mc-2026-"),
        ("br-mc-", "bank-"),
        "basic-readout-hard",
        "basic-readout",
        "2026-11-20 (plan 0101)",
    ),
    "multihop": Reused(
        "multihop",
        "multihop_st",
        ("mh2-mc-", "mt-regex-2026-10-30+md+fz"),
        ("bank-",),
        "multihop-hard",
        "multihop",
        "2026-11-20 (plan 0101)",
    ),
    "multilingual": Reused(
        "multilingual",
        "multilingual_st",
        ("mt-regex-",),
        ("mcrx-", "bank-", "mt-regex-2026-10-30+leg-regex"),
        "multilingual-hard",
        "multilingual",
        "2026-11-20 (plan 0101)",
    ),
    "typo": Reused(
        "typo",
        "typo_st",
        ("mt-regex-", "mc-2026-"),
        ("bank-",),
        "typo-hard",
        "typo",
        "2026-11-20 (plan 0101)",
    ),
}
```

Retained for `"multihop_mt"`, restated because the entry is rewritten: a stored result under
`multihop_mt` whose stamp starts with `mh2-mc-` or `mt-regex-2026-10-30+md+fz` is the
multi-token multihop family's (read under its current key, now `multihop`); ANY other stamp
(`mc-2026-09-16`, `mt-regex-2026-09-23`, …) is the removed regex family's, read as
`multihop_mt_regex` and excluded from the macro as `removed`. `REMOVED_FAMILIES
["multihop_mt_regex"]` is unchanged except that its text names the live key `multihop`.

Stamp prefixes, as verified against every stamp in the repo's floors, ATI files, adapted
`floors/` and `lenses/scores.json` (the stamps found: single-token `bank-2026-10-10`,
`bank-2026-10-30b`, `bank-mc-2026-11-01-v3…`, `br-mc-2026-11-01-v5b…`, `mcrx-2026-11-0…`;
multi-token `mc-brmt-2026-10-31r…`, `mh2-mc-2026-11-01…`, `mt-regex-2026-09-23`,
`mt-regex-2026-10-30+…`, `mc-2026-09-16`). The longest matching prefix over both tuples
decides (so `mt-regex-2026-10-30+leg-regex`, the single-token multilingual family's
`opts=judge=regex` diagnostic, beats `mt-regex-`).

Settled against the code (critique finding 4): `multitoken/family.py:1958` and `:2194` set
`diag_pv = ML_MC_PROMPT_VERSION if v2 else PROMPT_VERSION` for ANY multilingual family under
the unpinned `opts=judge=mc`, and both members of the multilingual pair are `mt_family`
families on v2-shaped banks. So a `mc-ml-…` or `mc-2026-…` stamp under the key `multilingual`
can be either member's diagnostic: both prefixes are in NEITHER tuple of that entry, and such
a result is `RenamedKey` (refused, never guessed). For the other three pairs the single-token
member is a `bank_family` and cannot emit an `mc-` or `mt-regex-` stamp, so `mc-2026-` stays
in their `live_stamps`. The implementer still runs `git log -S` over `basic/prompts.py`,
`multitoken/prompts.py`, `multitoken/regex.py` for every historical value of the stamp
constants and adds any prefix found to the right tuple. Import-time invariant, also a test (T2): for each entry whose
two holders are registered, each holder's registered `prompt_version` classifies as that
holder.

### 3.3 Functions (exact behaviour)

```python
class RenamedKey(SystemExit): ...  # exit 2; the message names the rename and both keys
```

- `canonical(name)`: unchanged (`LEGACY_FAMILY_NAMES.get(name, name)`).
- `legacy_names(name)`: unchanged.
- `partner(name) -> str | None`: the other member of `name`'s 0101 pair (`multihop` <->
  `multihop_st`, …), else None.
- `shared_key(name) -> str | None`: the bare key `name`'s pair has shared (`multihop` for both
  members), else None.
- `lookup_names(name) -> list[str]`, the keys a file or directory of the current family `name`
  may sit under, in lookup order:
  - a family that is the `other` of a reused key (the four `_st` families): `[name, <bare key>]`;
  - a family that is the `live` of a 0101 reused key (the four multi-token families):
    `[name, *legacy_names(name)]`, e.g. `["multihop", "multihop_mt_v2", "multihop_mt"]`,
    `["basic_readout", "basic_readout_mt"]`;
  - every other family: `[name, *legacy_names(name)]` (unchanged:
    `["wrong_intermediate", "wrong_bridge"]`).
  Retained from 2026-11-04: `multihop_mt_v2` is still tried before `multihop_mt`. Changed: the
  current key is tried first for the 0101 pairs, which is safe only because every hit under a
  bare key is checked by content (`owner`, below); the old "former key first for a reused key"
  order existed because `multihop_mt` files could not be told apart by content.
- `owner(key, *, stamp=None, header=None, ids=None, plan_sha=None) -> str | None`: which
  holder of the reused `key` the evidence identifies; None with no evidence. Rules, in order:
  `stamp` (non-empty): `Reused` prefixes, longest match; a non-empty stamp matching neither
  tuple raises `RenamedKey`. `plan_sha`: equal to `reads.plan_sha(live)` or `(other)` (passed
  in by the caller as a pre-computed pair, so `registry` does not import `reads`). `header`:
  `live_header` / `other_header`. `ids`: `live` when the ids intersect only `family_ids(live)`,
  `other` when only `family_ids(other)`, None when neither, `RenamedKey` when both. Two kinds
  of evidence that disagree raise `RenamedKey`.
- `attribute_rows(rows) -> rows`: each row's `family` re-keyed by its own id (§5.7a):
  `canonical` for a non-reused key, `owner(key, ids=[row["id"]])` for a reused one,
  `RenamedKey` when the id is in neither member's banks.
- `family_ids(family) -> frozenset[str]`: every item id of every `items*.json` under
  `family_root(family)` plus, under `$WSB_BANK_ROOT`, the set's bank of the family when the
  set has one; cached per (family, root). It must NOT call the exiting `bank_path`: ten
  in-repo sets have a multi-token typo bank and no single-token one, and asking for the
  partner's ids there has to return the registered ids, not exit. It uses `root_bank(base,
  family)` (below), which returns None for a missing bank.
- `root_bank(base, family) -> Path | None`: THE rule for "which file under an adapted root is
  this family's bank", used by `bank_path`, `family_ids`, `readplan.families`,
  `adapt/run.py:774` and `:852-856`, `adapt/store.bank_file`: the first `lookup_names` file
  that exists and passes the header rule (a file under a reused key: the multi-token family
  takes it unless its header is `other_header`; an `_st` family takes it only when its header
  IS `other_header`). No caller tests `(base / f"{k}.json").exists()` on its own any more, so
  a pre-0101 set that holds only the single-token `multihop.json` no longer "has" the
  multi-token family.
- `bank_pins(family) -> list[str]`: THE list of `WSB_BANK_FILE_<NAME>` variables that pin a
  family, used by `bank_path`, `runner.adapted_bank_stamp` (240-241), `fast.entry` (93) and
  `reads.lineage_drops` (207), which today each build `(fam, *legacy_names(fam))` themselves:
  the current key, its former keys, and for an `_st` family ALSO the bare key (so a pre-0101
  `WSB_BANK_FILE_MULTIHOP` is seen, not ignored, by `multihop_st` and by the fast "pins fail
  closed" check).
- `stored_family(stored_key, prompt_version) -> str`. SIGNATURE CHANGE: it takes the key AS
  STORED (not canonicalized), because the two reused keys of the multihop family resolve
  differently. `stored_key` not in `REUSED_FAMILY_KEYS` -> `canonical(stored_key)`. Else, by
  stamp: live -> `r.live`; other -> `r.other`; EMPTY or missing stamp -> `r.live` (the bare key
  means the live family unless the content says otherwise; hand-built test results have no
  stamp); a non-empty stamp of neither -> `RenamedKey`. For `multihop_mt`
  (`other_stamps=None`) a non-live stamp, empty included, is `multihop_mt_regex`, exactly as
  today.
- `family_dir(root, name) -> Path`: for each key of `lookup_names(name)` whose directory
  exists: a key not in `REUSED_FAMILY_KEYS` is returned as today; a reused key is returned only
  if `dir_owner(path)` is `name` or None-and-`key == name`; a directory owned by the partner is
  skipped. If nothing is returned and `root/name` exists but belongs to the partner:
  `RenamedKey` ("`<root>/multihop` holds results of `multihop_st`, written before 2026-11-20
  when the single-token family was keyed `multihop`; use a fresh `out=` or rename the directory
  to `multihop_st`"). Else `root/name`. Retained from v1.2.0 / 2026-11-04: an existing
  directory under a former key is reused so its cached verdicts are kept; `multihop_mt`
  directories keep today's rule (no content check: the removed family has no bank to compare).
- `dir_owner(path) -> str | None`: `results.json` present -> `stored_family(its family, its
  config.prompt_version)`; else the item ids of the first 2,000 rows of `cells.jsonl` or (a
  digest store dir) `L*.jsonl`, each id = the row `key` minus a `digest:` / `ntok:` prefix, cut
  at the first `|` -> `owner(key, ids=…)`; else None.
- `bank_path(family)`. Pins (`bank_pins`): a variable named for a BARE key
  (`WSB_BANK_FILE_MULTIHOP`) is ambiguous by construction, so its file must carry a header
  that POSITIVELY matches: for the multi-token family `live_header`, else exit ("the file's
  header is `<value or none>`; `WSB_BANK_FILE_MULTIHOP` pins the multi-token family since
  2026-11-20"); for the `_st` family, a bare-key variable whose file's header is
  `other_header` exits with "rename the variable to `WSB_BANK_FILE_MULTIHOP_ST`" (never
  silently used, never silently ignored); a header-less or list-shaped file under a bare-key
  variable exits for both. A variable named for an unambiguous key (`…_MULTIHOP_ST`,
  `…_MULTIHOP_MT`, `…_MULTIHOP_MT_V2`) is taken as today, with one check: a header that is the
  partner's value exits. Under `$WSB_BANK_ROOT`: `root_bank`, else the existing "has no bank
  for" exit, with the rename named when a skipped partner file was seen. Without overrides:
  `REPO_ROOT / spec.bank` as today. (Tests that pin a toy bank through a bare-key variable
  gain the header; listed in §9.2 V7.)
- `overlay_path`: unchanged apart from `lookup_names` (overlays stay
  `adapted/<m>/<family>/<file>`; the only overlay dirs of the eight families are the 16
  `basic_readout_mt/` dirs, renamed to `basic_readout/`; an unmigrated set's
  `basic_readout_mt/` is still found through `lookup_names("basic_readout")`, and the
  single-token family has no overlay dir in any set, so the bare-key overlay dir is the
  multi-token family's by construction; `overlay_path(<_st family>, …)` therefore never looks
  under the bare key).
- `load_all()`: walks two levels (§4).
- `register(spec)`: additionally raises `ValueError` when `spec.name` is in the package layout
  and `spec.group != category_of(spec.name)` (a family's directory is its category).

## 4. Path resolution: one helper family, one rule

```python
@functools.cache
def _layout() -> dict[str, str]:
    """family -> category, read from the package tree without importing anything:
    wsbench.evals.__path__/<category>/<family>/__init__.py. A family in two categories, or a
    category that is not a key of CATEGORIES, is a ValueError."""
def category_of(family: str) -> str            # canonical first; unknown -> KeyError
def family_rel(family: str) -> Path            # Path("evals") / category / family  (EvalSpec.bank, messages, README links)
def family_root(family: str) -> Path           # REPO_ROOT / family_rel(family)
def family_module(family: str, sub: str = "") -> ModuleType
    # importlib.import_module(f"wsbench.evals.{category}.{family}" + (f".{sub}" if sub else ""))
def repo_path(rel: str | Path) -> Path
    # REPO_ROOT / rel, except a path of the pre-0101 layout. Order of the rule (F8: `association`
    # is both a pre-0101 family key and a category):
    #   1. evals/<seg1>/<seg2>/… where (seg1, seg2) is a (category, family) pair of _layout()
    #      -> as written (a new-layout path, e.g. evals/association/conjunctive_association/…);
    #   2. evals/<seg1>/… where seg1 is baselines | fast | hallucinationbench -> as written;
    #   3. evals/<seg1>/<rest> where seg1 is a pre-0101 family key
    #      -> family_root(from_pre_0101(seg1)) / <rest>;
    #   4. anything else -> as written.
    # ONLY for path strings frozen inside data (F3 and the informational "bank" strings of
    # adapted report.json, which pre-0101 sets wrote in the old layout and post-0101 builds
    # write in the new one). Never for user input.
```

- `resource_path(family, name)` = `family_root(family) / name`. `frozen_bank_path` and
  `bank_path` are unchanged in form (`REPO_ROOT / spec.bank`).
- `EvalSpec.bank` stays a REPO_ROOT-relative `Path`, now built from `family_rel`:
  `bank=registry.family_rel("multihop") / "items_v6.json"`. The two factories' defaults
  (`basic/family.py:61`, `multitoken/family.py:~286`) become `family_rel(name) / "items.json"`.
- `load_all()`: `for category in pkgutil.iter_modules(evals_pkg.__path__)` then
  `for mod in pkgutil.iter_modules(<category path>)` -> `import_module(f"wsbench.evals.
  {category}.{mod}")`. `adapt/run.py:865-870` does the same walk through a new
  `registry.family_packages() -> list[str]` (dotted names) instead of its own `iter_modules`.
- By-name imports replaced by `family_module` (R1 of the script cannot match an f-string, so
  each of these is a listed hand edit, §8.6):
  - src: `registry._spec_for_bank` (365), `basic/mcjudge_bank.strings_of` (139),
    `baselines/prompt_only.py` (81, 99). `adapt/run.py:863-870` walks the packages itself and
    does `getattr(module, "SPEC", None)`: left one-level it would SILENTLY register nothing
    (a category package has no `SPEC`), so it must use `registry.family_packages()`.
  - tests: `tests/conftest.py:141-146` (the `real_families` fixture's one-level
    `iter_modules` walk + `.SPEC`: becomes `registry.family_packages()`),
    `test_prompts_in_readme.py:29`, `test_digest.py:517`, `test_lucky_guessing.py:23`,
    `test_multilingual.py:50`, `test_multilingual_language_leg.py:37`,
    `test_mt_regex.py:302,342`, `test_multitoken_family.py:205`,
    `test_prompt_only_scorer.py:28`, `test_round5_leakage_standard.py:37`,
    `test_round4_lucky_topic.py:21`, `test_runner.py:335`, `test_bank_judge_v2.py:54`,
    `test_prompt_tool_names.py:37` (15 f-string imports in `tests/`). The literal ones
    (`test_multilingual_multihop.py:115`, `test_multilingual_cited_case.py:55`,
    `test_nyt_connections.py:228`) are covered by R1.
  - not family-keyed, unchanged: `adapt/refill.py:319` (`wsbench.adapt.<name>`),
    `evals/user_modeling/judge.py:601` (`import_module(__package__)`).
- `readplan.frozen_lite_rule` (128), `nocot.OBSCURE` (16), `lucky_guessing.py:1128`,
  `evals/jlens_concept_pr/judge.BANK_DIR`, `evals/typo_mt` `BANK`, and every other
  `REPO_ROOT / "evals" / family / …` or `"evals/<family>/…"` literal in `src/wsbench` (72 lines
  in 65 files) -> `registry.family_root(...)` / `family_rel(...)` / `resource_path(...)`.
- `readplan.families()` (1387-1404): iterates `registry._layout()` and keeps the families whose
  `family_root` has `items*.json` or `manifest.json`, instead of `(REPO_ROOT / "evals").iterdir()`;
  under `$WSB_BANK_ROOT` a family is kept when `registry.root_bank(base, f)` is not None (or its
  `manifest.json` dir exists), not when any `lookup_names` file exists (§3.3: a pre-0101 set
  with only the single-token `multihop.json` must not list the multi-token `multihop`).
- `readplan.vector_file` keeps returning the bank's string unchanged (F3);
  `produce/producer.py` `_vector` opens `registry.repo_path(steer["vector_file"])` when the
  path is relative. `adapt/moral.py:992` and `adapt/mcstage.py:127` ("is this path under
  `evals/`") keep working at any depth.
- Env values: `WSB_BANK_FILE_<F>=evals/<old>/items.json` is user input and is NOT translated; a
  missing file whose path has the pre-0101 shape exits with "family directories moved under
  category folders on 2026-11-20 (plan 0101): `<family_rel(...)>/…`".

The rule: outside `registry.py`, no code builds a family's data path or module name by hand.
Enforced by `tests/test_family_paths.py` (TP):

1. an `ast` scan of `src/wsbench/**/*.py`, `atlas/*.py`, `viewer_app/*.py`,
   `.claude/skills/**/*.py`: no non-docstring string constant matches
   `^evals/(<category>|<pre-0101 family key>)(/|$)` (one alternation over the union of both
   name sets, so the `association` overlap is a single alternative, not two rules); no `BinOp`
   chain `X / "evals" / Y` whose next operand is anything but the literals `"baselines"`,
   `"fast"`, `"hallucinationbench"`. `registry.py` is the one exempt file.
   In those files AND in `tests/**/*.py`: no f-string or literal starting `wsbench.evals.`
   passed to `import_module` (the §4 list above).
2. `scripts/*.py` are one-off builders that ran once; their literals are rewritten by the
   table and stay literals. The test holds the list of script files that contain such a
   literal (`tests/golden/script_path_literals_0101.txt`) and fails when a file NOT in the list
   gains one (the list may only shrink).
   The layout checks here and in §8.5 ignore directories that hold nothing but `__pycache__`:
   after a pull, a stale `src/wsbench/evals/multihop/__pycache__/` survives and Python treats
   the directory as a namespace package (imports from it still fail). The PR body says to run
   `git clean -fdX src/wsbench/evals`.
3. every `evals/…` path written in `README.md`, `CLAUDE.md`, `AGENTS.md`, `NOTICE.md`,
   `docs/{producing_readouts,summarizer,adapt_judge_inputs}.md`, `.claude/skills/**/*.md`
   (audit records excluded), every family README, `tests/**/*.py` and the listed scripts
   exists on disk (globs and `<placeholders>` skipped).

## 5. Where each lookup happens (fail closed everywhere)

### 5.1 `results.py`

- `read_results(out_dir)`: `family = registry.stored_family(result.family,
  result.config.get("prompt_version"))` (the `canonical(...)` wrapper is dropped: the function
  canonicalizes non-reused keys itself). A `RenamedKey` propagates: `report` already exits 2 on
  unreadable results, and the message names the directory.
- `adapted_exclusions()`: the report's `families` entries are attributed with
  `adapt.store.report_key` semantics (§5.5), not by raw `LEGACY_FAMILY_NAMES` lookup. Retained:
  an entry under the current key wins over one under a former key.
- `_spec_of` (332) and every `registry.FAMILIES.get(registry.canonical(family))` are unchanged:
  they see families that `read_results` already attributed.
- `scripts/audit_run.py:57` (`registry.canonical(res["family"])`) -> `stored_family`.

### 5.2 `reads.py`

`load(args, family, path)` is the last guard, whatever the file is called. New block right
after `meta = read_sidecar(path)`, only when `registry.partner(family)` is not None:

1. sidecar with `plan_sha`: if it equals `plan_sha(partner)` (or, for a fast file,
   `fast_plan_sha(partner, declared=…)` when the partner is in that subset) -> `fail` with
   "`<path>` holds `<partner>` readouts (the sidecar's plan is `<partner>`'s; before 2026-11-20
   `<bare key>` named the single-token family, plan 0101): judge it with `family=<partner>`".
   Otherwise guard (iii) runs unchanged (own plan, lineage, or the existing "different plan"
   refusal).
2. no sidecar `plan_sha`: `readouts.ids_in(path)` (new: the distinct `id`s of the file,
   streamed, malformed lines skipped) -> `registry.owner(shared_key, ids=…)`; the partner ->
   the same `fail`; both -> `fail` (mixed file); own or None -> continue as today (None ends in
   the existing missing-cells exit 2).

`reads.owner_of(path, family) -> str | None` exposes exactly this decision for the runner.
`lineage_drops` and `min_full_positions`'s report lookups go through `store.report_key`
semantics (§5.5) instead of `lookup_names` membership alone. `_clean_row` is unchanged
(`hash_name`).

### 5.3 `runner.py`

- `readouts_path(root, name)`: for each key of `registry.lookup_names(name)` whose
  `<key>.jsonl` exists: a key not in `REUSED_FAMILY_KEYS` is returned; `multihop_mt` is
  returned (retained: no content check); a 0101 bare key is returned unless
  `reads.owner_of(path, name)` is the partner (the multi-token family accepts unidentified
  content under its own key; an `_st` family accepts the bare key's file ONLY when it is
  positively identified as its own). So a pre-0101 root (`multihop.jsonl` single-token,
  `multihop_mt.jsonl` multi-token) serves both families, and a post-0101 root serves both.
- `admit` (765-775): the "reading legacy `<file>`" line stays; when the family's own-key file
  was skipped as the partner's, the skip message says so (`no readouts: <root>/multihop.jsonl
  holds multihop_st readouts (pre-0101 name)`).
- `adapted_bank_stamp` (240-241), `judge_argv`, `_one`, `_one_proc`: keys only; no logic
  change. The process-mode child is spawned with the CURRENT key and must not print the swap
  notice (§5.6).
- `run_families` `dest`: `registry.family_dir(out, s.name)` (837), now content-checked (§3.3).

### 5.4 `digest.py`, `fast.py`, `tiers.py`, `readplan.py`

- `digest.py:2468`: `family_dir(Path(store).resolve(), name)` -> the content-checked
  `family_dir` (a pre-0101 `summ_store` keeps serving both families; a store directory of the
  partner under the family's own key is `RenamedKey`).
- `fast.py`: `_file(version)` returns the file with `families` keys and `dropped_families`
  values passed through `registry.rekey_pre_0101` / `from_pre_0101` when `fast.KEY_ERA[version]
  == "pre-0101"` (all three existing versions). `KEY_ERA` is TOTAL over `fast.VERSIONS`: an
  import-time check raises when a version has no era (never a default), and the per-entry
  `bank_sha` check (sha256 of the bank file) catches a wrong era. The files are NOT edited
  (`tests/test_fast_subset.py` keeps pinning their sha256). A future subset file is written in
  current keys and registered with era `"0101"`. Effect: fast-v2's `basic_readout` entry is
  served as `basic_readout_st`, its `basic_readout_mt` entry as `basic_readout`, its
  `multihop_mt` entry as `multihop`; `fast.families()` is the same 22 families under their
  current keys; `bank_sha` (file bytes) is untouched; `fast_plan_sha` is untouched
  (`hash_name`). `PAIR_FAMILIES` / `MAJORITY_FAMILIES` hold none of the eight.
- `tiers.py`: no change (`CORE` holds none of the eight keys; `full()` drops `typo_st`, as it
  dropped `typo`).
- `readplan.py`: its family tables (`LITE_SITE_FAMILIES` etc., lines 116, 585-594, 746-761,
  802-829) are renamed by the script; `plan()` keeps `canonical(family)`; rows carry the
  current key in `family` (so `wsbench plan` output shows `multihop`, hashing as
  `multihop_mt_v2`). A PLAN FILE written before 0101 and fed to `produce plan=FILE` afterwards
  carries old keys: its rows hash (through `hash_name`) to a sha that matches neither family,
  so the judge refuses the result at guard (iii); `Producer` additionally refuses a plan-file
  row whose `family` is a 0101 bare key and whose `id` is in `family_ids(partner)`.

### 5.5 `adapt/` and adapted sets

In-repo sets are renamed in place (§6). Unmigrated sets exist outside git (sets stay local
until frozen), so reads must still work on them:

- `store._legacy_ok` / `bank_file` -> `registry.bank_path`-style lookup with the header check.
- `store.report_key(section, family)`: among `lookup_names(family)` present in the section, a
  reused key is taken only when the set's own bank file identifies the holder (the bank under
  that key has `live_header` / `other_header`), or, for the `drops` / `patches` sections,
  when the entry's item ids do (`registry.owner(key, ids=…)`). Retained from 2026-11-04,
  restated because this function is rewritten: the removed regex family's entries
  (`drops.multihop_mt_regex`, ids `multihop-au-*`) are never read as the live family's, and a
  set written under `multihop_mt_v2` is still read.
- `gate_path` / `cand_path` (`adapted/<m>/gate|cand/<family>.jsonl`, untracked work files):
  same rule, ids as evidence.
- `adapt/run.py:774` and `:852-856` (does the set have this family's bank): `registry.
  root_bank`.
- `adapt/floors.py:222-224`: `stems = {canonical(p.stem) for p in rd.glob("*.jsonl")}` would,
  in a set whose `readouts/` still has pre-0101 names, canonicalize both `multihop.jsonl`
  (single-token) and `multihop_mt.jsonl` to `multihop` and never produce `multihop_st`: the
  single-token floor would be silently dropped. It becomes: each file is attributed with
  `reads.owner_of(path, <candidate family>)` over the families whose `lookup_names` contain
  the stem; a file under a bare key that cannot be attributed is `RenamedKey`.
- `adapt/mcstage.py:233` and `adapt/mhmt2.py:1811` (`family_dir(model_dir / "mc", family)`):
  the content-checked `family_dir` (§3.3) finds no `results.json` or `cells.jsonl` there, so
  for these two callers `dir_owner` is given the ids of the `build-*/` / `refill-*/` work
  files' rows (a `kind="mc_work"` argument that reads `*.jsonl` one level down); an
  unattributable non-empty directory under a bare key is `RenamedKey`.
- WRITES are fenced by a marker: `report.json` gains `"family_keys": "0101"` (written by the
  migration and by every new build). `adapt` subcommands that write (`build`, `refill`,
  `freeze`, `drop`, `floors`, `gate_adapted`, …) exit 2 on a set without the marker:
  "`adapted/<m>` was written before plan 0101; run `scripts/migrate_0101.py set <dir>`". Reads
  (judging under `WSB_BANK_ROOT`) need no marker.
- Family tables keyed by name (`adapt/families.py` `FAMILIES` / `REGENERATE` /
  `SUBJECT_FIELDS` / `REQUIRED_ITEM_FIELDS`, `judge_inputs.py`, `lint.py`, `author.py`,
  `mcstage.py`, `refill.py`, `onecue.py`, `ml_native.py`, `native_langs.py`, `rebuild.py`,
  `dataround.py`, `mhmt2.py` `FAMILY`, `mhstage.py`, `gate.py`): renamed by the script (269 key
  hits in 24 files). Function names such as `_basic_readout_mt` are renamed with them.
- New adapted banks keep writing the header `"family"` value of the registered bank
  (`store.original_bank` copies the header), never the key (T6).
- `adapt/__main__.py:173-187`: uses `cli._family` semantics (§5.6) for its family arguments.

### 5.6 `cli.py`

- `_family(name, *, notice=True) -> str`:
  - a former key -> the current one, with today's line on stderr
    (`note: family 'multihop_mt' was renamed to 'multihop'`; same for `multihop_mt_v2`,
    `basic_readout_mt`, `multilingual_mt`, `typo_mt`);
  - one of the four bare keys -> itself, and ONE line on stderr per key per process:
    `note: 'multihop' is the multi-token family since 2026-11-20 (was multihop_mt); the
    single-token family is 'multihop_st'`. Printed while `registry.SWAP_NOTICE` is True (ruling 0.4.5: the constant, this branch and its test are deleted at the next version tag; the guards are permanent). Printed
    (a constant with a removal note: delete it and the test after the transition); silenced by
    `WSB_NO_RENAME_NOTICE=1`, and never printed by `JudgeFamily` when `outcome=` is set (the
    process-mode child, which the parent calls with a current key).
  - an `_st` key: silent.
- Every command already routes `family=` / `families=` through `_family` / `_families`
  (lines 340, 412, 1030, 1173, 1265, 1360, 1605) and `ati_opt_in` through `canonical` (255);
  no new call site.
- `JudgeFamily` (352) and `RunFamilies` (537): `registry.family_dir` (§3.3).
- `_n_items` (1713): `registry.frozen_bank_path(spec.name)`.
- `wsbench list` shows the new keys and titles; `typo_st`'s tier column is `—` (superseded).

### 5.7 Baselines (`baselines/*.py`)

- `text_inversion.py`: `NOT_GATED` (141-147), the gate-field tables (207-212), `ATI_EXCLUDE`
  (246, 279, 310) renamed by the script. `_by_family(d, family)` (365): `d[family]` unless the
  entry's own stamp says the partner (entries carry the instrument stamp:
  `registry.owner(key, stamp=…)`), else a former key; the `bank_sha` and instrument guards stay
  the backstop (a mis-keyed entry is `stale`, exit 2) and their message gains the rename hint
  for the eight families.
- `prompt_only.py` / `lucky_guessing.py` / `logit_lens.py`: frozen files are read by current
  key after the in-place rename (§6). The loaders run one check on load: an entry under a bare
  key whose `prompt_version` is the partner's (by `registry.owner`) is a `RenamedKey` (a stale
  local floors file). A floor is drawn only when its stamp equals the row's, so a mis-keyed
  floor never draws even without the check. `prompt_only.ARCHIVE` (the 2026-10-29 archive) is
  read through `rekey_pre_0101` and not edited. `logit_lens._plan_sha` (146): F7.
  `lucky_guessing.TOPICS_DIR / f"{family}.json"`: files renamed (§6); `TOPIC_FAMILIES` and the
  other tables renamed by the script.
- `capable/questions.py` (256-269, 317): table keys and their `_asked("<family>", …)` /
  `_with_bridges("<family>")` arguments renamed; `capable/run.py` keys: F5.

### 5.7a ATI and prompt-only WORK DIRS (`out/prompts.jsonl`, `answers/`, `readouts/`, `judged/`)

These readers take family keys as stored, and §5.7 did not cover them. What the code does
today, traced (critique blocker 2):

- `text_inversion._canon_rows` (911-916, used by `current_shas` 927, `answered` 998, `_prompts`
  1004) sets `r["family"] = canonical(r["family"])`. After 0101 a pre-0101 `prompts.jsonl` row
  `multihop_mt` would become `multihop` and sit beside single-token rows already stored as
  `multihop`.
- `latest_answers` (690) keys answers `(r["family"], r["id"])` raw; `draw_verdicts` (768) takes
  `fam = d["family"]` raw; `_judged_paths` (1351) and `_check_not_pilot` (1358) build
  `judged/<answerer>/draw<d>/<fam>/results.json`; the readouts stage (733) writes
  `readouts/<answerer>/draw<d>/<fam>.jsonl` opened with `"w"`.
- `prompt_only_opus.py` (296, 318, 455, 469) writes `root / f"{fam}.jsonl"` with `"w"`;
  answers are matched by `(family, id)` AND `prompt_sha` (176-190).

Does a downstream check stop a cross-family merge? Yes for verdicts, no for the damage:

- `_answerer_draws` (1375-1403) assigns a verdict only for `i in ids` (the family's own bank
  ids) when `usable(ans.get((fam, i)))` and `v.get(i) is not None`. With the pair's ids
  disjoint (F10), no single-token answer or verdict is ever assigned to a multi-token item:
  every draw stays `None`. `fresh` / `prompt_sha` are also keyed `(family, id)`.
  `ROWLESS_IS_FAIL` holds none of the eight families, so a rowless item is not counted as a
  fail. Result: NOT a silent cross-family verdict.
- But `complete` is still True (a `results.json` exists under the family's directory), every
  item is unverified, and the family then falls under "more than `MAX_REFUSED_SHARE`
  unverified -> not gated": a re-gate or `scripts/ati_rederive.py` over a pre-0101 `out` would
  silently DROP the ATI entries of the four gated families of the eight (the two
  basic_readout and the two multilingual families), and the `"w"` opens would overwrite the
  other member's `<bare>.jsonl`. The protection also rests on F10, which is not structural.

So the behaviour is specified, not left to the id filter:

- `_canon_rows` becomes `registry.attribute_rows(rows)`: a row's family is
  `canonical(key)` for a non-reused key and `registry.owner(key, ids=[row["id"]])` for a
  reused one (the row's own id decides: a pre-0101 `multihop` row with a single-token id
  reads as `multihop_st`, a `multihop_mt` row as `multihop`); an id that neither member's
  banks hold is `RenamedKey`. `latest_answers` and `prompt_only_opus.current_answers` /
  `latest_fallback` use it too, so pre-0101 answers keep serving the right family (no
  re-asking) and never the other.
- `draw_verdicts(results_path, expect=<family>)`: the result's family is
  `registry.stored_family(d["family"], d["config"].get("prompt_version"))` and must equal
  `expect`, else `RenamedKey`.
- `_judged_paths`, `_check_not_pilot` and the two readouts writers resolve the per-family path
  with `registry.family_dir` / `runner.readouts_path` semantics (content-checked), and a WRITE
  to `<dir>/<bare>.jsonl` or `<dir>/<bare>/` that exists and is owned by the partner is
  `RenamedKey` before the file is opened.
- `stage=gate`, `gate_adapted` and `scripts/ati_rederive.py`: a family whose every item ends
  unverified while a judged directory exists is a `SystemExit` naming the directory (today it
  degrades to "not gated"), for every family.
- Test T12 (§9.3): a pre-0101 `out` fixture in BOTH layouts (panel `answers/<answerer>/draw<d>`
  and the flat plan-0014 one) holding both members of a pair under pre-0101 keys.

### 5.8 Viewers (`atlas/`, `viewer_app/`)

`atlas/build.py:575,625` and `viewer_app/index.py:452` take the family from the DIRECTORY
name (`fam = jd.name`, minus `_opus`), so an old run tree's `multihop/` would render as the
multi-token "Multihop". Hand edit (§8.6): the family is `results.read_results(jd).family`
when `results.json` exists, else `registry.dir_owner(jd)`, else the directory name only when
it is not a reused key (a reused, unattributable directory is skipped with a logged line).
Test T13: a pre-0101 tree with `multihop/` (single-token stamp) and `multihop_mt/` builds the
two families under their current keys and titles. Public exports already published are not
re-keyed (ruling 0.4.3).

### 5.9 The lens producer's cell store (`scripts/lens_readouts_modal.py`) and resumable readouts files

Rows of the store are `{"row_sha", "row": {"id", "layer", "pos", …}}`, so a store file is
attributable by the item ids it holds (`registry.owner(<bare key>, ids=…)`).

- `store_files(store, subject, arm, family) -> list[Path]` (new, replaces `store_path` for
  READS: `stored_shas`, the export's cell collection): every
  `<store>/<subject>/<arm>/<key>.jsonl` for `key in registry.lookup_names(family)` that
  exists and, when `key` is a reused key, whose ids attribute to `family`; a file under a bare
  key that holds ids of BOTH members, or of neither while non-empty, is `RenamedKey`.
- `store_path(…)` (WRITES) is always `<current key>.jsonl`. Before the first append of a run
  it must be absent, empty, or attributed to `family`; if it is the partner's, the driver
  exits ("`<path>` is the single-token family's store, written before 2026-11-20; run
  `scripts/migrate_0101.py set <store>/<subject>` or move it to `multihop_st.jsonl`") and
  appends nothing.
- An existing pre-0101 store (`multihop.jsonl` single-token, `multihop_mt.jsonl`
  multi-token), unmigrated: `multihop_st` READS `multihop.jsonl` (its `row_sha`s still match,
  thanks to (a) of F14: no GPU re-read) and writes new cells to `multihop_st.jsonl`;
  `multihop` reads `multihop_mt.jsonl` and, having new cells to write, is REFUSED until the
  store is migrated (its write target `multihop.jsonl` is the partner's). It can never read
  or append to the other family's file. After `migrate_0101.py set` (which renames store
  files two-phase by content, §8.3) both resume with zero re-reads.
- A fresh store: plain `<current key>.jsonl` for both members; no legacy candidate exists.
- The export (`<out>/<family>.jsonl`, opened `"w"`, and its `stale.unlink`): the same
  refusal before unlinking or overwriting a file that attributes to the partner.
- `Producer.run_family`: F16 (§2.2).
- T18 (§9.3) covers the four cases.

## 6. Every in-repo artefact keyed by family

"in place" = renamed by the script, value-preserving, checked by `json.loads(new) ==
translate(json.loads(old))`; all of these files are `json.dumps(indent=1, ensure_ascii=False)`
plus a newline, so the script rewrites them by load -> translate -> dump and requires the
untouched remainder to be byte-identical (it aborts if a file does not round-trip before the
change). "at read" = bytes untouched, translated by `rekey_pre_0101`. "history" = untouched.

| artefact | count | decision |
|---|---|---|
| `evals/<family>/**` | 3,770 files | moved byte-identical to `evals/<category>/<new key>/` (R100 renames); bank headers keep their `"family"` value (F9), as in every earlier rename |
| `evals/<family>/README.md` | 32 | moved, then rewritten (keys, paths, title line); prompt blocks are checked verbatim by `test_prompts_in_readme` |
| `evals/<family>/*.md` audit notes (e.g. `multihop_mt/V1_AUDIT_2026-10-15.md`) | 6 | moved; history, not rewritten |
| resource files read by path (`basic_readout_mt/exonyms.json`, `multihop/derived_forms.json`, `multihop/split_subjects.json`, `*/lite_rule.json`, `*/r4*_distractors.json`, `knowledge_cutoff/obscure_items.json`, `introspection/vectors/`, `jlens_concept_pr/manifest.json`) | — | moved with their dir; every reader goes through `registry.resource_path` / `family_root` (§4) |
| `evals/baselines/prompt_only.json`, `prompt_only_summary.json`, `logit_lens.json`, `lucky_guessing.json`, `anti_text_inversion.json` (incl. `_not_gated`) | 5 | in place: top-level family keys and inner `"family"` values (7, 7, 7 + 7, 7 and 8 occurrences). No value, stamp, `bank_sha`, id list or `_source` field changes |
| `evals/baselines/lucky_guessing_moral_v5.json`, `_v7.json` | 2 | no key of the eight: untouched |
| `evals/baselines/topics/{basic_readout_mt,multihop_mt,multilingual,multilingual_mt}.json` | 4 | renamed to `{basic_readout,multihop,multilingual_st,multilingual}.json` (two-phase, §8.3); inner `"family"` value in place |
| `evals/baselines/confusers/` (same four names) | 4 | same |
| `evals/baselines/archive/prompt_only_summary.qwen-2026-10-29.json` | 1 | at read (an archive is a record); keys `basic_readout`, `multihop`, `multilingual`, `typo` there mean the `_st` families |
| `evals/baselines/README.md`, `evals/fast/README.md` | 2 | rewritten (207 + 9 key hits); a dated note says what the keys were before |
| `evals/fast/fast_v1.json`, `fast_v2.json`, `fast_safety_v1.json` | 3 | at read (`fast.KEY_ERA`), never edited: sha-pinned byte for byte. Each holds `basic_readout` and `basic_readout_mt` (they swap) and `multihop_mt` as `families` keys, and `typo_mt`, `multihop`, `multilingual`, `multilingual_mt` in `dropped_families` |
| `evals/hallucinationbench/index.json`, `methods.json` | 2 | hold no family key: untouched; `hbindex.py` unchanged |
| `adapted/<m>/<family>.json` | 125 | renamed (two-phase): 17 `basic_readout` -> `basic_readout_st`, 17 `basic_readout_mt` -> `basic_readout`, 17 `multihop` -> `multihop_st`, 6 `multihop_mt` + 10 `multihop_mt_v2` -> `multihop`, 17 `multilingual` -> `multilingual_st`, 17 `multilingual_mt` -> `multilingual`, 7 `typo` -> `typo_st`, 17 `typo_mt` -> `typo`. Bytes identical. This also retires the last in-repo `multihop_mt_v2.json` files |
| `adapted/<m>/basic_readout_mt/{exonyms,hidden_rivals}.json` | 32 in 16 dirs | dir renamed to `basic_readout/`; bytes identical |
| `adapted/<m>/report.json` | 17 | in place: keys of `families`, `drops`, `patches` (272 keys), plus the marker `"family_keys": "0101"`. Per section the script asserts no two keys land on one (`multihop_mt` and `multihop_mt_v2` never share a section: checked) and, for `drops` / `patches` under `multihop_mt`, that the ids are `mh2-*` (-> `multihop`); `multihop_mt_regex` entries are left. Every renamed `families` entry is also checked against the set's renamed bank FILE: the bank's header value is the family's (F9) and its item count equals the entry's recorded count (`n_items` / `n_final`, whichever the entry carries), so a key collision is not the only thing caught. The informational `"bank": "evals/<family>/items_vN.json"` strings (in 16 reports) are left as written and read through `repo_path` |
| `adapted/<m>/floors/floors.json`, `floors/prompt_only_summary.json` | 17 + 16 | in place (494 + 107 keys) |
| `adapted/<m>/floors/lucky_guessing.json` | — | holds none of the eight today; covered by the same rule if it gains one |
| `adapted/<m>/anti_text_inversion.json`, `.with_qwen27b.json` | 6 + 1 | in place (64 keys); `bank_sha` values untouched and still valid (`hash_name`) |
| `adapted/<m>/lenses/scores.json` | 5 | in place: 424 row `"family"` values, each checked against its row's `instrument` stamp with `registry.owner` |
| `adapted/<m>/{mh2_refill,kcutoff,msdm,moral,agentic,introspection,jlens_concept_pr}/` stage dirs | — | not named by a key of the eight: untouched |
| `adapted/README.md` | 1 | rewritten |
| `adapted/<m>/AUDIT*.md`, `NOTES.md`, `AUDIT_RESPONSE.md`, set READMEs | 28 | history: not rewritten; `adapted/README.md` gains the key table of §0.1 for readers of those records |
| `examples/readouts/<family>.jsonl[.meta.json]` | 9 of the eight | renamed (two-phase); bytes identical; the files of the other 24 families do not move (the directory is flat) |
| `tests/golden/*` | about 60 | names and bytes untouched. `plan_sha_pre_0090.json` and `capable_questions.json` are keyed by pre-0101 keys and read through `rekey_pre_0101` in their tests (values unchanged); `tests/golden/README.md` gains the key table |
| `tests/fixtures/*` | 12 | untouched. `adapted_v1/` (`multilingual.json`, `multilingual_mt.json`, …) is now by construction a pre-0101 set, and becomes the fixture of the header-identification tests (T4) |
| `src/wsbench/adapt/data/*.json` (sha-pinned pools; "typo" occurs there as an English word) | — | never touched |
| `scripts/*.py`, `scripts/*.sh` | 68 with a key or path | rewritten mechanically (289 key hits, 141 path hits, 48 import lines); they are one-off builders, so the rewrite keeps them importable and their paths valid, nothing more. `scripts/ati_restamp_rename.py`, `scripts/drop_frac_0083.py` and other dated migration scripts are rewritten the same way (paths only) |
| `.claude/skills/**` | 20 | rewritten (351 key hits, 40 path hits), except `adapt-bank/SKILL_AUDIT.md` and `SKILL_AUDIT_RESPONSE.md` (history). `wsb-new-questions/scripts/*.py` are live code: under the §4 rule |
| `docs/producing_readouts.md`, `summarizer.md`, `adapt_judge_inputs.md` | 3 | rewritten |
| `docs/summary_mode_validation.md`, `plan0079_results.md`, `plan0012_results.md`, `summary_mode_audits/*` | 5 | history: not rewritten; each gains one line at the top pointing at the key table |
| `atlas/` (`export_cb.py`, `build.py`, `normal_gate.py`, `normal_gated.py`, `run_normal_judge.sh`, `site/app.js`, `site/index.html`, `CB_EXPORT.md`) | 8 | python rewritten by the script; `site/*` and the shell script by hand (§8.6). Run trees are read through `registry.family_dir` + `read_results` |
| `viewer_app/index.py`, `README.md`; `src/wsbench/viewer/build.py` `GROUPS` | 3 | rewritten (keys); `GROUPS` keeps its family set |
| `README.md`, `CLAUDE.md`, `AGENTS.md`, `NOTICE.md` | 4 | rewritten, by hand where prose (§10) |
| `plans/*.md` | 75 | history: not rewritten. `plans/README.md` gains one line: "family keys and paths in plans before 0101 are the pre-0101 ones; see 0101 §0.1" |
| `src/wsbench/basic/family.py` | | `MC_FAMILIES = {"basic_readout_st", "multihop_st"}`, `MC_BANK_FAMILIES = {"multihop_st"}`; default bank via `family_rel` |
| `src/wsbench/basic/prompts.py` | | `FAMILY_PROMPT_VERSIONS`, `DIGEST_TASK_NOTES`, `FAMILY_RULES` keys -> `_st` (F4) |
| `src/wsbench/basic/mcjudge_basic.py`, `mcjudge_bank.py` | | `CANNOT_OF`, `OPTIONS_VERSIONS`, `CALL_VERSIONS` keys -> `_st`; the `family: str = "multihop"` defaults (364-526) -> `"multihop_st"`; F1 |
| `src/wsbench/multitoken/{family,prompts,options,mcrx,regex}.py` | | `MC_FAMILIES`, `CALL_VERSIONS`, `BRMT`, `MC_PROFILES` users, `RAW_REGEX_FAMILIES`, `DIGEST_TASK_NOTES`, `ML_BANK_TAGS`, `ALIAS_FAMILIES`, `PREMISE_FAMILIES`, `LANG_CONFUSABLES`: multi-token keys lose `_mt`, the single-token `multilingual` entries become `multilingual_st`. The VALUES (stamps, notes, tags) do not change |

## 7. File tree (what moves; `->` = rename, bytes identical unless marked `*` = rewritten)

```
evals/
  basic/                         (new)   association/ basic_readout/ basic_readout_st/
                                         directed_modulation/ multi_concept_directed_modulation/
                                         multihop/ multihop_st/ multilingual/ multilingual_st/
                                         multilingual_multihop/ multilingual_typo/ poetry/
                                         typo/ typo_st/
  computational/                 (new)   arithmetic_intermediates/ buggy_code/ chain_intermediates/
  association/                   (was the family; now the category)
                                         conjunctive_association/ user_modeling/
  safety/                        (new)   agentic_misalignment/ jailbreak_recognition/
  anti_bag_of_features/          (new)   relational_multihop/ role_bound_association/
  logical_processing/            (new)   moral_rationale/ nyt_connections/
  model_specific/                (new)   hinted_cutoff/ introspection/ knowledge_cutoff/
                                         model_multihop/ model_specific_directed_modulation/
                                         wrong_intermediate/
  precision/                     (new)   jlens_concept_pr/
  baselines/                     (stays) *.json keys in place*; topics/ confusers/ 8 renames
  fast/                          (stays) untouched
  hallucinationbench/            (stays) untouched
    evals/basic_readout_mt/ -> evals/basic/basic_readout/
    evals/basic_readout/    -> evals/basic/basic_readout_st/
    evals/multihop_mt/      -> evals/basic/multihop/
    evals/multihop/         -> evals/basic/multihop_st/
    evals/multilingual_mt/  -> evals/basic/multilingual/
    evals/multilingual/     -> evals/basic/multilingual_st/
    evals/typo_mt/          -> evals/basic/typo/
    evals/typo/             -> evals/basic/typo_st/
    evals/association/      -> evals/basic/association/     (before evals/association/ is re-created)
    evals/<other family>/   -> evals/<category>/<family>/
src/wsbench/evals/
  __init__.py                    *
  <category>/__init__.py         (8 new, docstring only)
  <category>/<family>/…          (same mapping as evals/; every file *)
src/wsbench/registry.py reads.py runner.py results.py cli.py fast.py readplan.py digest.py
            split.py readouts.py nocot.py                                      *
src/wsbench/basic/*.py multitoken/*.py baselines/*.py capable/*.py adapt/*.py
            viewer/build.py produce/producer.py                               *
adapted/<17 sets>/               125 bank renames, 16 overlay dir renames, 62 JSON keys in place*
examples/readouts/               9 renames
scripts/migrate_0101.py          (new)
tests/test_rename_0101.py test_family_paths.py                               (new)
tests/golden/manifest_0101_pre.json  script_path_literals_0101.txt            (new)
scripts/manifest_0101.py  scripts/migrate_0101_residue.txt                   (new)
tests/test_<family>*.py          about 20 renames; 212 files *
README.md CLAUDE.md AGENTS.md NOTICE.md adapted/README.md evals/*/README.md
docs/{producing_readouts,summarizer,adapt_judge_inputs}.md .claude/skills/**    *
```

## 8. Execution: `scripts/migrate_0101.py` (run once; kept in the repo as the record)

The script does every move and every mechanical rewrite from literal tables at its top; it is
committed BEFORE it is run (§15), and the migration commit is exactly its output.

| subcommand | does |
|---|---|
| `plan` (dry run, the default) | prints the planned `git mv`s, the JSON key changes, and the text rewrites as unified diffs GROUPED BY RULE into `migrate_0101_plan/<rule>.diff` (§8.4), plus the residue; changes nothing |
| `apply` | preconditions of §8.1; then the phases of §8.3; ends with `check` |
| `check` | the post-checks of §8.5; exit 1 on any failure |
| `set <dir>` | migrates one adapted set outside git (§8.3 "set scope"); `--dry-run` by default |
| `branch <base>..<head>` | the open-branch procedure of §8.7 |

### 8.1 The rewrite is NOT idempotent, so the script refuses to run twice

A second pass would invert the result: R4 turns the new multi-token `"multihop"` into
`"multihop_st"`; R1 / R2 read `wsbench.evals.association.user_modeling` and
`evals/association/conjunctive_association/…` as "the family `association`" and move them
under `basic/` (F8). Therefore:

- `apply` refuses (exit 2, nothing changed) unless ALL hold: the tree is clean; `HEAD` is the
  commit that added the script, or a descendant with no migration commit (the script checks
  that `src/wsbench/evals/basic/` does not exist, that `evals/basic/` does not exist, and
  that `tests/golden/manifest_0101_pre.json` exists and its embedded `base_sha` is an ancestor
  of `HEAD`); no tracked file outside the KEEP list contains a post-migration mark:
  (1) a `_st` key
  (`(?<![A-Za-z0-9_])(basic_readout|multihop|multilingual|typo)_st(?![A-Za-z0-9_])`);
  (2) a path `evals/<category>/<family>` or (3) an import `wsbench.evals.<category>.<family>`
  (also `wsbench/evals/<category>/<family>`), where in both `<family>` is a NEW key that
  `CATEGORY` places in that `<category>`. The pair, not the category alone: today's tree is
  full of `wsbench.evals.association.judge` / `.prompts` (the FAMILY `association`:
  `baselines/lucky_guessing.py:286`, `scripts/mc_leakage_r4.py:781`,
  `tests/test_association_*.py`, `tests/test_basic_association.py:116-117`,
  `tests/test_lucky_guessing.py:484`) and `evals/association/items_v5.json`, which a
  category-only mark would match, so `apply` would always refuse. `judge`, `prompts`,
  `items_v5.json` are not families of the category `association`; `conjunctive_association`
  and `user_modeling` are, and neither string exists before the migration.
- The text-rewrite function refuses any single FILE that contains one of those three
  post-migration marks (it raises; it never "skips and continues"), so a partly migrated file
  cannot be half-inverted.
- `apply` writes its run marker `.git/migrate_0101_applied` as its first act and refuses when
  it exists (inside `.git/`, like the pre-run sha record of §8.3, so neither is a stray file
  for `git status` or the reviewer's `git diff --quiet`; `check` leaves the marker and deletes
  the sha record); a failed run is recovered with `git reset --hard && git clean -fd`, never by
  re-running over the partial tree.
- There is no general `rewrite <paths>` subcommand (revision 1 had one; it was the unsafe
  entry point). Branches use `branch` (§8.7), which works only from a pre-migration base.

### 8.2 The KEEP list (never touched by the text rewrite; hand-edited afterwards, each change reviewed)

KEEP files (the script reads them only to hash them):

- tests of the legacy / rename machinery, where a blind key substitution turns an assertion
  into a vacuous pass (`canonical("multihop_mt_v2") == "multihop_mt"` would become
  `canonical("multihop") == "multihop"`; `test_legacy_family_names.py:64`
  `canonical("multihop") == "multihop" and legacy_names("multihop") == []` would become a
  statement about `multihop_st`): `tests/test_rename_multihop_mt.py`,
  `tests/test_legacy_family_names.py`, `tests/test_rename_wrong_intermediate.py`,
  `tests/test_adapted_exclusions_alias.py`;
- every test file that mentions `canonical`, `legacy_names`, `lookup_names`, `stored_family`,
  `family_dir`, `hash_name`, `REUSED_FAMILY_KEYS`, `LEGACY_FAMILY_NAMES`, `multihop_mt_v2`,
  `multihop_mt_regex` or `wrong_bridge` (the script COMPUTES this set by grep at the commit it
  runs on and prints it; the computed set governs, and the list here is only what it is on
  030dd09b, before commit 2 adds helper names such as `family_dir` to more tests: the four
  above plus `test_adapt_floors_missing_only.py`,
  `test_adapt_refreeze_registered_edits.py`, `test_basic_prompts.py`, `test_fast_subset.py`,
  `test_logit_lens_floor.py`, `test_lucky_guessing.py`, `test_msdm_plan0034.py`,
  `test_r5_adapted_mode.py`, `test_readplan.py`, `test_refill_fresh_pool.py`,
  `test_refill_mh2.py`, `test_refill_wi.py`, `test_run_wait.py`,
  `test_token_note_prompts.py`, `test_wi_r4.py`, `test_wi_r4_scrape.py`,
  `test_wrong_intermediate.py`). For these the script applies ONLY R1 (imports) and R2 (data
  paths), which cannot change what an assertion means, and leaves every key literal for a
  line-by-line hand edit;
- the script's own tests and the path-rule test, which hold `_st` keys and category paths on
  purpose: `tests/test_migrate_0101.py`, `tests/test_family_paths.py`, and
  `scripts/migrate_0101.py`, `scripts/manifest_0101.py` themselves;
- `src/wsbench/registry.py` (all of §3 is hand-written);
- everything in the "must NOT touch" list of §8.3.

KEEP patterns (never rewritten in ANY file; each occurrence goes to the residue, §8.4, and is
classified by hand):

- a `"family"` dict entry or comparison whose value is spelled like a key: `"family": "<key>"`,
  `'family': '<key>'`, `["family"] == "<key>"`, `.get("family") == "<key>"`, `family="<key>"`
  inside a `json.dumps` / bank-header literal. These are the bank-header vocabulary of F9 in
  most places (`tests/test_multihop.py:52`, `tests/test_multilingual.py:64`,
  `tests/test_typo.py:17`, `tests/test_mc_builders_bank.py:74,78`,
  `tests/test_multihop_mc_bank_skip.py:31,55`, `tests/test_adapt_onecue.py:274,279`, the bank
  builders under `scripts/`) and must stay byte-identical so a rebuilt bank is byte-identical;
  in a few places they are a KEY (`tests/test_mc_builders_bank.py:241` writes
  `"family": "basic_readout_mt"`; `scripts/build_basic_readout_v2.py:1064` and
  `scripts/build_brmt_v2.py:623` are `gate_sampling` rows, whose seed goes through
  `hash_name`). Only a human can tell which, so none is rewritten mechanically;
- a key literal used for its SPELLING (§2.3): an argument or receiver of `startswith`,
  `endswith`, `removeprefix`, `removesuffix`, `split`, `rsplit`, `partition`, `replace`, an
  operand of `in <str>` where the right side is a string (not a collection of keys), or any
  argument of an `re.*` call. `family.startswith("multilingual")` (`adapt/onecue.py:146`) is
  the live case: rewritten, it would be true for one family instead of four;
- hyphenated source vocabulary (`"multilingual-mt"`, `"basic-readout-hard"`, `"-mt"`,
  `"-hard"`): never a key;
- any string containing a stamp prefix of §3.2, a 64-hex sha, or a golden / fixture file name
  (`multihop_mc_options_v5.json`, `basic_readout_mt_options_v2.json`, …).

`check` (§8.5) asserts that every KEEP file's sha256 equals its pre-migration value except
for R1 / R2 hunks in the grep-selected test files, and that no KEEP-pattern occurrence
changed. The hand edits to KEEP files happen in a LATER commit (§15, commit 5), so the
mechanical commit shows them untouched.

### 8.3 Tables, rules and phases

- `KEYS` = `PRE_0101_KEYS`; `CATEGORY` = the family -> category map of §0.2; both are literals
  in the script, and a test asserts they equal the registry's.
- `DIRS`: `evals/<old>` -> `evals/<category>/<new>` and `src/wsbench/evals/<old>` ->
  `src/wsbench/evals/<category>/<new>` for all 32 families.
- Text rewriting is ONE pass per file with ONE compiled alternation and a callback, so a swap
  cannot chain within a run, with alternatives ordered longest first. A key matches only with
  `(?<![A-Za-z0-9_])<key>(?![A-Za-z0-9_])` AND inside one of these contexts:

  | rule | pattern (key = any of the 9 old keys unless stated) | becomes |
  |---|---|---|
  | R1 import | `wsbench.evals.<any family>` (dotted; also `from wsbench.evals import <family>`, `wsbench/evals/<family>` in paths) | `wsbench.evals.<category>.<new>` |
  | R2 data path | `evals/<any family>` not preceded by `wsbench/` or an identifier character, followed by `/`, a quote, whitespace or `)` | `evals/<category>/<new>` |
  | R3 path join | `"evals" / "<family>"` | NOT rewritten in live code (reported for the §4 hand edit); rewritten to `"evals" / "<category>" / "<new>"` in `scripts/` |
  | R4 quoted key | `"<key>"`, `'<key>'` (the whole string literal), outside KEEP files and KEEP patterns | new key |
  | R5 CLI | `family=<key>`, `families=…,<key>,…` | new key |
  | R6 file stem | `<key>.jsonl`, `<key>.json`, `<key>.jsonl.meta.json`, `/<key>/` in `adapted/`, `readouts`, `runs` path text | new key |
  | R7 markdown | `` `<key>` `` (whole code span), `**<key>**` | new key |
  | R8 env | `WSB_BANK_FILE_<KEY upper>` (4 spellings occur, in 7 files) | upper-case new key |
  | R9 identifiers | python identifiers that embed a key, from an explicit per-file list in the script (`_basic_readout_mt`, `test_typo_mt_…`) | per list |

  The word-boundary rule alone keeps `multilingual_multihop`, `multilingual_typo`,
  `relational_multihop`, `model_multihop`, `multihop_mt_regex`, `multihop_mc_options`,
  `basic_readout_mt_options_v2`, `typo_mt_v2_options` whole. The context rules exist because
  `typo`, `multilingual` and `multihop` are also English words and field values.

Phases of `apply`:

1. Preconditions (§8.1). Record the sha256 of every tracked file (`.git/migrate_0101_before`,
   not in the work tree) for `check`.
2. Moves, two-phase so that every swap and the `association` case is collision-free: phase A
   `git mv <src> .migrate_0101_staging/<n>` for every source (dirs: `evals/`,
   `src/wsbench/evals/`; files: adapted banks, overlay dirs, examples, topics, confusers, test
   modules); phase B create the category dirs and `git mv` each staged entry to its
   destination; write the 8 category `__init__.py`; remove the staging dir.
3. Text rewrite over: `src/**/*.py`, `tests/**/*.py`, `scripts/**/*.{py,sh}`,
   `atlas/**/*.{py,sh}`, `viewer_app/*.py`, `.claude/skills/**/*.{py,md}` (minus the two audit
   records), the three live docs, every moved family `README.md`, `evals/baselines/README.md`,
   `evals/fast/README.md`, `adapted/README.md`; minus the KEEP list.
4. JSON key rewrite (§6 "in place") with the per-file checks.
5. `ruff format` + `ruff check --fix --select I` on the rewritten python only (import order
   changes when a dotted path grows a segment); the formatter's hunks are part of the
   mechanical commit and are reproducible.

The script must NOT touch: `plans/`; `evals/fast/*.json`; `evals/baselines/archive/`; any
`items*.json`, `manifest.json`, `*.npy`, pool or resource file (bank bytes); `tests/golden/`
and `tests/fixtures/`; `src/wsbench/adapt/data/`; `adapted/*/AUDIT*.md`, `NOTES.md`,
`AUDIT_RESPONSE.md`, set READMEs; the five results docs; the two skill audit records;
`uv.lock`; `CITATION.cff`; `.github/`; `LICENSE`; `scripts/manifest_0101.py` and its output;
itself; any stamp, sha, number or id list anywhere.

`set <dir>` scope (an adapted set outside git), two-phase like the in-repo moves: the bank
files; the `basic_readout_mt/` overlay dir; `report.json` / `floors/*.json` /
`anti_text_inversion*.json` / `lenses/scores.json` keys; and the per-family WORK files and
directories that revision 1 left out: `gate/<family>.jsonl`, `cand/<family>.jsonl`,
`readouts/<family>.jsonl[.meta.json]` and every `readouts/<arm>/<family>.jsonl`,
`floors/readouts/**/<family>.jsonl[.meta.json]`, `floors/results/**/<family>/`,
`mc/<family>/`, `judged/**/<family>/`; then the marker. Given a lens cell store directory (`<store>/<subject>`), it renames `<arm>/<family>.jsonl` the same way (§5.9). Each file or directory under a bare
key is attributed by content first (`registry.owner`: header, stamp, ids) and the run aborts
before changing anything if any is unattributable. It refuses a set that has the marker.

### 8.4 Reviewable dry run, and who reviews the residue

- `plan` writes one diff file per rule (`R1.diff` … `R9.diff`, `json-keys.diff`,
  `moves.txt`), each hunk tagged with the rule that produced it, plus `tests-values.diff`: the
  subset of hunks that fall inside an `assert` statement, a `pytest.mark.parametrize`
  argument list or a module-level constant of a file under `tests/`. A reviewer reads each
  CLASS of rewrite on its own; R1 and R2 are checked by pattern, R4 / R9 hunk by hunk.
- Rule for test values: every hunk in `tests-values.diff` must be one of (a) a key, path,
  import or file-stem substitution from the tables, in a non-KEEP file, or (b) an entry of
  §9.2. The PR body carries the count of each. Any other changed number, stamp, sha, id list,
  count or expected string blocks the merge.
- `plan` also writes `keep-proposed.diff`: what R4-R9 WOULD have done in the grep-selected
  KEEP test files (which get R1 / R2 only). It is not applied. It is the reference for the
  hand edits of commit 5: that commit's hunks in those files must equal `keep-proposed.diff`
  minus the hunks listed one by one under §9.2 V2 / V3 / V8, and the reviewer diffs the two.
  Without it every key literal in `test_lucky_guessing.py`, `test_readplan.py`,
  `test_fast_subset.py` would be hand-edited with nothing to review against.
- RESIDUE = every word-boundary hit that no rule rewrote: prose words, unquoted keys in `.sh`
  loops (`for f in basic_readout multihop …`), markdown table cells (`| multihop |`), the
  `DIGEST_TASK_NOTES` block printed in `evals/typo/README.md` (lines of the form
  `multihop: the model reads …`, which `test_prompts_in_readme` compares verbatim and which
  F4 changes), every KEEP-pattern occurrence, bank-header vocabulary, golden file names,
  historical stamps and messages inside `REMOVED_FAMILIES`. `plan` prints it as
  `residue.txt` (`path:line:text`). The residue is classified ("leave" / "hand edit to
  <text>") by the FRESH-EYE diff reviewer of the PR, not by the implementer; the classified
  file is committed as `scripts/migrate_0101_residue.txt`, its line count is reported in the
  PR body, and `check` fails on any residue line that is not in it.

### 8.5 `check`

- every data file recorded before the run (`evals/`, `adapted/`, `examples/`, `tests/golden/`,
  `tests/fixtures/`, `src/wsbench/adapt/data/`), mapped through `DIRS` and the rename tables,
  has the same sha256 now, except the 75 JSON files of §6 "in place", which must satisfy
  `json.loads(new) == translate(json.loads(old))`; the manifest diff is printed and must be
  empty; a missing or extra data file fails;
- `git diff -M100% --diff-filter=R --stat` covers every moved data file (none shows as
  modified); `git status` has no stray file; the staging dir is gone;
- the KEEP assertions of §8.2;
- no directory other than the 8 categories and `baselines`, `fast`, `hallucinationbench`
  under `evals/`, and no package other than the 8 categories under `src/wsbench/evals/`
  (`__pycache__`-only directories ignored);
- the residue equals the committed, reviewer-classified file;
- reproducibility: running `apply` in a fresh worktree of the script's commit (commit 3 of
  §15) gives a tree with `git diff --quiet` against the migration commit (commit 4).

### 8.6 Hand edits (commit 5 of §15; not mechanical)

1. `registry.py` (§3, §4): all of it.
2. `reads.py`, `runner.py`, `results.py`, `cli.py`, `fast.py`, `digest.py`, `readouts.py`
   (§5); `baselines/text_inversion.py`, `baselines/prompt_only_opus.py` (§5.7a);
   `baselines/logit_lens.py` (F7); `adapt/store.py`, `adapt/run.py`, `adapt/floors.py`,
   `adapt/mcstage.py`, `adapt/mhmt2.py`, `adapt/__main__.py` (§5.5); `atlas/build.py`,
   `atlas/normal_gated.py`, `viewer_app/index.py` (§5.8, §2.3); `scripts/lens_readouts_modal.py`
   store rule and `produce/producer.py` resume guard (§5.9). (The `frozen_name` sites F1, F2, F5, F6, F11-F15 and the
   `repo_path` / `family_root` conversions are done BEFORE the rename, commit 2.)
3. The f-string imports of §4 (4 in `src`, `adapt/run.py`'s walk, `tests/conftest.py`, 14 test
   files).
4. The eight `__init__.py` of the renamed families: titles (§0.1), docstrings,
   `superseded_by="typo"`. In `multilingual_st`, `DIGEST_TASK_NOTES["multilingual_st"]` and
   `ML_BANK_TAGS["multilingual_st"]` must select the SAME strings as today's
   `["multilingual"]` entries.
5. The KEEP files (§8.2), line by line, and the residue lines classified "hand edit".
6. Prose: `README.md`, `CLAUDE.md`, `AGENTS.md`, `NOTICE.md`, family README titles,
   `evals/basic/typo_st/README.md`'s `DIGEST_TASK_NOTES` block, `atlas/site/*`,
   `atlas/run_normal_judge.sh`, `scripts/adapt_set.sh`.
7. `tests/golden/README.md`, `adapted/README.md`, `plans/README.md`: the key table.

### 8.7 Open branches (#510 plan 0097, #515 plan 0099, and any local branch)

Stated in the PR body and in `CLAUDE.md` §Workflow until the next tag:

1. BEFORE rebasing, grep the branch's ADDED lines for the four bare keys and the old `_mt`
   keys: `git diff <merge-base>..HEAD | grep -nE
   '^\+.*\b(basic_readout|multihop|multilingual|typo)(_mt|_mt_v2)?\b'`. Every hit is read by
   a person: a line that adds `"multihop"` meaning the single-token family rebases onto the
   merge with NO textual conflict and would silently mean the multi-token family.
2. Rebase the branch onto the commit just BEFORE the migration commit (tagged
   `pre-0101-migration`; commits 1-3 of §15 are already there, so the helpers exist).
3. Run `python scripts/migrate_0101.py branch pre-0101-migration..HEAD`: it applies the moves
   and the rules of §8.3 to exactly the files the branch touches or adds, with the same KEEP
   list and the same refusals (§8.1: it refuses any file already carrying a post-migration
   mark), and commits the result as one commit.
4. Rebase onto the merge; conflicts are now only real ones.
5. Local adapted sets: `python scripts/migrate_0101.py set <dir>`.
6. After pulling: `git clean -fdX src/wsbench/evals` (stale `__pycache__` directories).

## 9. Tests

### 9.1 Sanctioned mechanical edits

The script may rewrite tests for keys (R4-R9), paths (R2) and imports (R1), and rename test
modules by this table (the implementer confirms each by the module the file imports; a file
that tests both members of a pair or all four multilingual families keeps its name):

| today | after |
|---|---|
| `test_basic_readout_mt.py`, `test_basic_readout_mt_sarin_drop.py` | `test_basic_readout.py`, `test_basic_readout_sarin_drop.py` |
| `test_basic_readout.py`, `test_basic_readout_{bank_v7,quote_line,slices,sum_check}.py` | `test_basic_readout_st.py`, `test_basic_readout_st_{…}.py` |
| `test_multihop_mt.py`, `test_multihop_mt_kant_option.py` | `test_multihop.py`, `test_multihop_kant_option.py` |
| `test_multihop.py`, `test_multihop_{bank_v5,derived_forms,dropped_items,mc_bank_skip,quote_line,target_prefix}.py` | `test_multihop_st.py`, `test_multihop_st_{…}.py` |
| `test_multilingual_mt.py` / `test_multilingual.py` | `test_multilingual.py` / `test_multilingual_st.py` |
| `test_typo_mt.py` / `test_typo.py` | `test_typo.py` / `test_typo_st.py` |
| `test_rename_multihop_mt.py`, `test_legacy_family_names.py`, `test_mt_*.py`, `test_multilingual_{cited_case,language_leg,lexicons,multihop,typo}.py`, `test_final_r1_multilingual.py`, `test_r3_multilingual_anchor.py` | names kept |

Review rule for the main session: `git diff -- tests/` is read separately. A changed line in a
pre-existing test is acceptable only if it is (a) a key, path, import or module-name
substitution from the tables, or (b) listed in §9.2. Any other changed number, stamp, sha, id
list, count or expected string is a red flag and blocks the merge until explained. The
mechanical commit's `tests-values.diff` (§8.4) is the list of every rewritten assertion value;
the KEEP files (§8.2) are absent from it by construction and are reviewed in the hand-edit
commit, where each of their changed assertions must appear in §9.2 V2 / V3 / V8.

Must pass with NO value change, named because they pin the sites of §2.2:
`tests/test_r4b_mc_banks.py`, `tests/test_r4_bridge_ml.py` (F11), the option goldens
`multihop_mc_options{,_v5}.json` (F1), `tests/test_capable*.py` against
`tests/golden/capable_questions.json` (F5), `tests/test_adapt_onecue.py` (F13),
`tests/test_lens_readouts_store.py` (F14; its store fixtures keep their `row_sha` values), `tests/test_common_confusers_r5.py`,
`tests/test_mc_builders_bank.py`, `tests/test_refill_mh2.py`, `tests/test_adapt_rebuild.py`,
`tests/test_adapt_phase2_fixes.py` (F15).

### 9.2 Assertions whose VALUE changes (the complete list; anything else is a defect)

| id | test | change | why it is right |
|---|---|---|---|
| V1 | `tests/test_basic_prompts.py` `PINNED["bank-2026-10-30b"]` | the sha constant | F4: the printed record's keys are renamed; `PROMPT_VERSION` and every sent prompt are unchanged. Same kind of re-pin as plans 0050 and 0058; a comment is added in that style. The test additionally asserts the record with its keys mapped back through `hash_name` hashes to the OLD constant, which proves that only the keys moved |
| V2 | `tests/test_rename_multihop_mt.py` | `test_new_name_is_the_family`, `test_old_name_is_a_former_key`, `test_former_key_files_win_under_the_reused_key`, `test_adapted_set_under_the_old_name*`, `test_real_adapted_sets_plan_multihop_mt`, `test_adapted_reports_keep_the_removed_familys_drops_apart` are rewritten for the key `multihop`: `lookup_names("multihop") == ["multihop", "multihop_mt_v2", "multihop_mt"]`; `canonical("multihop_mt_v2") == canonical("multihop_mt") == "multihop"`; the note text names `multihop`; the real-sets test asserts NO in-repo set ships `multihop_mt_v2.json` any more and every set that has the family plans it. KEPT with their constants: `PRE_PLAN_SHA`, `PRE_BANK_SHA`, `PRE_PROMPTS_SHA`, `PRE_STAMP`, `PRE_CALL_VERSION`, `test_hashes_unchanged_by_the_rename`, `test_instrument_and_prompt_bytes_unchanged_by_the_rename`, `test_seeds_unchanged_by_the_rename`, and `test_stored_results_are_told_apart_by_stamp` with the same five stamps and outcomes (`multihop_mt_regex` twice, the live family three times) | the plan rewrites the decision these tests encode; the retained invariants are restated in §3.1 / §3.2 |
| V3 | `tests/test_legacy_family_names.py` | `test_map_and_canonical` gains the five new entries; nothing else | §3.1 |
| V4 | tests asserting `spec.bank == Path("evals/<f>/…")`, `EvalSpec.group` directory, README link text | path values per `DIRS` | 0.2 |
| V5 | `wsbench list` / README / viewer title assertions | titles per §0.1 | decision A |
| V6 | tests asserting the exact `note: family … was renamed to …` line or `fast.families()` / `tiers` / `test_tiers.py` family-to-category literals | key names only | 0.1 |

| V7 | tests that pin a toy bank through a BARE-key variable (`WSB_BANK_FILE_BASIC_READOUT`, `WSB_BANK_FILE_MULTIHOP`: 2 of the 7 files that set such a variable) or build a toy root with `<bare>.json` for an `_st` family | the toy bank gains the header `"family"` value of F9, or the variable is renamed to the `_ST` form | §3.3: a bare-key pin needs a positive header match. No assertion changes |
| V8 | the other KEEP test files of §8.2 | hand edits, each either a key / path substitution or an assertion about `canonical` / `legacy_names` / `lookup_names` / `family_dir` restated for the new tables; listed one by one in the PR body | §3.1-§3.3 |

No count, pass rate, floor, `plan_sha`, `bank_sha`, stamp, call key, option list or id list
changes.

### 9.3 New tests

`tests/test_rename_0101.py` (parametrized over the four pairs unless noted):

- T1 hash neutrality: `scripts/manifest_0101.py --check` in-process: the manifest of §11.1
  computed now, with its family keys mapped back through `frozen_name`, is byte-identical to
  the committed `tests/golden/manifest_0101_pre.json` (the only declared difference: the F4
  record, which the manifest stores with its keys mapped back). Plus
  `plan_sha_pre_0090.json` holds with keys through `rekey_pre_0101` and values unchanged.
- T2 stamps: `stored_family(<bare key>, <st stamp>) == <_st>` and `… <mt stamp>) == <bare key>`
  for every historical stamp listed in §3.2 with and without `+digest-…`, `+reads-lite`,
  `+fast-…` suffixes; empty stamp -> the live family; an unknown stamp -> `RenamedKey`; old
  keys (`basic_readout_mt` etc.) -> the live family; each registered holder's current
  `prompt_version` classifies as itself; `read_results` + `macro` over a pre-0101 results tree
  (old `typo` with `bank-2026-10-30b` -> `typo_st`, excluded `superseded`; old `typo_mt` ->
  `typo`, in the macro).
- T3 readouts: a pre-0101 root (`<bare>.jsonl` with single-token ids, `<bare>_mt.jsonl` with
  multi-token ids) and a post-0101 root each serve BOTH families through
  `runner.readouts_path`; `reads.load(family=<bare>)` on a single-token file fails with the
  rename message (a) by sidecar `plan_sha`, (b) sidecar-less by ids; with `allow_missing=True`
  too; a mixed-id file fails; `judge family=<bare> readouts=<st file>` exits 2 with no call.
- T4 banks under a root: `tests/fixtures/adapted_v1` (pre-0101 names) resolves
  `bank_path("multilingual")` to `multilingual_mt.json` and `bank_path("multilingual_st")` to
  `multilingual.json` by header; a root holding only the single-token bank under the bare key
  gives "has no bank for 'multihop'" naming the rename; `WSB_BANK_FILE_MULTIHOP=<st bank>`
  exits naming the rename; every in-repo set resolves all of its eight-family banks, and each
  resolved file's header value is its family's (F9 table).
- T5 id disjointness within each pair over every registered bank version and every in-repo
  adapted bank.
- T6 adapt: a write subcommand on a marker-less set exits 2; `store.report_key` on a pre-0101
  report (the mixed `multihop_mt_v2` / `drops.multihop_mt` shape of glm-5.3 before migration,
  as a fixture dict) attributes every entry correctly; a new adapted bank's header value is the
  registered one.
- T7 out dirs and digest stores: `family_dir` on a pre-0101 out root returns `out/multihop` for
  `multihop_st` and `out/multihop_mt` for `multihop` (by `results.json`, and by `cells.jsonl`
  ids when there is no `results.json`); `out/multihop` holding single-token results and no
  other candidate -> `RenamedKey` for `multihop`; the same for a `summ_store`.
- T8 CLI: `families=multihop_mt` and `multihop_mt_v2` resolve to `multihop` with the rename
  note; a bare key prints the one-line notice once, not under `WSB_NO_RENAME_NOTICE=1`, not
  for `judge outcome=…`; `_st` keys are silent; `wsbench list` shows the 32 keys of §0.1 /
  §0.2 with the new titles.
- T9 `HASH_FAMILY_NAMES` and `FROZEN_KEY_NAMES` are referenced only in `registry.py` (source
  scan); `hash_name` of each of the nine entries and `frozen_name` of each of the eight equal
  §3.1; `frozen_name("multihop") != hash_name("multihop")` (the one difference, pinned).
- T10 fast: `fast.subset(v)` for the three versions has the translated keys, the file sha pins
  still hold, and each translated entry's `bank_sha` equals `fast.bank_sha(<new key>)`.
- T11 floors: every entry of the five `evals/baselines/*.json` files and of every adapted
  `floors/*.json` under a bare or `_st` key carries a stamp that `registry.owner` attributes
  to that key; the archive read through `rekey_pre_0101` has `_st` keys.

- T12 ATI / prompt-only work dirs (§5.7a): a pre-0101 `out` fixture in both layouts (panel and
  flat plan-0014) with `prompts.jsonl`, answers, readouts and judged results of BOTH members
  of a pair under pre-0101 keys: `attribute_rows` gives each row its own family;
  `_answerer_draws` for each member reads exactly its own verdicts; `draw_verdicts(expect=)`
  on the partner's `results.json` is `RenamedKey`; the readouts writer refuses to overwrite
  the partner's `<bare>.jsonl`; a gate in which every item of a family ends unverified beside
  an existing judged directory exits (does not write `_not_gated`); `prompt_only_opus` reuses
  pre-0101 answers for the right member and asks nothing.
- T13 viewers (§5.8): a pre-0101 run tree with `multihop/` (single-token stamp) and
  `multihop_mt/` yields the families `multihop_st` and `multihop` in `atlas.build` and
  `viewer_app.index`.
- T14 pins and existence (§3.3): `bank_pins("multihop_st")` contains
  `WSB_BANK_FILE_MULTIHOP`; `WSB_BANK_FILE_MULTIHOP=<single-token bank>` makes
  `bank_path("multihop_st")` exit naming `…_MULTIHOP_ST` and `bank_path("multihop")` exit; a
  header-less file under a bare-key variable exits for both; `fast.entry` fails closed on it;
  `readplan.families()` under a root holding only the single-token `multihop.json` lists
  `multihop_st` and not `multihop`; `family_ids("typo_st")` under a root with no single-token
  typo bank returns the registered ids without exiting; `adapt.floors` on a `readouts/` dir
  with pre-0101 names finds both members.
- T15 the migration script (unit tests on a synthetic mini-tree, no real data): `apply`
  refuses a tree with `src/wsbench/evals/basic/`; the rewrite function raises on a file that
  holds a post-migration mark as defined in §8.1 (a `_st` key; `evals/<category>/<family>` or
  `wsbench.evals.<category>.<family>` with the family one of that category's new keys) and
  does NOT raise on the pristine spellings `wsbench.evals.association.judge`,
  `from wsbench.evals.association import prompts`, `evals/association/items_v5.json`; `apply`
  passes its preconditions on a synthetic tree holding those; running the rules twice is impossible through the public entry points; a KEEP file
  and every KEEP pattern (`"family": "multihop"`, `header["family"] == "typo"`,
  `family.startswith("multilingual")`, `"multilingual-mt"`) come out byte-identical; the run
  marker and sha record live under `.git/` and `git status` is clean after `check`; `association` moves under `basic/` exactly once.
- T16 `frozen_name` sites (§2.2), direct unit pins beside the manifest:
  `r4_language_distractors("multilingual_st", "French")` equals the pre-0101
  `("multilingual", "French")` list, and likewise `("multilingual", <gold>)` vs the pre-0101
  `multilingual_mt`; `split.is_dev` of 20 ids per family; `mcjudge_bank.options_of` of 5
  items.

- T17 spelling logic (§2.3): the `ast` scan and its allowlist;
  `onecue._gold_forms("multilingual", item, role, block)` includes the item's `target` (as
  `("multilingual_mt", …)` did before), and likewise for `multilingual_typo` /
  `multilingual_multihop`.
- T18 the lens store and resumable files (§5.9, F14, F16), on synthetic stores: `row_sha` of a
  plan row of each renamed family equals the value recorded in the manifest; with a pre-0101
  store, `multihop_st` resumes from `multihop.jsonl` with zero pending rows and `multihop` is
  refused before any append; with a fresh store both write `<current key>.jsonl`; a store file
  holding both members' ids is `RenamedKey`; the export refuses to overwrite the partner's
  file; `Producer.run_family(family="multihop", out=<single-token file>)` raises before
  opening it.

`tests/test_family_paths.py` (TP): the three scans of §4, plus `registry._layout()` equals the
§0.2 table as a literal, plus `family_module` / `family_root` / `repo_path` unit cases
(`repo_path("evals/introspection/vectors/concept_vectors_L12.npy")` exists;
`repo_path("evals/baselines/prompt_only.json")` is unchanged; the F8 cases:
`repo_path("evals/association/conjunctive_association/items_v4.json")` is returned AS WRITTEN
(a new-layout path), `repo_path("evals/association/items_v5.json")` resolves to
`evals/basic/association/items_v5.json` (a pre-0101 path of the family), and
`repo_path("evals/basic/association/items_v5.json")` is as written).

## 10. Docs and conventions

- `README.md`: each family entry's link becomes `](evals/<category>/<family>/README.md)`
  (`tests/test_readme.py:51` builds it from `registry.family_rel`); the eight entries get
  their new titles and keys; the "Renamed families" paragraph gains the table of §0.1 with
  the date; Quickstart and Judges rows use the new keys. It also states ruling 0.4.3 in one
  paragraph: artefacts already published under the old keys (the adapted sets on HF, viewer /
  atlas exports, HallucinationBench's WSB method names) are not renamed; read them with the
  table; `wsbench` reads both.
- Family README per directory: unchanged convention, one level deeper. `test_prompts_in_readme`
  reads `registry.family_root(family) / "README.md"` and `registry.family_module(family,
  "prompts")`. No category-level README is added (ruling 0.4.4).
- `tests/test_adapt_skill_docs.py`: unchanged logic (it checks subcommands, scripts and the
  registered-bank table against the registry); the skill's bank table is rewritten by the
  script, and scan 3 of §4 covers the skill's paths.
- `CLAUDE.md`: "Renamed families" gains a 0101 paragraph (the tables of §3.1 / §3.2, the
  content rule, the retained `multihop_mt_v2` / `multihop_mt_regex` behaviour, F7's rule);
  "Family conventions" paths and keys; "Fast subset" (keys translated at load, files frozen);
  "Tiers and categories" (a category is a directory); "Invariants" (the §4 rule and its test);
  "Adding a family": `src/wsbench/evals/<category>/<family>/…`, `evals/<category>/<family>/…`,
  `bank=registry.family_rel(...)`, and "the directory is the category; `register` checks it".
- `AGENTS.md`, `NOTICE.md` (7 `evals/<family>` paths, one import path), `docs/producing_
  readouts.md` (keys; the note that `extra.steering.vector_file` is a pre-0101 layout string
  resolved by `registry.repo_path`, F3).

## 11. Verification gates (all required before merge; run the long ones in tmux, e.g. `tmux new -s wsb0101`, output to `logs/migrate_0101_<timestamp>.log`)

### 11.1 The pre/post manifest (`scripts/manifest_0101.py`, committed FIRST)

Provenance is the point: a snapshot retaken after hand edits proves nothing. So the script and
its output are the PR's first commit, generated on pristine origin/main; the output embeds
`"base_sha": "030dd09b…"` (the commit it was computed on) and the script's own sha256; the
reviewer regenerates it in a clean worktree of that commit
(`git worktree add /root/tmp/wsb-0101-pristine 030dd09b && cd /root/tmp/wsb-0101-pristine &&
git show <commit 1>:scripts/manifest_0101.py > /root/tmp/manifest_0101.py &&
WSB_NO_NYT=1 WSB_NO_NOCOT=1 PYTHONPATH=src python /root/tmp/manifest_0101.py --out
/root/tmp/manifest_pristine.json`) and requires `cmp` with the committed
`tests/golden/manifest_0101_pre.json`. The SAME file runs before and after, so it must import
cleanly on pristine main and on the migrated tree:

- its family list is `registry.FAMILIES` after `load_all()`; a family's data directory is
  `registry.frozen_bank_path(f).parent` (exists at every commit; `family_root` does not exist
  at commit 1);
- `fz = getattr(registry, "frozen_name", lambda k: k)`: every family key it WRITES goes
  through `fz` (identity on main and at commit 2, the pre-0101 key after the rename), so the
  output is byte-identical by construction only if nothing moved;
- it names its private imports, each guarded and each recorded in the output under
  `"imports"` with the module file's path-independent role, so a missing one is an error, not
  a silent omission: `wsbench.adapt.onecue` (`_order`, `_gold_forms`, `rows`),
  `wsbench.adapt.author` (the prompt builder at 1506, the F6 rng), `wsbench.adapt.generate`,
  `wsbench.capable.run`, `wsbench.split.is_dev`, `wsbench.digest` (the fingerprint at 1825),
  `wsbench.baselines.lucky_guessing._rng`, `wsbench.baselines.text_inversion.qwen_seed`, and
  from `scripts/` (loaded by file path with `importlib.util`): `lens_readouts_modal`
  (`row_sha`, `_plan_rows`, `_job`; the module imports `modal` at top level, so the manifest
  installs a stub `modal` module in `sys.modules` when the package is absent),
  `r4b_mc_refine.draw`, `common_confusers_r5` (its gate-row builder);
- coverage is explicit: for every family the output lists `n_calls` recorded per mode
  (`native`, `summary`), and `--check` fails when a family outside the named exception list
  has zero. Exceptions, each with its reason in the file: `nyt_connections` (no plan rows
  under `WSB_NO_NYT=1`; the `tests/conftest.py` stub of `nyt.puzzles` is used instead, so it
  does record calls and is NOT an exception unless the stub is unavailable outside pytest, in
  which case it is listed), `jlens_concept_pr` (`summary`: native-only by
  `digest.NATIVE_ONLY`), `model_specific_directed_modulation` (regex judge, no call in either
  mode), the regex-scored families in `native` mode (`multilingual`, `typo`,
  `multilingual_typo` after the rename: scorer `regex`, zero calls by design; their summary
  mode records digest calls).

Per family (all 32; the extra rows only where they apply), offline, no API call:

| entry | how |
|---|---|
| `plan_sha`; fast `plan_sha` per subset version that holds the family | `reads.plan_sha`, `reads.fast_plan_sha(declared=)` |
| ATI `bank_fingerprint` | `text_inversion.bank_fingerprint` |
| bank file sha256 and n items; sha256 of every other file in the family directory | file bytes |
| result stamp, call versions, option-seed versions | `spec.judge.prompt_version`, `CALL_VERSIONS`, `OPTIONS_VERSIONS`, `mcjudge_bank.CALL_VERSIONS` |
| sha256 over every upper-case constant of the family's `prompts` module (the F4 record stored with its keys mapped back through `frozen_name`) | as `test_rename_multihop_mt.PRE_PROMPTS_SHA` |
| recorded call fingerprints: an offline run of the family over `examples/readouts/<family>.jsonl` (5 fixed items: the first 5 ids of the bank, sorted, that the example file holds) in native AND summary mode, with `mcjudge.run_calls` and the digest's call primitive patched to record, for every call, `(key, fingerprint, sha256(system), sha256(user), prompt_version)` and to return a canned answer | proves no rendered judge prompt, no call key and no fingerprint moves |
| digest fingerprint (`digest.py:1825`) and the task note each of those items' digest is told | from the same patched run |
| the shown option lists of 5 fixed items (MC families) | `mcjudge_bank.options_of` (F1), `mcjudge_basic.options_for`, `multitoken.options` |
| `split.is_dev` of every item id (F2) | |
| `capable` reply / grade cache keys of 3 probe items (F5) | |
| adapt seeds: the first 5 values of the F6 `random.Random` objects for 2 (tier, seed) pairs | |
| language-distractor lists of 3 probe golds per family in `R4_LANG_POOLS`, and `r4b_balanced_language_distractors` over the registered bank's golds (F11) | |
| sha256 of the authoring prompt per tier (F12) | `adapt.author` prompt builder |
| `onecue._order` of 3 probe rows and their cache keys (F13) | |
| `lens_readouts_modal.row_sha` of 3 REAL plan rows per family (the first 3 of `_plan_rows(family, "qwen3.5-4b")`, the band of a subject the script knows), and the `_job` seed derived from those rows for a fixed arm name (F14). A fake pack would hide the family inside `row_sha` | |
| `onecue._gold_forms` (the banned forms) of one probe item per family in `onecue.FAMILIES` (§2.3: catches a rewritten `startswith("multilingual")`) | |
| the id prefix `family.split('_')[0]` per family (§2.3) | |
| `r4b_mc_refine` cache key and `draw` result on a fixed toy list; `common_confusers_r5` gate-row keys of 3 items (F15) | |
| lucky-guessing seeds and call keys of 3 probe items; `gate_sampling.seed`; `qwen_seed` | the `hash_name` sites |
| `wsbench list` row (n items, judge, calls per arm) minus key, title | |

### 11.2 Gates

1. Manifest: regenerated by the reviewer on pristine main, byte-identical to commit 1 (§11.1);
   `manifest_0101.py --check` passes at commits 2, 5 and 6 (§15).
2. `scripts/migrate_0101.py check` passes (§8.5); the data-file manifest diff is empty; the
   reviewer re-runs `apply` on commit 3 in a fresh worktree and gets commit 4 exactly.
3. `uv run pytest -q` green; `uv run ruff check .`; `uv run ruff format --check .`.
4. `git diff --stat <base>..HEAD -- tests/golden tests/fixtures` shows only the new files
   (`manifest_0101_pre.json`, `script_path_literals_0101.txt`).
5. `scripts/ati_rederive.py --check` passes on `evals/baselines/anti_text_inversion.json` and
   on the adapted ATI files it covers.
6. `uv run wsbench list` shows the new keys, titles, categories and tiers.
7. Before/after `report` on a whole pre-0101 results root. On pristine main:
   ```
   cp -r /root/tmp/x3q11/judged/qglm-rl600-x4/all /root/tmp/wsb-0101-gate/all_pre
   cp -r /root/tmp/wsb-fast-v2/runs/s3d-rl600      /root/tmp/wsb-0101-gate/fast_pre
   uv run wsbench report dir=/root/tmp/wsb-0101-gate/all_pre  json=True > all_pre.json
   uv run wsbench report dir=/root/tmp/wsb-0101-gate/fast_pre json=True --fast > fast_pre.json
   ```
   (copy first: `report` rewrites `summary.md`). After the rename, the same two commands on
   fresh copies. Pass = every row's value, CI, n, completeness, floors and exclusion reason,
   the macro value, the core macro and the "Not in macro" list are identical after mapping
   keys and titles through §0.1 (a small comparison script prints the diff; it must be
   empty). In particular the old `typo` row reads as `typo_st` (excluded `superseded`) and
   the old `typo_mt` row as `typo` (in the macro).
8. Cached-run replay, zero new calls, identical values. The dirs (all exist on this box):

   | pre-0101 key | readouts | cached out dir | flags |
   |---|---|---|---|
   | basic_readout | `/root/tmp/wsb-fast-v2/readouts/s3d-rl600/basic_readout.jsonl` | `/root/tmp/wsb-fast-v2/runs/s3d-rl600/basic_readout/` | `--fast` |
   | basic_readout_mt | `…/readouts/s3d-rl600/basic_readout_mt.jsonl` | `…/runs/s3d-rl600/basic_readout_mt/` | `--fast` |
   | multihop_mt | `…/readouts/s3d-rl600/multihop_mt.jsonl` | `…/runs/s3d-rl600/multihop_mt/` | `--fast` |
   | multihop, multilingual, typo_mt | the `readouts_root` in `/root/tmp/x3q11/judged/qglm-rl600-x4/all/run.json` | `/root/tmp/x3q11/judged/qglm-rl600-x4/all/{multihop,multilingual,typo_mt}/` | as in that `run.json` |
   | multilingual_mt | as recorded in its `run.json` | `/root/tmp/wsb-0079/judged/qwen3.5-2b/qwen3.5-2b.sft/multilingual_mt/` | `WSB_BANK_ROOT` of that run (a pre-0101 adapted set outside git: also exercises `root_bank`) |
   | typo | none cached on this box | on pristine main: `uv run wsbench judge family=typo readouts=examples/readouts/typo.jsonl out=/root/tmp/wsb-0101-gate/typo_pre limit=3` (live, 3 items), then replay it | |

   Procedure, per row: on pristine main record `results.json` (value, CI, counts, per-row
   passes) and `wc -l cells.jsonl`; copy the out dir; after the rename run, on the copy,
   `uv run wsbench judge family=<NEW key> readouts=<same file> out=<copy> <same flags>`, e.g.
   ```
   uv run wsbench judge family=basic_readout_st \
     readouts=/root/tmp/wsb-fast-v2/readouts/s3d-rl600/basic_readout.jsonl \
     out=/root/tmp/wsb-0101-gate/replay/basic_readout --fast
   ```
   and once as a whole root, to exercise the lookups of §5.3 and `family_dir`:
   ```
   cp -r /root/tmp/wsb-fast-v2/runs/s3d-rl600 /root/tmp/wsb-0101-gate/replay_root
   uv run wsbench run --fast readouts_root=/root/tmp/wsb-fast-v2/readouts/s3d-rl600 \
     out=/root/tmp/wsb-0101-gate/replay_root
   ```
   Pass = exit 0; every copied `cells.jsonl` gained ZERO rows (`wc -l` equal; the cache is
   append-only); spend is the preflight ping only; every recorded number identical; the only
   differences in `results.json` are `family` and timestamps. Then the refusals: each
   single-token file judged under its bare key exits 2 with the §5.2 message and adds no row.
9. One `anti_text_inversion=True` replay (the fast-v2 root's `basic_readout_mt` out dir with
   `anti_text_inversion=True` on main vs `family=basic_readout` after: same subset ids, same
   value, zero new rows), and one `summ_store` reuse replay (a pre-0101 `summ_store=` directory
   from the x3q11 run, if its `run.json` records one; else build one on pristine main from the
   fast-v2 `basic_readout_mt` readouts at `layers=[<one layer>]`, then after the rename judge
   `family=basic_readout` with the same `summ_store=` and require `adopted` > 0 and zero new
   digest rows in the store).
10. Independent fresh-eye review of the diff commit by commit (§15), including the residue
    classification (§8.4) and `git diff -- tests/` against §9; then
    `scripts/gated_merge.sh <pr>` (fail closed).

## 12. PR #510 (plan 0097, banks as password zips)

This PR lands first. Afterwards #510 changes one thing: its unit definition. A unit under
`evals/` is a family directory `evals/<category>/<family>/` (enumerate with
`registry._layout()` / `family_root`, not by listing `evals/*`), while `evals/baselines`,
`evals/fast` and `evals/hallucinationbench` remain units at the second level;
`adapted/<model>` units are unchanged. Its sidecar names and pack / unpack paths follow from
that. Nothing else in #510 changes.

## 13. Risks and their fail-closed behaviour

| risk | behaviour |
|---|---|
| a pre-0101 readouts file of the single-token family is judged under the bare key | refused in `reads.load` by sidecar `plan_sha`, else by item ids (§5.2); `run` does not even select it (§5.3) |
| a pre-0101 `results.json` under a bare key | attributed by stamp; an unknown non-empty stamp is `RenamedKey`, exit 2 (§3.3) |
| a pre-0101 out dir or digest store reused | `family_dir` picks by `results.json` / cache ids; the partner's directory under the family's own key is `RenamedKey`; never appended to |
| a pre-0101 adapted set (local, unpushed) | reads: bank picked by header (F9), report entries by bank / ids; writes: refused without the marker until `migrate_0101.py set` |
| a stale floors or ATI file keyed the old way | a floor draws only on stamp equality; ATI entries fail their `bank_sha` / instrument guard (exit 2); loaders also refuse a partner-stamped entry |
| `WSB_BANK_FILE_<BARE>` set by an old shell | header check -> exit naming the rename |
| an old plan file fed to `produce` | rows refused by id; any output fails guard (iii) |
| a stale import or path in an unmigrated branch, script or notebook | `ModuleNotFoundError` / missing file (§0.3); pre-0101 path messages name the move |
| the stamp tables miss a historical stamp | `RenamedKey` (refused, never guessed); T2 pins the known ones; the implementer's `git log -S` check (§3.2) |
| a hash name used as a lookup key (F7) | T9 forbids it |
| a name-embedding site moves (§2.2: option orders, dev split, language distractors, capable / onecue / builder keys, adapt seeds, the authoring prompt, the producer seed) | `frozen_name` at each; every site has an output in the manifest (§11.1), compared byte for byte; T16 |
| the multi-token multihop family's raw-key sites move from `multihop_mt` to `multihop_mt_v2` | `frozen_name`, not `hash_name`, at the sites this plan converts (§2.1); T9 pins the difference |
| the migration is run twice, or over a partly migrated file or branch | the script refuses (§8.1); no public `rewrite` entry point; T15 |
| a legacy-path test is rewritten into a vacuous pass, or a bank-header literal is rewritten | KEEP files and KEEP patterns, asserted byte-identical by `check` (§8.2) |
| an open branch adds a bare key with its old meaning and rebases without conflict | the added-lines grep, mandatory in the PR body (§8.7) |
| a re-gate over a pre-0101 ATI work dir silently un-gates a family or overwrites the partner's readouts | rows attributed by id, `draw_verdicts(expect=)`, write refusal, all-unverified is an exit (§5.7a); T12 |
| a viewer shows an old `multihop/` directory as the multi-token family | the family comes from `read_results` / `dir_owner` (§5.8); T13 |
| a pre-0101 `WSB_BANK_FILE_<BARE>` pin is ignored by the `_st` family or accepted header-less | `bank_pins` + positive header match (§3.3); T14 |
| a new-layout path under the `association` category is "translated" by `repo_path` | rule order of §4; TP unit cases |
| the lens producer's cell store misses for every stored cell, or new cells append to the partner's store file | `row_sha` over `frozen_name(family)`; reads by content, writes only to the current key and refused on the partner's file (§5.9); T18; real plan rows in the manifest |
| `produce` appends to a pre-0101 readouts file of the partner | F16: `RenamedKey` before the file is opened |
| a key literal used for its spelling is rewritten (`startswith("multilingual")`) | KEEP pattern; §2.3 table; manifest row; T17 |
| `apply` refuses the pristine tree because the family `association` looks like a category | marks are (category, family-of-that-category) pairs (§8.1); T15 |
| the script rewrites an English word or a bank value | context rules + reviewer-classified residue + untouched-bytes check (§8.4, §8.5) |
| the `association` family / category collision (F8) | two-phase move; `_layout()` rejects a family in two categories; category packages export nothing |
| fast files edited by mistake | sha pins in `test_fast_subset.py` unchanged and still asserted |
| process-mode children spam the swap notice | suppressed under `outcome=` (§5.6), tested (T8) |
| a published plan row names a vectors path that no longer exists (F3) | `Producer` resolves through `repo_path`; documented (ruling 0.4.2) |
| external consumers (HF datasets, viewer / atlas exports, HallucinationBench) keyed by old names | not renamed (ruling 0.4.3); the README carries the key table |

## 14. Open questions for the owner

None. The six questions of revision 1 are decided (§0.4).

## 15. Implementation order (six commits, each checkable on its own)

| # | commit | contains | must be green |
|---|---|---|---|
| 1 | manifest | `scripts/manifest_0101.py` and `tests/golden/manifest_0101_pre.json`, generated on pristine 030dd09b; nothing else | the reviewer's regeneration in a clean worktree is byte-identical (§11.1); full pytest (unchanged code) |
| 2 | code that is valid BEFORE any rename | `registry.frozen_name` with an EMPTY `FROZEN_KEY_NAMES` (identity) and its use at F1, F2, F5, F6, F11-F15 (incl. `row_sha`, F14) and the F16 guard; `registry.family_root` / `family_rel` / `family_module` / `family_packages` / `repo_path` / `resource_path` over a layout scan that accepts the flat tree (a family directly under `evals/` has category `""`), with EVERY call site converted (§4, incl. the f-string imports in `src` and `tests`, `readplan.families`, `logit_lens.py:146` -> `lookup_names`); `root_bank`, `bank_pins`, `attribute_rows`, `owner`, `dir_owner`, the generalised `Reused` record holding only today's `multihop_mt` entry, the new `stored_family` signature; era-aware loaders (`fast.KEY_ERA` total, `rekey_pre_0101` with an EMPTY `PRE_0101_KEYS`); §5.7a's `draw_verdicts(expect=)` and the all-unverified exit; TP scans 1 and 3 | full pytest and ruff; `manifest_0101.py --check` byte-identical (no key has changed, so no mapping is involved: this proves the refactor alone moves nothing); no file moved, no key renamed; `git diff -- tests/` shows no changed assertion value |
| 3 | the migration script | `scripts/migrate_0101.py`, its unit tests (T15), `scripts/migrate_0101_residue.txt` as classified by the fresh-eye reviewer from `plan`'s output; tag `pre-0101-migration` on this commit | full pytest; `migrate_0101.py plan` runs clean and its per-rule diffs and `tests-values.diff` are attached to the PR for review BEFORE commit 4 is made |
| 4 | the mechanical migration | exactly the output of `migrate_0101.py apply` on commit 3: moves, rule rewrites, JSON keys, formatter hunks. Nothing hand-written. Reproducible because the formatter is `uv run ruff` at the version pinned in `uv.lock` (the script calls it that way and records `ruff --version` in the commit message) | `migrate_0101.py check`; the reviewer's own `apply` on commit 3 reproduces this tree (`git diff --quiet`); KEEP files byte-identical. The test suite is NOT expected to pass here (the registry tables still describe the old keys); CI is not required green on this commit and the PR is not mergeable at it |
| 5 | hand edits and new tests | `registry.py` tables (`LEGACY_FAMILY_NAMES`, `HASH_FAMILY_NAMES`, `FROZEN_KEY_NAMES`, `PRE_0101_KEYS`, the four new `REUSED_FAMILY_KEYS` entries), `register`'s category check, the layout scan made two-level only, the eight family `__init__.py`, the remaining §5 guards (`reads.load` block, `readouts_path`, `family_dir` content rule, `cli._family` notice, adapt marker fence, floors, viewers), the KEEP files, `tests/test_rename_0101.py` (T1-T14, T16), TP scan 2, V1-V8 | full pytest and ruff; `manifest_0101.py --check` byte-identical under the key mapping; gates 5-9 of §11.2; `git diff <commit 4>..<commit 5> -- tests/` contains only KEEP-file edits, new tests and V1-V8 |
| 6 | docs | `README.md`, `CLAUDE.md`, `AGENTS.md`, `NOTICE.md`, family README prose, `adapted/README.md`, `tests/golden/README.md`, `plans/README.md`, the three live docs, skills | `tests/test_readme.py`, `test_prompts_in_readme.py`, `test_adapt_skill_docs.py`, TP scan 3; full pytest; manifest check once more |

Commits 4 and 5 are pushed together (CI runs on the head); the review reads them separately.
