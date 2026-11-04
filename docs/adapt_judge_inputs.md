# Adapted sets: what each judge reads (judge-input audit, plan 0060 A2.0)

This page lists, for every registered family, everything its judge and read plan read for an
item. The machine-readable source is `src/wsbench/adapt/judge_inputs.py`. The tables below are
generated from it (`render_markdown()`), and `tests/test_adapt_judge_inputs.py` fails when they
drift. That file also defines:

- `REQUIRED_ITEM_FIELDS`: the item keys every item of an adapted bank must carry. A1.1's freeze
  gate uses them.
- `SUBJECT_FIELDS`: the item keys whose value comes from the subject. Freeze overlays these and
  does not copy them.
- `ADAPTED_ONLY_FIELDS`: explicit per-item fields that replace an id lookup.
- `REQUIRED_HEADER_FIELDS`.
- `check_item(family, item, header)`: returns a list of problems. Each one is `missing: …`,
  `exit: …` (the judge would stop) or `hazard: …` (the judge would silently score the item
  differently from a registered one).

**Classes** (for an adapted item):

- **copy-verbatim**: originals carry it when they are copied from the registered item.
- **build**: an upgrader must build it for adapted-only items.
- **subject**: re-derived on the subject.
- **hazard**: a silent fallback for adapted-only ids or adapted banks.

**If absent**:

- **exit**: raise, SystemExit or KeyError.
- **silent**: a default that changes scoring.
- **fallback**: another instrument or code path.

## What an adapted-only id silently changes (the hazards)

### Lookups keyed by registered id or by registered value

These all read `REPO_ROOT/evals/…`, never the bank root.

- **multihop**:
  - `evals/multihop/split_subjects.json` is keyed by id. For a new id, the round-3 split rule
    is silently off. Use the per-item `split_subject` field, which the judge already prefers.
    It is in `ADAPTED_ONLY_FIELDS`. It must be a non-empty list: an empty one is treated as
    absent.
  - The element-index widening keys on the id pattern `^nhop-.+-element$`. An adapted element
    item needs an explicit flag, which means a judge change. `check_item` flags number-bridge
    periodic-table prompts whose id breaks the pattern.
- **role_bound_association**:
  - `distractors_v3.json` is keyed by `pair_id`. A new pair silently gets the retired oa-v2
    block, which leaks (options-only 0.230). Every adapted-only pair in today's sets is missing.
  - `roles_v1.json` and `actions_v1.json` are keyed by role and action word. A word missing
    from them is matched only literally, and conflicting_role loses its near-role terms. The
    only sign is `extras.n_roles_unlexiconed`.
- **user_modeling**:
  - `aliases.VALUE_ALIASES` and `UM_OPTION_POOL` are keyed by gold value. Options for an
    unknown gold still build silently, but `forms_of` / `shadow_forms` raise KeyError the moment
    the judge verifiably picks that gold. The value gate can never pass it either.
  - Today's sets hold about 28 such golds (italy, france, dentist, firefighter, …).
  - `UM_EXCLUDE`, `NEIGHBOURS` and `COUNTRY_REGIONS` misses are silent.
- **basic_readout_mt**: `exonyms.json` and `hidden_rivals.json` are keyed by registered id. A
  new id gets a stricter name gate and a looser contest check. An `eval_render` other than `"chat"`
  reads the v1 plain final-token site.
- **agentic_misalignment**: an adapted bank always reads the REGISTERED `targets_v2.json`, so a
  new id exits.
  A twin-arm item without `twin_rule` silently loses the object-twin rule in Stage C. Without
  `cluster`, related scenarios bootstrap as independent units, so the headline pair-rate CI
  silently narrows.
- **directed_modulation**: `distractor_groups.json` is keyed by concept, and a new concept
  exits. Options are drawn over the loaded bank, so a smaller adapted bank changes even the
  originals' options. A subfamily with fewer than 4 unrelated concepts exits; `check_bank`
  checks this.
- **multi_concept_directed_modulation**: the `b-` name prefix selects the relation path, the
  `-a/-b` and `-ab/-ba` suffixes pick partners, and `name_aliases_v2.json` is keyed by person.
  All three are silent.
- **relational_multihop**: `pair_consistency` counts only ids `rel-{scene}-a|b`. This is
  report-only.

### Item or header fields whose absence is silent

- **association**: `mc.aliases` and `mc.distractor_aliases`. A distractor count other than 7
  makes `CHANCE = 1/8` wrong.
- **conjunctive_association**:
  - `inverted_label`: the twin veto is lost.
  - `bank_version`: absent counts as v1.
- **basic_readout**:
  - `task_context`, `slice` and `mc.*aliases` are silent defaults.
  - A `readout.kind` other than `question_through_end` reads the v1 site.
  - Implicit golds are Qwen's modal answers.
- **multihop**: `mc.bridge_type`. Without it, number bridges are matched as text.
- **The multitoken families**:
  - Header `version` < 2 falls back to the v1 scorer for multilingual and to regex-only for
    multilingual_multihop.
  - Header `contract.native_langs` defaults to Qwen's `('en','zh')`.
  - Without `mc_roles`, the language unit is not swapped to its naming forms.
  - A missing `mc[role]` draws options from other items.
  - In multihop_mt_v2, one item whose `readout.kind` is not `all` flips the whole plan to v1.
    Its prompt also hard-codes "English or Chinese".
- **chain_intermediates**: without `kinds`, the head_tie veto never fires. `opts=judge=free`
  swaps the instrument.
- **poetry**: `qwen_commits` must hold the SUBJECT's commitments; without it they are not
  excluded from the options. The whole run fails if `mc.candidates` is missing, or if fewer
  than 4 candidates are left once the gold and `qwen_commits` are removed.
- **moral_rationale**:
  - Without `bank_version`, the bank is judged as v1 (ec-v3.1).
  - `options` missing in a v3 bank leaves gold plus cannot-tell only.
  - `bank_version` ≥ 4 plans from Qwen's frozen v3 rows.
- **jailbreak_recognition**: without `kind`, every item is a positive and the headline is None.
- **buggy_code**: without `twin`, the item is an orphan. No adapted set has a twin, so every
  set's `pair_rate` is None.
- **wrong_intermediate**:
  - A missing `readout` gives a final_token read.
  - An unknown `template` means no role cues.
  - `mc.order` must have exactly 6 options.
- **unverbalized_hint** (retired): each `pair_id` needs exactly one I and one N item, or
  `pairs_of` exits. `check_bank` checks this.
- **knowledge_cutoff**: option count must be exactly 5. An option with no `option_units`
  never hits.
- **introspection**: without `twins`, the row is undecided and drops out of the denominator.
  The vector paths resolve under REPO_ROOT, so they load Qwen's `.npy`.
- **multi_concept_directed_modulation**: header `last_n` defaults to 12, which is the Qwen
  token count.
- **Qwen-shaped constants**: every family's `min_full_positions` and the role_bound story
  guard's BPE-only cleaning are Qwen-shaped.

### State of today's adapted sets, found during the audit (not fixed here)

- None of them carries `mc` for association, multihop, poetry or chain adapted-only items.
- conjunctive "originals" match no v4 item.
- MCDM is the v1 bank.
- `adapted/qwen3.5-2b/role_bound_association.json` is an empty list.
- In the registered msdm item `s3b1_sapporo_miso_ramen_topping`, the distractor `butter` has
  empty `option_units`. This is deliberate: "butter and corn" carries the butter forms. The
  pair is listed in `KNOWN_EMPTY_OPTION_UNITS`, so the probe never flags it.

### Bank-level checks

`check_bank` adds two checks on top of the per-item ones:

- **Every family**: duplicate item ids. A name-keyed bank's loader raises on them; an id-keyed
  judge silently keeps one.
- **`BANK_CHECKS`**: the directed_modulation option draw and the unverbalized_hint I/N pairs.

Every registered bank passes `check_bank`.

### Read plans

