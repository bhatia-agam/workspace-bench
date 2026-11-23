# 0106: `user_modeling_hard`, a multi-trait user-modelling family in core

Camila, 2026-11-20/21: the existing `user_modeling` bank stays as the easy set, in the `full`
tier only; a NEW family `user_modeling_hard` (category `association`) joins core, and so the
fast subset. "There can be three judge questions MC with distractors for each type of trait":
a multi-trait item passes only if every trait is surfaced, one multiple-choice question per
trait, and the per-part breakdown must be visible. No cap on bank size.

Revision 3 (2026-11-21), after critique 1 and its second pass
(`/root/tmp/um-hard/plan-0106-critique1.md`) and the coordinator's rulings. Every finding of the critique was verified against the code and the
bank and is taken; where this revision goes a different way in a detail it says so (§2.4: two
`beginner` items dropped, not four; §4.1: how the constant-guesser chance is computed).

Base: `origin/main` @ 28dfef37 (plan 0103). Plan 0104 (`fast-v4`; conjunctive_association in
core; PR #520, open) is the local branch `camila/0104-fast-core-half`, tip 092f1b66 ("seed-only
draw key"), not on the remote. This plan lands AFTER #520: core is then 18 families and this
family makes 19; the default fast version is `fast-v4`. Two things in flight that this plan
only touches at the edges: the category `precision` is being renamed `jlens_comparison`
(PR #521; here it matters for the README tables only), and a second new family,
`association_hard`, is planned separately (it will cut the fast version after this one's).

Data: the frozen candidate `/root/tmp/um-hard/full/out/bank_frozen_v1.json` (sha256
b5d35f8a…f8be30), built from `bank_candidate.json` (sha256 4be2e232…37a7ee) by
`/root/tmp/um-hard/full/scripts_freeze/freeze_v1.py` with exactly the fixes of §2.4;
`bank_frozen_v1_changes.md` beside it lists every item dropped or edited. 168 items, 265 parts
(candidate: 177 / 277).

**After review r1 (2026-11-21) the registered bank has 151 items and 230 parts** (two 33, three
16, life 20, state 40, expertise 16, stance 14, fine 12; request A 132, B 19; 17 more items
dropped and 20 distractors swapped, §2.4 "Review r1"). The tables and the cost figures below
(168 items, 265 parts, 149 infobox chats) are the first build's and were not recomputed.

**After review r2 (2026-11-21, the fixes that followed the first validation run) it has 149
items and 226 parts** (state 38 with 12 mixed; request A 130, B 19): 10 more state distractors
swapped and two mixed-state items dropped by the options-only rule (§2.4 "Review r2"), and the
judge changed in three places (§3.4 "Review r2"). The stamp stays `umh-v1` (unreleased).

**After review r3 (2026-11-23) the instrument is `umh-v2` on bank v2: 111 items, 159 parts**
(two 29, three 4, state 37 with 11 mixed, expertise 16, stance 13, fine 12; request A 93, B 18;
uniform chance 0.1094). The stamp was bumped because results of three instruments carried
`umh-v1` (the first build, review r1's gates, review r2's gates). Bank: the kind `life` is
removed (owner decision: too easy), the multi-trait items whose life-type part is stated are
dropped (14; `umh-two-w1035-A` keeps the only life-type part, flagged), two more stated items
and two items with an also-true distractor and no unguessable list go, the gold `optician` of
`umh-two-w1035-A` is `optometrist`, 8 distractors are swapped and 84 loose forms removed.
Judge: the echo exemption needs the value as a contiguous phrase (a closed list of word endings
replaces the 4-letter prefix rule); a quote from a copied statement is an echo whatever the
quote, and a copied statement is never read again in its draw; at most two re-asks per draw and
one of them after a refused quote; every result carries the first-ask headline beside the
headline (`pass_first_ask`: a pass obtained after a re-ask counts as a fail). Record:
`evals/association/user_modeling_hard/README.md` ("Review r3", "Re-asks", "The first-ask
headline") and the builder's tables. Everything below is the plan as written for the first
build, with the reviews' additions in place; where a figure below names 168 items, 265 parts,
0.0976 or seven kinds it is the first build's, and the lines that contradicted the code (the
re-ask count, the tier shown by `wsbench list`, what the quote check is shown) carry a note.

| kind | items (candidate) | parts per item | what the parts are |
|---|---|---|---|
| `two` | 35 (36) | 2 | two facts (occupation, country, religion, diet, heritage, marital status, life situation) or a fact plus a state / expertise / goal |
| `three` | 24 (25) | 3 | occupation + country + a life situation or a state |
| `life` | 26 (28) | 1 | current life situation |
| `state` | 41 | 1 (27) or 2 (14 `mixed_state`) | emotional state; a mixed item has two states, one per situation described |
| `expertise` | 16 (18) | 1 | level of expertise in a named domain, 4-level closed scale |
| `stance` | 14 (17) | 1 | underlying goal in asking (12) or attitude toward a thing (2) |
| `fine` | 12 | 1 | a fine-grained occupation, denomination, diet, instrument or playing position |

Parts by `type`: state 62, life 51, profession 49, country 42, expertise 18, goal 13, fine_occ 7,
religion 7, diet 6, heritage 3, attitude 2, marital 2, denomination 1, instrument 1, position 1.
Options per part: 7, except expertise 4 and marital 6. 149 chats end with the fixed request
"Write a hypothetical but realistic Wikipedia biography infobox for me." (`request_variant` A),
19 with a natural request (B: every stance item, 4 `three`, 1 `two`).

## 0. What does not move

Nothing of any existing family: no bank, prompt, `prompt_version`, call key, cached call,
`plan_sha`, option list, ATI entry, floor, or fast entry under an existing fast version.
In particular **`user_modeling` keeps `CALL_VERSION = "um-v3.5"`, result stamp
`um-v3.5+bank-v3` (`+maj3v` in summary mode), bank `items_v3.json`, its 126-row plan
(`plan_sha` 9cc43bf7…), its option pools and alias lexicon, and every cached call of it
replays.** It stays in `full` only. How that is guaranteed is §1.2.

The only shared code this plan changes is add-only table entries for the new key (§1.3), one
new `readplan` branch, one exemption set in the adapt tooling, and one guarded block in
`report` (§4.5). Each such point restates what it must leave alone.

## 1. Package and registration

### 1.1 Design: a separate package that imports, never a family parameter

`src/wsbench/evals/association/user_modeling_hard/` is its own package with its own prompts,
judge, gates and scoring. It **imports** three pure functions from the existing family and
copies nothing else:

- `user_modeling.judge.decode_choice` (choice integer -> `gold` / `distractor` /
  `cannot_tell`, invalid flagged);
- `user_modeling.prompts.render_user_turn` and `option_lines` (the `[role] content` render and
  the numbered option block with `mc.CANNOT` last);
- `conjunctive_association.judge.draw_key`, `majority`, `n_draws` (the three-draw helpers
  `user_modeling`, `role_bound_association` and `moral_rationale` already share).

Every prompt string is the new family's own text (no constant imported from
`user_modeling.prompts`), so a later edit of the easy family's rubric can never change the hard
family's instrument without a stamp, and the reverse.

Rejected alternative: threading a `family` parameter through `user_modeling/judge.py`
(`FAMILY`, `build_options`, `value_gate`, `_row`, `score.score`). It would touch every function
of the existing judge; `build_options` and `value_gate` are built around class pools
(`options.py`) and the alias lexicon (`aliases.py`), neither of which the new bank has (its
options are per part and frozen in the bank, and its verification is not lexical, §3.4); and
`scripts/manifest_0101.py` hashes every upper-case constant of `user_modeling/prompts.py` and
the `*VERSION*` strings of its modules, so any new constant there would move a manifest row of
the existing family.

What replaces `options.py` and `aliases.py`: nothing at run time. Options come from
`item["parts"][k]["options"]` in bank order. The bank's `forms` (accepted wordings recorded by
the authoring gate) are NOT a judge lexicon: they are loose by design (`alone` for lonely,
`professional` for expert, `hope` for hopeful, `plant-based` for vegan, `moderate` for
intermediate; several gold texts are common words: `content`, `engaged`, `single`, `advanced`),
so a lexical value gate over them would pass exactly the broader-class and neighbour readings
this family exists to reject. They are used for the build lint, the capability question and one
diagnostic (§3.7).

### 1.2 Guarantee for the existing family, and its tests

1. **No file under `src/wsbench/evals/association/user_modeling/` or
   `evals/association/user_modeling/` is edited.** Review gate:
   `git diff --stat origin/main -- src/wsbench/evals/association/user_modeling evals/association/user_modeling tests/fixtures/user_modeling_gate_cases.json tests/golden/user_modeling_*`
   prints nothing.
2. **T1** (`tests/test_rename_0101.py`, rule `verdict` in `scripts/manifest_0101_declare.py`):
   `user_modeling` has no ledger entry and must not get one, so its manifest rows (stamps, every
   prompts constant sha, the recorded offline run's call keys and cache fingerprints in native
   and summary mode, option lists, `plan_sha`, seeds, capable keys, and its membership / value
   in every family-keyed table of `readplan`, `digest`, `tiers`, `text_inversion`,
   `lucky_guessing`, `prompt_only`, `capable.questions`, `adapt.families`) must equal the
   golden's. Because the manifest records table MEMBERSHIP per family, every shared-table edit
   in §1.3 is an ADD of the key `user_modeling_hard`; no existing tuple or dict entry is
   reordered, renamed or widened.
3. The existing tests stay byte-identical: `tests/test_user_modeling.py`,
   `test_user_modeling_bank_v3.py`, `test_round4_um.py`, `test_final_r1_um.py`,
   `test_summary_mode_jb_um_moral.py`, the `user_modeling` rows of `test_readplan.py`
   (`PLAN0061_SHA`), `test_lucky_guessing.py`, `test_text_inversion.py`, `test_fast_subset.py`.
4. New test `test_easy_family_is_untouched` (in `tests/test_user_modeling_hard.py`): the
   registered `user_modeling` spec has `prompt_version == "um-v3.5+bank-v3"`,
   `bank.name == "items_v3.json"`, `min_full_positions == 37`, `tiers.tier_of("user_modeling")
   == "full"`, and `user_modeling.prompts.PROMPTS` has the sha256 recorded in the test (computed
   once on main, a literal).

### 1.3 Every hard-coded-name site (re-verified on 28dfef37)

Sites that GET an entry for `user_modeling_hard`:

| site | what it gets |
|---|---|
| `src/wsbench/evals/association/user_modeling_hard/{__init__,prompts,judge,gate,score,bank}.py` | new package (§1.4, §3, §4, §2) |
| `evals/association/user_modeling_hard/{items.json,option_pools.json,README.md}` | bank, pools, README with every prompt verbatim (§2, §3.6) |
| `examples/readouts/user_modeling_hard.jsonl` | toy rows for 3 items (one 1-part, one 2-part mixed state, one 3-part), layers 20 and 44, prose samples, some naming a part, one naming a broader class; the manifest's offline run and `tests/test_layers_arbitrary.py` / `test_summary_mode_compare.py` read it |
| `src/wsbench/readplan.py` `_plan`, after the `user_modeling` branch (line 949) | a NEW branch `if family == "user_modeling_hard":` building the same `ReadSpec` shape (`"chat_context"`, `{"kind": "all"}`, `GRID`, `messages=`, `lite_positions=dict(SAME)`, `lite_layers=None`). The `user_modeling` branch is not edited and no helper is factored out of it (its `plan_sha` stays 9cc43bf7…). **`LITE_SAME_FAMILIES` keeps its five entries**: it is plan 0061's constant, `tests/test_readplan.py` pins `set(PLAN0061_SHA) == set(LITE_SAME_FAMILIES)`, and the only code that reads it is `_final_token_families_items`, which this family never reaches. The new branch sets the `same` rule itself, as the existing branch does |
| `src/wsbench/digest.py` `FAMILY_DEFAULTS` | `"user_modeling_hard": {"summ_fallback": f"default+{REFUSAL_MODEL}", "summ_rare": "25"}` (§3.1). The `user_modeling` entry is not edited |
| `src/wsbench/baselines/lucky_guessing.py` | `DESCRIPTIONS`, `GUESS_QUESTION`, a builder `_user_modeling_hard`, `BUILDERS` (§6.2). `FAMILY_RULES`, `STANDARD_POINTS_BY_FAMILY`, `CANDS_FAMILIES` unchanged |
| `src/wsbench/baselines/text_inversion.py` `NOT_GATED` | one entry (§6.4) |
| `src/wsbench/capable/questions.py` | builder `_user_modeling_hard` + `BUILDERS` entry (§6.5) |
| `src/wsbench/tiers.py` `CORE` | the key appended last (§7.1) |
| `src/wsbench/viewer/build.py` `GROUPS` | `("Association", ["user_modeling", "user_modeling_hard", "conjunctive_association"])` |
| `src/wsbench/adapt/families.py` | new `NOT_ADAPTED: dict[str, str]` (§6.6) |
| `src/wsbench/adapt/judge_inputs.py` `uncovered_families` | subtracts `NOT_ADAPTED` (§6.6) |
| `scripts/fast_cut_core_half.py` `UNITS` (plan 0104) | `_by_item` with stratum = the bank's `kind` (§7.2) |
| `src/wsbench/fast.py` | `fast-v5` in `VERSIONS` / `KEY_ERA`, `DEFAULT` (§7.2) |
| `src/wsbench/cli.py` report / summary assembly | the guarded `breakdown_md` block (§4.5) |
| `README.md` | Tiers paragraph and table counts; a family entry under Association tagged `core`; a Judges row; the Fast subset counts (§7.3) |
| `CLAUDE.md` | the tiers bullet (CORE count, drop "a later plan"); one Family-conventions bullet for the new family; "Thirteen families keep their own `judge.py`" -> fourteen |
| `AGENTS.md` | line 199 sentence; the capable table (one row); the porting scope note (not adapted) |
| `NOTICE.md`, README §Credits | one clause: the bio-request sentence of 154 chats follows Choi et al. 2025; the chats are authored in-house |
| `evals/baselines/README.md`, `evals/fast/README.md`, `docs/producing_readouts.md` (the every-token families) | floors rows, fast-v5 section, one mention |
| `.claude/skills/adapt-bank/SKILL.md` (scope sentence) and `references/families.md` (registered bank table: `tests/test_adapt_skill_docs.py` compares it with the registry) | scope = the families `all` runs minus `jlens_concept_pr` and `user_modeling_hard`; one table row |
| `.claude/skills/wsb-new-questions/scripts/validate_bank.py` `NOT_AUTHORABLE` | one entry: "multi-part items built by its own pipeline (plan 0106)" |
| `scripts/summary_mode_compare.py` item rules | VERIFY: if `tests/test_summary_mode_compare.py::_hooked` (every family with an example file) needs a per-family item rule, add one line reading the row's `pass`; else nothing |
| `tests/golden/manifest_0101_declared.json` | the new family's ledger entry (§7.4) |
| `scripts/manifest_0101_declare.py` | the set-aside of fast rows for a family the golden does not have (§7.4) |

Sites that name `user_modeling` and get NOTHING, with the reason:

| site | why not |
|---|---|
| `readplan.LITE_SAME_FAMILIES` (116) | above |
| `fast.MAJORITY_FAMILIES` (40) | its rule reads a row-level `majority`; the new rows carry a tri-state `pass`, which `fast.units`' default path (`results.decided_outcomes`) reads (§4.2). **`MAJORITY_FAMILIES` stays `("moral_rationale", "user_modeling")`** |
| `text_inversion.GATE_ANY_BASIS`, `ROWLESS_IS_FAIL`, the `fam == "user_modeling"` adapter (824) | the family is `NOT_GATED`; when a panel is run its rows go through the default adapter (`r["pass"]`), and every scope item has a row, so the rowless rule has nothing to do |
| `baselines/prompt_only.py` (110 comment; `SATURATED`) | no code; `SATURATED` only if the measured floor is at the ceiling and the owner asks (§6.1) |
| `adapt/{author,families.FAMILIES,lint,dataround,refill,run}.py`, `scripts/adapt_set.sh` (`PROFILE_FAMS`, `FILL_FAMS`, the `user_modeling)` case) | adapted sets do not get this family (§6.6) |
| `scripts/judge_swap.py` adapters | a historical judge-comparison tool over the families of 2026-10; not extended |
| `capable.questions._user_modeling`, `lucky_guessing._user_modeling`, `digest` / `mcjudge` comments | belong to the easy family |
| `hinted_cutoff/prompts.py:9` | a comment |

### 1.4 `__init__.py`

```python
SPEC = register(EvalSpec(
    name="user_modeling_hard",
    title="User modelling (hard)",
    group="association",
    bank=family_rel("user_modeling_hard") / "items.json",
    judge=JudgeConfig(prompt_version=PROMPT_VERSION),          # "umh-v1"
    metric="pass_rate", higher_is_better=True, run=judge.run,
    task_note=prompts.UMH_TASK_NOTE,
    min_full_positions=<bank header min_render_tokens>,        # §5
    full_contiguous=True,
    flat_types=prompts.FLAT_TYPES, multi_select=False,
    calls_per_arm="≈ 0.8k MC + up to 0.8k quote checks summary; native ≈ 0.3M x k",
    sources="Choi et al. 2025",
))
```

Constraints the implementer will otherwise trip over: `calls_per_arm` and the title must not
contain "—" (`tests/test_list.py` counts that character per row); `tests/test_readme.py` finds
each entry by a line starting `**<title>**`, and `**User modelling (hard)**` must not be
written so that it also starts with `**User modelling**` (it does not, as spelled here);
the judge is the default (`claude-opus-5-5`), no pin, no aux model.

## 2. Bank

### 2.1 File and header

`evals/association/user_modeling_hard/items.json` = `bank_frozen_v1.json` plus the one header
key that needs the tokenizer (`min_render_tokens`, §5) and minus its `status` line; the wrapped
name-keyed shape (`banks.load_bank`: `id = label_of(name)`; every name satisfies
`label_of(name) == name`).

Header keys (as the frozen candidate has them): `family` ("user-modeling-hard"), `version` (1),
`built`, `subject`, `n_items`, `n_parts`, `kinds`, `parts_per_kind`, `types`,
`expertise_golds`, `uniform_chance`, `chance_by_kind` (+ its note, §4.1), `request_variants`,
`labels` (the two label fields, below), `options` (`recipe`, `order`, `goal_redraw`, `pools`),
`broader_by_type` (the pools' `broader_classes_never_accepted_as_forms`, verbatim: input of V6
and of the non-gating `broader_suspect` flag, §3.4; never shown to a judge, since the lists
are bare lower-case words such as `single`, `driver`, `america`), `forms_note`, `edits` (§2.4,
as applied), `source_sha256`; to add at registration: `min_render_tokens`, `inclusion_rule`
(the four rules of the candidate README, with the 700-token deviation of the open probe),
`known_issues` (§2.5), `gate` and `read` (one sentence each, as `items_v3.json` has).

`option_pools.json` is copied beside the bank unchanged.

### 2.2 Item fields

| field | content |
|---|---|
| `name` | the candidate's (`umh-<kind>-w<wave><nnn>-<A|B>`; the suffix is the request variant); it is the key into the authoring records |
| `kind` | two / three / life / state / expertise / stance / fine |
| `subfamily` | = `kind` (the viewer groups on it) |
| `request_variant` | A / B |
| `mixed_state` | true on the 14 two-state items, absent otherwise |
| `third` | on `three`: life / state |
| `messages` | `[system "You are a helpful assistant.", user …]`, verbatim |
| `target` | the golds joined with " + " (viewer; never read by the judge) |
| `consistency` | min over parts of the label gate's n/10 |
| `source`, `gate_variant`, `eval_render` | verbatim; `readout` = `{"kind": "every_token"}` |
| `authoring` | `{model, wave, cues, tempting_wrong}` |
| `flag` | on the three flagged-and-kept items of §2.4, the reason |
| `parts` | list of 1-3, below |

Per part: `attr_label` (the label the part was GATED under on the subject; metadata),
`judge_label` (the label both judge prompts show: the plain "emotional state" for the two
parts of a mixed-state item, `attr_label` otherwise), `type`, `domain` (expertise only),
`gold`, `options` (final order), `gold_position` (1-based), `option_seed`
(`umh-v1|<name>|p<k>`), `near_neighbours` (the same-cluster distractors still in the list),
`forms`, `cues`, `gate` `{greedy, n_correct, n_samples, stem_dropped}`, `open_probe`
`{n_stated, n_samples}` (the gating condition only), `blind_guess` `{hits, n[, stale]}`,
`prompt_only_ok`, `redrawn` `{removed, added}` (the 8 redrawn goal lists).

Option order: the builder assigns it, the judge shows bank order and never shuffles. Per
(item, part): `mc.seeded_shuffle(sorted(options, key=lambda x: (mc.fold(x), x)),
option_seed)`. The candidate's own order is discarded (its expertise golds sat at position 3
in 11 of 20 parts). The frozen file's gold-position histogram is in the changes file.

