# 0108: `association_hard`, a hard association family (obscure and compound concepts), registered in full

Camila, 2026-11-20/21, on the existing `association` family (91 items; a scene implies a
concept it never names; 8-way MC + cannot tell): it is too easy, and the hard version "should
be hard for the olens and nla level methods as well". Her last instruction on the bank: "just
focus on the 68 obscure items but try to get some more to get to 100". Earlier: the hard
association goes in the fast and core tiers and the original `association` stays full-only.
She has since been shown a viewer of the candidate bank and has NOT reconfirmed core / fast.

So this plan registers a NEW family `association_hard` (category `association`) **in the
`full` tier only**, exactly as `user_modeling_hard` was registered by plan 0106: no entry in
`tiers.CORE`, no fast cut, floors pending. Core, fast and the fast cut are deferred to her
decision (§11, §12). **The `association` family's files, stamps, cached calls, floors, ATI
entry and manifest rows do not move** (§0, §1.2).

Base: `origin/main` @ 34de102e (plan 0106 merged). Worktree `/root/tmp/wsb-0108`, branch
`camila/0108-association-hard`. This file is the only change of the planning step; nothing
is implemented yet.

Two things the owner should read before anything else, because both go against what she asked
for (details in §A and §12):

1. **With the judge artefacts removed the bank is NOT hard for the Oracle lens or the NLA.**
   The artefacts were hiding passes, not misses: on the 109 candidates the Oracle lens (RL)
   goes from 94 to 99 of 109, the NLA from 82 to 90, and the prompt-only reader from 104 to
   107 (0.98). The J-lens stays near the floor (9 to 14). The family separates token lenses
   from prose lenses; it does not separate a strong prose lens from a reader of the text.
2. **The bank this plan can register without new authoring has 93 items, not 100**: 16 of the
   109 are reproducibly guessable from their options alone (§2.2).

## A. Investigation this plan rests on (2026-11-23; scratch `/root/tmp/assoc-hard/plan0108/`)

Nothing below was read from an earlier report without being re-run. Raw readouts of the three
lens arms survive in the viewer build's shards (`/root/tmp/assoc-hard/viewer_build/shards/`),
so every arm was re-judged end to end through `wsbench judge` (stored per-layer and stage-2
digests replayed from the stored caches, copied; the judge calls fresh), not on a sample.
Scripts, logs and results: `plan0108/scripts`, `plan0108/proto`, `plan0108/runs`.

### A.1 What "the 68 obscure items" are, and how the 109 relate to them

The first full authoring run (2026-11-20/21, `full/out/README.md`) kept 81 items: 13 of design
A (peripheral concepts) and **68 of design B** = 40 `obscure` + 14 `complex_qualified` + 14
`complex_unnatural` (`full/out/b_kept68.json`). The owner dropped design A and called the 68
"the obscure items". The top-up wave b3 added 60 gated items (68 + 60 = 128); 19 persistent
options-only leakers were then dropped: **109 = 58 of the 68 + 51 of wave b3** = 56 obscure +
28 complex_qualified + 25 complex_unnatural (`full/out/bank_final_B.json`, sha256
f233ff5b…406005). The 109 ARE the outcome of her instruction; none of them is "extra".

### A.2 Baseline: the registered `association` judge on the FINAL lists

The stored results (94 / 82 / 9 of 109) pooled two reads, and six first-read items were judged
on an option list that was rebuilt afterwards (underwater hockey, a priest hole, a pamonha,
una zampogna, batik, a tidal bore; 21 items also had accepted forms added later). Re-judging
all 109 with the registered judge (`assoc-mc-2026-11-01-v3+gate-a2`) on the final lists and
forms (`runs/base-*`) gives the same totals and **no verdict moved on any of the six**: 94 /
82 / 9. There is no option-list artefact in the lens numbers. Prompt-only readers on the same
footing: `po-opus-v1` 104, the four-bullet pilot reader 102.

### A.3 Every lens fail, classified (baseline, 109 items)

Read from the judged record, the digest the judge saw and the raw readouts (regular-expression
counts over every raw line, then by hand; the earlier Opus classification in
`full/lensread*/analysis.json` was used as a second opinion and disagrees in one item, the
rubber pickaxe, where it missed the stating line).

Classes. *Real miss*: no readout line states the whole gold. *Contested*: lines state the gold
AND a rival listed option (or a spray of unlisted variants) about as often, so by the
family's own conflict rule nothing wins; a correct fail. *Compound artefact*: a line the judge
saw states the whole compound, no rival is comparably stated, the judge picked the bare head,
a sibling compound or cannot tell. *Other judge miss*: the same for a non-compound gold.
*Quote-gate artefact*: the judge picked the gold and the gate refused it wrongly. *Digest
loss*: the one stating line is not in the digest. *Option-list artefact*: none (A.2).

| arm | fails | real miss | contested | compound artefact | other judge miss | quote gate | digest loss |
|---|---|---|---|---|---|---|---|
| Oracle lens (RL) `s3d-rl600` | 15 | 4 | 4 | 5 | 1 | 1 | 0 |
| NLA `mlnla11-rl600` | 27 | 15 | 2 | 8 | 1 | 0 | 1 |
| J-lens `jlens-public` | 100 | 93 | 0 | 5 | 0 | 2 | 0 |

- s3d. Real: a pamonha, a tidal bore, a green flash, a lyrebird. Contested: a red tide (2
  lines against 22 for the jellyfish bloom), ein Archiv in einem U-Boot (49 lines say archive
  and submarine, 47 say library and submarine), a drowned forest (10 against 8 for a drowned
  village or town), a dress made of glass (3 weak lines, "transforms into glass", against 13
  that give the dress another material). Compound: un cuchillo desafilado (15 lines say dull or
  blunt knife; picked `un cuchillo`), a pitchfork made of chocolate, a bald sheep, a hammock
  made of stone, a boat made of cheese (picked `a boat made of bread`, stated once). Other: a
  flying buttress (one clear line, cannot tell). Quote gate: a cinema in a submarine (two lines
  hold a listed form; steps 3b / 3c cannot credit them because the gold form contains the
  option `a submarine`).
  The earlier report's "11 artefacts, 4 real misses" reproduces as 11 fails in which a line
  states the gold; **4 of those 11 are contested, not judge errors**, and the right count of
  judge errors is 7.
- NLA. Compound: a penguin at the stock exchange, a pickaxe made of rubber, a pitchfork made of
  chocolate, a capsized lifeboat, a dry fountain, a vegetarian dog, a pulpit made of ice, a
  cinema in a submarine. Other: an astrolabe (49 lines against 16 for the sundial; cannot
  tell). Contested: a platypus (11 lines; otter 10, beaver 14), a solar halo (named only inside
  runs of alternatives). Digest loss: un coche de galleta ("A race car made of cookies": the
  plural defeats the listed form, so the line is not pinned and the judge never saw it). Real:
  the other 15 (korfball among them: one line offers it as a hedge, the readouts answer
  netball).
- J-lens. Compound (one token list holds the head and the qualifier, the judge picked the
  bare head): un boulanger intolérant au gluten, a flat tyre, un cuchillo desafilado, a
  dried-up river, a bald sheep. Quote gate: ein Ginkgobaum (`银杏`) and kimchi (`泡菜`), a
  faithful Chinese name that the accepted forms do not list (`gold_unlisted_script`).

Three mechanisms explain every judge error:

1. **The registered prompt cannot credit a compound next to its bare head.** "A single line
   that holds two or more of the listed options singles out none" and "singled out by clearly
   more lines than any other": every line that says "a dull knife" also holds the option `a
   knife`, and every scene paraphrase names the head. The bare head wins by construction.
2. **The accepted forms carry articles.** The registered bank's golds are bare (`chess`,
   `carnaval`); the candidate's are `a red tide`, `an astrolabe`. `mc.form_in("…levels of red
   tide toxins…", ["a red tide"])` is false, so the listed-form credit, the rare-option pins
   and steps 3b / 3c under-fire, for the gold and (symmetrically) for every distractor.
3. **Steps 3b / 3c treat the bare head as a competitor of the form that contains it.**

### A.4 The prototype and its test

`plan0108/proto/proto.py` runs the registered judge with: (P1) every form of every option
also without its leading article (`proto/bank_proto.py`; 604 gold forms, 679 of 763
distractors); (P2) the system prompt of §3.3; (P3) the 3b / 3c fix of §3.4. Every arm was
judged three times with fresh judge calls on the same digests, and an item passes on a
majority of the three (§3.5). Before = A.2; after = the prototype's majority of three.

| arm | before | after | single draws | fixed | new fail | on the 93 of §2.2: before → after |
|---|---|---|---|---|---|---|
| Oracle lens (RL) | 94 | **99** | 99, 100, 100 | 8 | 3 | 81 → 85 (0.914) |
| NLA | 82 | **90** | 91, 88, 88 | 10 | 2 | 71 → 78 (0.839) |
| J-lens | 9 | **14** | 14, 14, 13 | 6 | 1 | 6 → 12 (0.129) |
| prompt-only `po-opus-v1` (the floor) | 104 | **107** | 108, 106, 107 | 3 | 0 | 89 → 91 (0.978) |
| prompt-only, four bullets | 102 | **106** | 107, 106, 106 | 4 | 0 | 87 → 90 (0.968) |

Every flip was read:

- s3d, fail → pass (8): the seven judge errors of A.3 are all fixed and each quoted line states
  the whole compound; the eighth, a tidal bore, passes three draws of three on "a massive tidal
  wave allows surfers to ride for miles inland", a description credit I rate borderline (the
  earlier audit called the item a real miss). Pass → fail (3): an astrolabe (53 raw lines say
  sundial, 49 astrolabe: contested, the baseline pass was a coin flip; correct), un cajón
  flamenco ("sitting on an open crate like a drum": the baseline credited a description that
  does not name the instrument; defensible) and a steelpan ("steel drums being struck" in a
  warehouse: ambiguous; defensible). The four contested items still fail, as they should.