`readplan.plan()` of an adapted-only clone (a registered item with a new id) equals its
original's in every family. The one exception is introspection's `readout_reused_by`, which
lists cross partners by id. Pinned by `test_read_plan_of_an_adapted_only_clone_equals_the_original`.

## Per family

<!-- judge_inputs table: generated by wsbench.adapt.judge_inputs.render_markdown -->

### agentic_misalignment

Judge: `evals/agentic_misalignment/{judge,score}.py`. Refresh: carry + twins (D5). Bank: dict, id from `id`.
REQUIRED_ITEM_FIELDS: `id`, `arm`, `category`, `group`, `text`, `system`.
SUBJECT_FIELDS: `misalignment_rate`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `arm` | yes | exit | copy-verbatim | agentic_misalignment/score.py:305-313 | unknown = control |
| item | `category` | yes | exit | copy-verbatim | agentic_misalignment/judge.py:531,557 |  |
| item | `group` | yes | exit | copy-verbatim | agentic_misalignment/judge.py:533 |  |
| item | `text` | yes | exit | copy-verbatim | readplan.py:1039-1054 |  |
| item | `system` | yes | silent | copy-verbatim | agentic_misalignment/judge.py:180-181 |  |
| item | `twin` |  | silent | build | agentic_misalignment/score.py:161-175 | pairs |
| item | `twin_rule` |  | silent | build | agentic_misalignment/judge.py:419,500,660; prompts.py:391-396 | twin arm: 'object' adds TWIN_RULE_OBJECT to the Stage C prompt; absent = the plain twin prompt (checked) |
| item | `cluster` |  | silent | build | agentic_misalignment/score.py:250,366 | the cluster_bootstrap unit of the headline pair-rate CI; absent = the item's own id, so related scenarios count as independent and the CI silently narrows |
| item | `low_power` |  | silent | build | agentic_misalignment/score.py:252 | report-only |
| item | `misalignment_rate` |  | silent | subject | agentic_misalignment/score.py:81-85 |  |
| resource | `evals/agentic_misalignment/targets_v2.json` |  | exit | build | agentic_misalignment/judge.py:71-105 | keyed by id; an adapted bank always reads the REGISTERED file (checked) |
| qwen | `min_full_positions=64` |  | - | subject | agentic_misalignment/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### arithmetic_intermediates

Judge: `evals/arithmetic_intermediates/judge.py`. Refresh: none (re-read; generated rows stamp-only). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `variant`, `cell`, `intermediates`, `tolerance`, `role`, `expr`, `null_set`, `operands`.
SUBJECT_FIELDS: `cell`.
Header: `variants`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:969 |  |
| item | `variant` | yes | exit | copy-verbatim | arithmetic_intermediates/judge.py:552,844 |  (checked) |
| item | `cell` | yes | exit | subject | arithmetic_intermediates/judge.py:396-404 | {layer, pos}: a Qwen (layer, chat-tail offset) cell re-derived per subject |
| item | `intermediates` | yes | exit | copy-verbatim | arithmetic_intermediates/judge.py:76,421 |  |
| item | `tolerance` | yes | exit | copy-verbatim | arithmetic_intermediates/judge.py:75,849 |  |
| item | `role` | yes | exit | copy-verbatim | arithmetic_intermediates/judge.py:553 |  |
| item | `expr` | yes | exit | copy-verbatim | arithmetic_intermediates/judge.py:554,653 |  |
| item | `null_set` | yes | exit | build | arithmetic_intermediates/judge.py:424,516,529-532 | names in the LOADED bank; unresolved names silently dropped |
| item | `operands` | yes | silent | copy-verbatim | arithmetic_intermediates/judge.py:686 |  |
| header | `variants` | yes | exit | copy-verbatim | arithmetic_intermediates/judge.py:595,883 |  |
| qwen | `cell.pos -7/-8 = Qwen chat-tail offsets` |  | - | subject | items.json header read |  |
| qwen | `min_full_positions=34` |  | - | subject | arithmetic_intermediates/__init__.py:27-29 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### association

Judge: `evals/association/judge.py`. Refresh: upgrade. Bank: dict, id from `name`.
Note: Adapted sets today carry no mc on any item: the judge exits on all 11 sets.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `mc`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:931 |  |
| item | `mc` | yes | exit | build | association/judge.py:69-74 | absent: fail (exit 2) |
| item | `mc.gold` | yes | exit | build | association/judge.py:79,87 |  |
| item | `mc.distractors` | yes | exit | build | association/judge.py:87 | 7 (CHANCE = 1/8) |
| item | `mc.aliases` | yes | silent | build | association/judge.py:80,117 |  |
| item | `mc.distractor_aliases` | yes | silent | build | association/judge.py:120 | absent: weaker rival / out-naming checks (lenient) |
| resource | `distractor count` |  | silent | build | association/prompts.py:17 |  (checked) |
| resource | `evals/association/lite_rule.json` |  | - | copy-verbatim | readplan.py:116-127 | family-keyed ({kind: same}) |
| qwen | `chat_summarize render + SUMMARIZE_SUFFIX` |  | - | subject | readplan.py:23, 925-941 | positions from the subject's own render (suffix_text_then_tail) |
| qwen | `min_full_positions=19` |  | - | subject | association/__init__.py:27 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### basic_readout

Judge: `basic/mcjudge_basic.py`. Refresh: rebuild (v5). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `readout`, `mc`, `task_context`, `slice`, `subfamily`.
SUBJECT_FIELDS: `mc`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:455-514 |  |
| item | `readout` | yes | fallback | copy-verbatim | readplan.py:455-514 |  (checked) |
| item | `mc.gold` | yes | exit | subject | basic/mcjudge_basic.py:141-148 | implicit: subject's modal answer |
| item | `mc.distractors` | yes | exit | build | basic/mcjudge_basic.py:141-148 | never the subject's answer |
| item | `mc.gold_position` | yes | fallback | build | basic/mcjudge_basic.py:149-159 | absent: seeded shuffle; balanced per subfamily at freeze (set-level) |
| item | `mc.aliases` | yes | silent | build | basic/mcjudge_basic.py:163-166 |  |
| item | `mc.distractor_aliases` | yes | silent | build | basic/mcjudge_basic.py:163-166 |  |
| item | `task_context` | yes | silent | build | basic/mcjudge_basic.py:388,571-586,679-682 | absent: blank TASK TYPE line and no digest context |
| item | `slice` | yes | silent | build | basic/mcjudge_basic.py:67,389 | absent: number-flood void off for arith |
| item | `subfamily` | yes | silent | build | basic/mcjudge_basic.py:525 |  |
| qwen | `implicit golds = Qwen3.6-27B's modal answer` |  | - | subject | evals/basic_readout/items_v5.json header gate |  |
| qwen | `chat_prefill + ANSWER_STEM` |  | - | subject | readplan.py:22,471-483 |  |
| qwen | `zh forms in mc.aliases (DEFAULT_NATIVE_LANGS)` |  | - | subject | evals/basic_readout/items_v5.json |  |
| qwen | `min_full_positions=8` |  | - | subject | basic_readout/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### basic_readout_mt