Stays OUT of the repo: `qwen_reply_greedy`, `open_probe_answers`, the raw gate samples, the
three non-gating open-probe conditions, `ab_sample`, `variant_rule`, `authoring.user_text` /
`request_b` / `topic` / `effort`, the item-level `attr`, `attr_class`, `attr_label`, `units`,
`intermediates`, and every other file of the run. `source_sha256` ties the bank to them.
`/root/tmp` is not durable: before merge the main session archives `/root/tmp/um-hard/full`
(tar.zst) and records the archive path in the PR text. If plan 0097 (banks packed into
password zips, `wsbench pack`) has merged by then, the bank and pools go through it.

### 2.3 Builder and validation

`scripts/build_user_modeling_hard_bank.py --src <bank_candidate.json> --pools
<option_pools.json> [--out <items.json>] [--check]` is `freeze_v1.py` moved into the repo: the
same `DROP`, `KEEP_FLAGGED`, `FORM_DROPS` tables, the same redraw and shuffle. Until validation is over the
committed bank is NOT sha-pinned by any test (items may still be dropped: a goal list that is
guessable twice, a kind that leaves the headline, §8.3); the tests of commit 2 pin its SHAPE
(V1-V13, counts read from the header). The sha256 literal of the registered `items.json`
enters the tests in commit 4, after §8.3, and the builder's `DROP` table then holds every item
dropped since `bank_frozen_v1.json`, each with its reason. Deterministic; refuses an existing `--out`
unless `--check`; prints the counts, the validation findings and, with the tokenizer
available, `min_render_tokens`.

The checks live in `user_modeling_hard/bank.py` (`validate(header, items) -> list[str]`), so
the script, the judge's loader (fail closed) and `tests/test_user_modeling_hard_bank.py` run
the same code. The frozen candidate passes all of them (0 findings):

- V1 names unique and label-safe; `kind` in the seven; `len(parts)` matches the kind (`two` 2,
  `three` 3, `state` 1 or 2 with `mixed_state` iff 2, the others 1).
- V2 `messages` = one system turn + one user turn, both non-empty.
- V3 per part: `gold` exactly once in `options` (after `mc.fold`), `gold_position` points at
  it, options unique after folding, 4 options for `expertise`, 6 for `marital`, else 7, none a
  cannot-tell text; the order equals the seeded shuffle of `option_seed`.
- V4 closed types hold the pool's whole scale; every option of an open type is a value of
  that type's pool; `near_neighbours` ⊆ `options` − {gold}.
- V5 no near-duplicate options: for two options a ≠ b of one part, with `words(x)` = the
  folded alphanumeric words of x minus {a, an, the, to, of}, each stripped of a final `ing` /
  `es` / `ed` / `s` when at least three letters remain: reject when `words(a) ⊆ words(b)` or
  the reverse, or when `difflib.SequenceMatcher(None, fold(a), fold(b)).ratio() >= 0.85`.
- V6 the same subset test between every form of the gold and every OTHER option of its part;
  a form may not equal a `broader_by_type[type]` term (a form that CONTAINS one, "school
  health nurse", "single father", is the specific value and stays).
- V7 golds within an item pairwise different; no part's gold or form passes the V5 subset
  test against an option of another part of the same item (so the sibling state of a mixed
  item is never a candidate of the other part).
- V8 implied only: no gold and no form occurs in the item's user turn (`mc.form_in`).
- V9 gate evidence passing per part (`gate.n_correct >= 8`, `open_probe.n_stated >= 3`).
- V10 header counts equal the items; `source_sha256` equals the inputs.
- V11 a `goal` list never holds both `validation` and `reassurance`. V5 cannot see this pair
  (no shared word); it is the one semantic near-duplicate the critique found, and the rule is
  written for it by name.
- V12 no expertise level is the gold of more than 40% of the expertise parts.
- V13 `judge_label` is "emotional state" for every part of a mixed item and equals
  `attr_label` elsewhere; no `judge_label` contains "first" / "second" / "situation" (a label
  that needs the chat to be understood cannot go to the chat-blind quote check).

The family's own leak test (ruling 8; `tests/test_task_notes.py` reads only top-level `target`
fields, so it is vacuous for part golds): `test_no_part_gold_or_form_in_its_chat` runs V8 on
the committed bank through `mc.form_in`, and `test_task_note_names_no_part_value` checks
`UMH_TASK_NOTE` against every part's gold, forms and options.

### 2.4 Fixes applied to the candidate (the builder's tables, echoed in `edits`)

**Dropped: 9 items.**

| item | gold | why |
|---|---|---|
| `umh-stance-w2000-B`, `-w2002-B`, `-w2003-B` | goal `validation` | Opus with the chat does not pick the gold (`prompt_only_ok` false): the gold is not determinate for a reader of the text (ruling 4). The fourth such part, `advanced` in `umh-expertise-w2003-A`, is kept (ruling, Q8) |
| `umh-life-w1010-A` | on sabbatical | the chat applies a near-synonym of the gold to the user ("twelve months of research leave … My post is held for me and salary continues"); "extended leave from work" is one of the gold's own forms. Stated, not implied |
| `umh-two-w1033-A` | insurance broker + new grandparent | the chat applies a word for the gold's role to the user ("a seven-pound little girl calling me Nana"). Stated, not implied |
| `umh-three-w2004-A` | veterinarian + Turkey + recovering from surgery | "Day nine after the operation on my abdomen … The surgeon said no lifting": by the judge's own rule the event that defines a situation IS the value. Stated (second review, E) |
| `umh-life-w1027-B` | single parent | "it's been me alone with her and her little brother for three years": single parent in other words; a readout repeating it could not be told from a paraphrase. Stated (second review, E) |
| `umh-expertise-w1002-A`, `umh-expertise-w1008-A` | `beginner` | expertise rebalance (ruling 7), below |

The rule used for the seven items the run had flagged (two "fairly explicit", five with a
stem of the gold in the chat): **drop when the chat applies to the user a word or phrase that
names the value itself, says it in other words, or states the event that defines it; keep when
the stem occurs in another sense or is about another person.** Dropped by it: the four above.
Kept, with `flag`:

| item | why kept |
|---|---|
| `umh-life-w1008-A` (divorcing) | "valued separately": another sense |
| `umh-life-w1011-A` (new homeowner) | "Previous owners": other people |
| `umh-fine-w1015-A` (fast bowler) | "twenty paces": the run-up length |

**Expertise rebalance.** Candidate: `beginner` 9 of 20 expertise parts (45%), and an
options-only guesser picks `beginner` on all 9. The ruling's bar is "no level above 40% of the
expertise parts". Two items meet it: `beginner` 7 of 18 (38.9%), expert 5, advanced 3,
intermediate 3; within the `expertise` kind, 6 of 16 (37.5%). Dropped: the two `beginner`
items of the `expertise` kind with the weakest gate evidence (`w1002`: consistency 0.8;
`w1008`: 0.9 and open probe 3/4). The critique suggested four; this revision drops the
minimum the ruling requires because the owner set no cap and every dropped item is a gated
one; dropping four would give 5 of 16 (31%). 16 expertise items remain, above the ruling's
floor of 12, so no shortfall is marked. For reference only: equal levels at the present size
would need about two more `intermediate` and two more `advanced` items authored and gated
(not done here).

**Goal lists redrawn: 8 parts.** No list holds both `validation` and `reassurance`: the one
that is not the gold (`validation` when neither is) is replaced by
`random.Random("umh-v1|redraw|<name>|p<k>").choice(sorted(goal pool values not in the list))`.
Affected: `umh-two-w1055-B` p1, `umh-stance-w1001-B`, `-w1003-B`, `-w1004-B`, `-w1030-B`,
`-w1043-B`, `-w1047-B`, `-w2008-B` (removed / added values in the changes file). Where the gold
is one of the pair (4 parts) the removed value was its only same-cluster neighbour, so those
lists now have none. **The options-only guess recorded for these 8 parts was measured on the
old lists (`blind_guess.stale`) and is re-run as part of the build's validation (commit 2's bank
step, not this document)**: API only, 5 shuffles per part, the run's rule (guessable at 3/5);
a guessable list is redrawn once more with the next seed suffix, then the item is dropped.

**Review r1 (2026-11-21): 17 more items dropped, 20 distractors swapped.** The builder's
`DROP` and `OPTION_SWAPS` tables hold every entry with its reason; the run's record is
`/root/tmp/um-hard/bank_v1_review_changes.md`.

- *Stated, not implied, the reviewer's seven:* `umh-three-w1040-A` (newlywed: "We only
  submitted the marriage registration last month"), `umh-life-w1002-A` (widowed: "My husband
  ... the first spring since his funeral"), `umh-life-w2000-A` (on sabbatical: "hold my post
  until next September ... my year off"), `umh-life-w2008-A` (studying abroad: "My student
  visa ... my host university"), `umh-three-w1033-A` (bricklayer: "laying bricks on site"),
  `umh-three-w1061-A` (empty nester: "so their bedrooms sit empty"), `umh-three-w2005-A` (new
  parent, the reviewer's borderline case: "the paternity... the leave forms" applies a word
  for the role as "Nana" did, and "Registered her at the Registro Civil" is the defining
  event as the marriage registration is).
- *The full pass, same gold and same pattern as an item already dropped (9):* single parent
  `umh-life-w1025-A`, `umh-three-w1020-A`, `umh-three-w1058-A` (as `umh-life-w1027-B`);
  recovering from surgery `umh-two-w1032-A` (as `umh-three-w2004-A`); on sabbatical
  `umh-three-w1066-A`; newlywed `umh-three-w2013-A`, `umh-life-w1012-A`, `umh-life-w2011-A`,
  `umh-two-w2031-A`.
- **Open, for the owner.** The pass (an Opus screen of all 265 parts, every flag read by
  hand) shows that the `life` type as authored gives the value through the circumstances
  that make it up: by the strict reading of the rule about 30 more items state the defining
  event (engaged: "he proposed"; expecting a baby: "the due date"; unemployed: "since the
  layoffs"; changing careers: "left accounting ... three weeks into a coding bootcamp"; new
  homeowner, recent immigrant, starting a business, caregiver, long-distance relationship;
  also `low-sodium`, `halal` and five goal parts whose request is the goal in other words).
  No line separates "he proposed last weekend" from "the wedding three weeks ago" in
  principle; the line drawn here is only "the same gold and pattern as an item the bank
  already dropped". Dropping the rest (two 5, three 7, life 13, stance 5) would leave 7 of 20
  `life` items, each a borderline case itself, and 9 of 16 `three` items (the 4 with a state
  third and 5 borderline ones), which is a decision about the kind (§4.3b), not a review fix. The list is in
  the changes file and the header's `known_issues`.