- NLA, fail → pass (10): the eight compound artefacts and the astrolabe are fixed and right;
  a solar halo passes two draws of three on "halo around sun" (borderline: the readouts name
  it among alternatives). Pass → fail (2): a tidal bore ("a tidal-bore/waterfall
  competition", a hedge; correct) and a bakery inside an operating room (two of three quote
  re-judges refused "a bakery inside an emergency room" / "a bakery kitchen disguised as an
  operating theater"; a borderline false fail). Still failing: the digest loss, the two
  contested items, the real misses.
- J-lens, fail → pass (6): four compounds whose head and qualifier sit in one token list
  (`flat | tire`, `river | dried`, `knife | dull | blunt`, `allergic | gluten | … | baker`) are
  right under the shared token rule ("tokens of one list may combine"); a seismograph
  (`seismic | sensors | recording`) and a library in a helicopter (`helicopter | library`:
  co-occurrence, the token list cannot say "in") are borderline. Pass → fail: a tally stick.
  The two Chinese-form artefacts are NOT fixed by the prototype (they need the forms pass of
  §2.4).
- Prompt-only: all seven fixed items are right ("untangling a knotted mooring rope" for a
  tangled rope; "a black lace veil (a mantilla)"). Of the two that still fail, one is correct
  under the one-line rule (the reader says "a military vessel doubling as an archive" in one
  bullet and "submarine" in another) and one is a false fail (a quote spanning two bullets).

Passes (30 per prose arm drawn with seed 108 from the passes after, all 14 of the J-lens):
s3d 30 of 30 state the whole gold (one lenient: "饼干 (cookie) as the car"); NLA 29 of 30
(one borderline: "nautical/hospital lighthouse imagery" for a hospital inside a lighthouse);
J-lens 11 of 14 with the three borderline ones named above.

What each part buys (single draws, `runs/p0-*`): the article-less forms and the gate fix under
the OLD prompt give 96 / 79 / 104 for s3d / NLA / prompt-only against 94 / 82 / 104; the
compound rule in the prompt is what removes the artefacts. Plural-tolerant pins (§3.2):
tested as a fourth change on one draw (`runs/p2-*`): the NLA's un coche de galleta gets its
one stating line pinned and passes; no other verdict moves on s3d, the NLA or the prompt-only
reader.

### A.5 Noise: why three draws

A single judging is unstable on this bank. Same digests, three independent draws of the
prototype: 8 of 109 s3d items do not agree across the draws (NLA 7, J-lens 7). A fresh
stage-2 digest plus a fresh draw of the REGISTERED judge moved 9 of 109 s3d items (5 up, 4
down). The unstable items are the contested ones and the description credits.
With a majority of three the instrument is stable enough: two independent majority-of-three
judgings (six draws, `runs/p1*`, `p1r2..r6`) give 99 and 100 for s3d with 3 of 109 items
differing (an astrolabe, l'affogato, a dress made of glass) and 90 and 90 for the NLA with 2
differing (ein Archiv in einem U-Boot, a tidal bore); on the 93 items of §2.2 that is one
item per arm. Over six draws 95 of 109 s3d items pass every draw and 5 none.
The quote-miss re-ask plays no part: 0 to 2 draws per arm used it and the first-ask figure
equals the headline for every arm (§4.2 still reports it).

### A.6 Guessability from the options alone

- LLM guessers (`lucky_guessing` blind and described, 5 draws each; the run's `final`
  measurement and a confirmation measurement made for this plan, `runs/guess_confirm.json`):
  family level 0.026 / 0.039 blind and 0.161 / 0.161 described against 0.125. The excess is
  concentrated: **16 items are picked at least 3 times of 5 by a guesser in BOTH
  measurements** (18 in the first; the earlier README put that down to noise, the
  confirmation shows it is not). Without them the described guesser is at 0.039 / 0.034.
- A model-free structural guesser finds the gold of the complex kinds. The lists are the grid
  {A+B (gold), A+B′, A′+B, A′+B′, B, B′, C+B′, A′+D}: the gold is the only option whose
  qualifier occurs in exactly two options and whose head occurs in exactly three. The rule
  "pick the option with that signature" (`scripts/structural.py`) hits **0.82 of the 53
  complex items** (chance 0.125). No LLM guesser found it (blind 0.03), which is why the run
  missed it; the leakage standard this repo applies (moral_rationale's `side_prior`) counts
  such a reader. §2.3 removes it by rule.

## 0. What does not move

Nothing of any existing family: no bank, prompt, `prompt_version`, call key, cached call,
`plan_sha`, option list, ATI entry, floor, tier, or fast entry under any fast version. In
particular **`association` keeps `CALL_VERSION = "assoc-mc-2026-11-01-v3"`, result stamp
`assoc-mc-2026-11-01-v3+gate-a2+bank-v5`, bank `items_v5.json` on `items_v3.json`'s read plan,
`ASSOC_SEED`, its `lite_rule.json`, its ledger entry of plan 0107, its floors and its (empty)
ATI entry, and stays in `full` only.** `tiers.CORE` keeps its 18 families and `fast.DEFAULT`
stays `fast-v4`. The shared code this plan changes is add-only table entries for the new key
and one new `readplan` branch (§1.3); each point restates what it must leave alone.

## 1. Package and registration

### 1.1 Design: a separate package that imports, never a family parameter

`src/wsbench/evals/association/association_hard/` is its own package with its own prompts,
judge, gate and bank module. It imports pure functions and no prompt:

- `association.judge.holding_lines` and `flat_list_void` (the token-list void, step 2b; both
  take everything they need as arguments), and the constant `FLAT_RUN_MIN`;
- `conjunctive_association.judge.draw_key`, `majority`, `n_draws` (the draw helpers
  `user_modeling`, `user_modeling_hard`, `role_bound_association` and `moral_rationale`
  already share).

It does NOT import `association.judge.load_items`, `bank_concepts`, `build_options`,
`pin_options`, `gate_gold`, `_names_only_gold` or any `association.prompts` constant: the first
four read the `association` bank or seed by name, and the gate and the prompt are what
differs. The few lines it needs of them (the sentence splitter, the negation pattern, the pin
loop) are written out in the new `gate.py` / `judge.py`.

Rejected: threading a `family` or `bank` parameter through `association/judge.py`. Its
`FAMILY`, `ASSOC_SEED`, `HOMOGRAPH_GOLDS` and `load_items` are module state, and
`scripts/manifest_0101.py` hashes every upper-case constant of `association/prompts.py` and
the `*VERSION*` strings of its modules, so a new constant there moves a manifest row of a
family that already carries a ledger entry (plan 0107) and would need a stamp bump it has no
reason for.

### 1.2 Guarantee for the existing family, and its tests

1. **No file under `src/wsbench/evals/association/association/` or
   `evals/association/association/` is edited.** Review gate: `git diff --stat origin/main --
   src/wsbench/evals/association/association evals/association/association
   examples/readouts/association.jsonl examples/readouts/association.jsonl.meta.json` prints
   nothing.
2. T1 (`tests/test_rename_0101.py`): the `association` entry of
   `tests/golden/manifest_0101_declared.json` is not touched and still verifies; every
   shared-table edit of §1.3 is an ADD of the key `association_hard` (the manifest records
   table membership per family), no existing tuple or dict entry is reordered or widened.
3. `tests/test_basic_association.py`, `test_association_v2.py`, `test_association_v3.py`,
   `test_association_proper_noun_gate.py`, `test_summary_mode_assoc3.py`, the `association`
   rows of `test_readplan.py`, `test_lucky_guessing.py`, `test_text_inversion.py`,
   `test_fast_subset.py`, `test_logit_lens_floor.py` and `test_po_floors_r3.py` stay
   byte-identical.
4. New test `test_easy_family_is_untouched` (`tests/test_association_hard.py`): the
   registered `association` spec has `prompt_version ==
   "assoc-mc-2026-11-01-v3+gate-a2+bank-v5"`, `bank.name == "items_v5.json"`,
   `min_full_positions == 19`, `tiers.tier_of("association") == "full"`, and
   `association.prompts.PROMPTS` has the sha256 recorded in the test (a literal computed once
   on 34de102e).

### 1.3 Every hard-coded-name site (verified on 34de102e)

Sites that GET an entry for `association_hard`:

| site | what it gets |
|---|---|
| `src/wsbench/evals/association/association_hard/{__init__,prompts,judge,gate,bank}.py` | new package (§1.4, §2, §3, §4) |
| `evals/association/association_hard/{items.json,grid_v1.json,forms_v1.json,README.md}` | bank, the two frozen builder inputs (§2.3, §2.4), README with every prompt verbatim |
| `examples/readouts/association_hard.jsonl` (+ `.meta.json`) | toy rows for 3 items (one per kind), layers 20 and 44, prose samples: one states the compound, one only the head, one a sibling |
| `src/wsbench/readplan.py` `_plan` | a NEW branch `if family == "association_hard":` placed before the `association` / conjunctive / role-bound branch, building the same `ReadSpec` (`"chat_summarize"`, `{"kind": "suffix_text_then_tail", "text": SUMMARIZE_SUFFIX.strip()}`, `GRID`, `text=it["prompt"]`, `suffix=SUMMARIZE_SUFFIX`, `lite_positions=dict(SAME)`). **The existing three-family branch, `LITE_SITE_FAMILIES` and `frozen_lite_rule` are not edited** (no `lite_rule.json` for the new family: it sets `same` itself, as `user_modeling_hard`'s branch does), so their `plan_sha`s stay |
| `src/wsbench/baselines/lucky_guessing.py` | `DESCRIPTIONS["association_hard"]`, a builder `_association_hard` (options in bank order), `BUILDERS`; `TOPIC_FAMILIES` + the key (the builder supplies `meta["topic"] = fine_topic(mc)`, as `_association` does). `FAMILY_RULES`, `GUESS_QUESTION` unchanged |
| `src/wsbench/baselines/text_inversion.py` `NOT_GATED` | one entry (§6.4) |
| `src/wsbench/capable/questions.py` | a builder `_association_hard` + `BUILDERS` entry (§6.5); `tests/golden/capable_questions.json` gains the family's block |
| `src/wsbench/adapt/families.py` `NOT_ADAPTED` | one entry (§6.6); `FAMILIES`, `REGENERATE` and the `association` entries of `adapt/{lint,author,refill,run,dataround,mcstage,judge_inputs}.py` are not edited |
| `scripts/readme_evals_table.py` | one description line; the README table is regenerated |
| `scripts/summary_mode_compare.py` item rules | `"association_hard": {"assoc-hard-v1+gate-h1": "assoc-hard-v1+gate-h1+maj3v"}` |
| `.claude/skills/wsb-new-questions/scripts/validate_bank.py` `NOT_AUTHORABLE` | "compound items with a frozen option grid, built by its own builder (plan 0108)" |
| `.claude/skills/adapt-bank/{SKILL.md,references/families.md}` | scope sentence and one table row (not adapted) |
| `README.md`, `docs/evals.md`, `docs/judges.md`, `docs/tiers.md`, `docs/read_sites.md`, `AGENTS.md`, `CLAUDE.md`, `evals/baselines/README.md`, `plans/README.md` | §7.3 |
| `tests/golden/manifest_0101_declared.json` | the new family's ledger entry (§7.4) |

Sites that name `association` and get NOTHING, with the reason:

| site | why not |
|---|---|
| `readplan.LITE_SITE_FAMILIES`, `frozen_lite_rule`, the three-family branch | above |
| `digest.FAMILY_DEFAULTS` | `association` has no entry and the new family needs none (default digest model, default caps; A.4 was measured with the defaults) |
| `basic/prompts.py` `DIGEST_TASK_NOTES_TEXT["association"]` | the bank judge's note of the test-only v1 registration; the new family has its own task note (§3.1) |
| `adapt/*` (`FAMILIES`, `lint`, `author.Brief`, `refill`, `run`, `dataround`, `mcstage`, `judge_inputs`) | adapted sets do not get this family (§6.6) |
| `capable.questions._asked("association", …)` | belongs to the easy family |
| `tiers.CORE`, `fast.py`, `evals/fast/*`, `scripts/fast_cut_core_half.py` `UNITS` | deferred (§11) |
| `prompt_only.SATURATED` | only if the measured floor is at the ceiling and the owner asks (§6.1) |
| `registry.py` | nothing: `register` reads the category from the package tree |

### 1.4 `__init__.py`

```python
SPEC = register(
    EvalSpec(
        name="association_hard",
        title="Association (hard)",
        group="association",
        bank=family_rel("association_hard") / "items.json",
        judge=JudgeConfig(prompt_version=PROMPT_VERSION),  # "assoc-hard-v1+gate-h1"
        metric="pass_rate",
        higher_is_better=True,
        run=judge.run,
        task_note=prompts.DIGEST_TASK_NOTE,
        min_full_positions=19,
        full_contiguous=True,  # as association
        calls_per_arm="≈ 0.3k MC (3 draws) + up to 0.3k quote re-judges summary; native ≈ 1k x k",
    )
)
```

No `sources` (in-house items, no credit line). The title must not make `tests/test_readme.py`
match the easy family's entry: it finds an entry by a line starting `**<title>**`, and
`**Association (hard)**` does not start with `**Association**` followed by ` —` (the same
situation as "User modelling (hard)"; a test asserts both entries are found once). No "—" in
`calls_per_arm` or the title (`tests/test_list.py`). Default judge (`claude-opus-5-5`), no pin,
no aux model.

## 2. Bank v1: 93 items

### 2.1 File, header, item fields

`evals/association/association_hard/items.json`, the wrapped name-keyed shape
(`banks.load_bank`; every name satisfies `label_of(name) == name`; the candidate's names are
kept, they key the authoring records). Header: `family` ("association-hard"), `version` (1),
`built`, `subject` ("Qwen3.6-27B"), `render` ("chat_summarize"), `n_items`, `by_kind`,
`by_lang`, `by_domain`, `gate` and `read` (one sentence each, as `items_v5.json` has),
`inclusion_rule` (§2.2, the four rules in words), `option_rule` (§2.3), `form_rule` (§2.4),
`chance` (`uniform` 0.125, `structural_by_kind`, §4.3), `edits` (the builder's tables as
applied), `known_issues` (§2.6), `source_sha256` (`bank_final_B.json`, `grid_v1.json`,
`forms_v1.json`, the two guesser measurements).

| field | content |
|---|---|
| `name` | the candidate's (`ah-<wave>-<ob|cq|cu><nn>-<slug>`) |
| `kind` | `obscure` / `complex_qualified` / `complex_unnatural`; `subfamily` = `kind` (the viewer groups on it) |
| `lang` | scene language: en 70, pt 7, es 7, it 4, fr 3, de 2 |
| `prompt` | the scene, verbatim; never edited |
| `intermediates` | `[gold]` (the association schema's key; read by the viewer) |
| `source`, `consistency`, `consistency_greedy`, `gate_variant`, `eval_render` | verbatim |
| `mc.gold` | the gold as shown, with its article |
| `mc.aliases` | accepted forms: the candidate's, each also without its leading article, plus the forms pass, minus `FORM_DROPS` (§2.4) |
| `mc.distractors` | the 7 distractors as shown |
| `mc.distractor_aliases` | per distractor: its article-less form and the forms pass's names (§2.4) |
| `mc.options` | the 8 options in the order the judge shows them; **frozen in the bank, never shuffled at run time**: `mc.seeded_shuffle(sorted(options, key=lambda x: (mc.fold(x), x)), f"assoc-hard-v1|{name}")` |
| `mc.gold_position` | 1-based index of the gold in `mc.options` |
| `mc.category` | the fine category, verbatim (the lucky guesser's topic) |
| `mc.grid` | complex kinds only: `{"heads": [B, B′], "qualifiers": [A, A′, C], "cells": {option: [qualifier, head]}}` (§2.3) |
| `authoring` | `{wave, domain, cues, chain, components, gate: {rule, greedy, n_correct, n_samples}, guess: {final: {blind, described}, confirm: {blind, described}}}` |

Stays OUT of the repo: `pilot_meta.open_question` (Qwen's replies), `qwen_summary`, the raw gate
samples, `pilot_meta.lens` (per-arm outcomes: a bank must not carry which arms failed on an
item), the list-rebuild histories. `source_sha256` ties the bank to them. `/root/tmp` is not
durable: before the PR is opened the main session archives `/root/tmp/assoc-hard` (tar.zst,
the recipe of the workspace-volume note) and records the path in the PR text.

### 2.2 Which of the 109 are in, and why

Rule, fixed before any arm's verdict on the new instrument was looked at per item and blind to
arm outcomes: **an item is dropped when an options-only guesser (blind or described) picks its
gold at least 3 times of 5 in two independent measurements [superseded: see §13] on the same list** (the run's
`final` measurement and this plan's confirmation). It is the run's own persistent-leaker rule
(`full/scripts/drop_leakers.py`: "leaking both before and after"), applied once more to the
lists that were final, and uniformly to all three kinds (the run used 5 of 5 for complex).

OUT, 16 (blind / described of 5: final, then confirmation):

| item | gold | kind | final | confirmation |
|---|---|---|---|---|
| `ah-b1-ob18-bindery-floating-inks-comb` | paper marbling | obscure | 1 / 5 | 1 / 5 |
| `ah-b1-ob23-harbour-wave-court-case` | a tsunami | obscure | 0 / 5 | 0 / 5 |
| `ah-b1-cu25-trading-floor-in-the-carriage` | a stock exchange on a train | complex_unnatural | 0 / 4 | 0 / 4 |
| `ah-b2-ob15-wax-resist-fishing-village` | batik | obscure | 0 / 4 | 0 / 4 |
| `ah-b2-ob23-tidal-bore-surf-contest` | a tidal bore | obscure | 0 / 5 | 0 / 5 |
| `ah-b2-ob35-monastery-brass-star-disc` | an astrolabe | obscure | 0 / 4 | 0 / 5 |
| `ah-b2-cq07-trawler-mooring-snarl` | a tangled rope | complex_qualified | 0 / 5 | 0 / 5 |
| `ah-b2-cq19-divers-among-the-stumps` | a drowned forest | complex_qualified | 0 / 4 | 0 / 3 |
| `ah-b3-ob01-ink-cloud-reef` | a cuttlefish | obscure | 0 / 3 | 0 / 5 |
| `ah-b3-ob15-cast-party-torched-dessert` | a baked Alaska | obscure | 0 / 4 | 2 / 5 |
| `ah-b3-ob17-pausa-prova-orchestra` | l'affogato | obscure | 0 / 5 | 0 / 4 |
| `ah-b3-ob22-courthouse-rain-monster` | a gargoyle | obscure | 0 / 5 | 0 / 5 |
| `ah-b3-ob26-convalescent-cathedral-sketch` | a flying buttress | obscure | 0 / 4 | 0 / 5 |
| `ah-b3-ob46-shepherd-split-hazel` | a tally stick | obscure | 0 / 5 | 0 / 4 |
| `ah-b3-cq28-linguist-shrunken-sweater` | a shrunken sweater | complex_qualified | 1 / 5 | 2 / 5 |
| `ah-b3-cq32-kitchen-pet-refuses-roast` | a vegetarian dog | complex_qualified | 0 / 3 | 0 / 3 |

IN, 93: every other item of `bank_final_B.json` (45 obscure, 24 complex_qualified, 24
complex_unnatural; 50 of the first run's 68 and 43 of wave b3). Three more leaked in one
measurement only and stay (a flat tyre: blind 2 then 4; una zampogna: described 3 then 1; un
tappeto bruciato: described 4 then 2); they are listed in `known_issues`.

Said plainly, because the rule is blind to it: several of the 16 are items the lenses find
hard (a tidal bore, an astrolabe, a drowned forest, l'affogato, a gargoyle, a flying buttress).
A.4's last column gives every arm on the 93. The dropped items go to
`/root/tmp/assoc-hard/plan0108/runs/two_run_leakers.json` and the archive, not into the repo;
rebuilding their lists and re-gating them belongs to the refill toward 100 (§11).

Other defects found and what happens to each (all by rules that read the scene, the options
and the forms only):

| defect | items | action |
|---|---|---|
| gold form named in the scene (`mc.form_in`, article-less forms included) | none | validation rule V8 keeps it so |
| a distractor named in the scene | `ah-b3-ob38-archivo-catedral-velo` (la mantilla): the scene says "sobre una peineta alta" and `la peineta` is a distractor | `OPTION_SWAPS`: that one distractor is replaced by a same-category member the scene does not name (the proposer sees the gold and the category only), the item re-screened 5 of 5 and its two guessers re-run; if the screen or the two-run rule fails, the item is dropped (92) |
| the complex grid identifies the gold structurally (A.6) | all 48 complex items | §2.3: one option replaced per item by rule |
| an accepted form that is an ordinary word for something else | a steelpan: `a pan` (and so `pan`); a didgeridoo: `mago`; an airship: `飞船` (spaceship); un cajón flamenco: the article-less `cajón` (a crate, in the scene's language; `a cajón` stays) | `FORM_DROPS` (§2.4) |
| a faithful name missing from the forms | ein Ginkgobaum (`银杏`), kimchi (`泡菜`); unknown others | the uniform forms pass of §2.4, for gold and distractors alike |
| six first-read items judged on an earlier list | underwater hockey, a priest hole, a pamonha, una zampogna, batik, a tidal bore | re-judged on the final lists (A.2): no verdict moved; nothing to carry |

### 2.3 Options: the bare head stays; the grid becomes symmetric

Policy, stated once: **the bare head of a compound gold is a distractor on purpose, and the
judge must be able to tell them apart.** The scene of a `complex_qualified` item all but names
the head ("el ave del árbitro" for un pájaro recién nacido); a readout that echoes the head
and never the qualifier has not surfaced the concept, and without the bare head in the list
the nearest option to "a bird" would be the gold. The artefact of A.3 came from the judge's
rule about a line that holds two options, not from the list; §3.3 changes the rule and keeps
the list.

What does change is the grid's shape. v1 lists of the complex kinds are the full grid of
three qualifiers on two heads plus the two bare heads:

```
A+B (gold)   A′+B    C+B        B
A+B′         A′+B′   C+B′       B′
```

Against the candidate's grid {A+B′, A′+B, A′+B′, B, B′, C+B′, A′+D} this replaces ONE option,
`A′+D`, by `C+B`, using components the item already has ("a spotted cow" becomes "a limping
sheep" beside a bald sheep; "a hammer made of glass" becomes "a pickaxe made of paper" beside
a pickaxe made of rubber). Every compound option then has the same signature (its qualifier
in two options, its head in four), so the structural guesser of A.6 is left with "a bare head
is never the gold": 1 in 6.

`scripts/association_hard_grid.py` (new; run once [superseded: see §13], its output `grid_v1.json` is committed and
is the builder's input): parses each complex item's seven distractors into the roles from the
gold's `components`; composes `C+B` (Opus 5.5, low effort, from the components alone, for
agreement and word order in es / pt / it / fr / de; a deterministic check then requires the
eight strings to be exactly the six cells and the two heads); runs the repo's scene screen on
the new list (Opus with scene + 8 options, the gold 5 of 5; an item that fails is reported
and dropped, never hand-fixed); re-runs the blind and described guessers on it twice and
applies §2.2's rule. The 10 complex items whose options have three content words (A.6's
table) go through the same parse; one that does not fit the 3 x 2 shape is reported for a
hand table entry, with the reason.

This edits option lists that lens arms were already judged on. It is allowed because the rule
reads nothing but the options (lesson of review r4 of plan 0106, F2); the arms are re-judged
on the new lists in §8, from stored reads (options are never in the render).

`obscure` lists are unchanged: seven other members of the gold's fine category.

### 2.4 Forms: article-less matching forms, one uniform pass, a short drop table

- **Article rule** (mechanical, in the builder): every accepted form of the gold and every
  distractor also lists itself without one leading article (a, an, the, some; un, una, uno,
  unos, unas, el, la, los, las, lo; le, les, une, des, du, l'; il, i, gli, un'; um, uma, o, os,
  as; ein, eine, einen, einem, einer, der, die, das). Inner articles stay ("archive in a
  submarine"). Prototype: 604 gold forms and 679 distractor forms added on the 109.
- **Forms pass** (`scripts/association_hard_forms.py`, run once, output `forms_v1.json`
  committed): for EVERY option of every item, gold and distractor alike and without saying
  which is which, Opus 5.5 lists the standard English and Chinese names of the concept (the
  two languages the lens arms write in, whatever the scene's language); a second call audits
  each proposed name as "the same concept" (the run's alias audit). The gold's go to
  `mc.aliases`, the distractors' to `mc.distractor_aliases`, which `association`'s bank v3
  introduced for the same reason. The proposer never sees a scene or a readout.
- **`FORM_DROPS`** (builder table, each entry with its reason): the four of §2.2, and the
  article rule never produces an article-less form listed there. Rule for an entry: the form
  alone, read with no context, is an ordinary word or name for a different thing.
- Lint (validation rule V6): no accepted form of the gold equals, after folding, a form of
  another option of its item, except that the gold's forms may CONTAIN the forms of the bare
  head and of `mc.grid` siblings (the declared components; the family's replacement for the
  adapt lint's "distractor names or is named by a gold form", which every complex item fails
  by design).

### 2.5 Builder and validation

`scripts/build_association_hard_bank.py --src <bank_final_B.json> --grid <grid_v1.json>
--forms <forms_v1.json> --guess <final.json> <confirm.json> [--out <items.json>] [--check]`.
Deterministic; refuses an existing `--out` unless `--check`; prints counts, the gold-position
histogram, the validation findings. Tables in the script, echoed in the header's `edits`:
`DROP` (the 16, each with its two measurements), `OPTION_SWAPS`, `FORM_DROPS`. **Every bank
edit goes through these tables and the two frozen inputs, never by hand in `items.json`, and
no scene is ever edited.**

`association_hard/bank.py` `validate(header, items) -> list[str]`, run by the builder, by the
judge's loader (fail closed) and by the bank tests:

- V1 names unique and label-safe; `kind` in the three; `lang` in the six.
- V2 `prompt` non-empty, 1 to 3 sentences.
- V3 `mc.options` has 8 entries, unique after folding, none a cannot-tell text; the gold is in
  it exactly once and `gold_position` points at it; the order equals the seeded shuffle of
  `assoc-hard-v1|<name>`; `set(options) == {gold} | set(distractors)`.
- V4 complex kinds: `mc.grid` has 2 heads and 3 qualifiers, its `cells` are exactly the six
  compound options, the two bare heads are the other two options, the gold is the cell
  `[qualifiers[0], heads[0]]`; obscure: no `mc.grid`.
- V5 no near-duplicate options (for two options, neither's folded content-word set is a
  subset of the other's), except a bare head inside its own compounds.
- V6 the form lint of §2.4.
- V7 every form in `FORM_DROPS` is absent; every form has its article-less twin unless
  dropped.
- V8 implied only: no gold form and no distractor form occurs in the scene (`mc.form_in`).
- V9 gate evidence: the direct gate passed (greedy correct and at least 8 of 10).
- V10 guess evidence: no item is at 3 of 5 or more in both recorded measurements.
- V11 header counts equal the items; `source_sha256` equals the inputs.
- V12 gold positions: no position holds more than 25% of the golds (reported as a histogram).

### 2.6 Recorded in `known_issues`, not edited

The three one-measurement leakers; no human review of scenes, golds or forms (all graders are
`claude-opus-5-5`); the mix is 48% obscure / 52% complex; the bank is selected on Qwen3.6-27B's
own gate; the prompt-only floor is expected at the ceiling (§6.1).

## 3. The judge

One judged unit per item in summary mode (the default): the digest of every read cell, then
ONE 8-way MC + cannot tell, asked in three independent draws; code only verifies a gold pick,
it never overrules the judge. Native mode (`opts=aggregate=native`): one MC per (item, layer),
one draw, the item passes if any layer passes (the ATI rule), as `association`.

### 3.1 Digest and task note

Default digest settings (digest-v5, layered for a multi-layer run). `DIGEST_TASK_NOTE`:

```
the model read a short scene (sometimes not in English) that evokes one thing without naming it (an object, an animal, a place, an instrument, a dish, a phenomenon or an activity, sometimes in an unusual state, made of an unusual material or set in an unusual place), and was then asked to summarize the story in one sentence; the thing, and what is unusual about it, may appear in only one or a few readouts
```

It names no gold, no option and no tool (`tests/test_task_notes.py`,
`test_prompt_tool_names.py`). It differs from `association`'s note, so the stored per-layer
digests of the candidate reads do not replay: §8 re-digests (about 1.1k digest calls per arm).

### 3.2 Pins

As `association`'s round-3 pins, written out in the new `judge.py` (never a call into
`association.judge.pin_options`, which reads the `association` bank): for every shown option,
gold and distractors alike, that no digest line names, pin up to 2 raw prose samples that
name it. An option's forms are the bank concept entry that holds it (every form the bank
lists for that concept in any item: `mc.aliases` where it is a gold, `mc.distractor_aliases`
where it is a distractor; the merge `association.judge.bank_concepts` does, written out here
over this family's bank) plus the option as shown. The pin predicate is plural-tolerant,
`mc.form_hits(text, forms, suffix=2)`; the gate's listed-form credit (§3.4 step 3) stays
exact.

### 3.3 Prompts (verbatim; `prompts.py` `PROMPTS`, and the family README under "Judge prompts")

`SYSTEM_SUMMARY` (`{READOUT_PHRASE}` = `mc.READOUT_PHRASE`, `{CANNOT}` = `mc.CANNOT`, both
interpolated at import as `association` does). `SYSTEM_NATIVE` is the same text with "You get
a digest of those readouts across every read layer and token position (described in the note
below)" replaced by "You get the readouts at one layer, grouped by token position". This is
the prototype's text, character for character (`plan0108/proto/proto.py`, `SYSTEM`):

```
You judge {READOUT_PHRASE}, recorded while the model read a passage you cannot see. You get a digest of those readouts across every read layer and token position (described in the note below) and ONE multiple-choice question: which listed concept do the readouts state? Some options are compounds: a thing with a qualifier ("a blunt knife"), a thing made of an unusual material ("a boat made of cheese"), or one place inside another ("a cinema in a submarine"); the list may also hold the bare thing ("a knife") and the same thing with another qualifier, material or place.

What states an option. Pick an option only if one readout line states that concept itself: the word in any case, inflection or spelling variant, an established synonym or alias, a faithful translation into any language, a narrower instance that necessarily entails it ("a puppy" names "dog"), or a description that depicts the concept itself. A line states a COMPOUND option only if that ONE line expresses every part of it, the thing and its qualifier, material or enclosing place, about the same object, in any wording, word order or language ("the knife was too dull to cut" states "a blunt knife"; "a fork ... described as made of chocolate" states "a pitchfork made of chocolate"). Parts found in different lines never add up, and a part the line denies is not expressed ("a metal fork that only smelled of chocolate" does not state a fork made of chocolate). Do NOT pick an option you can only infer from clues, scene details or evidence ("crayon drawings on the fridge" do not name "child"; "the blade crushed the tomatoes" does not state "blunt"); a broader category, the general topic, a merely related idea, a different word that contains the option's letters, and word fragments state nothing.

More specific wins. A line that states a compound states that compound only: it is not a line for the bare thing, nor for an option that shares only one part with it, and it does not count as a line holding two options. Lines that name only the bare thing say nothing for or against its compounds: however many they are, they never outvote a line that states a listed compound. Pick the bare thing only when lines name it and NO line states a listed compound of it. A line that gives the thing a qualifier, material or place found in no option states no compound.

Lists and conflicts. A single list or line that holds two or more DIFFERENT listed options (not a compound and its own parts) singles out none of them, whatever their order; a line that is a run of interchangeable words of one kind (animals, materials, places, names, ...) singles out none of them, whatever their rank, even when only one of them is a listed option. If lines state two or more options that exclude each other (different things, or the same thing with different qualifiers, materials or places), pick one only if it is stated as what the passage is about, or is stated by clearly more lines than any other; lines that state nothing never count toward this. If no line states an option, or no option wins, choose "{CANNOT}". Do not use world knowledge or plausibility to fill gaps.

Give a SHORT quote copied character for character from inside ONE readout line that states the option you picked; for a compound, the quote must contain every part of it.
```

The examples in it are bank values (a blunt knife, a boat made of cheese, a cinema in a
submarine, a pitchfork made of chocolate). That is deliberate and the same choice
`association`'s prompt makes with the Pentagon: every option list that holds one of them also
holds its siblings, so naming the form of a compound gives away no answer. A test asserts that
no example sentence quoted in the prompt occurs in any scene.

The other strings are `association`'s texts under the new family's own constants (own
constants, so that an edit of the easy family's prompts can never move this instrument and the
reverse): `QUESTION` ("Which concept do the readouts state?\n{listing}"), `USER_SUMMARY`,
`USER_NATIVE`, `NATIVE_NOTE_PROSE`, `RETRY_LINE`, `QUOTE_USER`, `QUOTE_USER_TOKENS`, and the
shared `SUMMARY_NOTE` / `SUMMARY_NOTE_ABSTRACTIVE`. Token readouts get the shared token-list
rule through `digest.token_note_of("association_hard")` (`mc.token_note`, never written in the
prompt): "tokens of one list may combine", so a token list states a compound when it holds a
token for each part. The quote-only re-judge (step 5) is asked under the same system prompt.

### 3.4 The gate of a gold pick (`gate.py`, `GATE_VERSION = "gate-h1"`)

`association`'s steps with two changes, each stated with what is retained:

1. Not gold: fail (distractor / cannot tell / invalid choice); a failed call: undecided.
2. The quote must verify (`digest.quote_ok`) against the item's evidence lines (summary) or
   `digest.native_lines` (native). A miss is re-asked ONCE (key `<draw key>|retry1`,
   `RETRY_LINE` appended) and the retried answer is gated from step 1; a second miss is
   `gold_unverified` (fail). *Retained from `association`; the only re-ask in the family.*
2b. Token readouts: `association.judge.flat_list_void` (imported), called as `association`
   calls it and as the prototype ran it: `others` = the other shown options AS SHOWN (with
   their articles), `rivals` = this bank's concepts with all their forms, `FLAT_RUN_MIN` = 3;
   a voided pick is `gold_flat_list` (fail). *Retained unchanged.* The bare head is one rival
   concept, so a list holding the head and the qualifier (`knife | dull | blunt`) is not a
   flat run; a test pins that, and that a list holding the gold's parts and two more bank
   concepts of its kind is voided.
3. The quote holds a listed form of the gold (`mc.form_in`, exact, case-blind): pass,
   `gold_listed_form`. *Retained.* The homograph rule (`HOMOGRAPH_GOLDS`) is not carried: no
   gold of this bank is also a place name written as a common word.
3b / 3c. The prose sample holding the quote (3b: the quote's sentence or a neighbour) or
   another evidence sentence (3c) names a listed form of the gold, not after a negation, and
   no other shown option: pass (`gold_listed_line`, `gold_listed_evidence`). **Changed: the
   other options are tested on the sentence with every matched gold form blanked out**, so
   "a submarine" inside "an upscale submarine cinema" no longer blocks the gold; **retained:
   a sentence that names another option OUTSIDE the gold's form still blocks, and both steps
   apply only when the judge's quote itself names no other option** (the same masking applies
   to that test).
4. A quote without Latin letters that holds no listed form: `gold_unlisted_script` (fail).
   *Retained*; the forms pass of §2.4 is what makes it fair to a lens that writes Chinese.
5. Otherwise ONE quote-only re-judge (`<draw key>|quote`): gold again is `gold_description`
   (pass); anything else `gold_desc_rejected` (fail); a failed call leaves the draw
   undecided. *Retained.* No statement-in-context variant, no second re-judge.

**Stamp discipline (review r3 of plan 0106, S1).** `gate.py` is code, in no call fingerprint.
Any change to it bumps `GATE_VERSION`, which is part of the result stamp; a test pins the
sha256 of `gate.py`'s source beside `GATE_VERSION` (`test_gate_source_is_pinned`), so the gate
cannot change under a stamp that has results, frozen or not. A prompt or option change bumps
`CALL_VERSION`.

### 3.5 Draws and the item verdict

`N_DRAWS = 3` in summary mode (`conjunctive_association.judge.n_draws`, so `opts=draws=1` is
the single-draw diagnostic and drops `+maj3v`). Keys: draw 0 `<id>|L-1`, then `#d1`, `#d2`
(`draw_key`); `|retry1` and `|quote` hang off the draw's key. Each draw ends pass / fail /
api_fail by §3.4; the item's verdict is `majority` of the three draw verdicts (a failed draw
never votes but counts in the half: pass / fail / api_fail is undecided). This is
`role_bound_association`'s and `user_modeling`'s rule (`+maj3v`), chosen on A.5. It is not a
re-ask: every draw is made whatever the others returned.

### 3.6 Stamps

`CALL_VERSION = "assoc-hard-v1"` keys every judge call (prompts + options). `PROMPT_VERSION =
"assoc-hard-v1+gate-h1"`; `judge.instrument(header)` adds `+bank-v<N>` for a bank of version
N >= 2 (none for v1); summary results add `+maj3v` (nothing under `opts=draws=1`, which adds
`conjunctive`'s draws stamp) and the digest tail. Option order comes from the bank, so no
seed is in the stamp.

## 4. Scoring

### 4.1 Headline and rows

`pass_rate` over decided items, bootstrap CI (`family.pass_rate_result`), `chance` 0.125. One
row per item: `id`, `gold`, `gold_pos`, `kind`, `lang`, tri-state `pass`, `outcome` and
`credit` of the first passing draw (else of draw 0), `draws` (per draw: `choice`, `pick`,
`quote`, `quote_ok`, `retried`, `outcome`, `rejudge_pick`), `unanimous`, `pass_first_ask`, and
the digest's audit fields (`col.row`). `fast.units`, `results.decided_outcomes` and the ATI
adapter take their default paths (a row-level `pass`).

### 4.2 Extras

`gate_extras` over all draws (`association`'s keys); `by_kind` (n, passed, rate per kind);
`by_lang`; `unanimous_items`; `picked_bare_head` (complex items whose majority pick is the
bare head: the readout named the thing and not what is unusual about it);
`picked_sibling`; **`pass_rate_first_ask`** (a draw that passed only after the step-2 re-ask
counts as a fail; reported beside the headline in the family README and in `breakdown_md`,
review r3 of plan 0106, S2); `breakdown_md` (by kind, the two diagnostics, first-ask), which
`wsbench report` prints under `## breakdowns` through the existing guarded block.

### 4.3 Chance

Uniform 1 in 8. A reader who knows the construction never picks a bare head: 1 in 6 on the
complex kinds. The README and the header's `chance.structural_by_kind` state both (obscure
0.125, complex 0.167; item-weighted 0.146 on 45 + 48). The lucky floor of record is the
highest measured guesser (`lucky_guessing.bar`).

## 5. Read plan

The same read as `association`, verified in `readplan._plan` on 34de102e: render
`chat_summarize` (the scene + "\n\nSummarize the preceding story in one sentence.", thinking
off), positions `suffix_text_then_tail` of the summarize suffix = **the 19 suffix and chat-tail
tokens, one contiguous run ending at the final token; scene positions are never read**; layers
`GRID` (20, 24, …, 60). The merged candidate reads confirm it: 109 items x 19 positions x 11
layers = 22,781 cells per arm. `reads=lite` = `same`. Size for v1: 93 x 209 = 19,437 cells per
11-layer arm. `min_full_positions=19`, `full_contiguous=True`.

The stored reads of the candidate (two reads, two `plan_sha`s, 141- and 51-item planning
banks) are valid inputs for v1's 93 items cell for cell, but their sidecars declare other
plans. §8 re-keys them: one readouts file per arm restricted to the 93 ids with a sidecar
declaring the registered plan's `plan_sha`, after a script has checked, per item, that the
stored cells' positions and read-site tokens equal the registered plan row's
(`scripts/association_hard_rekey.py`, scratch-only, not committed).

## 6. Floors and gates

### 6.1 Prompt-only (expected at the ceiling)

`po-opus-v1` with the Sonnet 5.5 fallback, judged by this instrument, frozen into
`evals/baselines/prompt_only_summary.json` by `baseline` / `freeze` (always with `source=`).
Prototype: 107 of 109 (91 of 93). The family README says what that means in the easy family's
words: this family separates lenses from each other and from token lenses, not a lens from a
reader of the text. Not added to `prompt_only.SATURATED` unless the owner asks. Until the
floor is frozen the family sits in `tests/test_po_floors_r3.py` `PENDING_FLOOR`
("plan 0108 validation (instrument assoc-hard-v1+gate-h1)"), which also keeps it out of
core by test.

### 6.2 Lucky guessers

Builder `_association_hard`: `Item(id, [mc.options], [mc.gold_position], meta={"topic":
fine_topic(mc), "kind": kind})`. Variants blind, described, topic, uniform (5 draws).
`DESCRIPTIONS["association_hard"]`: "which thing an unseen short scene evokes without naming
it; some options are a thing with a qualifier, an unusual material or an unusual place".
Standard, per kind and for the family: every measured guesser at most that kind's chance +
0.05 (0.175 obscure, 0.217 complex with the structural chance). Expected from A.6 on the 93:
blind 0.03, described 0.04 (measured on the candidate lists; re-measured on the rebuilt
grids). The structural reader is a test, not a model: `bank.structural_floor(items)` (the
best single-signature rule's expected hit rate per kind) must be at most 1 / 6 on the
committed bank.

### 6.3 Logit-lens L63

Needs GPU reads (`logit_lens`, layer 63, `tokens10`), judged with `layers=63`, frozen into
`evals/baselines/logit_lens.json`. Deferred with the other new reads (§11); until then the
report draws no logit-lens cell for the family and `tests/test_logit_lens_floor.py` is
unaffected (it checks committed entries).

### 6.4 ATI

`NOT_GATED["association_hard"]`: "new family (plan 0108): no panel run; the prompt-only reader
solves nearly every item, so few would survive". Skipped under `anti_text_inversion=True`;
`ati-subset-v2` unchanged.

### 6.5 Capable questions

`_association_hard`: one `Question` per item on the bank's own gate: `obscure` on
`NAME_REFERENT`, the complex kinds on the compound-aware question of the authoring run,
written out as the family's own constant `NAME_COMPOUND` ("This text describes something it
never names. Reply with one short noun phrase that names it completely, including every
element the text makes essential (a defining property of the thing, or a second thing or
circumstance it is combined with), and nothing else."); golds `[gold, *aliases]`, reference
`gate.n_correct / gate.n_samples`. AGENTS.md's table gets the row.

### 6.6 Adapt tooling

`NOT_ADAPTED["association_hard"]`: "selected on Qwen3.6-27B's own gate (plan 0108); no adapted
set carries it". **`adapt.families.FAMILIES["association"]` and every `association` entry of
the adapt modules keep serving the easy family unchanged**; `judge_inputs.uncovered_families`
already subtracts `NOT_ADAPTED`.

## 7. Tiers, fast, ledger, docs

### 7.1 Tier

`full` only. `tiers.CORE` is not edited (18 families); `tiers.tier_of("association_hard") ==
"full"`. `full` becomes 33 families (`registry.FAMILIES` 34 with the superseded `typo_st`).

### 7.2 Fast

None. Under `--fast` the family is `NotInFast` (skipped). `fast.py`, `evals/fast/` and
`scripts/fast_cut_core_half.py` are not edited.

### 7.3 Docs

- `README.md`: the evals table row (regenerated by `scripts/readme_evals_table.py`; tier
  column `-`, 93 questions), the count of evals in the full tier wherever it is stated.
- `docs/evals.md`, under Association after the easy family's entry: `**Association (hard)** —
  [link]` and the three lines (*What it is*: a scene implies an uncommon thing, or an
  ordinary thing in an unusual state, material or place, without naming it; does the lens
  state the WHOLE concept at the summarize-request positions; 93 items, every one named by
  Qwen3.6-27B when asked. *Example*: the hayfield scene → `a pitchfork made of chocolate`
  among `a pitchfork`, `a pitchfork made of glass`, `a shovel made of chocolate`, … ("a
  farmer lifting a pitchfork" does not count). *Judged by*: one 8-way MC + cannot tell in
  three draws with majority; a compound counts only when one line states every part, a line
  for the compound is not a line for its bare head; quote gate; chance 1/8, 1/6 for a reader
  who never picks a bare head).
- `docs/judges.md`: one row (`assoc-hard-v1+gate-h1`, 93 items, `+maj3v`, the compound rule,
  the first-ask figure).
- `docs/tiers.md`: one sentence (registered in full; core and fast await the owner).
- `docs/read_sites.md`: the family named beside `association` (same sites, `same` lite rule
  set in code).
- `AGENTS.md`: the capable table row; the porting note (not adapted).
- `CLAUDE.md`: one Family-conventions bullet (separate package and what it imports; options
  frozen in bank order; the compound rule; `GATE_VERSION` and the source pin; builder tables
  and the two frozen inputs; rebuild recipe; `NOT_GATED`, `NOT_ADAPTED`, `PENDING_FLOOR`); the
  count of families that keep their own `judge.py` (fourteen to fifteen); the tiers bullet's
  full count.
- `evals/baselines/README.md`: the pending floors line. `plans/README.md`: the plan's row.
- `evals/association/association_hard/README.md`: sources (in-house), what it is, status,
  the bank (counts, the rules of §2 with every table), read sites, scoring, the investigation
  of §A in short, every prompt verbatim, history.
- No `NOTICE.md` / Credits line (no external source).

### 7.4 Ledger

A family the golden manifest does not have needs an entry; plan 0106's rule already covers
it (`manifest_0101_declare.without_fast`, `g is None`: its fast rows are outside the hash, so
a later fast cut does not stale the entry). After everything the manifest hashes for the
family is final (bank, prompts, example file, table entries):

```
python scripts/manifest_0101_declare.py association_hard --plan 0108 \
  --note 'new family: hard association, assoc-hard-v1+gate-h1 on bank v1 (93 items)' --write
python scripts/manifest_0101.py --check tests/golden/manifest_0101_pre.json
```

`scripts/manifest_0101.py`, `scripts/manifest_0101_declare.py` and the golden are not edited;
**the five existing ledger entries, `association`'s included, are not touched** (a test
compares their bytes before and after). Before merge, any change to the family's rows means
deleting its own entry by hand and declaring again; after merge, a stamp or bank bump. A later
move into core is declared by listing it in `TIER_MOVES` (plan 0104), not by a new entry.

## 8. Validation before merge

Local first: the branch is not pushed until this section passes.

### 8.1 Reads

No GPU in this plan. The candidate reads cover all 93 items for `s3d-rl600` (Oracle lens
(RL)), `mlnla11-rl600` (NLA) and `jlens-public` (J-lens), re-keyed as §5 says. The prompt-only
readouts are regenerated by `wsbench baseline kind=prompt_only_opus stage=build|ask|readouts`
on the registered bank (Claude calls).

### 8.2 Judging

Per arm: `wsbench judge family=association_hard readouts=… out=…
layers=20,24,28,32,36,40,44,48,52,56,60`, registered instrument, no overrides, a `summ_store`
shared by the two judgings of an arm. Every arm is judged TWICE into fresh out dirs (digests
shared, judge calls fresh): the noise measurement of §8.4. Calls per arm and judging: 93 x 11
digests + 93 stage-2 (first judging only), 279 MC, about 150 quote re-judges.

All of it runs in one named tmux session with a timestamped log, the arms in sequence in the
same session, outputs on local disk and rsynced after:

```
tmux new -s ah-val 'bash /root/tmp/assoc-hard/val/run_all.sh 2>&1 | tee /root/tmp/assoc-hard/val/logs/val_$(date +%F_%H%M).log'
tail -f /root/tmp/assoc-hard/val/logs/val_<stamp>.log
```

### 8.3 Hand read (pre-registered)

Unit: an item verdict under one arm. Material per unit: the scene, the options, the gold and
its forms, the digest's evidence lines, the three draws (pick, quote, outcome), and a
regular-expression count of raw lines per option. Labelled right or wrong by the main session
and, independently, by a fresh-context subagent given the same material WITHOUT the judge's
verdict; the hand label is their agreement, disagreements are listed and left out of the
rates with their count.

- Both prose arms and the prompt-only arm: EVERY fail, and EVERY pass credited as
  `gold_description` on a complex item (the leniency A.4 found borderline cases in).
- Passes otherwise: 40 per prose arm, drawn with a recorded seed before any verdict is looked
  at, stratified by kind in the bank's proportions.
- J-lens: every pass, and 40 fails by the same draw.
- 30 verdicts set aside for the owner (15 passes, 15 fails, 10 per kind), verdict hidden.

Error classes: false pass (head only, sibling, parts from two lines, co-occurrence without
the relation, inference from clues, a hedge among alternatives) and false fail (compound not
credited, bare head preferred, contested when one side clearly wins, quote gate, digest
loss, missing form).

### 8.4 Pass criteria (fixed now)

| number | criterion |
|---|---|
| judge error, per arm and pooled: P(wrong given pass), P(wrong given fail), and P(wrong) reweighted to the arm's own pass / fail mix, Wilson intervals | GATE: pooled reweighted under 5%; no arm above 8%; P(wrong given pass) under 5% on each prose arm |
| noise: items whose majority verdict differs between the two judgings of an arm | GATE: at most 5% of items on every arm (5 of 93); the flipped items are listed |
| compound artefacts (A.3's class) among the fails read | GATE: none on a prose arm where the digest holds a stating line and no rival is comparably stated |
| undecided share per arm | GATE: under 5% |
| prompt-only floor, CI | report; expected 0.95 to 1.0 |
| `s3d-rl600`, `mlnla11-rl600`, `jlens-public`, by kind | report; expected about 0.91, 0.84, 0.13 (A.4 on the 93, candidate lists) |
| `pass_rate_first_ask` beside every headline | report; expected equal |
| lucky blind / described / topic, per kind and family | GATE per kind: at most the kind's chance + 0.05 |
| `bank.structural_floor` | GATE: at most 1 / 6 per complex kind |
| digest loss among the fails read | report; if above 5% of a prose arm's items, re-run that arm with `summ_max=25` and report both (a digest-fingerprint change, free before merge, adopted only with the owner's OK) |
| the owner's 30 against the agreed hand label | report |

One revision is allowed: if a GATE is missed, one targeted change to the prompt (a
`CALL_VERSION` bump to `assoc-hard-v2`) or to the gate (`gate-h2`), every arm re-judged, the
read repeated on a fresh sample for the affected class and in full where §8.3 reads in full.
A second miss stops the merge and goes to the owner. Items leave the bank in validation only
by a rule that reads no arm outcome; a bank change after any result is a new bank version
(`+bank-v2`), never an edit under the same stamp (review r4 of plan 0106, F1).

After the gates pass, in this order: pin the bank's sha256 in the tests; freeze the
prompt-only and lucky floors and empty the `PENDING_FLOOR` entry only if both are frozen;
declare the ledger entry; run the full suite; push.

## 9. Tests

### 9.1 New (offline; the family's `run_calls` monkeypatched with a scripted judge, digests through `tests/summary_fakes.FakeLLM`)

`tests/test_association_hard.py`

- registration: category, tier `full`, not in `tiers.CORE`, bank path, stamp, the 19
  positions; `test_easy_family_is_untouched` (§1.2); `test_both_association_entries_are_found`
  (the README and `docs/evals.md` entries of the two families are each matched once).
- prompts: every `PROMPTS` entry verbatim in the README (the shared test); the rendered
  system and user turn hold no placeholder; the options appear in bank order with cannot-tell
  last; no prompt example sentence occurs in a scene; the task note names no option.
- call plan: summary makes 3 MC calls per item with keys `<id>|L-1`, `#d1`, `#d2`;
  `opts=draws=1` makes 1 and drops `+maj3v`; an unsummarized item makes none; native makes one
  per (item, layer).
- gate, one scripted case each: listed form in the quote; **a compound quote whose gold form
  contains the bare head passes steps 3b and 3c** ("an upscale submarine cinema", the s3d case
  of A.3); **a sentence that names another option outside the gold form still blocks**
  ("a library and a cinema in a submarine" with `a library in a submarine` listed); a quote
  naming only the bare head goes to the re-judge and a scripted bare-head answer fails it
  (`gold_desc_rejected`); the quote miss is re-asked once and the second answer replaces the
  first; a second miss is `gold_unverified`; a Chinese quote with a listed Chinese form
  passes, without one is `gold_unlisted_script`; a token list holding the head and the
  qualifier is not voided as a flat list, one that also holds two more bank concepts is.
- article forms: "dangerous levels of red tide toxins" is a listed-form credit for `a red
  tide`; a form in `FORM_DROPS` is never matched (`pan`).
- pins: an option no digest line names gets at most two raw samples; the plural case ("a race
  car made of cookies" for the form "car made of cookie") is pinned; an option the digest
  names gets none; gold and distractors are treated alike.
- draws: pass / pass / fail passes; pass / fail / fail fails; pass / fail / api_fail is
  undecided; `unanimous`; `pass_first_ask` is false for an item whose second passing draw
  needed the re-ask.
- scoring: `by_kind`, `picked_bare_head`, `picked_sibling`, `pass_rate_first_ask`,
  `breakdown_md`; `results.decided_outcomes` reproduces the value; `fast.units` returns one
  unit per item through the default path.
- `test_gate_source_is_pinned`: sha256 of `gate.py` equals the literal recorded beside
  `GATE_VERSION`.

`tests/test_association_hard_bank.py`: `bank.validate` returns nothing on the committed
bank; each V rule fires on a mutated copy; header counts; `source_sha256` literals; the
committed bank rebuilds byte-identical from the three inputs (`--check`); `structural_floor`
at most 1 / 6; the gold-position histogram; the bank's sha256 literal (added after §8, not
before).

`tests/test_association_hard_tables.py`: the lucky builder (bank order, topic); `NOT_GATED`
leaves the family out of an ATI scope; `NOT_ADAPTED` and `families.get`; the capable builder
(the right question per kind); the authoring validator refuses the family; the five existing
ledger entries are byte-identical to 34de102e's.

The family must also survive the registry-parametrised suites with their random fake judge:
`test_layers_arbitrary.py`, `test_summary_mode_compare.py`, `test_token_note_prompts.py`,
`test_task_notes.py`, `test_prompt_tool_names.py`, `test_mc_cannot_tell.py`, `test_capable.py`,
`test_lucky_guessing.py`, `test_list.py`, `test_readme.py`, `test_family_paths.py`,
`test_rename_0101.py`.

### 9.2 Edits to pre-existing tests: this list is exhaustive

Any other change to a test that predates this PR is a defect of the implementation and must
be reported, not made. In particular no assertion about `association` changes.

| test | exact change |
|---|---|
| `tests/test_tiers.py` | `CATEGORY` + `"association_hard": "association"`; `N` (18) and `CORE` unchanged |
| `tests/test_family_paths.py` | `LAYOUT` + `"association_hard": "association"` |
| `tests/test_rename_0101.py` | the two `== 33` (lines 1019, 1364) become `== 34` |
| `tests/test_groups.py` | the `association` list gains `"association_hard"` after `"association"` (sorted order) |
| `tests/test_readplan.py` | `len(fams) == 33` becomes `34`, the comment gains "+ association_hard (0108)" |
| `tests/test_migrate_0101.py`, `tests/test_fast_subset.py` | `since = {"user_modeling_hard"}` gains `"association_hard"` (a family registered after the migration / after plan 0090) |
| `tests/test_glm_ati.py` | the subtracted set gains `"association_hard"` (no adapted set carries it) |
| `tests/test_adapt_skill_docs.py` | the scope subtracts `"association_hard"` too; `len(scope) == 30` unchanged |
| `tests/test_po_floors_r3.py` | `PENDING_FLOOR` + the entry of §6.1 |
| `tests/test_mc_cannot_tell.py` | `_last_option` gains a branch `if family == "association_hard":` returning the last shown option of the family's first item (add-only; `association` has its own branch, which is not edited) |
| `tests/test_lucky_guessing.py` | only if it pins the key set of `TOPIC_FAMILIES` or `DESCRIPTIONS`: the key added |
| `tests/golden/capable_questions.json` | the new family's block added, every existing block byte-identical |
| `tests/test_token_note_prompts.py` | `SUMMARY_JUDGED` + `"association_hard"` (add-only: its summary judge takes the shared token note) |

`tests/test_no_token_interpreter.py` `TOKEN_FAMILIES` is NOT edited unless the suite requires
every family with a token path to be listed (verify; `association` is not in it).

## 10. Files, order of work, gates

```
src/wsbench/evals/association/association_hard/
  __init__.py  prompts.py  judge.py  gate.py  bank.py                     new
evals/association/association_hard/
  items.json  grid_v1.json  forms_v1.json  README.md                      new
examples/readouts/association_hard.jsonl  (+ .meta.json)                  new
scripts/build_association_hard_bank.py                                    new
scripts/association_hard_grid.py  scripts/association_hard_forms.py       new (run once [superseded: see §13]; outputs committed)
plans/0108-association-hard.md                                            new (this file)
tests/test_association_hard.py  tests/test_association_hard_bank.py
tests/test_association_hard_tables.py                                     new
src/wsbench/readplan.py                    one new branch
src/wsbench/baselines/lucky_guessing.py    builder, description, TOPIC_FAMILIES + 1
src/wsbench/baselines/text_inversion.py    NOT_GATED + 1
src/wsbench/capable/questions.py           builder, NAME_COMPOUND
src/wsbench/adapt/families.py              NOT_ADAPTED + 1
scripts/readme_evals_table.py  scripts/summary_mode_compare.py            one entry each
.claude/skills/wsb-new-questions/scripts/validate_bank.py                 NOT_AUTHORABLE + 1
.claude/skills/adapt-bank/{SKILL.md,references/families.md}
README.md  CLAUDE.md  AGENTS.md  docs/{evals,judges,tiers,read_sites}.md
evals/baselines/README.md  plans/README.md
evals/baselines/{prompt_only_summary,lucky_guessing}.json                 floors (commit 4)
tests/golden/manifest_0101_declared.json   + the new family's entry
tests/golden/capable_questions.json        + the new family's block
tests/…                                    the edits of §9.2
```

Scratch, never committed: `/root/tmp/assoc-hard/val/` (re-keyed reads, out dirs, logs, the
hand-read record until it is copied into the family README).

### 10.1 Commit sequence

One worktree, one issue, one PR; local until commit 4 is done. Implementation from this plan
by `codex-implementer` if its MCP server is up (it was not on 2026-11-23: "Executable not
found in $PATH: codex"; otherwise the main session implements directly), files only, no git;
the main session reviews each diff, runs `git diff -- tests/` separately and checks it
against §9.2 line by line.

| commit | content | must be green |
|---|---|---|
| 1 | the two one-off scripts and their frozen outputs (`grid_v1.json`, `forms_v1.json`), the builder, `bank.py`, `items.json`, `tests/test_association_hard_bank.py` (the bank pinned by shape and by rebuild, not yet by sha). No registration | full suite; `build_association_hard_bank.py --check`; `structural_floor` at most 1 / 6; the scene screen and the guesser re-runs recorded in the header |
| 2 | the family: `__init__`, `prompts`, `judge`, `gate`, the family README with every prompt, the toy example file, the `readplan` branch, `tests/test_association_hard.py`, the §9.2 edits that registration forces (tiers, family paths, rename counts, groups, readplan count, migrate / fast `since`, `PENDING_FLOOR`). Registered in `full`, not in `tiers.CORE` | full suite; §1.2's empty diff; T1 with a PROVISIONAL ledger entry for the new family (deleted and declared again whenever its rows change before merge) and the five existing entries byte-identical |
| 3 | the remaining table additions (lucky guessing, `NOT_GATED`, capable, `NOT_ADAPTED`, validator, summary-mode-compare rule) and the docs, with the §9.2 edits that belong to them and `tests/test_association_hard_tables.py` | full suite; every §9.2 edit accounted for; a live smoke `limit=3` on the re-keyed s3d reads |
| 4 | validation outputs (§8): the hand-read record and the numbers in the family README, the frozen prompt-only and lucky floors, the bank's sha256 literal, the final ledger entry | §8.4's GATE rows; full suite; ruff check and format |

Gates: `uv run pytest -q`; `uv run ruff check .` and `ruff format --check .`; T1 green with
exactly one new ledger entry; §1.2's empty diff; module docstrings of one to three lines and
no `from __future__ import annotations`.

## 11. Explicitly deferred

- **Core and fast.** The owner's earlier word was core and fast; she has not reconfirmed
  after the viewer. When she does: `tiers.CORE` + 1 (and `TIER_MOVES`), the `UNITS` entry of
  `scripts/fast_cut_core_half.py` (stratum = `kind`), the next fast version with seed
  20261121, the fast pins and docs, in one follow-up commit; it requires the floors frozen and
  `PENDING_FLOOR` emptied (the test of plan 0106 enforces it).
- **Oracle lens (SFT) reads**, the logit-lens L63 floor and any re-read on the registered
  plan: GPU. The three RL / NLA / J-lens arms are validated from stored reads.
- **The road to 100 items**: rebuilding the lists of the 16 dropped items or authoring and
  gating replacements (authoring calls and a Qwen gate on GPU). Not in this plan; no item is
  authored here.
- **Making the family hard for the Oracle lens** (§12, question 1): a bank question, not a
  judge question.
- ATI panel; adapted sets; a hyphen-insensitive form match ("tidal-bore"; seen once, on a
  dropped item, not tested).

## 12. Questions for the owner

1. **Is a family that the Oracle lens passes at about 0.91 and the text reader at about 0.98
   what she wants registered as "hard"?** The honest reading of §A: the candidate looked
   harder than it is because the judge could not credit compounds. Options: (a) register it
   as planned, described as "token lens against prose lens"; (b) hold registration and go
   back to the bank (the items the prose lenses really miss are few: a green flash, a
   lyrebird, a pamonha, un cajón flamenco, a steelpan, and for the NLA the unnatural materials
   it never states; the contested items show a second kind of difficulty, a lens that names
   the right thing and its neighbour equally often).
2. **93 items now, or wait for 100?** The 16 dropped by the two-run guesser rule include
   several lens-hard items. Alternatives: keep them flagged in the bank (109, with a
   described-guesser floor of 0.16 against 0.125), or refill first.
3. **The conflict rule.** A lens that states the gold in 49 lines and a sibling in 47 fails
   (four s3d items). The plan keeps the easy family's rule (an option must win); the
   alternative, "any stating line passes", would credit a lens that sprays alternatives.
4. **Token lists and "X in Y".** `helicopter | library` in one list can pass a library in a
   helicopter under the shared token rule. Keep, or require prose for the unnatural kind?
5. **Core and fast** (§11).
6. Her 30 verdicts (§8.3).

## 13. Implementation record (2026-11-23)

The owner settled §12's first question ("hard association is fine, make a PR"). What was built
differs from the plan above in these points; the family README has the tables.

**The bank of record is v2 with 56 items, not 93** (30 obscure, 9 complex_qualified, 17
complex_unnatural). Every drop is by a rule that reads the scene, the options and the forms
only.

- `ah-b2-cq20-repetition-sous-les-pigeons` (un théâtre en ruine) does not fit §2.3's grid: two
  qualifiers on four heads, no third qualifier to build the missing cell from. Dropped (92).
- **The grid pass was run twice, and both runs are committed** (`grid_run1.json`,
  `grid_v1.json`). The first run's compose prompt mis-built five cells and refused them; the
  second, with a corrected prompt, made the lists the bank uses. The symmetric grid removes
  the structural leak (`bank.structural_floor` 1/6), but on it an LLM guesser finds the most
  natural or vivid cell (blind 0.30, described 0.24 on the 47 rebuilt lists). On the 42 lists
  identical in both runs the guesser verdict differed for six items, because the described
  guesser's solved examples are drawn from the other items of the pass. Following the owner's
  ruling in plan 0112 (no item admitted on a second gating measurement), an item stays only
  if it passes in BOTH runs: the second run's 18 drops stand (17 complex items, two of which
  passed in the first run, and la mantilla, whose replaced list is guessable), and the four
  the first run dropped and the second passed leave too (un boulanger intolérant au gluten, a
  penguin at the stock exchange, a sagging sofa, a dress made of glass). The five lists that
  differ between the runs are decided by the committed run. One item, um coelho gigante, had
  its third qualifier on the gold's head; the pass composes whichever cell is missing.
- "Two measurements" in §2.2 and §2.3 are replicate draws of one prompt (5 + 5), close to
  deterministic; they are not independent measurements. The variance that matters is across
  example sets and option orders, which the rule does not sample.
- **A.6's "blind 0.03" was an option-order artefact.** The candidate lists were built and
  selected with the guessers in the loop on ONE option order (the `association` seed). On the
  44 obscure lists of the first build a blind guesser is at 0.014 in that order and at 0.21 in
  the bank's frozen order (described 0.31, 16 items at 3 of 5 or more). The rule was applied
  again in bank order (`scripts/association_hard_reguess.py`, `reguess_v1.json`): 14 obscure
  items left.
- **Bank v1 and v2.** The first build (74 items) was registered on the branch and judged on
  every arm before its options-only gate failed in bank order (blind 0.154, described 0.211).
  The bank therefore changed after results existed, and by §8.4 that is a new version: the
  bank of record is `version: 2`, stamp `+bank-v2`. Bank v1 never left the branch. On the
  kept items the verdicts of every arm are the same on v1 and v2 under `gate-h1`.
- Forms: the forms pass never sees the scene and named three golds in another sense of the
  word (un banco as a bench, una chimenea as a fireplace, offbeat as eccentric). Those forms
  and 13 more forms on 7 items of the same kind found by reading every kept item's forms against its scene
  are in `FORM_DROPS`. No recorded verdict rested on one.
- The topic guesser is not gated on (owner decision): `mc.category` is close to a definition
  of the gold. Measured, frozen, `lucky_guessing.NOT_A_FLOOR`.

**`gate-h2`, the one revision §8.4 allows.** The first validation's review found one NLA fail
of A.3's kind by mechanism: `a library in a helicopter` was picked in every draw, a digest
line held the listed form "helicopter library", and the pick still went to the quote-only
re-judge (which answered the bare head), because `gate-h1` skipped steps 3b / 3c whenever the
quote named another option, the gold's own bare head included. `gate-h2`: (a) the gold's own
bare head in the quote no longer keeps 3b / 3c from running (inside them nothing changed);
(b) a quote without Latin letters and without a listed form goes to the quote-only re-judge
like any other (step 4 of §3.4 is gone: it failed faithful Chinese token pairs before the
re-judge). On the stored answers of all ten runs (a) flips that one item and nothing else.

**Other deviations.** Plan commits 2 and 3 are one commit. `structural_floor` reads a part
written in two words as one part. Forms pass: a single CJK character is never a form; a name
that another option of the item lists, or that the scene contains, is not listed. The gate
does not carry the capital-letter rule the prototype inherited in steps 3b / 3c. The judge's
concept pool is frozen in the bank header (`concepts`, V13). The toy readouts file has no
sidecar. §9.2 was not exhaustive: `test_no_token_interpreter.py` (README count),
`test_user_modeling_hard.py` (`NOT_ADAPTED` set), `test_user_modeling_hard_tables.py` (viewer
group list) and `test_dm_blind_judge.py` (`NOT_A_FLOOR` literal and a docstring) each gained
the family. The hand read of §8.3 was done by two blind reads per verdict by the judge's own
model plus the implementer's read of every disagreement and mismatch.

**Validation** (56 items, `gate-h2`, stored readouts; the family README has CIs, kinds, the
second judging and the hand read with its intervals): Oracle lens (RL) 0.929, NLA 0.821,
J-lens 0.161, prompt-only 0.982, four-bullet prompt-only 0.982; lucky blind 0.021, described
0.100 (per kind under the bars), topic 0.411 (not a floor). The prompt-only floor is above
every lens. §8.4's gates are met on point estimates with wide intervals; the owner's 30 are
set aside, unread.