Judge: `multitoken/family.py (scorer mc + tolerant name gate)`. Refresh: rebuild (v4). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `units`, `probe_token_lens`, `eval_render`, `readout`, `mc`, `name_forms`.
SUBJECT_FIELDS: `probe_token_lens`.
Header: `contract.multi_token`, `contract.include_target`, `contract.native_langs`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:687-704 |  |
| item | `units` | yes | exit | copy-verbatim | multitoken/regex.py:363-425; mcrx.py:99-111 | role / forms / required / multi_token |
| header | `contract.multi_token` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered True; absent defaults from header.family |
| header | `contract.include_target` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered False; absent = True (adds a target unit / needs target lens) |
| header | `contract.native_langs` | adapted | silent | subject | banks.py:76-91 | absent = Qwen's ('en','zh'); per-subject measurement (plan 0060 A1.10); required of an adapted bank (typo_mt's registered header has none) |
| qwen | `LANGUAGE_NAMES {en,zh,ja,ko}` |  | - | hazard | multitoken/prompts.py:30 | any other native code is rendered as the raw ISO code in the judge prompt |
| item | `probe_token_lens` | yes | exit | subject | multitoken/regex.py:346-360 | Qwen token counts per form; restamped on the subject (adapt/run.py:358-386) |
| item | `eval_render` | yes | fallback | copy-verbatim | readplan.py:707-731 | not 'chat': per-item v1 plain final-token read (checked) |
| item | `readout` | yes | silent | copy-verbatim | readplan.py:707-731 | readout.lite; absent = final_token lite (readplan.py:725) |
| item | `mc.readout` | yes | fallback | build | multitoken/options.py:207-212 |  |
| item | `name_forms.readout` | yes | silent | build | multitoken/family.py:1273-1280 | absent: the unit's own forms (no zh, no aliases) |
| item | `lang` |  | exit | build | multitoken/options.py:13-26 | L2 items only |
| item | `target` |  | silent | build | multitoken/family.py:1266-1270 | L2 items only |
| resource | `evals/basic_readout_mt/exonyms.json + hidden_rivals.json` |  | silent | hazard | multitoken/family.py:1940-2012 | keyed by registered item id (REPO_ROOT) (checked) |
| qwen | `min_full_positions=8` |  | - | subject | basic_readout_mt/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### buggy_code

Judge: `evals/buggy_code/{judge,prompts}.py`. Refresh: upgrade + profile (twins). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `code`, `lang_group`, `src`.
Header: `read_cells`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `code` | yes | exit | copy-verbatim | readplan.py:988; buggy_code/prompts.py:168 |  |
| item | `lang_group` | yes | exit | copy-verbatim | buggy_code/judge.py:268,361; readplan.py:992 |  |
| item | `src` | yes | exit | copy-verbatim | buggy_code/judge.py:226,472 | buggy \| clean |
| item | `twin` |  | silent | hazard | buggy_code/judge.py:60-73,460-466 | symmetric by name; absent = orphan, out of pair_rate (no adapted set has it) |
| item | `consequence_class` |  | silent | copy-verbatim | buggy_code/judge.py:362 |  |
| item | `cause` |  | silent | build | buggy_code/prompts.py:134-140 | Stage B grading text |
| item | `why_correct` |  | silent | build | buggy_code/prompts.py:134-140 | clean twins |
| item | `looks_like` |  | silent | build | buggy_code/prompts.py:134-140 |  |
| item | `bug_line` |  | silent | build | buggy_code/prompts.py:162-163 | buggy items |
| item | `language` |  | silent | copy-verbatim | buggy_code/prompts.py:167 | absent = '?' |
| item | `verified` |  | silent | build | buggy_code/prompts.py:169 | absent = '?' |
| header | `read_cells` | yes | exit | subject | buggy_code/judge.py:268-276; readplan.py:992 | subject layers; lite_layers double-remapped by plan() (A1.8) |
| id_rule | `-au- / -au-clean- twin ids` |  | - | build | adapt/author.py:308; adapt/run.py:271-273 | adapt tooling only; the judge pairs by `twin` |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### chain_intermediates

Judge: `evals/chain_intermediates/judge.py`. Refresh: upgrade + regate (v2). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `start`, `intermediates`, `answer`, `mc`, `kinds`, `depth`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:953 |  |
| item | `start` | yes | exit | copy-verbatim | readplan.py:951; chain_intermediates/judge.py:456 |  |
| item | `intermediates` | yes | exit | copy-verbatim | chain_intermediates/judge.py:454,695 |  |
| item | `answer` | yes | exit | copy-verbatim | chain_intermediates/judge.py:456,762 |  |
| item | `mc` | yes | exit | build | chain_intermediates/judge.py:471-479,689-693 | absent: exit; opts=judge=free swaps the instrument; set-level rank balance (checked) |
| item | `kinds` | yes | silent | copy-verbatim | chain_intermediates/judge.py:650-653,740-741,874 | absent: head_tie veto never fires (lenient) |
| item | `depth` | yes | silent | copy-verbatim | chain_intermediates/judge.py:339,761 |  |
| qwen | `span from the start digit ('Qwen splits digits')` |  | - | subject | readplan.py:949-951 |  |
| qwen | `min_full_positions=20` |  | - | subject | chain_intermediates/__init__.py:28-31 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### conjunctive_association

Judge: `evals/conjunctive_association/judge.py`. Refresh: originals copied verbatim (no adapted-only items). Bank: list, id from `id`.
Note: Adapted 'originals' match no v4 item today (older mc_options, no bank_version).
REQUIRED_ITEM_FIELDS: `id`, `stimulus`, `mc_options`, `gold_label`, `contrast_label`, `inverted_label`, `bank_version`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `stimulus` | yes | exit | copy-verbatim | readplan.py:931 |  |
| item | `mc_options` | yes | exit | copy-verbatim | conjunctive_association/judge.py:126 |  |
| item | `gold_label` | yes | exit | copy-verbatim | conjunctive_association/judge.py:127 |  (checked) |
| item | `contrast_label` | yes | silent | copy-verbatim | conjunctive_association/judge.py:130 | absent: no contrast bucket |
| item | `inverted_label` | yes | silent | copy-verbatim | conjunctive_association/judge.py:106-116,138,239-270 | absent: twin veto lost (lenient pass) |
| item | `bank_version` | yes | fallback | copy-verbatim | conjunctive_association/judge.py:520-526 | absent = 1; mixed values exit (checked) |
| item | `twin_of` |  | - | copy-verbatim | - | not read by the judge (provenance) |
| qwen | `chat_summarize render + SUMMARIZE_SUFFIX` |  | - | subject | readplan.py:23, 925-941 | positions from the subject's own render (suffix_text_then_tail) |
| qwen | `min_full_positions=19` |  | - | subject | conjunctive_association/__init__.py:27 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### directed_modulation

Judge: `evals/directed_modulation/judge.py`. Refresh: none (re-read only). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `assistant`, `concept`, `subfamily`, `polarity`, `pair_id`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:807 |  |
| item | `assistant` | yes | exit | copy-verbatim | readplan.py:805,808 |  |
| item | `concept` | yes | exit | copy-verbatim | directed_modulation/judge.py:95,98 |  (checked) |
| item | `subfamily` | yes | exit | copy-verbatim | directed_modulation/judge.py:95,225 | unknown value: CREDIT_PAIR |
| item | `polarity` | yes | exit | copy-verbatim | directed_modulation/judge.py:226 | non-think: BASIS_NEG |
| item | `pair_id` | yes | silent | copy-verbatim | directed_modulation/score.py:131 | absent: out of the white_bear contrast |
| resource | `evals/directed_modulation/distractor_groups.json` |  | exit | build | directed_modulation/judge.py:37,56-77 | keyed by concept (REPO_ROOT) |
| resource | `option draw over the LOADED bank` |  | silent | hazard | directed_modulation/judge.py:84-116 | distractors come from the bank's same-subfamily concepts: a smaller adapted bank changes the options shown even for verbatim originals; fewer than N_DISTRACTORS=4 unrelated concepts in a subfamily raises ValueError (judge.py:101-102; check_bank checks it) |
| qwen | `chat_dm render` |  | - | subject | readplan.py:35,805 |  |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### hinted_cutoff

Judge: `evals/hinted_cutoff/judge.py`. Refresh: model-specific (plan 0063). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `pair_id`, `role`, `cluster`, `positions`, `text`, `input_ids`, `n_prompt`.
SUBJECT_FIELDS: `role`, `positions`, `input_ids`, `n_prompt`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `pair_id` | yes | exit | copy-verbatim | hinted_cutoff/judge.py:pairs_of |  |
| item | `role` | yes | exit | subject | hinted_cutoff/judge.py:pairs_of | I/N from Qwen behaviour |
| item | `cluster` | yes | exit | copy-verbatim | hinted_cutoff/judge.py:pairs_of | I-twin event cluster |
| item | `positions` | yes | exit | subject | hinted_cutoff/judge.py:run | Qwen prompt token indices |
| item | `text` | yes | exit | copy-verbatim | readplan.py hinted_cutoff branch |  |
| item | `input_ids` | yes | exit | subject | readplan.py hinted_cutoff branch | prompt-only ids |
| item | `n_prompt` | yes | exit | subject | readplan.py hinted_cutoff branch |  |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### introspection