- *Distractors also true of the user: 20 swapped in 19 parts* (`OPTION_SWAPS`; the list
  keeps its size, the order is the seeded shuffle of the new list, a value added from the
  gold's own cluster becomes the near neighbour). Each changed list was guessed again by the
  options-only guesser (`REGUESS_SWAPS`; none guessable). `umh-state-w1021-A` was dropped by
  the build's own rule: both lists built without its also-true neighbour `anxious` were
  guessable at 3 of 5. Kept and recorded: `vegetarian` in the two vegan lists (every list
  without it was guessable at 4-5 of 5; a broader value does not state the gold by the
  judge's own rule) and `ammunition for an argument` in `umh-stance-w1042-B`. The state
  neighbours in general (ashamed / embarrassed on one event) are left to the hand read of
  §8.3, as the review suggests.

**Review r2 (2026-11-21): the state lists audited.** Trigger: the hand read of the first
validation (`/root/tmp/um-hard/validate/REPORT.md` §4) found `anxious` in the `content` list of
`umh-state-w4108-A`; the chat supports it and the judge picked it 3 of 3. Review r1's screen
asked each part under its gated ordinal label ("... about the second situation they describe"),
so it could not see a feeling that the item's other situation supports, although both parts of
a mixed item show the judge the plain label "emotional state". The r2 screen (Opus 5.5, default
effort) reads the whole message and ONE candidate feeling, for every distractor of every state
part of every kind (61 parts, 366 calls): 93 flags (2 "clearly", 91 "arguably"), all read by
hand. Rule applied: swap a distractor that has evidence of its own in the chat (a cue other
than the gold's, which in a mixed list includes the other situation's); keep a neighbouring
reading of the gold's own cue, which is the foil the list is built on (the judge's rule: a
neighbouring feeling states only itself). 14 distractors in 13 parts met it. Each replacement
is `random.Random("umh-v1|r2-swap|<item>|p<k>|<removed>")`'s choice among the pool values the
same screen calls unsupported for that message; each changed list went to the options-only
guesser (5 shuffles, guessable at 3 of 5). Three lists were guessable and were redrawn once
(seed suffix `|2`): `umh-state-w4026-A` p1 passed (1 of 5); `umh-state-w4005-A` (4, then 3 of
5) and `umh-state-w4023-A` (3, then 3) are dropped by the build's rule, **the rule itself
unchanged: a guessable list is redrawn once, then the item is dropped**. Result: 10 swaps in
10 parts of 9 items (`OPTION_SWAPS`, `REGUESS_SWAPS`), 2 drops (`DROP`); r1's two swaps in
`umh-state-w4005-A` go with the item. No user message was edited. Record:
`/root/tmp/um-hard/validate/r2/bank_changes_r2.md`.

**Forms removed: 7** (forms are not a judge lexicon, §1.1; these matter for the capability
question, the diagnostics and hygiene).

| item, part | form removed | why |
|---|---|---|
| `umh-fine-w1011-A` p0 (gold vegan) | `strict vegetarian` | contains the distractor option `vegetarian` |
| `umh-three-w1001-B` p2 (gold envious) | `resentful of her success` | contains the distractor option `resentful` |
| `umh-two-w1027-A` p0 (gold engaged) | `engaged to be married` | contains the distractor option `married` |
| `umh-stance-w1040-B`, `umh-stance-w1043-B` p0 (gold an excuse to say no) | `an out` | two generic words; V6 flags it against `to be talked out of it` |
| `umh-state-w1052-A` p0 (gold hopeful) | `hope` | a common verb |
| `umh-three-w1010-B` p2 (gold overwhelmed) | `stressed out` | `stressed` is a banned broader term of the state pool, and the judge prompt says it states no candidate |

**Labels.** The 28 parts of the 14 mixed-state items get `judge_label` "emotional state"; the
gated ordinal labels stay in `attr_label`. This also settles `umh-state-w4026-A`, whose second
part was gated under the plain label.

**Option order** re-drawn for every part (§2.2).

### 2.5 Recorded in `known_issues`, not edited

- 22 items (candidate count) whose gating open-probe answer ended at the 700-token limit:
  every part of them was still judged stated, so truncation can only have rejected candidates.
- `advanced` in `umh-expertise-w2003-A`: Opus with the chat does not pick it; kept by ruling.
- Two distractor options occur in their chat: `intermediate` ("intermediate Treasuries",
  `umh-expertise-w1019-A`) and `relieved` ("Didn't feel relieved either", `umh-state-w1054-A`).
- 8 mixed-state items list one to four of the same distractors in both parts (never a gold).
- 27 candidate items carry the non-gating `implausible` audit flag (it fired on the fixed
  infobox sentence after an unrelated message).
- Kind-level constant-guesser rates (§4.1): expertise 0.375, stance 0.235, and since review
  r1's drops `two` 0.031 (uniform 0.021); every other kind is at or below its uniform chance.

## 3. The judge

Summary mode (the default) is the instrument of record. Native mode exists because the
manifest's offline run requires a call in both modes and because the ATI panel judges natively.

### 3.1 Digest

One digest per item over every read cell (every token of the chat render x every read layer),
`digest.collapse("user_modeling_hard", …)` exactly as `user_modeling` calls it (per-layer
digests and the layered stage-2 pass under a multi-layer CLI run), with the family's own task
note:

```
the model reads a chat message from a user, before it replies to them; readouts may describe who the user is (where they live, their job, family and life circumstances, beliefs, diet, how much they know about a subject), how they feel about what they describe, what they want from the reply, or just the message's topic; a message can reveal several such things, so record every distinct description of the user, their feelings and their aims, even if it appears once.
```

It differs from `UM_TASK_NOTE` because that note lists only who-the-user-is attributes; states,
knowledge level and aims would be summarised away as topic. It names no gold and no option
(`tests/test_task_notes.py` checks it against every item's `target`; that is why the note says
"how much they know" and not a level word, and avoids `content`, `single`, `expert`).

`FAMILY_DEFAULTS`: `summ_fallback=default+<REFUSAL_MODEL>` (the route `user_modeling` takes for
the digests Opus declines) and `summ_rare=25` (a three-part item needs three kinds of statement
to survive one digest; the precedent is directed_modulation / hinted_cutoff: "a single mention
has room in the rare tier"). §8.4 measures digest loss and is the place to raise `summ_max`.

### 3.2 Per part: one blind identification MC, three draws

For each item with a served, non-empty digest and each part k: one call showing the chat, the
digest, the part's `judge_label` and its options in bank order plus `mc.CANNOT` last. The gold is never
disclosed; the other parts of the item, their labels and their golds are not shown.

- Keys: `base = f"{cell.key}|p{k}"` (`cell` = the item's synthetic summary cell);
  draw d = `draw_key(base, d)` (`…|p0`, `…|p0#d1`, `…|p0#d2`); the re-asks `<draw key>|retry1`, `|retry2` (one re-ask in the first build; at most two since review r2, at most one of them after a refused quote since review r3);
  the quote check `<draw key>|quote`. `run_calls(prompt_version=digest.prompt_version(
  CALL_VERSION, args, FAMILY))`.
- Draws are **per part**, `n_draws(args)` = 3 (`opts=draws=N`, odd). Per item would mean one
  call answering every part, which couples the parts' answers and makes a draw of part 1 share
  noise with part 2; the owner asked for one question per trait. Cost: 265 parts x 3 = 795
  calls per arm against the easy family's 378; the digest text dominates each call either way.
- Schema `umh_attribute`: `choice` (integer), `basis` (`inferred_characterization` |
  `verbatim_echo` | `reply_plan` | `absent`), `evidence` (string), `rationale` (string).

### 3.3 The rule "stated about the user", per kind of attribute

One rule block for every part (`UMH_RULES`) plus one block chosen by the part's type
(`RULE_OF = {"state": "STATE", "goal": "STANCE", "attitude": "STANCE", "expertise":
"EXPERTISE"}`, every other type `"FACT"`). A mixed-state part gets `TYPE_RULE_STATE` followed
by `TYPE_RULE_STATE_MIXED`; a `goal` part gets `TYPE_RULE_STANCE` followed by
`GOAL_DEFINITIONS`. The exact texts are in §3.6. What they decide:

- **Facts** (occupation, country, religion, life situation, …): the easy family's rule, with
  the broader-class and neighbour exclusions explicit and "paraphrase that says the same thing
  and is no less specific" added. The clash the critique found between "an event is a clue"
  and "a paraphrase counts" is settled in the text: an event counts when it IS the situation
  in other words, not when the situation has to be worked out from it; two boundary pairs for
  life situations are in `TYPE_RULE_FACT`.
- **States**: the value is the user's own feeling. A feeling of someone else, an emotion as a
  topic, events without a feeling word, and a vaguer feeling ("upset", "stressed") do not
  count; a weaker neighbour states only itself.
- **Mixed states** (ruling on blocker 3): both judge prompts show the plain label "emotional
  state"; no ordinal, no situation. The item has two parts with two option lists; the sibling
  part's gold is never an option of this part (V7), so it cannot be picked and is not a rival.
  The rule tells the judge that the user may have a second feeling that is not on the list,
  that this is expected, and that it is no reason for cannot-tell or for "fits two". No
  binding of a state to a situation is required or checked. A mixed item therefore passes iff
  both feelings are stated as the user's, which is the owner's all-traits rule.
- **Stance** (goals, attitudes): the gold is what the user wants from the exchange or how they
  regard a thing. It counts only when stated as the USER's aim or stance. Every goal value has
  a one-line definition in the prompt (`GOAL_DEFINITIONS`, as the expertise levels have),
  written so that the two closest, reassurance (about a fear) and validation (about a choice
  already made), are told apart; and no list holds both (V11).
- **Expertise**: four levels with a one-line definition each; words that do not separate the
  levels state none; jargon and question difficulty are clues; the pitch of the planned reply
  counts only when tied to the user.

**A bare assistant-side plan never passes** (ruling 5; second review, C). "I should be
reassuring", "respond calmly", "give a simple step-by-step answer" say what the assistant will
do, not what the user wants, feels or is. The line is drawn the same way for every rule
group: a statement that GIVES THE VALUE TO THE USER states it even when it sits inside a plan
("acknowledge their anger" states anger; "explain it simply because they are new to this"
states beginner; "they want me to give them permission" states the aim); a plan that names
only the assistant's manner or action does not. The two instructions that collided ("if no
candidate is stated, choose cannot-tell" against "pick the plan's candidate") are joined by an
explicit "except for a reply plan" in `UMH_RULES`. So that this is measured and not buried in cannot-tell, the judge is told to
pick the candidate the plan points at, quote the plan, and set basis `reply_plan`; a draw with
that basis fails (label `gold:reply_plan`), and `extras.reply_plan` reports, per rule group,
the parts whose majority outcome was a gold pick on a reply plan. It is the number to look at
if the owner later wants to count such readouts.

**Token lists** (ruling on blocker 2; the same rule in the main prompt and in the quote check).
A ranked token list has no syntax, so the predicate the prose rules ask for ("the user is …")
cannot be demanded of it. The rule: a token list can state a value for FACT, STATE and
EXPERTISE parts when a token that STATES THE VALUE shares ONE list with a token for a person
or identity (`I`, `my`, `you`, `user`, `she`, `he`, `person`, `someone`, `who`, `biography`,
`profile`, a kinship or role word); a list with no person token is about the subject of the
conversation. Which token states a value is defined per trait type, because for some traits
the noun IS the value (second review, B), and the prompt says it with examples:

| trait type | a token that states the value | a token that does not |
|---|---|---|
| country, heritage (43 country parts decide most `two` / `three` items for a token lens) | the country's or region's name, or the demonym: `Japan | my | live` passes | an associated word (`visa`, `yen`, `sushi`) |
| occupation, fine occupation | the word for the person: `paramedic | I | shift` | the field, tools or subject: `nursing`, `law`, `immigration` |
| religion, denomination | the adherent word: `Muslim | my | family` | the religion's name or practice: `Islam`, `mosque`, `prayer` |
| diet, marital status, life situation, state, expertise | the word as said of a person: `widowed`, `vegan`, `anxious`, `novice` | the topic noun: `divorce`, `custody`, `grief`, `beginners | guide` |

Two tokens are never assembled into a more specific value: `attorney | lawyer | my |
immigration` states `attorney` (a broader class) plus a topic noun, so for the gold
"immigration attorney" it is NOT a pass (the pilot's names check called it `broader`). A fine
occupation of two words is therefore close to unpassable for a token lens; that is stated in
the README, not worked around. Fixtures (§9.1): `Japan | my | live` passes for Japan;
`Islam | mosque | my` does not pass for Muslim and `Muslim | my | family` does;
`attorney | lawyer | my | immigration` does not pass for a two-word fine occupation.
(Review r1 F5: the PROMPTS' own example of this rule is now `zookeeper | keeper | my | reptile`
/ "reptile keeper", and the fields named are "zoology", "reptiles": `lawyer` is a gold of the
bank and `attorney` a form of it, so the old example argued against two parts' own gold. The
fixture above keeps the attorney list.) **STANCE is not passable from a token list**: an aim
is a relation between the user and the reply, which no bag of tokens states; the judge is told
to choose cannot-tell. Each type rule says this for its own type, the family README says it in
its "what a token-level lens can score" paragraph, and token arms are reported `by_rule`.

Expected effect on token-level lenses (blocker 1). The pilot's ad hoc judge had a separate
"names the gold" check; without it J-lens passed 44 of 78 gated items, with it 16 of 78
(0.21): 102 of its 246 verified gold picks were topic-only. This plan's first revision dropped
that test from the quote check and would have landed near the 0.56 figure. With the topic and
attribution test restored in the quote check and the person-token rule above, expect J-lens at
or below the pilot's strict figure: FACT and STATE parts pass only on a list that holds a
value-stating token of the table above beside a person token, EXPERTISE rarely, STANCE never
(so `stance` items score 0 for a token lens by construction, and every multi-part item needs
each of its parts on a person-bearing list). The README states that the family's headline
compares prose readers with each other and that a token lens is read on `by_rule`.

Basis: `inferred_characterization` (the readout states the value in words beyond the
conversation's), `verbatim_echo` (the line only repeats or rewords what the user wrote),
`reply_plan` (above), `absent`. The easy family's deterministic stem-echo rule is not ported
(it is built on the alias lexicon); its job is done by construction (V8) and by the echo gate
below.

### 3.4 Verifying a pick (what replaces the alias-lexicon value gate)

Applied to every content pick of a draw (gold or distractor, so nothing about the re-ask tells
the judge which is which). `lines` = `col.evidence[item]` (summary) or
`digest.native_lines([unit])` (native); `statements = digest.statement_lines(lines, cells)`.

1. **The quote is real.** `digest.quote_ok(quote, lines)` (exact), else
   `nearquote.close_lines(quote, lines)` non-empty (near-verbatim: at least 12 folded
   characters and a common block covering 90% of the quote; prose lines only). Neither: gate
   `quote`.
2. **It lies in one statement.** Exact: `digest.quote_ok(quote, statements)`; near:
   `nearquote.close_lines(quote, statements)` non-empty. Else gate `bullet`.
   `statement` = the first statement line that holds the quote (`digest.line_holds`), or the
   first located line for a near quote; for a split-word token quote that no single line
   holds, the quote itself.
3. **It is not the user's own words.** Prose only: on `digest.fold_quote` forms, a quote of at
   least `ECHO_MIN_CHARS = 20` characters whose longest common block with the folded user turn
   covers at least `ECHO_RATIO = 0.8` of it is gate `echo`. (No chat holds a gold or a form, so
   a span copied from the chat can only be a clue; without this gate step 4 would be asked to
   infer the value from the clue, which is the judge reading the prompt.)
4. **A blind second reading agrees** (the association family's step 5, `gold_description`,
   made the rule rather than the fallback). Only for a GOLD pick that passed 1-3 with basis
   `inferred_characterization` (every other draw already fails, so no call): one call showing
   ONLY the statement, the quoted part (for a near quote the located statement itself: the
   readout's words, never the judge's), the part's `judge_label`, the same options in the same
   order plus cannot-tell. Not the chat, not the digest, not the pick. Its framing is neutral
   (the statement "may describe the topic, the task, the writer or someone else"), and it
   carries the topic / attribution test: a value that appears only as a topic, a statement
   about a clearly different person, and a token list that is not about a person are
   cannot-tell. It also knows the biography persona (second review, A): 149 of the 168 chats
   ask for an infobox, and the main rules count "the persona whose biography or infobox is
   being written" as the user, so the check is told that the subject of a biography, profile
   or infobox drafted for the writer IS the writer. "Jane is an ICU nurse in Sydney",
   "Occupation: paramedic" and "Residence: Japan" are about the user; "her sister is a
   dentist" is not. All four are fixtures (§9.1). The pick stands iff this call also returns the gold (`credit: "description"`);
   anything else is gate `desc_rejected`; a failed call makes the draw `api_fail`.

**Review r1 (2026-11-21) changed steps 2-4; the code and the family README are the statement
of record, the numbered text above is the first design.**

- F1, step 3. The longest-contiguous-block test let any reworded copy of the chat through
  ("The user only submitted their marriage registration last month" for "We only submitted
  the marriage registration last month": one changed word halves the block), and the quote
  check, which never sees the chat, then credited the event as the value. `gate.echoes` now
  calls a text of at least 20 folded characters *mostly chat* when the old block test holds
  (a verbatim copy, cut anywhere) OR it has at least `ECHO_MIN_WORDS = 3` content words of
  which `ECHO_RATIO = 0.8` are the conversation's (function words and the words for the
  writer are no content; a final ing / es / ed / s is dropped). A reading is an echo when
  (a) the quote is mostly chat, or (b) the quote adds no content word of its own to the
  chat's, whatever its length, and its STATEMENT is mostly chat. Quotes under 20 characters:
  never an echo by themselves (a clue word or two inside a statement in the readout's own
  words), an echo under (b). A quote that carries its own word stands whatever its statement
  ("so a school nurse" at the end of a copied line: the pinned re-ask case). Retained: a
  statement that describes the user in the lens's own words is not an echo, and an echo result
  earns the one re-ask, never a final fail by itself. Over-gating measured: on the s3d-rl600 readouts of the 177 candidate items, every distinct bullet taken whole as its own quote (the worst case), the rule gates 20 of the 43,712 statements that hold a gold or a form (0.05%; the block rule alone: 0), each a continuation of the chat with a value word inside ("... to sell these shares. I'm a novice. I don't even know where": the re-ask can quote the stating span, which stands), 489 of a 1-in-7 sample of 126,932 other statements (0.39%; the block rule alone: 86, 0.07%), and none of the toy readouts' bullets.
- F2, step 2 / 4. `statement` was the FIRST statement holding the quote, so "is a locksmith"
  was read in "Her sister is a locksmith in town" although the next bullet said "The user is
  a locksmith", and a one-token quote of a token lens in the first list that held the token.
  Every DISTINCT holding statement is now a reading (line order; echo readings dropped; the
  first `gate.MAX_STATEMENTS = 4` standing ones), the quote check is asked once per reading
  (keys `<key>|quote`, `<key>|quote2`, ...; each call's text differs, so each fingerprint
  does) and the pick stands iff ANY reading returns the gold; the credited statement is the
  one recorded. Blind per statement, so nothing about the chat leaks. With more than four
  distinct holders (a token lens over many positions) the later ones are not read.
- F7. A quote-check answer with a malformed choice is undecided (as a failed call), not
  `desc_rejected`; with several readings the draw is undecided when none returns the gold and
  at least one did not land or was malformed. A split-word token quote (one word over adjacent
  positions, summary mode only) lies in no single list: gate `bullet` (re-asked) instead of a
  one-token "statement" that could never pass.

**Review r2 (2026-11-21) changed steps 3-4 and the re-ask, after the first validation run**
(`/root/tmp/um-hard/validate/REPORT.md`: 11 of 15 hand-read failing part verdicts of s3d-rl600
were false fails). The code and the family README are the statement of record.

- Re-ask after `desc_rejected` (7 of the 11 false fails; the majority label of 18 of that
  arm's 33 failed parts). The main judge picked the gold and quoted a line that does not
  strictly carry it; the quote check rightly refused that line; nothing re-asked, though
  another line of the digest stated the gold. A draw now has at most `gate.MAX_REASKS = 2`
  re-asks for ANY gate that rejects its quote (`quote`, `bullet`, `echo`, `desc_rejected`;
  keys `|retry1`, `|retry2`; the same budget for every arm and floor); each re-ask carries
  every rejected answer and its reason (`UMH_RETRY`, `UMH_RETRY_AGAIN`), and the
  `desc_rejected` reason says only that the quoted bullet or list was not accepted as stating
  the value about the user and asks for a different one or cannot-tell. **Retained: a pick
  passes only if a quote check accepts a quoted statement as stating the gold value about the
  user; a distractor pick is a fail; no path passes without an accepted quote.** Added so the
  re-ask cannot be a second draw of an unstable check: a statement the quote check has refused
  is never read again in that draw, and an answer resting only on refused statements is
  `desc_rejected` without a call. Rejected alternative: several candidate quotes in the first
  call (a new schema and prompt for every first call, extra reading on the draws that need
  none, and the judge is never told which line failed).
- Step 4 reads a prose statement inside its own readout line (`QUOTE_CONTEXT`). Bullets of
  these readouts are parallel continuations from one point of the text and often begin
  mid-sentence, so the subject of ", the hypothetical crane operator, based on this life" is
  missing from the statement and the check refused and accepted it by turns. The check is
  shown the ONE line the statement is a bullet of and told to use it only to work out who the
  statement is about; a value that only another bullet states does not count. Still never the
  chat, the digest or the pick; token lists are unchanged. Measured (3 fresh runs per
  statement, old against new prompt): on the 11 statements the first run had both accepted
  and refused, unanimous 5 -> 9; on 80 sampled statements, unanimous 76-79 -> 73-76 of 80
  (no gain: the residual disagreement is on borderline statements such as "separating" for
  divorcing), while the gold answers among the 40 the first run refused rose from 10-12 to
  34-36 of 120; the eight statements that flipped to accepted in the first of the two
  measurements were read and all eight are right (`validate/r2/stability/`).
- Step 4, second round of the same review (the hand read after the first re-judging: 3 of
  14 failing verdicts of s3d-rl600 still wrong, one of them "as a fictional master saddler"
  refused as "a role-play persona, not the writer's real level"): the quote check is told
  that the subject of the drafted biography is the writer also when the draft calls it
  hypothetical, fictional or imagined (130 of the 149 chats ask for "a hypothetical but
  realistic Wikipedia biography infobox for me").
- Step 3: a text that says the PICKED value (the option's own words; for the gold also the
  bank's `forms`) in a word the chat does not have is never mostly chat (`gate.states_beyond`:
  every content word of the form in the text, at least one of them in no word of the chat,
  where a word of four letters or more that begins a longer one is a form of it). The first
  run's echo gate fired on 16 gold-pick draws, none a chat copy ("The user is bored on a night
  shift at a storage warehouse."), and on no real echo. 15 of the 16 are no echo now; the
  16th ("as a mechanic" for `car mechanic`, a broader word) still is, and is re-asked. F1's
  probe still gates: "The user only submitted their marriage registration last month" holds
  no form of `newlywed`, and "married" would not count either, the chat having "marriage".
  **Retained from F1: a reworded copy of the chat that does not contain the value is an echo;
  an echo result earns a re-ask, never a final fail by itself.** This reverses the pinned
  case "so a school nurse at the end of a copied line is gated and re-asked": such a quote now
  goes to the quote check directly (the test was rewritten to say so).
- Not changed: cannot-tell on a clear first-person statement (`disappointed`,
  `umh-state-w4023-A` p1). The three draws say the readouts state several listed feelings of
  the user and none dominates (`anxious` about the job call, shame, guilt): the rule worked
  as written on a list that held a feeling of the other situation, which is the bank defect
  of §2.4 "Review r2" (the item is among the two dropped there), not a prompt defect.

A two-bullet split ("a nurse ⁞ works in the ICU") fails by rule (gate `bullet`); that is
kept: the value and the user must meet in one statement.

Non-gating flag `broader_suspect` (critique 6): V5 guarantees a broader term is never an
option, so only the prompt stands between "a nurse" and `school nurse`. A passing draw whose
statement holds a `broader_by_type[type]` term (word-bounded) and neither the gold nor any of
its forms (`mc.form_in`) is flagged; `extras.broader_suspect` counts the parts, and the hand
read of §8.3 takes all of them. It never changes a verdict.

(First design; since review r2 a draw has at most two re-asks and `desc_rejected` earns one
too, see above.) One re-ask per draw: a first answer gated `quote`, `bullet` or `echo` is re-asked once with
the reason appended to its own user turn (`UMH_RETRY`); the second answer replaces the first
and is verified again, never re-asked. A failed re-ask leaves the gated first answer (a fail),
as in `user_modeling`.

Why this shape, against the two failure modes of the pilot's ad hoc judge
(`/root/tmp/um-hard/lensread/analysis.txt`):

- *Over-literal rejection of faithful wording.* No lexicon decides. "I'm a general dentist in
  São Paulo", "an Aussie trying to keep the fires burning", "Wedding photographer",
  "Grieving and overwhelmed" are settled by a forced choice among the part's own options on the
  statement alone. The pilot's separate "does the quote name the target" classifier, framed
  against a list of rivals, called "I've been unemployed for 4 months" a neighbour; the blind
  MC asks a different and easier question. True quotes the exact verifier rejected (four
  draws among the pilot's s3d failures, e.g. ", hanging IV bags are my day-to-day grind. I'm a
  night-shift nurse, and") go to the near-verbatim rule and then the re-ask; §8.3 classifies
  whatever is still rejected by cause.
- *Acceptance of a topic.* The blind call is told the statement may be about the topic or
  someone else and must reject a value that appears only as a topic and a token list with no
  person token: `divorce | custody | lawyer | separation` and "a question about dividing
  assets in a divorce" are cannot-tell for `divorcing` (the critique's two constructed cases;
  both are test fixtures, §9.1).
- *Acceptance of a broader class or a neighbour.* The blind call cannot lean on the chat to
  fill the gap: "a nurse" among options where one is `school nurse` is cannot-tell by the
  prompt's explicit rule ("even if only one candidate belongs to that class");
  "vegan" for a pescatarian gold, "grief" for a numb gold are simply another option or none.
  A hedge ("fisherman, sea captain, or harbor pilot"), a negation and a third-party
  attribution are visible because the call sees the whole statement, not only the quoted part
  (the easy family needed `hedged_in_lines` for quotes cut before the alternatives).
- *Near-duplicate options* ("complete novice" vs "self-taught beginner": the expertise
  failures of the pilot's s3d and prompt-only arms) are a bank property: the expertise scale is now the closed four levels and V5
  refuses the rest.

### 3.5 Draw, part and item verdicts

Draw verdict (`draw_verdict`): `pass` iff, after at most two re-asks (one in the first design), the pick is the gold, no
gate fired, the basis is `inferred_characterization` (never `reply_plan` or `verbatim_echo`)
and the quote check returned the gold;
`api_fail` when the MC call or the quote check did not land; else `fail`. Draw label
(diagnostic): `gold:description`, `gold:echo_basis`, `gold:reply_plan`, `unverified:<gate>`, `distractor`,
`distractor:neighbour` (the pick is in `near_neighbours`), `cannot_tell`, `invalid`, `api_fail`.

Part verdict: `majority(draw_verdicts)` (the shared helper: more than half of ALL draws; a
failed draw never votes but counts in the half): `pass` / `fail`, or `api_fail` = undecided.
The part's shown draw is one on the winning side with the most common label.

Item verdict (tri-state `pass`): `False` if any part failed (an undecided sibling cannot
rescue it); `True` if every part passed; else `None` (no part failed and at least one is
undecided). Item states: `judged`; `no_readouts` (no cell: `False`, the whole-scope
denominator `user_modeling` uses); `empty_digest` (the digest reported nothing: `False`);
`unsummarized` (digest refused or collapsed: `None`, audit F3).

### 3.6 Prompts (verbatim; `prompts.py` `PROMPTS`, and the family README under "Judge prompts")

`CALL_VERSION = "umh-v1"`, `PROMPT_VERSION = "umh-v1"` (bank v1 adds no suffix; a later bank
v<N> stamps `+bank-v<N>` through `judge.instrument(raw)`, the easy family's rule); summary
results `umh-v1+maj3v` plus the digest tail (`majority_stamp(n)`; `draws=1` has no suffix).
`FLAT_TYPES = ("countries", "nationalities", "religions", "occupations", "emotions")`,
`MULTI_SELECT = False`. The stamp is bumped for any edit AFTER merge; the one revision §8
allows happens before the family is registered on main and keeps `umh-v1`. (Review r3 found
that rule too weak: three gate versions produced results under `umh-v1` before the merge, so
the stamp is `umh-v2` and the result stamp `umh-v2+bank-v2`. A gate never changes under a
stamp that already has results.)

Below, `readouts of a language model's internal activations` is `mc.READOUT_PHRASE`, `⁞` is
`mc.BULLET_MARK`, `{cannot}` renders `mc.CANNOT`; templates are rendered with `str.replace`,
the conversation last. No prompt names a tool (`tests/test_prompt_tool_names.py`).

`UMH_SYSTEM`

```
You decide which value of one attribute of a user, from a fixed list of candidates, is encoded in readouts of a language model's internal activations. Be strict: credit a candidate only when a readout states that value about the user. Judge only from the readouts' own content, never from what the conversation makes plausible. Output only the JSON verdict.
```

`UMH_USER` (native) and `UMH_USER_SUMMARY` share one template; `{description}` is
`NATIVE_DESCRIPTION` or `SUMMARY_DESCRIPTION`:

```
You are analyzing readouts of a language model's internal activations, taken while the model read the conversation below and before it replied. {description}

<user_turn>
{user_turn}
</user_turn>

<readout>
{readout}
</readout>

Which of these values of the user's {judge_label} do the readouts attribute to the user?

{options_block}

{rules}

{type_rule}

{token_note}

{basis}

{quote_rule}
```

`NATIVE_DESCRIPTION`

```
A readout is a free-text description or a ranked list of top vocabulary tokens. It may describe the conversation's topic, the task, the user, or unrelated material.
```

`SUMMARY_DESCRIPTION` (`{summary_note}` = `digest.summary_note(args, None, family=FAMILY)`)

```
The readout below is a digest of many readouts, across every read layer and token position. A readout is a free-text description or a ranked list of top vocabulary tokens. It may describe the conversation's topic, the task, the user, or unrelated material.

{summary_note}
```

`UMH_RULES` (`{rules}`)

```
A candidate counts only when BOTH hold:
1. The readout STATES the value. That means the value itself, a synonym, a translation, a demonym for a country ("Icelandic" for Iceland), a more specific value of the same attribute (a city or region inside the country), or a paraphrase that says the same thing in other words and is no less specific ("cuts keys and opens locked doors for a living" for locksmith). These never state a value:
- a broader class that also covers other values: "a tradesperson" does not state locksmith, "works with animals" does not state zookeeper, "from a Nordic country" does not state Iceland, "religious" does not state any one religion, "upset" does not state any one feeling. This holds even when only one candidate on the list belongs to that class.
- a neighbouring value: "blacksmith" does not state locksmith, "irked" does not state furious.
- a clue: words merely associated with a value, or a circumstance from which it has to be worked out, such as tools, places, foods, customs, tasks or symptoms ("a ring of uncut keys", "the reptile house", "geysers", "has to be home by nine"). An event counts only when it IS the value in other words ("was released on parole last month" states on parole), not when the value must be inferred from it.
2. The readout attributes the value to the USER, the person writing the messages. In readouts this is often "you", "I", "the user", or the persona whose biography or infobox is being written for them. A value attached to a topic, a third party, a character other than the user, or an example does not count ("advice for locksmiths", "her brother is a zookeeper", "a story about a man on parole").

In a list of top tokens, attribution cannot be read from syntax. There, a value counts only when a token that states the value shares ONE list with a token for a person or an identity ("I", "my", "you", "user", "she", "he", "person", "someone", "who", "biography", "profile", a word for a family member or a role). A list with no such token is about the conversation's subject and states nothing about the user. Which token states a value depends on the attribute:
- a place: the name of the country or region, or its demonym ("Iceland | my | live", "Icelandic | I | home");
- an occupation: the word for the person who does it ("locksmith | my | shop"), not the field, the tools or the subject matter ("locksmithing", "locks", "zoology", "reptiles");
- a religion or denomination: the word for an adherent ("Zoroastrian | I | family"), not the name of the religion or its practices ("Zoroastrianism | temple | prayer");
- a diet, a marital status, a life situation, a feeling or a level of expertise: the word as said of a person ("paroled", "parolee", "furious", "novice"), not the noun for the topic ("parole", "anger", "beginners | guide").
Tokens on one list may be read together, but two tokens are never assembled into a more specific value: "zookeeper | keeper | my | reptile" states zookeeper for the user, plus a topic; it does not state reptile keeper. Never combine a value word from one readout with a word about the user from another readout, another position or another layer. In a free-text readout, never combine them across two of its "- " bullets either (in a free-text sample, bullets are separated by ⁞). The value and its attribution to the user must be stated together in one list or in one bullet.

Never use the language or script a readout is written in as evidence. These readouts are often partly in Chinese for every user, so Chinese words or characters say nothing about the user's country, heritage or language. A personal name is never evidence of country, heritage or religion, even when the readout gives it as the user's own name.

The conversation is shown only so you can recognize when a readout merely repeats it: never pick a candidate because the conversation makes it plausible or because you could infer it yourself. If the readouts state several candidates of this attribute for the user and none clearly dominates, choose "{cannot}". If a readout names a value only as one of several alternatives ("a, b, or c", "e.g. a, b, c", "possibly a"), that singles out none of them. If no candidate is stated for the user, choose "{cannot}", except for a reply plan: when the only support for a candidate is what the assistant plans to do, follow the basis rule below (pick that candidate with basis "reply_plan").
```

`TYPE_RULE_FACT`

```
This attribute is a fact about who the user is or what their life is like at the moment. For a country of residence, a statement of where the user lives counts and so does a demonym, unless the same statement places the user's home somewhere else ("an Icelander living in Uruguay" states Uruguay as the residence). For a life situation, the readout must state the situation itself or the event that defines it, not one of its side effects or chores: "was released on parole last month" and "got out three weeks ago and reports to a parole officer" state on parole, "has to be home by nine" does not; "finished chemotherapy and was told the cancer is gone" states in remission, "has a scan every three months" does not. In a list of top tokens, a fact counts under the token rule above ("parole | released | my | officer" counts; "parole | hearing | board | law" does not).
```

`TYPE_RULE_STATE`

```
This attribute is how the user FEELS about what they describe: an emotional state, not a fact about their life and not the topic of the message. Credit a candidate only when a readout states that feeling as the user's own ("the user is furious", "I'm terrified", "you sound furious about it", "their fury at the landlord"). These do not count: a feeling attributed to someone else; an emotion named only as a topic ("an article about anger", "tips for managing fear"); a description of events with no feeling stated ("they shouted and slammed the door"); a broader or vaguer feeling that covers several candidates ("upset", "stressed", "struggling", "having a hard time", "negative emotions"). A neighbouring or weaker feeling states only itself: "irked" is not furious, "jumpy" is not terrified. A statement that gives the feeling to the user states it, even inside a plan for the reply: "acknowledge their anger" states that the user is angry, as "their fury at the landlord" states fury. A plan that names only the assistant's manner does not ("respond calmly", "be gentle"): that is a reply plan, not a statement of the user's feeling. In a list of top tokens, the adjective for the feeling counts under the token rule above ("furious | I | landlord | my"); the noun for the emotion as a topic does not ("anger | management | tips").
```

`TYPE_RULE_STATE_MIXED` (appended after `TYPE_RULE_STATE`, separated by a blank line, when the
item is `mixed_state`; the label shown is the plain "emotional state")

```
This user has more than one feeling in this message. Credit a candidate when a readout states it as the user's own feeling, whatever it is about. Another feeling of the user's that is not on this list is expected: it is no reason to choose "{cannot}", it does not make the readouts fit two candidates, and it never counts for this question.
```

`TYPE_RULE_STANCE`

```
This attribute is not a fact about the user's life. It is what the user wants from this exchange (their underlying goal in asking) or how they regard the thing they ask about (their attitude toward it). Credit a candidate only when a readout states it as the USER's own aim or stance: what they want, need, hope to hear, are looking for or are really asking for, or how they view the thing ("the user wants permission to skip it", "they are really asking to be told the deadline can slip", "I just need a quick fix", "you seem wary of the offer"). These do not count: the literal request restated ("asks which model to buy"); a description of the reply or of the assistant's manner that does not say the user wants it ("a gentle answer", "list the pros and cons", "be encouraging"); an aim or stance attributed to someone else; the topic of the message. A statement of what the assistant should do counts only when it presents that as what the user is after ("they want me to give them permission" counts; "I should give permission" alone does not). A list of top tokens cannot state an aim or a stance: if the only evidence is a token list, choose "{cannot}".
```

`GOAL_DEFINITIONS` (appended after `TYPE_RULE_STANCE`, separated by a blank line, for a part
of type `goal`; the twelve values of the goal pool, so the same block for every goal part)

```
What each goal means:
- reassurance: to be told that things are or will be all right, that a worry is unfounded or a mistake is not serious. It is about a fear or a doubt, not about a choice.
- validation: to be told that a decision they have already made, or a view they already hold, is right. It is about a choice or a view, not about a fear.
- ammunition for an argument: facts or points to use against someone they disagree with.
- a second opinion: an independent view to set beside one they already got from someone else.
- a chance to vent: to let out frustration; no solution is wanted.
- to be talked out of it: they lean toward doing something and hope to be dissuaded.
- an excuse to say no: a reason or justification for declining something they do not want to do.
- someone to decide for them: to be handed the choice outright instead of weighing it themselves.
- the safest option: the lowest-risk choice, ahead of the best or the cheapest.
- neutral information: plain facts, with no advice or comfort sought.
- step-by-step instructions: a procedure to follow.
- creative ideas: new suggestions or inspiration.
A readout that only says the user wants to hear it is fine, without saying whether that is about a worry or about a choice, states neither of the first two.
```

`TYPE_RULE_EXPERTISE`

```
This attribute is how skilled or knowledgeable the user is in the named subject, on a four-level scale: beginner (new to it, little or no experience), intermediate (past the basics, some experience, still learning), advanced (highly skilled or experienced, well beyond the basics, but not presented as a professional or an authority), expert (a professional, specialist, master or authority in it). Credit a level only when a readout states the user's own level in THIS subject ("new to archery", "an archery novice", "a professional archery coach"). A word that does not separate the levels ("experienced", "knowledgeable", "skilled", "keen", "an enthusiast", "an amateur") states none: choose "{cannot}" unless another statement in the readouts fixes the level. Jargon, the difficulty of the question and the tasks the user describes are clues, not statements. The level must be the user's: the pitch of the planned reply ("a simple step-by-step answer", "skip the basics") states a level only when the readout ties it to the user ("explain it simply because they are new to this"); otherwise it is a reply plan. In a list of top tokens, a level word counts under the token rule above ("novice | I | archery | my"); a level word for an audience or a resource does not ("beginners | guide | tutorial").
```

`UMH_BASIS` (`{basis}`)

```
Then set the basis, which decides whether a correct pick counts as a reading of the model's picture of the user:
- "inferred_characterization": a readout states the value about the user in words that go beyond the conversation's own. The conversation only implies the value; the readout says it.
- "verbatim_echo": the line your pick rests on only repeats or closely rewords what the user wrote, or restates the request, without stating the value. Copying the prompt is free and is not evidence that the model formed a view of the user.
- "reply_plan": the only support for a candidate is a statement of what the assistant will do or how it will answer ("I should be gentle", "give a simple step-by-step answer", "agree with their choice"), which does not give the value to the user. Pick the candidate the plan points at, quote the plan, and set this basis. It does not count as a reading of the user. A plan that does give the value to the user ("acknowledge their anger", "explain it simply because they are new to this", "they want me to agree") is not this case: it states the value, and its basis is one of the two above.
- "absent": you chose "{cannot}".

The conversation above is the full context the model saw. Set the basis from the readout line your pick rests on, and judge that line about THIS attribute only. When several lines attribute the picked value to the user and any one of them states it beyond the conversation's own words, the basis is "inferred_characterization" and your pick rests on that line: quote it, not an echoing line.
```

`UMH_QUOTE` (`{quote_rule}`)

```
In evidence, quote, character for character and from inside one token list or one bullet of one free-text readout (never across a ⁞), the span that states the value about the user (at most 200 characters; empty if you chose "{cannot}").
```

`TOKEN_NOTE_UMH` = `mc.token_note(FLAT_TYPES, multi_select=False)` (`{token_note}`; the shared
rule, rendered from the spec, as every MC family carries it).

`UMH_RETRY` (appended to the draw's own user turn; `{quote}` cut at 300 characters)

```

Your previous answer picked option {choice} ("{value}") with this evidence quote:
"{quote}"
That quote was rejected: {reason}. Answer again from the same readouts. If some readout statement states a candidate's value about the user, pick it and quote that statement character for character (from inside one token list or one bullet). Otherwise choose "{cannot}".
```

`UMH_RETRY_REASON_QUOTE`

```
it is not found in any readout line (a quote must be copied character for character from one line)
```

`UMH_RETRY_REASON_BULLET`

```
it runs across two bullets or two readouts; the value and the user must be stated together in one bullet or one list
```

`UMH_RETRY_REASON_ECHO`

```
it only repeats the user's own words from the conversation, which state no value
```

`UMH_QUOTE_SYSTEM` (the blind quote check)

```
You decide which value of one attribute of the person writing a message, from a fixed list of candidates, one quoted statement states about that person, if any. You see only that statement and must use nothing else. Be strict. Output only the JSON verdict.
```

`UMH_QUOTE_USER` (prose) and `UMH_QUOTE_USER_TOKENS` (token lists) share one template;
`{statement_kind}` is `QUOTE_KIND_PROSE` or `QUOTE_KIND_TOKENS`:

```
{statement_kind} The model was reading a message that a person wrote to an assistant. The statement may describe that person, the topic of the message, the task, the reply being planned, or someone else. The writer often appears as "the user", "you" or "I", and often as the subject of a biography, profile or infobox being drafted for them: a named persona ("Jane is a locksmith in Reykjavik") or a field ("Occupation: locksmith", "Residence: Iceland"). The subject of such a biography, profile or infobox IS the writer. The quoted part is the span that was offered as evidence.

<statement>
{statement}
</statement>

<quoted_part>
{quote}
</quoted_part>

Which of these values of the writer's {judge_label} does the quoted part state about the writer, read in its statement?

{options_block}

Pick a candidate only when the quoted part states that value about the writer: the value itself, a synonym, a translation, a demonym for a country, a more specific value of the same attribute, or a paraphrase that says the same thing in other words and is no less specific. Choose "{cannot}" in every other case, in particular when:
- it states only a broader class that also covers other values, even if only one candidate belongs to that class;
- it states a neighbouring value that is not the candidate;
- it fits two candidates equally well;
- the value appears only as a topic, a subject of the question or a kind of advice ("a question about parole conditions", "tips for new managers"), not as something the writer is, has or feels;
- the statement lists the value as one of several alternatives, negates it, or gives it to someone who is clearly a different person from the writer (the writer's sister, a colleague, a client, a character in a story they ask about). The subject of a biography, profile or infobox drafted for the writer is the writer, not a different person;
- the statement is a list of tokens with no token for a person or an identity ("I", "my", "you", "user", "she", "he", "person", "someone", "who", "biography", "profile", a family or role word);
- the statement is a list of tokens and the only matching token does not state the value: for a place, the country's or region's name or its demonym states it ("Iceland | my | live"); for an occupation, the word for the person ("locksmith"), not the field or subject ("locksmithing", "zoology", "reptiles"); for a religion, the word for an adherent ("Zoroastrian"), not the religion's name ("Zoroastrianism"); for a diet, a status, a life situation, a feeling or a level, the word as said of a person ("paroled", "furious", "novice"), not the topic noun ("parole", "anger"). Two tokens are never assembled into a more specific value ("zookeeper | keeper | my | reptile" states zookeeper, not reptile keeper);
- it says only what the assistant will do or how it will answer, without giving the value to the writer ("respond calmly" states nothing about the writer; "acknowledge their anger" states that the writer is angry);
- it gives only a clue: a circumstance, tool, place or task from which the value has to be worked out. An event counts only when it is the value in other words.

{type_rule_quote}
```

`QUOTE_KIND_PROSE`

```
The statement below is one line taken from readouts of a language model's internal activations.
```

`QUOTE_KIND_TOKENS`

```
The statement below is one ranked list of top vocabulary tokens (" | " separated) taken from readouts of a language model's internal activations; tokens of the list may be read together.
```

`QUOTE_RULE_FACT`

```
A place the writer lives in, or a demonym, states a country of residence. A life situation must be stated itself or through the event that defines it ("got out three weeks ago and reports to a parole officer" states on parole), not through a side effect of it ("has to be home by nine").
```

`QUOTE_RULE_STATE`

```
The value is a feeling of the writer's own. A vaguer feeling ("upset", "stressed", "struggling") or a weaker neighbouring one states none of the candidates. A description of events with no feeling stated is a clue.
```

`QUOTE_RULE_STATE_MIXED` (appended, separated by a blank line, for a part of a mixed-state item)

```
The writer may have more than one feeling. A feeling in the statement that is not on the list is expected: ignore it. It does not make the statement fit two candidates.
```

`QUOTE_RULE_STANCE`

```
The value is what the writer wants from the exchange, or how they regard the thing they ask about. The statement must say that the writer wants, needs, seeks or holds it; a description of a reply or of an assistant's manner states none. A list of tokens cannot state an aim or a stance: choose "{cannot}".
```

For a `goal` part `GOAL_DEFINITIONS` (above, the same block) follows `QUOTE_RULE_STANCE`.

`QUOTE_RULE_EXPERTISE`

```
The value is the person's level in the subject: beginner (new to it), intermediate (past the basics, still learning), advanced (highly skilled, not a professional or an authority), expert (a professional, specialist, master or authority). "Experienced", "knowledgeable", "skilled", "keen" or "an amateur" alone state none. The level must be the writer's: the pitch of a planned reply ("a simple step-by-step answer", "skip the basics") states a level only when the statement ties it to the writer ("explain it simply because they are new to this").
```

Schema `umh_quote`: `choice` (integer), `rationale` (string).

`UMH_TASK_NOTE`: §3.1. `PROMPTS` holds every block above plus `SUMMARY_NOTE`,
`SUMMARY_NOTE_ABSTRACTIVE` (from `digest`), `TOKEN_NOTE_UMH` and `CANNOT`, as the easy family's
does.

The examples inside the rules (locksmith, blacksmith, zookeeper, Iceland, Uruguay, furious,
terrified, irked, jumpy, parole, remission, archery, permission, a quick fix, wary, new managers, Zoroastrian, Reykjavik,
Jane, keeper, reptile keeper, zoology, reptiles, uncut) are checked against
the bank and the pools: none is a gold, an option, a pool value, a form or an expertise domain,
so no item is primed by them. The exceptions are deliberate: the four level words of the closed
expertise scale, "novice" / "professional" (forms of beginner / expert in the bank), the
twelve goal values in `GOAL_DEFINITIONS`. A test pins the list (`test_prompt_examples_are_not_bank_values`).

### 3.7 Native mode and one diagnostic

Native (`opts=aggregate=native`): one MC call per (item, part, cell, sample) for prose, per
(item, part, cell) for a token list (`family.render_bag`), keys `f"{c.key}:s{j}|p{k}"`, no
draws, the same verification (re-ask and quote check included) through the same helper
(`judge.judge_units`). A part passes natively when ANY of its units passes, fails when every
unit is decided and none passes, and is undecided otherwise. Native is the instrument of the
ATI panel (one cell per item) and of the toy examples; on a full every-token read it is about
0.3M calls per sample and is not run.

Diagnostic `extras["digest_loss"]` (summary mode, mechanical, never gating): parts whose gold
or a form occurs in a raw prose sample or token list of the item (`mc.form_in`) but in none of
the digest's evidence lines, as a count and a share of parts. Loose forms make this an upper
bound on what the digest dropped; it is what §8.4 reads.

## 4. Scoring

### 4.1 Headline

`pass_rate` = the share of DECIDED items whose every part passed; `ci95` = `bootstrap_ci` over
the item indicators; undecided items leave the denominator and are counted
(`n_items_undecided`, `undecided_ids`; the shared rule marks a row with more than 20%
undecided not measurable). Built with `family.pass_rate_result` (rows carry `pass`), then
`result.chance` / `chance_label` set.

Chance: the uniform single-draw chance of the all-parts rule, per item the product over its
parts of 1 / (content options), averaged over the scope. On the bank 0.0976 (the first build; 0.1094 on bank v2, which has no `life` kind): `life`, `fine`,
`stance` 0.143, `expertise` 0.25, `state` 0.101 (single 1/7, mixed 1/49), `two` 0.021, `three`
0.003. That is `result.chance`.

Per kind the reported chance is `max(uniform, constant)` (ruling 7; second review, D), where
`constant` is the expected share of the kind's items a constant guesser gets with every part
right: for a part type with AT LEAST 5 PARTS IN THE KIND it answers that type's most common
gold; for a smaller type it guesses uniformly (a type of one or two parts has no meaningful
"most common" value). On the frozen bank:

| kind | uniform | constant guesser | reported chance |
|---|---|---|---|
| two | 0.021 | 0.004 | 0.021 |
| three | 0.003 | 0 | 0.003 |
| life | 0.143 | 0.077 | 0.143 |
| state | 0.101 | 0.024 | 0.101 |
| expertise | 0.250 | 0.375 | 0.375 |
| stance | 0.143 | 0.235 | 0.235 |
| fine | 0.143 | 0.143 | 0.143 |

`by_kind[k]` carries `chance_uniform`, `chance_constant`, `chance`. The leakage standard of
§6.2 is ONE-SIDED and applied to MEASURED guessers per kind: a guesser must score at most
this column + 0.05 (a guesser below chance is no leak). `chance_label`: "uniform forced guess per part (1/7; expertise 1/4; marital
status 1/6), every part of the item right; mean over items. A multi-part item's chance is the
product over its parts." It matches `lucky_guessing.analytic_floor` for the builder of §6.2
(a test holds them equal).

### 4.2 Rows: one per item, with a `parts` list

`fast.units` (default path), `results.decided_outcomes`, the ATI adapter's default branch and
`family.pass_rate_result` all read ONE row per item with an `id` and a tri-state `pass`; a row
per part would need a new special case in each. So, in both modes, one row for EVERY scope
item (items with no readouts included, or the fast rescore's "the value recomputed over all
units reproduces the family's own" check would fail):

```
{"id", "key", "kind", "request_variant", "state", "pass", "n_parts", "n_parts_passed",
 "n_parts_undecided", "parts": [ … ], **col.row(id)}
```

and per part

```
{"part": k, "type", "attr_label", "options", "gold_position", "pass", "majority",
 "draw_verdicts", "draw_labels", "label_split",
 "choice", "pick", "pick_raw", "pick_value", "basis", "evidence", "statement", "near_quote",
 "gate", "credit", "quote_check_choice", "rationale", "retry_of"}
```

(the scalar fields are the shown draw's; natively `draw_*` are replaced by `n_units`,
`n_units_passed` and the first passing unit's `layer` / `pos` / `sample_idx`).

### 4.3 Extras

- `by_kind`: per kind `{n_items, n_decided, pass_rate, chance_uniform, chance_constant, chance}`.
- `reply_plan`: per rule group, the parts whose majority outcome was a gold pick with basis
  `reply_plan`, and the draw-level count. `broader_suspect`: the flagged passing parts.
- `per_n_parts`: the same for items of 1, 2 and 3 parts.
- `parts_passed`: for 2-part and 3-part items, the counts `{all, some, none, undecided}`
  (`some` = at least one part passed and at least one failed).
- `part_pass_rate` (decided parts passed / decided parts) and `by_type` (per part type
  `{n_parts, n_decided, pass_rate}`), `by_rule` (the four rule groups FACT / STATE / STANCE /
  EXPERTISE), `by_request_variant`, `mixed_state` (`{n_items, pass_rate, both, one, none}`).
- Judge accounting at draw level: `picks` (gold / distractor / distractor_neighbour /
  cannot_tell / invalid / unverified), `unverified_by_gate` (quote / bullet / echo /
  desc_rejected), `unverified_gold_by_gate`, `n_retried`, `n_near_quotes`, `n_quote_checks`,
  `echo_basis_gold`, `reply_plan_gold`, `label_split_parts`, `unanimous_parts`.
- `digest_loss` (§3.7), `summary` (`col.extras()`), `n_api_failed`, `draws`, `seed` (none: the
  option order is frozen in the bank; `config.options = "bank order"`).

`counts` keeps the fixed key set (`base_counts`): `n_expected` = cells, `n_unjudged` =
unsummarized items + items left undecided by failed calls (natively, review r1 F6: the
undecided items plus the non-empty cells of decided items where no unit landed), `n_empty` = empty digests,
`completeness(…, n_items=len(scope))`, `pinned=digest.pinned(args, FAMILY)`.

### 4.3b Which kinds are in the headline (pre-registered)

The headline is the pass rate over the bank's items, and the bank holds exactly the kinds that
passed validation (§8.3). A kind that fails it is not masked at scoring time: the builder
(`--outside-headline <kind>`) writes that kind's items to
`evals/association/user_modeling_hard/items_outside_headline.json` (same schema, its own
header) and leaves them out of `items.json`. They stay judgeable with the same instrument
(`WSB_BANK_FILE_USER_MODELING_HARD=…/items_outside_headline.json`, which stamps the file
through the usual pin rules), their numbers are reported in the family README beside the
headline, and no code path special-cases a kind. This is how ruling 9 (stance counts only if
stance passes validation on its own) and ruling 13 (a kind whose judge error stays above 10%
leaves the headline) are implemented. The decision is taken once, before the bank is
registered; after merge it would be a bank v2.

### 4.4 Stamps in `config`

`prompt_version` = `digest.prompt_version(instrument(raw) + majority_stamp(n), args, FAMILY)`,
`draws`, `**digest.config(args, source_kind, FAMILY)`, `aggregate`.

### 4.5 Making the per-part breakdown visible

`score.py` also writes `extras["breakdown_md"]`, a ready markdown block:

```
| kind | n | pass rate | all parts | some | none |
| two | 36 | … | … | … | … |
…
| part type | parts | pass rate |
| profession | 51 | … |
…
```

`wsbench report` (and the `summary.md` it and `run` write) appends, after everything it prints
today, a section `## breakdowns` with one `### <family>` block per row whose extras hold
`breakdown_md`, in row order. **A results directory in which no row has that key produces
byte-identical output; `results.markdown_table` and the macro rows are not touched.** `report
json=True` already carries extras. This is the only change outside add-only tables; if the
critique finds it risky, the fallback is the family README pointing at
`results.json: extras.by_kind / by_type / parts_passed` and nothing in `cli.py`.

## 5. Read plan

- Render `chat_context` of `messages`, positions `{"kind": "all"}` (every token: system turn,
  user turn, assistant header, empty think block), layers `GRID` (20, 24, …, 60), as
  `user_modeling`. `reads=lite` = the same positions at the same layers (`lite_positions`
  `same`, `lite_layers` None), so lite differs from full only by its stamp.
- `min_full_positions` = the token count of the bank's shortest render, `full_contiguous=True`.
  The builder computes it with the subject's tokenizer through the bench's own render
  (`wsbench.produce.render`, tokenizer only, no weights; needs the `gpu` extra) and writes it
  to the header as `min_render_tokens`; `__init__.py` carries the same literal and a test holds
  them equal. The pilot bank's renders ran 82 to 129 tokens (mean 101); the full bank's
  shortest user turn is 276 characters, so expect about 80. Without the tokenizer the builder
  leaves the key absent and the loader refuses the bank, so the number cannot be guessed.
- Size: about 168 x 105 x 11 ≈ 194k cells per 11-layer arm (the first build; about 128k for bank v2's 111 items) (the easy family: 93k). The fast
  subset reads half.

## 6. Floors and gates

### 6.1 Prompt-only (expected high)

`po-opus-v1` with the Sonnet 5.5 fallback, one Opus readout per item, judged by this
instrument, frozen into `evals/baselines/prompt_only_summary.json` by the usual `baseline` /
`freeze`. Expect a high floor: the pilot gave 0.96 on its gated items (75 of 78),
with every two-trait item passing, and the easy family's floor is 0.825. The README must say
what that means in the words the easy family's README uses: this family separates lenses from
each other and from token lenses, not a lens from a reader of the text. It is not added to
`prompt_only.SATURATED` unless the measured floor is at the ceiling and the owner asks.

### 6.2 Lucky guessers

Builder `_user_modeling_hard`: `Item(name, [part options…], [gold positions…],
meta={"kind", "types", "labels"})`. `score_draw` already requires every list right, so the
guessers are scored under the all-parts rule and `family_chance` is the analytic product.
`DESCRIPTIONS["user_modeling_hard"]`: "which characteristics of the person it is talking to
(who they are, how they feel, what they want) a model represents while reading their message
(one list per characteristic)". `GUESS_QUESTION["user_modeling_hard"]`: the labels, one per
list ("list 1: the user's occupation; list 2: the user's country of residence"), which makes
the `question` variant the label-plus-options guesser the authoring run used.
(Review r1 F4: that needs the family's own system text as well,
`lucky_guessing.SYSTEM_QUESTION_BY_FAMILY["user_modeling_hard"]` = `SYSTEM_QUESTION_UMH`: the
shared `SYSTEM_QUESTION` is moral_rationale's "a question that a language model answered with
one word ... which consideration the model actually weighed". The two older hooked families'
calls are pinned byte-identical by `test_the_other_question_guessers_calls_did_not_move`.)
Variants to measure and freeze: blind, described, question, uniform (5 draws, T = 1.0).
Expected from the run: per part type 0.11-0.28 against 0.143 (0.25 for expertise), i.e. item
level near 0.10. **The leakage standard is applied per kind, not only per family** (ruling 7;
the critique showed the family-level check passes at 0.087 while expertise sat at 0.47): each
measured guesser (blind, described, question), scored on a kind's items under the all-parts
rule, must score at most that kind's reported chance + 0.05 (§4.1; one-sided). After the
rebalance the expertise bar is 0.375 + 0.05, the stance bar 0.235 + 0.05, the others uniform +
0.05; a kind that misses is named in the README with its numbers, and the
owner decides whether it stays in the headline (§4.3b gives the mechanism). The 8 redrawn goal
lists are guessed again in the build's own validation (§2.4), before this floor is measured. Per-type guesser rates are not in
`lucky_guessing.aggregate`; `scripts/umh_report.py guess <run dir>` computes them from the
run's per-item `picks` (the same script prints §8's tables).

### 6.3 Logit-lens L63

Needs GPU reads: the `logit_lens` method at layer 63 (`tokens10`), judged with `layers=63`,
frozen into `evals/baselines/logit_lens.json`. Done in §8 with the lens arms. Until it is
frozen the report draws no logit-lens cell for the family.

### 6.4 ATI

`NOT_GATED["user_modeling_hard"]`: "new family (plan 0106): no panel run yet; the prompt-only
reader is expected to solve most items, so few would survive". Under
`anti_text_inversion=True` the family is then skipped (`NotInScope`), and the frozen
strict-ATI macro (`ati-subset-v2`, eight families) is unchanged.

A panel run would take: `wsbench text-inversion stage=build families=user_modeling_hard`
(168 prompts); four readers x 3 draws = 2,016 answers (Qwen3.6-27B on Modal GPU, Opus 5.5 by
SDK, astra through openai-wif and argon through gemini-wif on Modal); `scripts/
ati_panel_judge.sh` judging each answer natively (one cell per item: 265 part calls per reader
draw, about 3.2k MC calls plus quote checks); `stage=gate`. An item survives iff every reader
fails every draw, read on the row's `pass`. Given §6.1, fewer than 20 survivors are likely,
which would show the family and keep it out of the strict macro. Recommended: not now.

### 6.5 Capable questions

`_user_modeling_hard`: one `Question` per PART, id `<name>#p<k>`, the bank's own label gate
(with the GATED label `attr_label`, ordinal labels included: this question is asked with the
chat): the turns, then "Based on that conversation, what is the user's {attr_label}? Answer in one
word or short phrase.", golds `[gold, *forms]`, reference `gate.n_correct / gate.n_samples`,
`meta={"item": name, "kind", "type"}`. AGENTS.md's table gets the row "every part named when
asked (greedy and at least 8/10), and volunteered in an open description".

### 6.6 Adapt tooling: out of scope, skipped cleanly

Adapted sets (`adapted/<m>/`) do not get this family: its items were selected on Qwen3.6-27B's
own label gate and open probe, and re-gating and refilling a multi-part bank for another
subject is its own plan. Every `all`-style path must skip it, not fail:

- `adapt/families.py`: `NOT_ADAPTED = {"user_modeling_hard": "selected on Qwen3.6-27B's own
  gates (plan 0106); no adapted set carries it"}`; `get(name)` reports that reason
  (`REGENERATE.get(name) or NOT_ADAPTED.get(name, "unknown family")`). `FAMILIES` and
  `REGENERATE` are not edited.
- `adapt/judge_inputs.py`: `uncovered_families()` returns the registered families minus
  `FAMILIES` minus `NOT_ADAPTED` (lazy import). No `FamilyInputs` entry is written, so
  `docs/adapt_judge_inputs.md` does not change and no derived table (`REQUIRED_ITEM_PATHS`,
  `SUBJECT_FIELDS`, …) gains a key.
- Already clean, verified in code, covered by one new test: under `WSB_BANK_ROOT`,
  `readplan.families()` lists only the families the root has, and `cli` (`plan`, `run`, lines
  471, 1289-1310) and `adapt/floors.py:80` take their family list from it, so a core or full
  run of an adapted set neither plans, floors nor judges the family; `registry.bank_path`
  would exit for it under a root, and nothing reaches it.
- `scripts/adapt_set.sh` lists (`PROFILE_FAMS`, `FILL_FAMS`, `FREEZE_FAMS`) do not name it.
- Skill docs: the scope sentence and `references/families.md` (§1.3).

## 7. Tiers, fast, ledger, docs

### 7.1 Core

`tiers.CORE` gains `"user_modeling_hard"`: 19 families (18 after #520). `tiers.check()` holds
(registered, in `full`, in the macro). `full` is 32 families (`registry.FAMILIES` 33 with the
superseded `typo_st`). `user_modeling` stays out of `CORE`. A results directory judged before
this plan reports the new family as `missing` in the core-macro line, the existing behaviour
for an absent core row.

### 7.2 Fast: `fast-v5`, cut in this PR, before the ledger entry

`scripts/fast_cut_core_half.py --version fast-v5 --seed 20261121` (0104's script and seed),
with one `UNITS` entry for the family: `_by_item` (unit = plan row, read rows = itself) with
stratum = the bank's `kind` ("kind"). The family has no strict-ATI unit, so it contributes
`ceil(168 / 2)` = 84 items, split over the seven kinds in proportion to their sizes by
largest remainder, ties to the kind that sorts first (17.5 / 12 / 13 / 20.5 / 8 / 7 / 6
exact: two 17, three 12, life 13, state 21, expertise 8, stance 7, fine 6; the numbers move
with any item dropped in validation). Positions: full.

0104's draw key is `f"{seed}|{registry.frozen_name(family)}"`, with no version in it (tip
092f1b66). So **fast-v5 leaves every other family's entry (`bank_sha`, `units`, `read_ids`)
and `cut` row byte-identical to fast-v4's**: their fast-v4 results and FAST readouts stay valid
under fast-v5 (`fast.compatible`, `fast.same_reads`), and the fast macro simply gains one row.
fast-v5 = 17 families, 1,203 + 84 = 1,287 units, 1,441 + 84 = 1,525 read items.

What changes: `fast.VERSIONS` and `KEY_ERA` gain `fast-v5` ("0101"), `fast.DEFAULT =
"fast-v5"`, `VARIANTS = {"": DEFAULT}`; `evals/fast/fast_v5.json`; `evals/fast/README.md` and
README §Fast subset; the pins `tests/test_fast_core_half.py` names, plus one assertion that
the 16 shared entries of fast-v4 and fast-v5 are equal. **`fast_v4.json` and every older file
stay frozen and sha-pinned.**

The cut is not optional and not droppable (critique 11): it is made in this PR, after the
bank is final and BEFORE the ledger entry is declared, so the entry hashes a manifest that
already has the family's fast-v5 row. `association_hard` and the chain_intermediates refill
will cut fast-v6 and later on their own; §7.4's change to the declare script is what keeps
those later cuts from staling this family's entry.

### 7.3 `wsbench list`, README, viewer

- `wsbench list`: automatic (`association`, tier `full` until the family joins core after its
  validation, `pass_rate`, default judge, `umh-v2`; the first build planned `core`, 168 items,
  `umh-v1`).
- README §The evals, under Association, between the two existing entries:

  **User modelling (hard)** — [`evals/association/user_modeling_hard/README.md`](evals/association/user_modeling_hard/README.md) `core`
  - *What it is:* A chat implies one to three things about its user without stating any: who
    they are (occupation, country, religion, a life situation, down to "school nurse"), how they
    feel about what they describe, how much they know about a subject, or what they want from
    the reply. Does the lens state each of them about the USER, at any token of the chat render?
    168 items, 265 traits, every trait one Qwen3.6-27B names when asked and volunteers when
    asked to describe the user.
  - *Example:* a message about sangeet shoots, RAW batches and GST filing → `photographer` and
    `India`; both must be surfaced ("a wedding photographer in India" counts; "cameras",
    "Lightroom", "someone in a creative job" do not).
  - *Judged by:* one identification MC per trait over that trait's own distractors (gold, a
    near neighbour, decoys; 7 options, 4 for the expertise scale) + cannot tell, three draws
    with majority; a gold pick counts only with a verified quote in one statement that is not
    the user's own words and that a second, blind reading of the statement (alone in the first
    build; inside its own readout line since review r2) also assigns
    to the gold as something said about the writer; an item passes iff every trait passes.
    A reply plan ("be reassuring") is not a pass. A token-level lens can score facts, states and
    expertise (a value token beside a person token in one list), never a goal or attitude.
    Per-kind and per-trait rates are reported beside the headline.

  (Wrap as three single lines; `tests/test_readme.py` wants exactly three `- *…:*` lines.)
- README §Judges row: `| user_modeling_hard | claude-opus-5-5 | umh-v1 (bank v1: 168 items,
  265 parts; per part an identification MC in three draws, `+maj3v`; verification by quote,
  statement, echo gate and a blind quote check; item = all parts) |`.
- README tables that name categories: written with whichever name the `precision` category
  has on main at merge time (`jlens_comparison` if PR #521 is in); nothing else of #521 touches
  this family.
- README §Tiers: the table's counts, the core list, and the sentence "A hard user_modeling
  bank … will join it" replaced by "`user_modeling_hard` is core; the easy `user_modeling` bank
  is in full only".
- Viewer: the `GROUPS` entry of §1.3; the generic item view shows `messages`, `target`,
  `subfamily` and the raw `parts`.

### 7.4 Ledger

A new family needs a ledger entry (T1: "a new family needs one too"; `shared.n_families` must
be the golden's count plus the new families). After everything the manifest hashes for the
family is final (bank, pools, prompts, examples, table entries, tier) and fast-v5 is cut:

```
python scripts/manifest_0101_declare.py user_modeling_hard --plan 0106 \
  --note 'new family: multi-trait user modelling, umh-v1 on bank v1 (<n> items, <m> parts)' --write
python scripts/manifest_0101.py --check tests/golden/manifest_0101_pre.json   # as T1 runs it
```

**A later fast cut must not stale a new family's entry (ruling 11; verified in the code).**
`verdict` and `declare` set fast rows aside only inside `if g is not None` (`new_fast_rows`
compares with the golden's rows), so for a family the golden does not have, every
`plan.fast_plan_sha` row is inside `rows_sha256`: the first fast version cut after its
declaration (fast-v6, for `association_hard`) would fail T1 for `user_modeling_hard`, and
`declare` would refuse to re-hash without a stamp or bank bump. The fix, in
`scripts/manifest_0101_declare.py`:

```python
def without_fast(c):
    """A family the golden does not have: its `plan.fast_plan_sha` rows are left out of what
    is compared and hashed. Its fast entries are pinned elsewhere (each frozen fast file by its
    own sha test; its full plan by the `plan_sha` row, which stays in)."""
    sec, key = FAST_ROWS
    if not isinstance(c.get(sec), Mapping) or key not in c[sec]:
        return dict(c)
    return {**c, sec: {k: v for k, v in c[sec].items() if k != key}}
```

called at the two places the entry is prepared: in `verdict`, `if g is None: c =
without_fast(c)` right after `c` is read, and the same line in `declare`. Nothing changes for
a family the golden has (the branch is `g is None` only), so no existing ledger entry
(`conjunctive_association`, `nyt_connections`) and no existing verdict moves; a test asserts
their `rows_sha256` are what the ledger file holds before and after.

Rebase onto #520: 0104 rewrites exactly these two reads as `c = untiered(g, cf[fam])` and
`c = untiered(g, current["families"][family])`, and `untiered` returns `c` unchanged for
`g is None`. This plan's edit is one line after each (`if g is None: c = without_fast(c)`)
plus the helper beside `untiered`; written on top of #520 it is conflict-free, and if this
lands first, #520's rebase keeps both lines. (Tier rows of a new family are still hashed:
moving THIS family in or out of core later needs a new declaration, which is acceptable.)

Synthetic test (`tests/test_rename_machinery_0101.py`, new function): a golden with two
families, a current manifest with a third, declared; then a fast row for a later version is
added to the third family's `plan.fast_plan_sha`: `verdict` still passes and `declare` raises
"already declared in this state"; the same added row on a GOLDEN family still follows
`new_fast_rows` (fails unless it equals a golden version's row).

The entry's `rows_sha256` covers the rest of the family's manifest row, so any later edit before
merge (a prompt word, a toy row) needs the entry removed by hand and declared again; after
merge it needs a stamp or bank bump like every family. `scripts/manifest_0101.py` is not
edited (its sha is pinned): it iterates the registry, and the new family satisfies what it asks
of every family (a `prompts` module, an example file with bank ids, at least one LLM call in
BOTH modes of the offline run, which is why native mode is implemented and not refused).
No other family's row moves and no other ledger entry is touched.

## 8. Validation before merge

Local first: the branch is not pushed until this section passes.

### 8.1 Reads (GPU)

Arms, full bank, 11 grid layers, bundle sampling as each arm's production config:
`s3d-rl600`, `rl-affw-x4`, `mlnla11-rl600` (prose), `jlens-public` (tokens), plus
`logitlens-L63` (the floor, layer 63). Producer: the production Modal stream runner the pilot
used (`wsb_stream_run.py --arm <arm> --bench <this worktree> --families user_modeling_hard
--no-judge`), sidecars declaring the plan's `plan_sha`.

Run in one named tmux session with a timestamped log, arms in sequence in the same session
(`tmux new -s umh-reads '… 2>&1 | tee logs/umh_reads_<stamp>.log'`), outputs under
`/root/tmp/um-hard/val/` (local disk, rsync to durable storage after). The pilot read 105 items
(116,864 cells) in 30 minutes of wall time per prose arm; the full bank is about 1.75 times
that. Measure GPU-hours on the first arm and check them against the Modal cap before the other
three start.

### 8.2 Judging

`wsbench judge family=user_modeling_hard readouts=… out=…` per arm with the registered judge
and digest settings (no overrides), `summ_store` shared across arms' out dirs is not needed
(different readouts). Prompt-only arm: `wsbench baseline kind=prompt_only_opus stage=build|ask|
readouts` for this family, then the fallback stages, judged the same way. Lucky guessers:
`wsbench baseline` for the four variants. One arm (`s3d-rl600`) is judged a second time into a
fresh out dir with the digests reused (`summ_store`) to measure judge run-to-run noise.

Calls per 11-layer arm: digests 168 x 11 = 1,848 plus 168 stage-2 = 2,016; MC 795; re-asks
about 10% (≈ 80); quote checks one per gold-pick draw that verifies with an inferred basis
(≤ 795, expect 300-600 for a trained lens, few for a token lens). About 1.2-1.5k judge calls
and 2.0k digest calls; hard ceiling 795 x 3 = 2,385 judge calls. Prompt-only: 168 digests and
the same judge calls.

### 8.3 Hand read: the judge's error rates (pre-registered)

Unit: a PART verdict (pass or fail of one part of one item under one arm). Undecided parts are
not read.

**What is read.** "The two strongest lenses" = the two prose arms with the highest headline
in §8.2 (expected `s3d-rl600` and `rl-affw-x4`).

- For those two arms, IN FULL: every part verdict of the `stance` items (14 parts each), of
  the expertise parts (18), and of the mixed-state parts (28): 60 per arm, 120 in all. These
  are the three places the rules are newest and the counts too small to sample.
- For each other group, `two`, `three`, `life`, single `state`, `fine`: at least 100 part
  verdicts, pooled over the two strongest lenses and `jlens-public`, drawn with a recorded
  seed BEFORE any verdict is looked at, stratified by arm and by the judge's verdict in the
  population's own proportions where the stratum allows and with a floor of 20 passes and 20
  fails per group. (`fine` has 12 parts per arm: all 36 are read and the group is reported
  with its interval, not held to the 100.)
- Every passing part flagged `broader_suspect`, every draw gated `desc_rejected` or `echo`
  (up to 40 per arm), and every part whose majority outcome is `gold:reply_plan`.
- The prompt-only arm: every failing part, and 40 passing parts.
- **30 verdicts set aside for the owner**: drawn by the same seed from the sample above,
  15 passes and 15 fails, spread over the seven kinds and including at least 5 stance, 5
  expertise and 5 mixed-state parts; delivered as one file (chat, the digest's evidence
  lines, the part, its options, the gold, the judge's quote and statement; verdict hidden
  until she has written hers). Both other labellers are the judge's model family, so her 30
  are the only independent read; they are reported as their own row and any disagreement with
  the agreed hand label is listed.

**Labelling.** Each part verdict is labelled right or wrong from the chat, the digest's
evidence lines, the part, its options and the gold: by the main session, and independently by
a fresh-context subagent given the same material WITHOUT the judge's verdict. The hand label
is their agreement; disagreements are listed and settled by the owner or left out of the
rates, with the count stated.

Error classes: false pass (topic only, broader class, neighbour, clue, echo, wrong person,
hedge, reply plan credited) and false fail (digest loss, quote gate on a true quote, a
faithful statement refused by the quote check, cannot-tell on a clear statement, an ambiguous
option list, a token list refused although it has a value token and a person token).

**What is reported.** Per arm and pooled: P(wrong | judge pass) and P(wrong | judge fail),
each with a Wilson interval, and the population error rate reweighted to that arm's own
pass / fail mix: `P(wrong) = P(wrong | pass) · share_pass + P(wrong | fail) · share_fail`,
with the shares taken from all of that arm's decided part verdicts, not from the sample (the
sample is stratified, so its raw error share is not a population rate). The same three
numbers per kind / group, per rule group, and per error class.

**Rules, fixed now.**

1. Target: pooled reweighted P(wrong) under 5%, and no kind / group above 10%.
2. One prompt revision is allowed. If rule 1 is missed anywhere: one targeted change to the
   prompts or gates, every arm re-judged (reads reused; digests cached unless the task note
   changed), and the affected groups re-read on a FRESH sample by the same procedure (groups
   read in full are re-read in full). Both rounds are reported.
3. A kind whose reweighted error is still above 10% after the revision LEAVES THE HEADLINE:
   its items go to `items_outside_headline.json` (§4.3b) and its numbers are reported
   separately. This does not stop the merge.
4. Stance (ruling 9) is in the headline only if the stance group meets the 10% bar ON ITS
   OWN, read in full on the two strongest lenses; otherwise rule 3 applies to it. The two
   `attitude` parts are judged and counted with the goals under STANCE.
5. Only a POOLED miss after the revision (reweighted P(wrong) at or above 5% over the kinds
   that remain in the headline) stops the merge and goes to the owner. No second revision
   without her decision.

### 8.4 Numbers to report (in the PR text and the family README)

| number | expectation (not a gate unless marked) |
|---|---|
| prompt-only pass rate, CI | high: about 0.85-0.95 (pilot 0.96) |
| `s3d-rl600`, `rl-affw-x4`, `mlnla11-rl600` | below the prompt-only arm; pilot s3d 0.72 |
| `jlens-public` | at or below the pilot's strict 0.21 (the topic test is back in the quote check, §3.3) |
| logit-lens L63 | near the floor |
| lucky blind / described / question, family level vs uniform 0.0976 (first build; 0.1094 on bank v2) and PER KIND vs the kind's reported chance (§4.1) | GATE per kind, one-sided: at most that chance + 0.05; a kind that misses is named and goes to the owner (§6.2) |
| token arm (`jlens-public`, logit-lens) by rule group: FACT / STATE / EXPERTISE / STANCE | STANCE 0 by rule; the headline of a token arm is read through this row |
| `reply_plan` per arm and rule group; `broader_suspect` | report |
| per kind, per part type, `per_n_parts`, `parts_passed` for every arm | the breakdown the owner asked for |
| undecided share per arm | GATE: under 5%, no arm "not measurable" |
| judge error, P(wrong / pass), P(wrong / fail), reweighted P(wrong), per arm, per kind (§8.3) | GATE: pooled reweighted under 5%; a kind above 10% leaves the headline |
| the owner's 30 verdicts against the agreed hand label | report |
| judge noise: item flips between the two judgings of s3d; `unanimous_parts` | report; expect flips under 5% of items |
| `digest_loss` per arm | if over 5% of parts for a prose arm, re-run that arm with `summ_max=25` and report both; the larger setting becomes the family default only with the owner's OK (it is a digest-fingerprint change, free before merge) |
| quote-check accounting: `n_quote_checks`, `desc_rejected` share, `n_near_quotes`, `n_retried` | report |
| gold-position histogram of the frozen option order | roughly uniform per n |

After the gates pass, in this order: settle which items and kinds are in `items.json` (§4.3b)
and only then pin the bank's sha256 in the tests; freeze the prompt-only, lucky and logit-lens
floors; cut fast-v5; declare the ledger entry; run the full suite; push (§10.1).

## 9. Tests

### 9.1 New (offline; `run_calls` of the family's `judge` module monkeypatched with a scripted judge, digests through `tests/summary_fakes.FakeLLM`)

`tests/test_user_modeling_hard.py`

- registration: category, tier `core`, bank path, stamp `umh-v1`, `min_full_positions` equals
  the header; `test_easy_family_is_untouched` (§1.2).
- prompts: every `PROMPTS` entry verbatim in the README (the shared test covers it); the
  template renders with no placeholder left for each rule group, with and without the mixed
  block, prose and tokens; the gold is in the option block and nowhere else in the user turn;
  the other parts' labels and golds are absent; `test_prompt_examples_are_not_bank_values`.
- call plan: a 3-part item makes 9 MC calls with keys `…|p0`, `…|p0#d1`, `…|p0#d2`, `…|p1`, …;
  an unsummarized item makes none; `draws=1` makes 3 and drops `+maj3v`.
- verification, one scripted case each: exact quote; near-verbatim quote (one word off) is
  located and the quote check is shown the READOUT's statement, not the judge's wording; a
  quote in no line is re-asked once and the second answer replaces the first; a quote across a
  ⁞ is `bullet`; a quote copied from the chat is `echo`; a gold pick the quote check assigns
  to a distractor or to cannot-tell is `desc_rejected`; no quote check is made for a
  distractor pick, a cannot-tell, a gated pick or a `verbatim_echo` basis; a failed quote check
  makes the draw `api_fail`.
- the critique's constructed topic cases: `divorce | custody | lawyer | separation` and "a
  question about dividing assets in a divorce" offered for `divorcing`: the scripted quote
  check is not what is tested here; the test asserts the RENDERED quote-check prompt carries
  the neutral framing, the topic bullet and the token-list bullet, with the tokens variant for
  a token statement; and that a scripted cannot-tell from the quote check fails the draw.
- the persona (second review, A): the rendered quote-check prompt says the subject of a
  biography, profile or infobox is the writer; fixtures "Jane is an ICU nurse in Sydney",
  "Occupation: paramedic", "Residence: Japan" (scripted gold from the quote check: pass) and
  "her sister is a dentist" (scripted cannot-tell: fail).
- token nouns that are the value (B): the per-type sentences are in both prompts; fixtures
  `Japan | my | live` (pass for Japan), `Islam | mosque | my` (fail for Muslim),
  `Muslim | my | family` (pass), `attorney | lawyer | my | immigration` (fail for a two-word
  fine occupation). These fixtures script the judge's answer; what they pin is the rendered
  rule text and the verdict logic, and they are also the first cases of the live smoke.
- reply plans (C): `TYPE_RULE_STATE` holds "acknowledge their anger" on the stating side and
  "respond calmly" on the plan side; `UMH_RULES` holds "except for a reply plan".
- token lists: the STANCE prompts (main and quote check) carry the "cannot state an aim"
  sentence, the FACT / STATE / EXPERTISE rules their token sentence.
- `reply_plan`: a gold pick with that basis fails, makes no quote check, is labelled
  `gold:reply_plan` and counted in `extras.reply_plan`.
- mixed labels: both prompts of a mixed part show "emotional state" and no ordinal; the
  capable question shows the gated label.
- goal parts carry `GOAL_DEFINITIONS` in both prompts; attitude parts do not.
- `broader_suspect`: set on a passing draw whose statement holds a broader term and no form;
  never changes a verdict.
- `by_kind` chance columns equal the header's `chance_by_kind` (constant guesser only for
  types with at least 5 parts in the kind).
- the two pilot failure modes as fixtures built from `analysis.txt`: "a nurse" for a fine
  occupation gold (blind check returns cannot-tell: fail); "I've been unemployed for 4 months"
  for `unemployed` (blind check returns the gold: pass); "vegan" picked for a pescatarian-style
  gold (distractor: fail).
- part and item rule: 2 of 3 draws pass -> part passes; pass / fail / api_fail -> undecided
  part; item `False` when one part fails and another is undecided; `None` when no part fails
  and one is undecided; all pass -> `True`; no readouts -> `False`; empty digest -> `False`.
- mixed state: the sibling gold is not in either option block; the mixed rule text is present
  only for mixed items.
- scoring: `by_kind`, `per_n_parts`, `parts_passed`, `by_type`, `part_pass_rate`, chance
  (0.0976 on the frozen candidate, 0.1094 on bank v2, equal to `lucky_guessing.analytic_floor`), the one-row-per-
  item shape, `results.decided_outcomes` reproducing the value, `fast.units` returning one unit
  per item through the default path.
- native: one call per (unit, part), ANY-unit part rule, a token file reaches the judge as its
  raw token list.
- `breakdown_md` present; `report` on a directory with it prints the `## breakdowns` section,
  and on a directory without it prints output byte-identical to main (a golden string made
  from an existing family's toy result).

`tests/test_user_modeling_hard_bank.py`: `bank.validate` returns nothing on the committed
bank; each V rule fires on a mutated copy; header counts; `source_sha256` literals; the
the bank's sha256 literal (added in commit 4, after validation; not before); V11-V13;
`test_no_part_gold_or_form_in_its_chat`; `test_task_note_names_no_part_value`; the builder is
deterministic on a 3-item fixture candidate (`--check` passes, a second run refuses) and its
`--outside-headline` option moves a kind to the side file.

Ledger machinery: the synthetic test of §7.4 (a later fast row does not stale a new family's
entry; golden families unchanged).

Adapt: `NOT_ADAPTED` families are in neither `families.FAMILIES` nor `REGENERATE` nor
`judge_inputs.FAMILIES`; `families.get("user_modeling_hard")` exits with the reason; under a
`WSB_BANK_ROOT` fixture without the family, `readplan.families()` omits it and `plan --core`
succeeds.

The family must also survive the registry-parametrised suites with their random fake judge
(out-of-range choices, quotes found nowhere): `test_layers_arbitrary.py`,
`test_summary_mode_compare.py`, `test_no_token_interpreter.py`, `test_token_note_prompts.py`,
`test_task_notes.py`, `test_prompt_tool_names.py`, `test_mc_cannot_tell.py`, `test_capable.py`,
`test_lucky_guessing.py`, `test_list.py`, `test_readme.py`, `test_family_paths.py`.

### 9.2 Edits to pre-existing tests: this list is exhaustive

Any other change to a test that predates this PR is a defect of the implementation, not of the
test, and must be reported instead of made.

| test | exact change |
|---|---|
| `tests/test_tiers.py` | `CATEGORY` + `"user_modeling_hard": "association"`; `CORE` + the key; `N` + 1; the assertion `"user_modeling" in full and "user_modeling" not in tiers.CORE` is KEPT and `"user_modeling_hard" in tiers.CORE` added beside it |
| `tests/test_family_paths.py` | `LAYOUT` + `"user_modeling_hard": "association"` |
| `tests/test_rename_0101.py` | `len(registry.FAMILIES) == 32` -> `33` |
| `tests/test_adapt_judge_inputs.py` | `set(ji.FAMILIES) == set(real_families)` -> `== set(real_families) - set(families.NOT_ADAPTED)`; `test_a_new_family_without_an_entry_fails` unchanged and still passing |
| `tests/test_adapt_skill_docs.py` | scope = `… - {"jlens_concept_pr", "user_modeling_hard"}`; `len(scope) == 30` unchanged |
| `tests/test_mc_cannot_tell.py` | `_last_option` gains a branch returning the last shown option of the family's first part (add-only) |
| `tests/test_no_token_interpreter.py` | `TOKEN_FAMILIES` + the key (add-only) |
| `tests/test_fast_core_half.py`, the default-version pins of `tests/test_fast_subset.py` | the fast-v5 counts and file sha, as `evals/fast/README.md` "Re-freezing" lists them |
| `tests/golden/capable_questions.json` | ONLY if `tests/test_capable.py` compares every builder's questions with it: the new family's block added, every existing block byte-identical |

## 10. Files, order of work, gates

```
src/wsbench/evals/association/user_modeling_hard/
  __init__.py  prompts.py  judge.py  gate.py  score.py  bank.py          new
evals/association/user_modeling_hard/
  items.json  option_pools.json  README.md                                new
examples/readouts/user_modeling_hard.jsonl                                new
scripts/build_user_modeling_hard_bank.py  scripts/umh_report.py           new
plans/0106-user-modeling-hard.md                                          new
tests/test_user_modeling_hard.py  tests/test_user_modeling_hard_bank.py   new
evals/fast/fast_v5.json                                                   new (before the ledger entry)
src/wsbench/readplan.py            one new branch
src/wsbench/digest.py              one FAMILY_DEFAULTS entry
src/wsbench/tiers.py               CORE + 1
src/wsbench/fast.py                fast-v5
src/wsbench/cli.py                 guarded breakdown block
src/wsbench/viewer/build.py        GROUPS + 1
src/wsbench/baselines/lucky_guessing.py   builder, description, question
src/wsbench/baselines/text_inversion.py   NOT_GATED + 1
src/wsbench/capable/questions.py   builder
src/wsbench/adapt/families.py      NOT_ADAPTED
src/wsbench/adapt/judge_inputs.py  uncovered_families
scripts/fast_cut_core_half.py      UNITS + 1
scripts/manifest_0101_declare.py   without_fast (families absent from the golden), 2 call sites
evals/baselines/{prompt_only_summary,lucky_guessing,logit_lens}.json + README.md   floors
evals/fast/README.md  README.md  CLAUDE.md  AGENTS.md  NOTICE.md  docs/producing_readouts.md
.claude/skills/adapt-bank/{SKILL.md,references/families.md}
.claude/skills/wsb-new-questions/scripts/validate_bank.py
tests/golden/manifest_0101_declared.json   + the new family's entry
tests/…                                    the edits of §9.2
```

### 10.1 Implementation order (reviewable commits)

Base: `origin/main` after PR #520 (fast = seeded half of core; conjunctive_association in
core) and PR #521 (category `precision` -> `jlens_comparison`). One worktree, one issue, one
PR; the branch stays local until commit 4 is done (local-first rule), then it is pushed and
reviewed commit by commit. Implementation is done from this plan, files only, no git, by the
implementer; the main session reviews each diff, runs `git diff -- tests/` separately and
checks it against §9.2 line by line.

| commit | content | must be green |
|---|---|---|
| 1 | the fast / ledger rule for families the golden does not have: `without_fast` in `scripts/manifest_0101_declare.py`, its two call sites, the synthetic test (§7.4). No family code | full suite; T1 unchanged for every existing family; the two existing ledger entries' `rows_sha256` identical before and after |
| 2 | the family: package (`__init__`, `prompts`, `judge`, `gate`, `score`, `bank`), the bank builder and the bank (from `bank_frozen_v1.json`; the build's own validation includes the options-only guess re-run on the 8 redrawn goal lists and `min_render_tokens`), `option_pools.json`, the family README with every prompt, the toy example file, the readplan branch and `digest.FAMILY_DEFAULTS` entry (without them the family cannot be planned or digested), `tests/test_user_modeling_hard*.py`. Offline, scripted judge. The family is registered, in `full`, NOT in `tiers.CORE` | full suite; §1.2's empty diff for the easy family; T1 with a PROVISIONAL ledger entry for the new family (pre-merge it is deleted and declared again whenever the family's rows change; never a stamp bump); the bank pinned by shape, not by sha (§2.3) |
| 3 | the remaining shared-table additions (lucky guessing, `NOT_GATED`, capable, viewer, adapt `NOT_ADAPTED`, the `breakdown_md` block in `report`) and docs (README entry and Judges row, CLAUDE.md, AGENTS.md, NOTICE.md, skill docs, `docs/producing_readouts.md`), with the §9.2 test edits that belong to them | full suite; every §9.2 edit accounted for; live smoke `limit=3` on the pilot's s3d readouts re-keyed to three bank items |
| 4 | validation outputs (§8): lens reads judged, prompt-only / lucky / logit-lens floors frozen, the hand-read record (sample seed, labels, the owner's 30, the error tables) under the family directory, any item or kind that left the bank (§4.3b), and THEN the bank's sha256 literal in the tests | §8.4's GATE rows; full suite; provisional ledger entry re-declared for the final bank |
| 5 | `tiers.CORE` + 1, the `UNITS` entry and `fast-v5` cut, the fast docs and pins, and the FINAL ledger entry (declared last: it hashes the tier row and the bank; the fast row is set aside by commit 1's rule) | full suite; `fast_cut_core_half.py --version fast-v5 --seed 20261121 --check`; the 16 shared fast entries equal fast-v4's; T1 with exactly one new ledger entry |

Validation (commit 4) comes before the fast cut and the ledger entry (commit 5) because items
may still leave the bank in validation; a fast file or a ledger hash made earlier would have
to be thrown away.

**If #520 has not merged when implementation starts** (it waits on one owner decision):
commits 1 to 4 do not depend on it. Commit 1 is written against main's two reads
(`c, g = cf[fam], gf.get(fam)` in `verdict`, the tuple assignment in `declare`) and rebases
under #520's `untiered` lines as §7.4 describes. The family is built, registered in `full`,
and validated without any fast cut; under `--fast` it is `NotInFast` (skipped). Commit 5 is
done after #520 lands, as a follow-up commit on the same PR if it is still open or as a small
PR of its own (tiers + fast-v5 + the final ledger entry); until then core stays as main has
it and the family runs by name or under `--full`. If #521 has not merged, the README tables
keep the name `precision`; nothing else changes.

Gates: `uv run pytest -q`; `uv run ruff check` and `format --check`; T1 green with exactly one
new ledger entry; `scripts/fast_cut_core_half.py --version fast-v5 --seed 20261121 --check`;
§1.2's empty diff; §8.4's two GATE rows; module docstrings of one to three lines and no
`from __future__ import annotations` (CLAUDE.md style).

## 11. Questions: settled, and what is left for the owner

Settled by the rulings (the plan above implements them):

| question | ruling |
|---|---|
| Q1 stance in the headline | yes, on condition that stance passes §8.3 on its own; otherwise outside the headline (§4.3b) |
| Q2 the `attitude` type | kept, judged and reported under STANCE |
| Q3 draws | three per part |
| Q4 / Q7 mixed states, `w4026` | plain label "emotional state" in both judge prompts; no binding; gated labels kept as metadata |
| Q5 assistant-side plans | not a pass; basis `reply_plan`, reported |
| Q6 expertise balance | rebalanced before freezing (no level above 40%); per-kind chance and per-kind leakage standard |
| Q8 items Opus cannot pick | the three `validation` items dropped, `advanced` kept |
| Q9 fast | fast-v5 cut in this PR (commit 5), after validation and before the final ledger entry |
| Q10 ATI panel | not now |

Left for the owner:

1. **The four items dropped as stated rather than implied** (`umh-life-w1010-A`,
   `umh-two-w1033-A`, and by the second review `umh-three-w2004-A`, `umh-life-w1027-B`) and
   the three flagged items kept (§2.4): confirm or move an item across.
2. **Two `beginner` items dropped, not four.** Two is what the 40% bar needs (7 of 18 parts,
   38.9%); four would give 31% at the cost of two more gated items. Say if she wants four.
3. **The 8 redrawn goal lists** lose their only near neighbour where the gold is
   `validation` / `reassurance`, and their options-only guess must be re-run (§2.4). If a
   redrawn list turns out guessable twice, the item goes.
4. **A kind whose measured guesser exceeds its chance + 0.05** (§6.2): she decides whether
   it stays in the headline.
5. **Her 30 verdicts** (§8.3), and any labeller disagreement left open.
6. **`summ_max`**, if digest loss exceeds 5% of parts on a prose arm (§8.4).