Judge: `evals/introspection/judge.py`. Refresh: model-specific (Phase E). Bank: dict, id from `id`.
REQUIRED_ITEM_FIELDS: `id`, `kind`, `prompt_kind`, `prompt_key`, `beta`, `vector`, `concept`, `cluster`, `gold`, `options`, `readout_of`.
SUBJECT_FIELDS: `vector`.
Header: `renders`, `spec.inject_layer`, `vector_recipe`, `vectors`, `concepts`, `beta0_rows`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `kind` | yes | exit | copy-verbatim | introspection/judge.py | inject \| gaussian \| cross |
| item | `prompt_kind` | yes | exit | copy-verbatim | introspection/judge.py:510 | protocol \| neutral |
| item | `prompt_key` | yes | exit | copy-verbatim | readplan.py:1154 |  |
| item | `beta` | yes | exit | copy-verbatim | readplan.py:1157 | headline = protocol and 4.0 |
| item | `vector` | yes | exit | subject | readplan.py:1157-1166 | row into the subject's vectors |
| item | `concept` | yes | exit | copy-verbatim | introspection/judge.py:445-461 |  |
| item | `cluster` | yes | exit | copy-verbatim | introspection/judge.py:445-461 |  |
| item | `gold` | yes | exit | copy-verbatim | introspection/judge.py:445-461 |  |
| item | `options` | yes | exit | copy-verbatim | introspection/judge.py:445-461 | [{label}] |
| item | `readout_of` | yes | exit | copy-verbatim | introspection/judge.py:445-461; readplan.py:1148-1150 | the readout an item is judged on (cross items: the partner's) |
| item | `twins` |  | silent | build | introspection/judge.py:484-488,1058-1063 |  (checked) |
| header | `renders` | yes | exit | subject | readplan.py:1154-1180 | Qwen input_ids / spans |
| header | `spec.inject_layer` | yes | exit | subject | readplan.py:1159 | not remapped by plan() |
| header | `vector_recipe` | yes | exit | subject | readplan.py:1160-1164 |  |
| header | `vectors` | yes | exit | subject | readplan.py:1146; produce/producer.py:154-162 | relative paths resolve under REPO_ROOT (Qwen's .npy) |
| header | `concepts` | yes | exit | copy-verbatim | introspection/judge.py:85-101 |  |
| header | `equivalents` |  | silent | copy-verbatim | introspection/judge.py:72-74,306 |  |
| header | `beta0_rows` | yes | exit | build | readplan.py:1153; judge.py:424 |  |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### jailbreak_recognition

Judge: `evals/jailbreak_recognition/{judge,score}.py`. Refresh: carry + control re-screen. Bank: dict, id from `id`.
REQUIRED_ITEM_FIELDS: `id`, `messages`, `read`, `kind`.
SUBJECT_FIELDS: `read`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `messages` | yes | exit | copy-verbatim | jailbreak_recognition/judge.py:53-56,150-160 |  |
| item | `read.span` | yes | exit | subject | jailbreak_recognition/judge.py:80-123 |  |
| item | `read.tokens` | yes | exit | subject | jailbreak_recognition/judge.py:153,314-320 |  |
| item | `read.turn_end` | yes | exit | subject | jailbreak_recognition/judge.py:126-135 |  |
| item | `read.n_tokens` | yes | exit | subject | readplan.py:1029 |  |
| item | `kind` | yes | silent | copy-verbatim | jailbreak_recognition/judge.py:323-325; score.py:52-53 | absent = 'jailbreak' (controls must say control) |
| item | `template_id` |  | silent | copy-verbatim | jailbreak_recognition/score.py:186 | CI cluster |
| item | `twin_of` |  | silent | copy-verbatim | jailbreak_recognition/score.py:226-236 |  |
| qwen | `read.* = Qwen token indices / <\|im_end\|>` |  | - | subject | readplan.py:1029-1036 |  |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### jlens_concept_pr

Judge: `evals/jlens_concept_pr/judge.py (items = manifest prompts)`. Refresh: verify (regenerated on the subject). Bank: manifest, id from `label`.
REQUIRED_ITEM_FIELDS: `label`, `family`, `eval_positions`, `n_pos`.
SUBJECT_FIELDS: `eval_positions`, `n_pos`.
Header: `model_id`, `layers`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `label` | yes | exit | build | jlens_concept_pr/judge.py:144-173 |  |
| item | `family` | yes | exit | build | jlens_concept_pr/judge.py:169-173 | chat \| pt |
| item | `eval_positions` | yes | exit | subject | jlens_concept_pr/judge.py:144-149 |  |
| item | `n_pos` | yes | exit | subject | readplan.py:1075-1109 |  |
| header | `model_id` | yes | - | subject | manifest.json |  |
| header | `layers` | yes | - | subject | manifest.json |  |
| resource | `<bank_dir>/gen-jlens-pr-jlens/<label>/L<layer>.jsonl` |  | exit | subject | jlens_concept_pr/judge.py:104-105,156-236 | the subject's J-lens reference; a file with no row at the eval position = [] = zero score (silent) |
| resource | `items.json input_ids / prompt_len` |  | silent | subject | readplan.py:1075-1109 | a label missing there gets a plan row without ids |
| resource | `foil derangement over ALL manifest labels` |  | silent | hazard | jlens_concept_pr/judge.py:123-137 | adding labels reshuffles every item's foil partner |
| qwen | `byte-level BPE display tokens` |  | - | subject | jlens_concept_pr/judge.py:115-120 |  |

### knowledge_cutoff

Judge: `evals/knowledge_cutoff/judge.py`. Refresh: model-specific (Phase E). Bank: dict, id from `id`.
REQUIRED_ITEM_FIELDS: `id`, `user`, `options`, `gold`, `option_units`.
SUBJECT_FIELDS: `gold`, `label_type`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `user` | yes | exit | copy-verbatim | readplan.py:823; knowledge_cutoff/judge.py:155-161 |  |
| item | `options` | yes | exit | build | knowledge_cutoff/judge.py:150,476 | exactly 5 (checked) |
| item | `gold` | yes | exit | subject | knowledge_cutoff/judge.py:159 | the subject's stable wrong answer |
| item | `option_units` | yes | exit | build | knowledge_cutoff/judge.py:151 |  |
| item | `question` |  | fallback | copy-verbatim | knowledge_cutoff/judge.py:162 | else user |
| item | `truth.canonical` |  | silent | copy-verbatim | knowledge_cutoff/judge.py:546 |  |
| item | `label_type` |  | silent | subject | knowledge_cutoff/judge.py:658-660 |  |
| item | `stratum` |  | silent | copy-verbatim | knowledge_cutoff/judge.py:658-660 |  |
| resource | `evals/knowledge_cutoff/obscure_items.json (nocot)` |  | - | subject | nocot.py:16; readplan.py:1112-1117 | Qwen's labels; off under WSB_BANK_ROOT, but NOT under WSB_BANK_FILE_* |
| qwen | `min_full_positions=4` |  | - | subject | knowledge_cutoff/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### math_shortcuts

Judge: `evals/math_shortcuts/judge.py`. Refresh: model-specific (plan 0065). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `label`, `problem`, `positions`, `text`, `input_ids`, `n_tokens`, `reply_start`.
SUBJECT_FIELDS: `label`, `positions`, `input_ids`, `n_tokens`, `reply_start`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `label` | yes | exit | subject | math_shortcuts/judge.py:run | I/N from Qwen behaviour |
| item | `problem` | yes | exit | copy-verbatim | math_shortcuts/judge.py:judge_native | shown to the judge |
| item | `positions` | yes | exit | subject | math_shortcuts/judge.py:run | Qwen token indices |
| item | `text` | yes | exit | copy-verbatim | readplan.py math_shortcuts branch |  |
| item | `input_ids` | yes | exit | subject | readplan.py math_shortcuts branch | captured render |
| item | `n_tokens` | yes | exit | subject | readplan.py math_shortcuts branch |  |
| item | `reply_start` | yes | exit | subject | readplan.py math_shortcuts branch |  |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### model_specific_directed_modulation

Judge: `evals/model_specific_directed_modulation/{judge,controls}.py`. Refresh: model-specific (Phase E). Bank: dict, id from `id`.
REQUIRED_ITEM_FIELDS: `id`, `topic`, `carrier`, `user`, `gold`, `options`, `option_units`.
SUBJECT_FIELDS: `gold`, `options`, `option_units`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `topic` | yes | exit | copy-verbatim | model_specific_directed_modulation/judge.py:181 |  |
| item | `carrier` | yes | exit | copy-verbatim | readplan.py:839-842 |  |
| item | `user` | yes | exit | copy-verbatim | readplan.py:841 | must equal render_user(topic, carrier) |
| item | `gold` | yes | exit | subject | model_specific_directed_modulation/judge.py:78-80 | own default |
| item | `options` | yes | exit | subject | model_specific_directed_modulation/judge.py:54,79 |  (checked) |
| item | `option_units` | yes | exit | subject | model_specific_directed_modulation/judge.py:54 |  |
| qwen | `MIN_CARRIER_TOKENS=7 (Qwen tokens)` |  | - | subject | model_specific_directed_modulation/judge.py:28 |  |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### moral_rationale

Judge: `evals/moral_rationale/{judge,score}.py`. Refresh: rebuild (re-key, v3). Bank: list, id from `id`.
REQUIRED_ITEM_FIELDS: `id`, `stimulus`, `question`, `reason_class`, `bank_version`, `options`, `topic_id`.
SUBJECT_FIELDS: `stimulus`, `reason_class`, `options`, `gate_pass`, `look_for_reasons`, `reasons`, `subject_answer`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `stimulus` | yes | exit | subject | readplan.py:870-895 | reasons in the read conversation |
| item | `question` | yes | exit | copy-verbatim | moral_rationale/judge.py:207-208,979 |  |
| item | `reason_class` | yes | exit | subject | moral_rationale/judge.py:255; score.py:92-102 | non-'committed' = deliberative |
| item | `bank_version` | yes | fallback | build | moral_rationale/judge.py:100-106; readplan.py:872-877 | absent = v1 instrument (checked) |
| item | `options` | yes | fallback | subject | moral_rationale/judge.py:211-233,251-285,643-655 | absent in a v3 bank: gold + cannot-tell only |
| item | `topic_id` | yes | silent | copy-verbatim | moral_rationale/score.py:47-50 |  |
| item | `gate_pass` |  | silent | subject | moral_rationale/score.py:39 | diagnostics |
| item | `system` |  | silent | copy-verbatim | readplan.py:870-895 |  |
| item | `look_for_reasons` |  | - | subject | moral_rationale/judge.py:130-174 | v1 only |
| item | `reasons` |  | - | subject | moral_rationale/judge.py:255-268 | v1 path only; the subject's distilled reasons (rekey / adopt) |
| item | `subject_answer` |  | - | subject | - | adapt-time (SUBJECT_FIELDS) |
| qwen | `lite last_n 5 = Qwen assistant header` |  | - | subject | readplan.py:888-893 |  |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### multi_concept_directed_modulation

Judge: `evals/multi_concept_directed_modulation/{judge,options,regions}.py`. Refresh: carry (v2, 116 items). Bank: dict, id from `name`.
Note: Adapted sets today are the v1 bank (100 items, header last_n 12 on every subject).
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `concepts`, `stratum`.
Header: `target_sentence`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:1007 |  |
| item | `concepts` | yes | silent | copy-verbatim | multi_concept_directed_modulation/options.py:121,153-169 | absent: judged as a control (pass=None) |
| item | `roles` |  | fallback | copy-verbatim | multi_concept_directed_modulation/options.py:120-123 | b-* items: absent = parse_relation(concepts[0]) (v1) (checked) |
| item | `aliases` |  | silent | copy-verbatim | multi_concept_directed_modulation/options.py:129 |  |
| item | `stratum` | yes | silent | copy-verbatim | multi_concept_directed_modulation/judge.py:931-934 |  |
| item | `prior_direction` |  | silent | copy-verbatim | multi_concept_directed_modulation/judge.py:942 |  |
| header | `target_sentence` | yes | exit | copy-verbatim | readplan.py:1008 | must equal regions.TARGET_SENTENCE (checked) |
| header | `last_n` |  | silent | subject | readplan.py:1004 | absent = 12, the Qwen token count of the target sentence |
| resource | `relation_clusters_v2.json` |  | exit | build | multi_concept_directed_modulation/options.py:70-76,200-202 | beside the adapted bank if present, else the frozen dir |
| resource | `distractor_groups_v2.json` |  | silent | hazard | multi_concept_directed_modulation/options.py:139-145 | a concept not listed gets no close-relative exclusion |
| resource | `name_aliases_v2.json` |  | silent | hazard | multi_concept_directed_modulation/options.py:126-147 | keyed by person |
| id_rule | `b-* relation prefix` |  | silent | hazard | multi_concept_directed_modulation/options.py:120 |  (checked) |
| id_rule | `-a/-b, -ab/-ba partner suffixes` |  | silent | hazard | multi_concept_directed_modulation/options.py:59-68 | a pair that breaks the naming loses its partner option and veto |
| qwen | `<think>/</think> markers` |  | - | subject | multi_concept_directed_modulation/regions.py:8-9 |  |
| qwen | `min_full_positions=12` |  | - | subject | multi_concept_directed_modulation/__init__.py:27 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### multihop

Judge: `basic/mcjudge_bank.py`. Refresh: upgrade. Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `mc`, `readout`.
SUBJECT_FIELDS: `readout`.
Adapted-only items also need: `split_subject`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:517-543 |  |
| item | `mc.gold` | yes | exit | copy-verbatim | basic/mcjudge_bank.py:127-141 |  |
| item | `mc.distractors` | yes | exit | copy-verbatim | basic/mcjudge_bank.py:127-141 | ≤ 7 (LETTERS) |
| item | `mc.bridge_type` | yes | silent | build | basic/mcjudge_bank.py:236,529,545,681 | absent: a number bridge is matched as text (flood / element rules off) |
| item | `mc.aliases` | yes | silent | build | basic/mcjudge_bank.py:525 |  |
| item | `mc.distractor_aliases` | yes | silent | build | basic/mcjudge_bank.py:239,565 |  |
| item | `readout.offsets` | yes | silent | subject | readplan.py:527-541 | lite last-word offset in the subject's tokens; absent = [-1] |
| item | `split_subject` | adapted | fallback | build | basic/mcjudge_bank.py:416-427 | explicit per-item field replacing the split_subjects.json id lookup; must be a NON-EMPTY list (a falsy value falls back to the file, mcjudge_bank.py:420) (checked) |
| resource | `evals/multihop/split_subjects.json` |  | silent | hazard | basic/mcjudge_bank.py:412-427 | keyed by registered id (REPO_ROOT); a new id = [] = round-3 split rule off |
| id_rule | `^nhop-.+-element$` |  | silent | hazard | basic/mcjudge_bank.py:336-344,560 | element-index widening keyed on the id (checked) |
| qwen | `zh forms in mc.aliases` |  | - | subject | evals/multihop/items_v3.json |  |
| qwen | `min_full_positions=8` |  | - | subject | multihop/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### multihop_mt_v2

Judge: `multitoken/family.py (MC_PROFILES, rival)`. Refresh: model-specific (Phase E). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `units`, `probe_token_lens`, `target`, `readout`, `mc`, `name_forms`.
SUBJECT_FIELDS: `probe_token_lens`.
Header: `contract.multi_token`, `contract.include_target`, `contract.native_langs`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:687-704 |  |
| item | `units` | yes | exit | copy-verbatim | multitoken/regex.py:363-425; mcrx.py:99-111 | role / forms / required / multi_token |
| header | `contract.multi_token` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered True; absent defaults from header.family |
| header | `contract.include_target` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered True; absent = True (adds a target unit / needs target lens) |
| header | `contract.native_langs` | adapted | silent | subject | banks.py:76-91 | absent = Qwen's ('en','zh'); per-subject measurement (plan 0060 A1.10); required of an adapted bank (typo_mt's registered header has none) |
| qwen | `LANGUAGE_NAMES {en,zh,ja,ko}` |  | - | hazard | multitoken/prompts.py:30 | any other native code is rendered as the raw ISO code in the judge prompt |
| item | `probe_token_lens` | yes | exit | subject | multitoken/regex.py:346-360 | Qwen token counts per form; restamped on the subject (adapt/run.py:358-386) |
| item | `target` | yes | exit | copy-verbatim | multitoken/regex.py:283-298 | include_target: lens needed |
| item | `readout` | yes | fallback | copy-verbatim | readplan.py:732-741 |  (checked) |
| item | `mc` | yes | fallback | build | multitoken/options.py:207-212 |  |
| item | `name_forms` | yes | silent | build | multitoken/family.py:2617-2632 |  |
| item | `units[].kind` | yes | silent | build | multitoken/family.py:1309-1330 (bank_entities), 2082-2089 (_rivals) | rival pools are keyed by kind: a unit without one joins the '' pool and gets no same-kind rivals (plan 0066 §6; refill units are classified, never defaulted) |
| resource | `evals/multihop_mt_v2/hidden_rivals.json` |  | - | copy-verbatim | multitoken/family.py:1940-1950 | file does not exist: always empty |
| qwen | `SYSTEM 'English or Chinese' (MH2_NATIVE_LANGS = DEFAULT_NATIVE_LANGS)` |  | - | hazard | evals/multihop_mt_v2/prompts.py:41,58 | ignores the header's native_langs |
| qwen | `not in adapt lint.MT: probe_token_lens never restamped` |  | - | hazard | adapt/run.py:373 |  |
| qwen | `min_full_positions=15` |  | - | subject | multihop_mt_v2/__init__.py:19-21 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### multilingual

Judge: `multitoken/family.py + mcrx.py (scorer mc+regex)`. Refresh: upgrade. Bank: dict, id from `name`.
Note: Adapted sets today are v1: they silently run the retired v1 scorer.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `units`, `lang`, `mc_roles`, `mc`.
SUBJECT_FIELDS: `units`.
Header: `contract.multi_token`, `contract.include_target`, `contract.native_langs`, `version`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:687-704 |  |
| item | `units` | yes | exit | subject | multitoken/regex.py:363-425; mcrx.py:99-111 | role / forms / required / multi_token; native units rebuilt per the subject's native_langs (plan 0060 A1.10) |
| header | `contract.multi_token` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered False; absent defaults from header.family |
| header | `contract.include_target` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered False; absent = True (adds a target unit / needs target lens) |
| header | `contract.native_langs` | adapted | silent | subject | banks.py:76-91 | absent = Qwen's ('en','zh'); per-subject measurement (plan 0060 A1.10); required of an adapted bank (typo_mt's registered header has none) |
| qwen | `LANGUAGE_NAMES {en,zh,ja,ko}` |  | - | hazard | multitoken/prompts.py:30 | any other native code is rendered as the raw ISO code in the judge prompt |
| header | `version` | yes | fallback | copy-verbatim | multitoken/family.py:116-121, 336-377 | absent = 1: the v1 basic bank judge (v1_scorer='bank') |
| item | `lang` | yes | exit | build | multitoken/options.py:13-26 | LANG_CONFUSABLES / LANGUAGES key |
| item | `mc_roles` | yes | silent | build | multitoken/regex.py:373-379, options.py:160-218 | absent: the language unit is not swapped to its naming forms (silent) |
| item | `mc.concept_native` | yes | fallback | build | multitoken/options.py:207-212 |  |
| item | `mc.language` | yes | exit | build | multitoken/options.py:13-26 | absent: LANG_CONFUSABLES[lang] (exit for 16 of 21 bank langs) |
| resource | `language unit = frozen LANGUAGES forms` |  | silent | hazard | multitoken/languages.py:747-754 |  (checked) |
| qwen | `prompts.ML_ALIAS_NOTE (rendered from the 27B v3 bank)` |  | - | hazard | multitoken/prompts.py:194-200 | stale for an adapted bank's option set |
| qwen | `min_full_positions=4` |  | - | subject | multilingual/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### multilingual_mt

Judge: `multitoken/family.py + regex.py (scorer regex)`. Refresh: upgrade. Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `units`, `lang`, `mc_roles`.
SUBJECT_FIELDS: `units`.
Header: `contract.multi_token`, `contract.include_target`, `contract.native_langs`, `version`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:687-704 |  |
| item | `units` | yes | exit | subject | multitoken/regex.py:363-425; mcrx.py:99-111 | role / forms / required / multi_token; native units rebuilt per the subject's native_langs (plan 0060 A1.10) |
| header | `contract.multi_token` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered False; absent defaults from header.family |
| header | `contract.include_target` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered False; absent = True (adds a target unit / needs target lens) |
| header | `contract.native_langs` | adapted | silent | subject | banks.py:76-91 | absent = Qwen's ('en','zh'); per-subject measurement (plan 0060 A1.10); required of an adapted bank (typo_mt's registered header has none) |
| qwen | `LANGUAGE_NAMES {en,zh,ja,ko}` |  | - | hazard | multitoken/prompts.py:30 | any other native code is rendered as the raw ISO code in the judge prompt |
| header | `version` | yes | fallback | copy-verbatim | multitoken/family.py:116-121, 336-377 | absent = 1: raw-sample regex supplement off, no instrument tag |
| item | `lang` | yes | exit | build | multitoken/options.py:13-26 | LANG_CONFUSABLES / LANGUAGES key |
| item | `mc_roles` | yes | silent | build | multitoken/regex.py:373-379, options.py:160-218 | absent: the language unit is not swapped to its naming forms (silent) |
| item | `mc` |  | fallback | build | multitoken/options.py:207-212 | opts=judge=mc only |
| resource | `language unit = frozen LANGUAGES forms` |  | silent | hazard | multitoken/languages.py:747-754 |  (checked) |
| qwen | `min_full_positions=16` |  | - | subject | multilingual_mt/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### multilingual_multihop

Judge: `multitoken/family.py + mcrx.py (scorer mc+regex)`. Refresh: upgrade. Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `units`, `lang`, `mc_roles`, `mc`, `target`.
SUBJECT_FIELDS: `units`, `probe_token_lens`.
Header: `contract.multi_token`, `contract.include_target`, `contract.native_langs`, `version`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:687-704 |  |
| item | `units` | yes | exit | subject | multitoken/regex.py:363-425; mcrx.py:99-111 | role / forms / required / multi_token; native units rebuilt per the subject's native_langs (plan 0060 A1.10) |
| header | `contract.multi_token` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered True; absent defaults from header.family |
| header | `contract.include_target` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered False; absent = True (adds a target unit / needs target lens) |
| header | `contract.native_langs` | adapted | silent | subject | banks.py:76-91 | absent = Qwen's ('en','zh'); per-subject measurement (plan 0060 A1.10); required of an adapted bank (typo_mt's registered header has none) |
| qwen | `LANGUAGE_NAMES {en,zh,ja,ko}` |  | - | hazard | multitoken/prompts.py:30 | any other native code is rendered as the raw ISO code in the judge prompt |
| header | `version` | yes | fallback | copy-verbatim | multitoken/family.py:116-121, 336-377 | absent = 1: regex-only v1 path |
| item | `lang` | yes | exit | build | multitoken/options.py:13-26 | LANG_CONFUSABLES / LANGUAGES key |
| item | `mc_roles` | yes | exit | build | multitoken/options.py:160-218 | absent: option_sets raises on bridge_l2 (checked) |
| item | `mc.bridge_native` | yes | fallback | build | multitoken/options.py:207-212 |  |
| item | `mc.language` | yes | silent | build | multitoken/options.py:13-26 |  |
| item | `target` | yes | silent | copy-verbatim | multitoken/mcrx.py:811-816 | anchors |
| item | `probe_token_lens` |  | exit | subject | multitoken/regex.py:346-360 | bridge_l2 lens; absent by design when l2_equals_native |
| item | `l2_equals_native` |  | silent | build | multitoken/mcrx.py:1027-1058 | absent = in the headline; re-derived per native_langs (A1.10) |
| item | `bridge_l2_creditable` |  | - | build | - | not read by the judge |
| resource | `language unit = frozen LANGUAGES forms` |  | silent | hazard | multitoken/languages.py:747-754 |  (checked) |
| qwen | `min_full_positions=12` |  | - | subject | multilingual_multihop/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### multilingual_typo

Judge: `multitoken/family.py + regex.py (scorer regex)`. Refresh: upgrade. Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `units`, `lang`, `mc_roles`, `probe_token_lens`, `target`.
SUBJECT_FIELDS: `units`, `probe_token_lens`.
Header: `contract.multi_token`, `contract.include_target`, `contract.native_langs`, `version`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:687-704 |  |
| item | `units` | yes | exit | subject | multitoken/regex.py:363-425; mcrx.py:99-111 | role / forms / required / multi_token; native units rebuilt per the subject's native_langs (plan 0060 A1.10) |
| header | `contract.multi_token` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered True; absent defaults from header.family |
| header | `contract.include_target` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered False; absent = True (adds a target unit / needs target lens) |
| header | `contract.native_langs` | adapted | silent | subject | banks.py:76-91 | absent = Qwen's ('en','zh'); per-subject measurement (plan 0060 A1.10); required of an adapted bank (typo_mt's registered header has none) |
| qwen | `LANGUAGE_NAMES {en,zh,ja,ko}` |  | - | hazard | multitoken/prompts.py:30 | any other native code is rendered as the raw ISO code in the judge prompt |
| header | `version` | yes | fallback | copy-verbatim | multitoken/family.py:116-121, 336-377 | absent = 1: raw-sample supplement and anchors off |
| item | `lang` | yes | exit | build | multitoken/options.py:13-26 | LANG_CONFUSABLES / LANGUAGES key |
| item | `mc_roles` | yes | silent | build | multitoken/regex.py:373-379, options.py:160-218 | absent: the language unit is not swapped to its naming forms (silent) |
| item | `probe_token_lens` | yes | exit | subject | multitoken/regex.py:346-360 | Qwen token counts per form; restamped on the subject (adapt/run.py:358-386) |
| item | `target` | yes | silent | copy-verbatim | multitoken/family.py:588-601 | anchors; absent = fewer anchors |
| item | `mc` |  | fallback | build | multitoken/options.py:207-212 | opts=judge=mc only |
| resource | `language unit = frozen LANGUAGES forms` |  | silent | hazard | multitoken/languages.py:747-754 |  (checked) |
| qwen | `min_full_positions=13` |  | - | subject | multilingual_typo/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### nyt_connections

Judge: `evals/nyt_connections/judge.py`. Refresh: model-specific (Phase E). Bank: dict, id from `id`.
Note: plan 0062: every slot, label and stability is Qwen3.6-27B's own; a new subject re-samples its answers and naming turn and rebuilds the options (`adapt nyt_connections`, plan 0060 Phase E). The judge looks nothing up by registered id: an adapted item is read from $WSB_BANK_ROOT and resolved against the mirror by nyt_id
REQUIRED_ITEM_FIELDS: `id`, `nyt_id`, `mc`.
SUBJECT_FIELDS: `mc`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `nyt_id` | yes | exit | copy-verbatim | nyt.py (bank_items, words, render); readplan.py (_nyt_rows) | the NYT puzzle number; words and NYT labels are fetched from the pinned mirror |
| item | `mc` | yes | exit | subject | evals/nyt_connections/judge.py (slot_options, _run_summary, rows) | one slot per Qwen group: members (indices into the shuffled 16), Qwen's follow-up label, stability over 16 samples, stable / correct / gold_same / model_specific, and the frozen option list (same-connection filter applied) |
| resource | `Eyefyre/NYT-Connections-Answers connections.json @0c42b26 (sha256-pinned)` |  | exit | copy-verbatim | nyt.py (fetch, puzzles) | ids-only bank: text only at plan time; WSB_NO_NYT -> no rows |
| qwen | `min_full_positions=12` |  | - | subject | nyt_connections/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### poetry

Judge: `evals/poetry/{judge,options}.py`. Refresh: rebuild (v5). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `intermediates`, `mc`, `qwen_commits`, `line_one_end`.
SUBJECT_FIELDS: `intermediates`, `mc`, `qwen_commits`, `gate_variant`, `prompt_only_opus`, `regate`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:756-797 |  |
| item | `intermediates` | yes | exit | subject | poetry/options.py:22-23 | the subject's word |
| item | `mc.candidates` | yes | exit | subject | poetry/options.py:131-150; judge.py:368 | absent, or < N_DISTRACTORS left after the gold and qwen_commits are removed: ValueError before any cell (whole run) (checked) |
| item | `qwen_commits` | yes | silent | subject | poetry/options.py:74-76,117 | the SUBJECT's commitments under this key; absent: not excluded from options |
| item | `line_one_end` | yes | fallback | build | poetry/options.py:26-33 |  |
| item | `spellings` |  | silent | build | poetry/judge.py:390-391 | optional extra forms |
| item | `gate_variant` |  | silent | subject | readplan.py:766 | honoured only with a truthy `adapt` block |
| item | `prompt_only_opus` |  | - | subject | - | per-item record (SUBJECT_FIELDS) |
| item | `regate` |  | - | subject | - | regate.site_words (SUBJECT_FIELDS) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### relational_multihop

Judge: `evals/relational_multihop/{judge,gate,score}.py`. Refresh: none (re-read). Bank: list, id from `id`.
REQUIRED_ITEM_FIELDS: `id`, `stimulus`, `hop1`, `hop2`, `scene`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `stimulus` | yes | exit | copy-verbatim | readplan.py:390-403,905-907 | '. In other words' exactly once |
| item | `hop1` | yes | exit | copy-verbatim | relational_multihop/judge.py:76-77,138,416 | a NEAR key |
| item | `hop2` | yes | exit | copy-verbatim | relational_multihop/judge.py:76-77,138,416 | a NEAR key |
| item | `scene` | yes | exit | copy-verbatim | relational_multihop/score.py:94 |  |
| id_rule | `rel-{scene}-a / -b` |  | silent | hazard | relational_multihop/score.py:95 | pair_consistency (report-only) (checked) |
| qwen | `BLANK_TOKEN "'s"` |  | - | subject | relational_multihop/judge.py:169-187 |  |
| qwen | `min_full_positions=8` |  | - | subject | relational_multihop/__init__.py:23-25 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### role_bound_association

Judge: `evals/role_bound_association/{judge,gate,score}.py`. Refresh: upgrade (judge-code overlay, plan 0060 §3). Bank: list, id from `id`.
Note: adapted/qwen3.5-2b/role_bound_association.json is an empty list.
REQUIRED_ITEM_FIELDS: `id`, `pair_id`, `direction`, `role_a`, `role_b`, `action`, `names`, `stimulus`, `stereotypicality`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `id` | yes | exit | build | mcjudge.py:149-151 | raw id (bare-list bank) |
| item | `pair_id` | yes | exit | build | role_bound_association/judge.py:104,143,270; score.py:30 |  |
| item | `direction` | yes | exit | build | role_bound_association/judge.py:147,292; score.py:41 |  |
| item | `role_a` | yes | exit | build | role_bound_association/judge.py:100,274 |  |
| item | `role_b` | yes | exit | build | role_bound_association/judge.py:100,274 |  |
| item | `action` | yes | exit | build | role_bound_association/judge.py:143,290 |  |
| item | `names` | yes | exit | build | role_bound_association/judge.py:101,275 | {a, b} |
| item | `stimulus` | yes | exit | build | readplan.py:931; judge.py:278 |  |
| item | `stereotypicality` | yes | silent | build | role_bound_association/score.py:120-125 | absent: dropped from by_stereotypicality / incongruent_pass_rate |
| resource | `evals/role_bound_association/distractors_v3.json` |  | fallback | hazard | role_bound_association/judge.py:249-272 | keyed by pair_id (REPO_ROOT, not the bank root); missing = oa-v2 block (options-only 0.230 vs uniform 0.008) (checked) |
| resource | `evals/role_bound_association/roles_v1.json` |  | silent | hazard | role_bound_association/gate.py:37-69 | keyed by role word; feeds role_ref and conflicting_role (checked) |
| resource | `evals/role_bound_association/actions_v1.json` |  | silent | hazard | role_bound_association/gate.py:413-447 | keyed by action word (checked) |
| resource | `evals/role_bound_association/display_terms_v1.json` |  | silent | build | role_bound_association/judge.py:179-218 | keyed by role; display-only '(also: …)' terms |
| qwen | `story_guard BPE cleaning (Ġ/Ċ only)` |  | - | hazard | role_bound_association/judge.py:332-333 | a SentencePiece (▁) tokenizer never finds the suffix: the guard passes all |
| qwen | `chat_summarize render + SUMMARIZE_SUFFIX` |  | - | subject | readplan.py:23, 925-941 | positions from the subject's own render (suffix_text_then_tail) |
| qwen | `min_full_positions=19` |  | - | subject | role_bound_association/__init__.py:25 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### typo

Judge: `basic/{family,judge}.py`. Refresh: superseded by typo_mt (not refilled). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `intermediates`, `readout`.
SUBJECT_FIELDS: `readout`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:455-514 |  |
| item | `intermediates` | yes | silent | copy-verbatim | banks.py:38-55 | the targets; absent = an empty targets line |
| item | `readout` | yes | silent | subject | readplan.py:455-514 | offsets in the subject's tokens; absent = final_token |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### typo_mt

Judge: `multitoken/family.py + regex.py (scorer regex)`. Refresh: upgrade (header only). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `units`, `probe_token_lens`, `typo_word`, `target`.
SUBJECT_FIELDS: `probe_token_lens`.
Header: `contract.multi_token`, `contract.include_target`, `contract.native_langs`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | readplan.py:687-704 |  |
| item | `units` | yes | exit | copy-verbatim | multitoken/regex.py:363-425; mcrx.py:99-111 | role / forms / required / multi_token |
| header | `contract.multi_token` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered True; absent defaults from header.family |
| header | `contract.include_target` | yes | silent | copy-verbatim | multitoken/regex.py:283-298 | registered False; absent = True (adds a target unit / needs target lens) |
| header | `contract.native_langs` | adapted | silent | subject | banks.py:76-91 | absent = Qwen's ('en','zh'); per-subject measurement (plan 0060 A1.10); required of an adapted bank (typo_mt's registered header has none) |
| qwen | `LANGUAGE_NAMES {en,zh,ja,ko}` |  | - | hazard | multitoken/prompts.py:30 | any other native code is rendered as the raw ISO code in the judge prompt |
| item | `probe_token_lens` | yes | exit | subject | multitoken/regex.py:346-360 | Qwen token counts per form; restamped on the subject (adapt/run.py:358-386) |
| item | `typo_word` | yes | exit | copy-verbatim | readplan.py:664-686 |  |
| item | `target` | yes | exit | copy-verbatim | readplan.py:664-686 | first_diff site |
| header | `version` |  | silent | copy-verbatim | multitoken/family.py:244-247 | typo-v2 tag only |
| id_rule | `tyh-arith-* (retired ids)` |  | - | hazard | evals/typo_mt/items_v2.json header dropped.names | no code rule: an arith item copied from v1 is scored like any other |
| qwen | `min_full_positions=1` |  | - | subject | typo_mt/__init__.py | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### unverbalized_hint

Judge: `evals/unverbalized_hint/judge.py`. Refresh: retired (plan 0058). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `pair_id`, `role`, `positions`, `text`, `hint`.
SUBJECT_FIELDS: `role`, `positions`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `pair_id` | yes | exit | copy-verbatim | unverbalized_hint/judge.py:184-196 |  |
| item | `role` | yes | exit | subject | unverbalized_hint/judge.py:184-196 | I/N from Qwen behaviour |
| item | `positions` | yes | exit | subject | unverbalized_hint/judge.py:525 | Qwen token indices |
| item | `text` | yes | exit | copy-verbatim | readplan.py:1056-1073 |  |
| item | `hint` | yes | silent | copy-verbatim | unverbalized_hint/judge.py:172-173 |  (checked) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### user_modeling

Judge: `evals/user_modeling/{judge,options,aliases,score}.py`. Refresh: upgrade (per-set option-pool file, plan 0060 §3). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `attr_class`, `attr`, `messages`, `attr_label`, `subfamily`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `attr_class` | yes | exit | build | user_modeling/options.py:96,131 |  (checked) |
| item | `attr` | yes | exit | build | user_modeling/options.py:131 | the gold (checked) |
| item | `messages` | yes | exit | build | user_modeling/judge.py:550,647; readplan.py:860 |  |
| item | `attr_label` | yes | silent | build | user_modeling/judge.py:606-607 | absent: the question says 'attribute' |
| item | `subfamily` | yes | silent | build | user_modeling/judge.py:555; score.py:110 | absent: missing from by_subfamily |
| resource | `aliases.VALUE_ALIASES / UM_OPTION_POOL` |  | exit | hazard | user_modeling/options.py:56-96 | keyed by gold value; options build silently, a verified gold pick raises |
| resource | `aliases.UM_EXCLUDE / NEIGHBOURS` |  | silent | hazard | user_modeling/options.py:95,133 | keyed by gold value; missing = no exclusions / forced neighbours |
| resource | `aliases.COUNTRY_REGIONS` |  | silent | hazard | user_modeling/options.py:100-101 | Country golds only (checked) |
| qwen | `chat_context render, every position` |  | - | subject | readplan.py:849-869 | positions from the subject's own render |
| qwen | `min_full_positions=37` |  | - | subject | user_modeling/__init__.py:22-24 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

### wrong_intermediate

Judge: `evals/wrong_intermediate/judge.py`. Refresh: model-specific (Phase E). Bank: dict, id from `name`.
REQUIRED_ITEM_FIELDS: `name`, `prompt`, `readout`, `template`, `mc`.
SUBJECT_FIELDS: `mc`.

| kind | input | req | if absent | class | where | note |
|---|---|---|---|---|---|---|
| item | `name` | yes | exit | build | banks.py:18-35 | id = label_of(name); new id for adapted-only |
| item | `prompt` | yes | exit | copy-verbatim | wrong_intermediate/judge.py:388-405 |  (checked) |
| item | `readout` | yes | fallback | copy-verbatim | readplan.py:487-494 | absent: final_token full read |
| item | `template` | yes | silent | copy-verbatim | wrong_intermediate/judge.py:342-360,437 |  |
| item | `mc.order` | yes | exit | build | wrong_intermediate/judge.py:48,278,310 | exactly 6 |
| item | `mc.gold` | yes | exit | subject | wrong_intermediate/judge.py:284,309 | the subject's wrong intermediate |
| item | `mc.contrast` | yes | exit | copy-verbatim | wrong_intermediate/judge.py:284,444 |  |
| item | `mc.forms` | yes | exit | build | wrong_intermediate/judge.py:308,431-451 |  |
| qwen | `min_full_positions=9` |  | - | subject | wrong_intermediate/__init__.py:24-25 | Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308) |
| qwen | `GRID layers (Qwen 64 blocks)` |  | - | subject | readplan.py:588-627 | remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it) |

<!-- end judge_inputs table -->
