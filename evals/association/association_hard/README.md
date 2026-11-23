# association_hard: an uncommon or compound thing a scene implies but never names

In-house items (no external source). Plans: `plans/0108-association-hard.md` (the family),
`plans/0116-association-hard-v3.md` (bank v3, the registered bank).

A short scene (1 to 3 sentences, sometimes not in English) evokes one thing without naming it,
and the model is asked to summarize the story in one sentence. The thing is either uncommon (a
didgeridoo, a red tide, a quipu: kind `obscure`) or an ordinary thing in an unusual state (`a
dead tree`: kind `complex_qualified`), made of an unusual material or set in an unusual place
(`a violin made of ice`, `a gym inside a courtroom`: kind `complex_unnatural`). The question is
whether a lens, read at the summarize-request positions, states the WHOLE concept: a readout
that says "a soloist playing the violin" has not surfaced `a violin made of ice`.

It is the hard sibling of [`association`](../association/README.md), whose files, stamps,
floors and read plan it leaves untouched: a separate package with its own prompts, judge, gate
and bank.

**Status.** Bank v3 (99 items, plan 0116) is registered, in the `full` tier only: not in core,
no fast cut, no ATI entry, no adapted set. The prompt-only reader solves nearly every item, so the family separates lenses
from each other (and prose lenses from token lenses); it does not separate a lens from a reader
of the text.

## Bank v3 (`items_v3.json`, 99 items)

Plan: `plans/0116-association-hard-v3.md`. Bank v2 (`items.json`, 56 items, below) stays in the repo as a
file and is no longer registered.

| kind | items | kept from bank v2 | new |
|---|---|---|---|
| `obscure` | 53 | 26 | 27 |
| `complex_qualified` | 16 | 9 | 7 |
| `complex_unnatural` | 30 | 17 | 13 |
| all | 99 | 52 | 47 |

Scene language: en 75, es 7, de 6, pt 5, it 4, fr 2.

### The four items of bank v2 that are dropped (`V3_DROP`, header `edits.v3.dropped_from_v2`)

| item | why |
|---|---|
| `ah-b1-ob32-farm-milk-sugar-prism` | a refractometer: blind-guessable from its options (the blind guesser picks it 14 times of 20 over the four measurements that exist: 5 and 2 of 5 in reguess_v1.json, 3 and 4 of 5 on the two floor runs); it was in bank v2 because one gating measurement was under 3 of 5 |
| `ah-b2-ob06-zampogna-presepe-montano` | una zampogna: its accepted forms `Italian bagpipe` / `意大利风笛` also fit the distractor `una piva` |
| `ah-b2-ob18-festival-shirt-spirals` | tie-dye: its accepted forms `扎染` / `绞缬` also fit the distractor `shibori` |
| `ah-b2-ob26-railway-sky-white-ring` | a solar halo: its accepted form `a ring around the sun` also fits the distractor `a corona` |

The other 52 items are carried byte-identical per item (scene, options, order, forms, gate and guess
records). They were not gated again and their forms were not derived again.

### The new items: the v2 recipe, each gate run ONCE

| stage | obscure | complex_qualified | complex_unnatural | all |
|---|---|---|---|---|
| authored (two sub-waves, b4 then b5; Opus 5.5 at low effort with the v2 authoring prompts) | 184 | 140 | 140 | 464 |
| lint-clean | 151 | 121 | 89 | 361 |
| option list built, scene screen 5 of 5 | 148 | 121 | 89 | 358 |
| **subject gate passed** (one Modal run, Qwen3.6-27B; greedy and at least 8 of 10) | 103 | 49 | 33 | 185 |
| options-only gate passed (one grid pass, one bank-order pass; under 3 of 5 in BOTH measurements) | 46 | 21 | 21 | 88 |
| bank rules and the hand read of the option lists passed | 41 | 20 | 20 | 81 |
| in the 100-item draft (selection in authoring order to the per-kind target) | 28 | 7 | 13 | 48 |
| **in the bank** (after the described-guesser gate: 11 dropped, 11 backfilled, 1 dropped) | 27 | 7 | 13 | 47 |

Recipe, unchanged from bank v2's authoring run (its scripts and prompts: the authoring brief with the
lessons of waves b2 / b3, the lint, the `samecat` / balanced-grid option recipes with their own
blind-leak loop, the alias audit, the 5-draw scene screen, the strict Opus grader of the subject's
answers), then this repo's three passes. Each gate was run ONCE, and its raw output is committed
under `v3/`:

1. **Subject gate** (`v3/qwen_requests.jsonl`, `v3/qwen_samples.jsonl.gz`, `v3/qwen_gate.json`): one
   Modal run over all 358 screened candidates, the gate question of record only (obscure:
   name-the-referent; complex: the compound-aware question), greedy + 10 samples at T 0.7. 185
   pass (greedy correct and at least 8 of 10); 173 fail and are out. No candidate was sampled
   twice; every request has its 11 replies (none empty).
2. **Options-only gate, in bank order, strict.** Complex kinds: `v3/grid_v3.json`
   (`scripts/association_hard_grid.py --no-tables --context <the 52 kept items>`), one run: 1 list
   does not fit the 3 x 2 grid, 34 lists are guessable in both measurements, and 5 more in one
   measurement only (the strict rule: v2 would have kept them). Obscure: `v3/reguess_v3.json`
   (`scripts/association_hard_reguess.py --waves b4,b5` on the provisional bank), one run: 57 of
   103 are guessable (56 in both measurements, 1 in one only). **A new item is in only when both
   guessers are under 3 of 5 in BOTH measurements of that one run**; no list was rebuilt and
   nothing was measured a second time. The described guesser's examples came from the
   provisional bank (kept items included; kept items were not measured).
3. **Bank rules and a hand read of the option lists** (`v3/options_audit_v3.json`, an Opus audit of
   scene + gold + wrong options, 10 flagged, read by hand; 88 candidates pass step 2, and the
   audit read the 87 left after the bank-rule drop): 1 candidate breaks V5 (near-duplicate options) and 6 are dropped by the table `CAND_DROP`:


| candidate | why |
|---|---|
| `ah-b4-ob08-stone-slide-on-frozen-loch` | curling: the authoring brief names it as an example its batch must not reuse |
| `ah-b4-ob49-monsoon-forest-hanging-pitchers` | a pitcher plant: two distractors are kinds of the gold (`a cobra lily`, `a sun pitcher`) |
| `ah-b4-ob39-sunday-brass-in-the-park` | a bandstand: the scene fits the distractor `a gazebo` as well (an octagonal open-sided roofed structure in a park), and `a pavilion` is a class that holds the gold |
| `ah-b5-ob15-courthouse-archive-gridded-canvas` | cross-stitch: the distractor `gros-point` is commonly defined as cross-stitch on canvas, which is what the scene shows |
| `ah-b5-cq01-courtroom-gavel-split` | a broken gavel: the grid's other head is `a hammer`, a class that holds a gavel, so `a broken hammer` is not cleanly wrong |
| `ah-b5-cu16-judge-hammer-of-ice` | a gavel made of ice: the grid's other head is `a hammer`, a class that holds a gavel, so `a hammer made of ice` is not cleanly wrong |

   Flagged and kept: `a sneaker wave` beside a rogue wave (a coastal wave, the scene is open sea),
   `a ground-effect vehicle` beside a hovercraft, `des socques` beside des sabots, `a lute` beside
   a sitar, `a basset hound` beside a bloodhound (the scene's forty-mile scent trail).
4. **Selection** (plan 0116 §2.5): of the 81 left, the first in authoring order up to the per-kind
   target (28 / 7 / 13, bank v2's proportions on 100) made a 100-item draft; the other 33 were the
   reserve.
5. **Forms** (`v3/forms_v3.json`, one forms pass as for v2; then `v3/forms_audit_v3.json`, a
   scene- and option-aware audit of every accepted form of the same 87 candidates, 93 forms
   marked on 40 candidates, read by hand). Dropped by table (`FORM_DROPS_V3`: 46 forms; 6 of the
   rows belong to three items that later left on floor run 1, `des sabots`, `une casserole
   trouée` and `a waterlogged piano`):


| item | form | why |
|---|---|---|
| `ah-b4-ob07-spinning-tablet-rain-ritual` (a bullroarer) | `a rhombus` | ordinarily the geometric shape |
| `ah-b4-ob07-spinning-tablet-rain-ritual` (a bullroarer) | `rhombus` | ordinarily the geometric shape |
| `ah-b4-ob17-maschere-carro-viareggio` (la cartapesta) | `纸浆塑形` | pulp moulding in general (also industrial moulded pulp), not papier-mâché |
| `ah-b4-ob23-rogue-swell-trawler-deck` (a rogue wave) | `a killer wave` | any deadly wave; also said of the distractor `a sneaker wave` |
| `ah-b4-ob23-rogue-swell-trawler-deck` (a rogue wave) | `killer wave` | any deadly wave; also said of the distractor `a sneaker wave` |
| `ah-b4-ob23-rogue-swell-trawler-deck` (a rogue wave) | `a monster wave` | any huge wave (big surf, a tsunami) |
| `ah-b4-ob23-rogue-swell-trawler-deck` (a rogue wave) | `monster wave` | any huge wave (big surf, a tsunami) |
| `ah-b4-ob34-bauernhof-warme-holzkiste` (ein Brutkasten) | `保温箱` | an insulated box or a neonatal incubator, not an egg hatcher |
| `ah-b4-ob36-gull-pillar-off-cliff` (a sea stack) | `a stack` | alone, a pile or a chimney stack |
| `ah-b4-ob36-gull-pillar-off-cliff` (a sea stack) | `stack` | alone, a pile or a chimney stack |
| `ah-b4-ob72-reed-boat-lake-fisher` (a reed boat) | `草船` | a straw or grass boat, not one of reeds |
| `ah-b4-ob76-chinese-sail-battens-junk` (a junk) | `junk` | alone, rubbish (`a junk` stays) |
| `ah-b4-ob78-fan-propelled-cushion-shore` (a hovercraft) | `an ACV` | also the Amphibious Combat Vehicle, near the distractor `an amphibious tank` |
| `ah-b4-ob78-fan-propelled-cushion-shore` (a hovercraft) | `ACV` | also the Amphibious Combat Vehicle, near the distractor `an amphibious tank` |
| `ah-b4-ob84-atelier-bloc-hetre` (des sabots) | `木屐` | usually geta-style wooden sandals |
| `ah-b4-ob84-atelier-bloc-hetre` (des sabots) | `wooden clogs` | also said of the wooden-soled distractors `des socques` / `des galoches` |
| `ah-b4-cq03-bouillon-fond-perce` (une casserole trouée) | `有洞的锅` | 锅 also covers a frying pan: fits the distractor `une poêle trouée` |
| `ah-b4-cq03-bouillon-fond-perce` (une casserole trouée) | `破了洞的锅` | 锅 also covers a frying pan: fits the distractor `une poêle trouée` |
| `ah-b4-cq09-storm-parlour-soaked-keys` (a waterlogged piano) | `a water-damaged piano` | any water damage: also fits the distractor `a mouldy piano` |
| `ah-b4-cq09-storm-parlour-soaked-keys` (a waterlogged piano) | `water-damaged piano` | any water damage: also fits the distractor `a mouldy piano` |
| `ah-b4-cq11-stove-dribbling-whistle-pot` (a leaking kettle) | `漏水的壶` | 壶 alone is any pot, jug or teapot |
| `ah-b4-cu10-misa-en-ruta` (una iglesia en un autobús) | `a church bus` | commonly a bus a church owns to carry its congregation |
| `ah-b4-cu10-misa-en-ruta` (una iglesia en un autobús) | `church bus` | commonly a bus a church owns to carry its congregation |
| `ah-b4-cu13-orli-sui-binari` (una sartoria su un tram) | `a tailor on a streetcar` | a person (also a passenger), not a tailor's shop on board |
| `ah-b4-cu13-orli-sui-binari` (una sartoria su un tram) | `tailor on a streetcar` | a person (also a passenger), not a tailor's shop on board |
| `ah-b4-cu13-orli-sui-binari` (una sartoria su un tram) | `tailor on a tram` | a person (also a passenger), not a tailor's shop on board |
| `ah-b4-cu13-orli-sui-binari` (una sartoria su un tram) | `tailor’s tram` | a tram a tailor owns or uses, not a shop on board |
| `ah-b4-cu18-granite-woodwind-recital` (a flute made of stone) | `a rock flute` | also a flute played in rock music |
| `ah-b4-cu18-granite-woodwind-recital` (a flute made of stone) | `rock flute` | also a flute played in rock music |
| `ah-b4-cu29-wax-sledge-on-the-farm` (a sled made of wax) | `a toboggan made of wax` | a toboggan has no runners; the scene's sled has two |
| `ah-b4-cu29-wax-sledge-on-the-farm` (a sled made of wax) | `toboggan made of wax` | a toboggan has no runners; the scene's sled has two |
| `ah-b4-cu29-wax-sledge-on-the-farm` (a sled made of wax) | `a sleigh made of wax` | a sleigh is a larger, usually horse-drawn vehicle |
| `ah-b4-cu29-wax-sledge-on-the-farm` (a sled made of wax) | `sleigh made of wax` | a sleigh is a larger, usually horse-drawn vehicle |
| `ah-b4-cu36-pupils-among-the-nets` (a school on a fishing boat) | `lessons held on a fishing boat` | an activity (also fishing lessons), not a school |
| `ah-b4-cu39-lemurs-down-the-aisle` (a zoo on an airplane) | `zoo flight` | a flight that carries zoo animals |
| `ah-b5-ob32-ship-bridge-swinging-needle` (a magnetic compass) | `指南针` | any compass: also said of the distractor `a gyrocompass` |
| `ah-b4-cq22-weeds-and-hammock` (a lazy farmer) | `a sluggish farmer` | slow or lethargic, not unwilling to work |
| `ah-b4-cq22-weeds-and-hammock` (a lazy farmer) | `sluggish farmer` | slow or lethargic, not unwilling to work |
| `ah-b4-cq29-divers-reef-hull` (a sunken ship) | `a shipwreck` | also a wreck stranded on rocks: fits the distractor `a stranded ship` |
| `ah-b4-cq29-divers-reef-hull` (a sunken ship) | `shipwreck` | also a wreck stranded on rocks: fits the distractor `a stranded ship` |
| `ah-b4-cq32-chef-warm-milk` (a broken fridge) | `损坏的冰箱` | physical damage: also fits the distractor `a cracked fridge` |
| `ah-b5-ob63-ministere-galette-pliee` (une crêpe) | `thin pancake` | any thin pancake (blini, a Chinese pancake) |
| `ah-b5-ob64-clinic-rice-saffron-pan` (paella) | `西班牙炖饭` | 炖饭 is the usual word for the distractor `risotto` |
| `ah-b5-ob64-clinic-rice-saffron-pan` (paella) | `西班牙炒饭` | fried rice, another dish |
| `ah-b5-ob14-railway-depot-rope-teams` (tug of war) | `rope pulling` | any hauling on a rope |
| `ah-b5-ob19-depot-freight-wagon-numbers` (stencilling) | `模板印刷` | stencil / template printing in industry too, broader than the craft |

   Marked by the audit and KEPT (a judgement call; the compound-noun forms follow bank v2's
   convention, `a submarine cinema`):


- `Darts`: `Dart`, `飞镖`
- `ein Brutkasten`: `incubator`
- `una sartoria su un tram`: `电车上的裁缝店`
- `a church inside a windmill`: `a windmill converted into a church`, `windmill converted into a church`
- `a cinema inside a lighthouse`: `Lighthouse cinema`, `a lighthouse cinema`, `lighthouse cinema`, `a lighthouse turned cinema`, `lighthouse turned cinema`, `lighthouse movie theater`, `灯塔电影院`, `灯塔影院`
- `a school on a fishing boat`: `trawler school`, `fishing boat school`, `渔船学校`
- `a zoo on an airplane`: `airplane zoo`
- `a breathalyzer`: `a breath analyzer`, `breath analyzer`
- `paella`: `西班牙海鲜饭`

6. **The described-guesser bar of plan 0108 is a gate, applied once** (decided on the draft by the
   reviewing main session, not by the owner;
   `FLOOR_DROP_1`, `FLOOR_DROP_2`, header `edits.v3.floor_runs`). The 100-item draft was never
   pushed. Its floor run (`v3/floor_run1/`) gave described 0.134 and `complex_qualified` 0.225,
   over that kind's bar of 0.217: the described guesser picked 11 NEW items 3 times of 5 or more,
   none of which it had picked in their gating run (its three solved examples are drawn from the
   item list, so they change with it):

   | dropped on floor run 1 | described hits of 5 |
   |---|---|
   | `ah-b4-ob84-atelier-bloc-hetre` (des sabots) | 3 |
   | `ah-b4-cq01-carpenter-dull-teeth` (a blunt saw) | 3 |
   | `ah-b4-cq03-bouillon-fond-perce` (une casserole trouée) | 5 |
   | `ah-b4-cq08-camp-lake-overturned-hull` (a capsized canoe) | 5 |
   | `ah-b4-cq09-storm-parlour-soaked-keys` (a waterlogged piano) | 4 |
   | `ah-b4-cu02-harbour-paper-anchor` (an anchor made of paper) | 5 |
   | `ah-b4-cu16-feather-forge-tool` (a hammer made of feathers) | 5 |
   | `ah-b5-ob08-surgeon-courtyard-webbing` (slacklining) | 5 |
   | `ah-b5-ob09-compliance-officer-jammer` (roller derby) | 3 |
   | `ah-b5-ob34-labo-tourner-tubes` (une centrifugeuse) | 3 |
   | `ah-b5-ob40-linguists-yew-corridors` (a hedge maze) | 5 |

   The reserve backfilled once, in authoring order, kind for kind (5 obscure, 4
   complex_qualified, 2 complex_unnatural): `a lazy farmer`, `a sunken ship`, `a broken fridge`, `a snow-covered car`, `a surfboard made of chocolate`, `a salamander`, `an armadillo`, `a monkey puzzle tree`, `une crêpe`, `paella`, `Handschuhe aus Honig`. Floor run 2 on that
   100-item bank (`v3/floor_run2/`): described 0.052; one new item was picked 5 of 5, `woodturning`
   (`ah-b4-ob18-grandpa-lathe-bowls`, 0 of 5 on run 1 and in its gating run), and is dropped with
   no backfill: **99 items**. Kept items of bank v2 are not dropped on these runs (they were
   admitted on bank v2's floor of record); the described guesser hit `a didgeridoo` (5 and 5), `a
   pickaxe made of rubber` (3 and 5), `a fjord` (4, then 0) and `a platypus` (0, then 5). 22
   candidates that passed every stage stay in reserve (`edits.v3.passed_not_selected`).
   **This procedure is a selection on the described guesser's own measurements, and its examples
   change with the item list: the final described floor is an optimistic estimate for the new
   items.**

Rebuild (from the repo alone; CI runs it):

```
python scripts/build_association_hard_bank_v3.py --out <fresh path>     # then copy it over
python scripts/build_association_hard_bank_v3.py --check
```

### Known issues of bank v3 (the header's `known_issues`)


- the 52 items kept from bank v2 keep its rule (guessable in one measurement of two stays; authoring.guess records both) and were not gated again; the new items are under 3 of 5 in both measurements of their one run; the options-only rates are conditioned on those selections, on the frozen option order and on the examples the described guesser was shown
- the topic guesser (the item's fine category beside the options) picks the gold far above chance: mc.category is close to a definition of the gold; measured, not a floor
- no human review of scenes, golds or forms: every grader is claude-opus-5-5
- the bank is selected on Qwen3.6-27B's own gate; the 52 kept items and the new ones passed it in different runs, each item in one run
- gold positions are a seeded shuffle and not balanced: a reader who always picks the first option is right on the share of items the header's histogram shows for slot 1
- the judge's concept pool (header `concepts`) is the whole bank's and was rebuilt for the added items, so no judge call of bank v2 replays; a successor bank that only drops items must carry this list unchanged for kept items' calls to replay
- the prompt-only reader is expected at the ceiling: the family separates lenses from each other and from token lenses, not a lens from a reader of the text
- the described-guesser bar was applied as a gate ONCE (edits.v3.floor_runs): new items the described guesser picked 3 of 5 or more on two floor runs were dropped, with one backfill between them; that is a selection on the guesser's own measurements, and its solved examples change with the item list, so the frozen described floor is an optimistic estimate for the new items; kept items it picked on those runs were not dropped
- `a whirlpool` lists `a maelstrom` as an accepted form and `a maelstrom` is a distractor of `a rogue wave`: the concept pool merges the two entries (as for any shared form), so a maelstrom line pins and blocks for both items
- the forms of the 52 kept items were not derived again; the forms of the new items come from one forms pass (v3/forms_v3.json) and one scene-aware audit read by the builder's author, not by a second person

Found after the bank was frozen (not in the header):

- **The frozen floor still shows items a guesser picks 3 times of 5 or more**, as every floor
  run of this family has (other examples each time). Described: 5 new items (`Handschuhe aus
  Honig` and `una iglesia en un autobús` 5 of 5; `a reed boat`, `a sea stack`, `a sitar` 4) and 5
  kept items (`a fjord` 5, `um trator de chocolate` 4, `a didgeridoo`, `a lithophone`, `a
  platypus` 3). Blind: `una clepsidra` (new) 3 of 5; it was 0 and 2 of 5 in its gating run, 1 and
  2 of 5 on floor runs 1 and 2. The gate was applied once (step 6 above) and nothing is
  dropped on the final measurement; every per-kind bar is met on it. The per-item draws of
  this final run are not in the repo (only its aggregates, in
  `evals/baselines/lucky_guessing.json`): a file added under this directory moves the
  family's manifest rows, which the ledger pins to the bank's stamp.
- **`a platypus` (kept) is the pattern `a refractometer` was dropped for, on the described
  guesser**: 3 then 1 of 5 in its gating measurements (`reguess_v1.json`), 5 of 5 on floor run
  2, 3 of 5 on the final floor. It is the only kept item that leaked in a gating measurement
  and stays.
- **`a leaking kettle` (`ah-b4-cq11-stove-dribbling-whistle-pot`) has a distractor its scene
  states**: the pot "began to whistle", and the list holds `a whistling kettle`. That is the
  `CAND_DROP` standard, and it was not found because the option audit's prompt excluded
  sibling-qualifier options ("the same thing with another qualifier are wrong BY DESIGN: never
  flag those"), so the audit could not find this class on any complex item. It makes the item
  harder for every arm (it is one of the prompt-only reader's three fails). The item stays:
  the bank is frozen.
- Several new `obscure` golds are not rare (`a sitar`, `lacrosse`, `tug of war`, `a whirlpool`,
  `a hovercraft`, `a magnetic compass`, `a breathalyzer`, `an armadillo`, `paella`, `une
  crêpe`): the authoring brief's "terms a quiz-goer knows" was read generously, and a gold the
  subject cannot name fails its gate.
- A marked form kept by hand is a judgement of one reader (the list above); `Dart` / `飞镖` also
  name the single dart, and `incubator` any incubator.

## Bank v2 (`items.json`, 56 items; no longer registered)

The 52 kept items of bank v3 were selected by the rules of this section.

| kind | items |
|---|---|
| `complex_qualified` | 9 |
| `complex_unnatural` | 17 |
| `obscure` | 30 |

Scene language: en 40, es 5, pt 5, it 3, de 2, fr 1.
Every item passed the direct gate on Qwen3.6-27B (thinking off; the greedy answer and at least
8 of 10 samples name the whole gold): `obscure` items on the name-the-referent question, the
complex kinds on a compound-aware question (`wsbench capable` asks the same two).

Example (`ah-b1-cu01-frozen-concert-strings`): "On the concert stage, the soloist tucked the four-stringed instrument under her chin and drew her bow, its curved body and scroll carved from a clear frozen block that misted faintly, like a window pane on a winter morning." The options, in the bank's frozen order:
`a violin`, `a cello made of ice`, `a cello made of paper`, `a cello made of glass`, `a cello`, `a violin made of glass`, `a violin made of ice`, `a violin made of paper`; gold `a violin made of ice`.

The bank is built by `scripts/build_association_hard_bank.py` from the authoring run's candidate
file (109 items) and the frozen inputs committed beside the bank: `grid_v1.json`,
`grid_run1.json`, `forms_v1.json`, `reguess_v1.json`. Every edit goes through the builder's
tables and those files, never by hand in `items.json`, and no scene is ever edited.
`bank.validate` (V1-V13, `wsbench.evals.association.association_hard.bank`) is run by the
builder, by the judge's loader (fail closed) and by the bank tests. The candidate file stays
out of the repo (it holds Qwen's replies, per-arm lens outcomes and the scenes of the dropped
items); the header's `source_sha256` ties the bank to it, and the byte-identical rebuild test
runs only where `WSB_ASSOC_HARD_SRC` points at a directory holding it (CI checks the bank's
sha256 literal). Rebuild:

```
python scripts/build_association_hard_bank.py --src <bank_final_B.json> \
    --guess <floors_B.json> <guess_confirm.json> --out <fresh path>     # then copy it over
python scripts/build_association_hard_bank.py --src ... --guess ... --check
```

### Which candidates are in

All rules read the scene, the options and the forms only, never a lens outcome. "Two
measurements" below are two replicate measurements, 5 draws each of ONE prompt; they are close
to deterministic. What does vary is the described guesser's three solved examples, which are
drawn from the other items present, so its picks depend on which items are in the list.

1. **Guessable from the options alone** (16 items): an options-only guesser (blind or
   described, `wsbench.baselines.lucky_guessing`) picks the gold at least 3 times of 5 in both
   replicate measurements on the same list.
2. **Does not fit the option grid** (1 item): `ah-b2-cq20-repetition-sous-les-pigeons` (un théâtre en ruine): its option list does not fit the 3 x 2 grid of §2.3: two qualifiers (en ruine, en construction) on four heads (théâtre, église, château, cinéma), so there is no third qualifier to build the missing cell from (owner decision 2026-11-23: dropped).
3. **Guessable from the rebuilt list** (18 + 4 items, the grid pass below): the same
   rule on the list the grid pass made. The pass was run TWICE and both runs are committed
   (`grid_run1.json`, then `grid_v1.json`). The first run's compose prompt mis-built five
   cells (it wrote "a lighthouse inside a windmill" for the missing place cell) and refused
   them; the second run, with a corrected prompt, is the one whose lists the bank uses. On
   the 42 lists that are identical in both runs the guesser verdict differed for six items
   (five more items in the pass changed every described prompt's examples). The rule is
   strict: an item stays only if it passes in BOTH runs, so the 18 the second run drops
   leave (two of them passed in the first run), and so do the 4 the first run dropped and
   the second run passed. The 5 lists that differ between the runs are decided by the
   committed run. One of the 18 is `la mantilla`, whose scene names a distractor (`la
   peineta`); the replaced list is guessable.
4. A rebuilt list that fails the 5-draw scene screen: none.
5. **Guessable in the bank's own option order** (14 obscure items, the bank-order pass:
   `scripts/association_hard_reguess.py`, output `reguess_v1.json`). The candidate
   lists of the obscure items had been built and selected on ANOTHER option order (the
   `association` seed), with the guessers in the loop: there a blind guesser picks their golds
   0.01 of the time, far below chance, and on the same lists in the bank's frozen order it
   picks them 0.21 of the time. The authoring run's "blind 0.03" was an artefact of that one
   order. The pass re-runs the family's blind and described guessers twice on every obscure
   item as the bank shows it, and the two-measurement rule is applied again.

| dropped by rule 1 | gold | kind |
|---|---|---|
| `ah-b1-ob18-bindery-floating-inks-comb` | paper marbling | obscure |
| `ah-b1-ob23-harbour-wave-court-case` | a tsunami | obscure |
| `ah-b1-cu25-trading-floor-in-the-carriage` | a stock exchange on a train | complex_unnatural |
| `ah-b2-ob15-wax-resist-fishing-village` | batik | obscure |
| `ah-b2-ob23-tidal-bore-surf-contest` | a tidal bore | obscure |
| `ah-b2-ob35-monastery-brass-star-disc` | an astrolabe | obscure |
| `ah-b2-cq07-trawler-mooring-snarl` | a tangled rope | complex_qualified |
| `ah-b2-cq19-divers-among-the-stumps` | a drowned forest | complex_qualified |
| `ah-b3-ob01-ink-cloud-reef` | a cuttlefish | obscure |
| `ah-b3-ob15-cast-party-torched-dessert` | a baked Alaska | obscure |
| `ah-b3-ob17-pausa-prova-orchestra` | l'affogato | obscure |
| `ah-b3-ob22-courthouse-rain-monster` | a gargoyle | obscure |
| `ah-b3-ob26-convalescent-cathedral-sketch` | a flying buttress | obscure |
| `ah-b3-ob46-shepherd-split-hazel` | a tally stick | obscure |
| `ah-b3-cq28-linguist-shrunken-sweater` | a shrunken sweater | complex_qualified |
| `ah-b3-cq32-kitchen-pet-refuses-roast` | a vegetarian dog | complex_qualified |

| dropped by rule 3 | gold | blind / described of 5, twice |
|---|---|---|
| `ah-b1-cq23-ambulance-on-rims` | a flat tyre | 5 / 2, 5 / 1 |
| `ah-b2-cq02-farmyard-dribbling-trail` | a leaking bucket | 5 / 5, 5 / 5 |
| `ah-b2-cq18-farmers-cross-the-bed` | a dried-up river | 0 / 5, 0 / 5 |
| `ah-b2-cu18-hayfield-cocoa-tines` | a pitchfork made of chocolate | 5 / 4, 5 / 5 |
| `ah-b3-cq01-hillside-farm-machine-on-its-back` | an overturned tractor | 5 / 0, 5 / 0 |
| `ah-b3-cq02-harbour-rescue-craft-hull-up` | a capsized lifeboat | 5 / 5, 5 / 5 |
| `ah-b3-cq07-overnight-express-white-drifts` | a snowbound train | 5 / 3, 5 / 4 |
| `ah-b3-cq09-commuter-line-blockage` | a fallen tree | 5 / 1, 5 / 1 |
| `ah-b3-cq15-smithy-crooked-flue` | a leaning chimney | 5 / 5, 5 / 5 |
| `ah-b3-cq22-courtroom-robe-dragging` | an oversized gown | 5 / 5, 5 / 5 |
| `ah-b3-cq27-tappeto-stazione-bruciato` | un tappeto bruciato | 5 / 5, 5 / 5 |
| `ah-b3-cq29-weaver-waits-for-fleece` | a bald sheep | 0 / 5, 0 / 5 |
| `ah-b3-cq34-menina-casinha-pequena` | um coelho gigante | 4 / 0, 5 / 1 |
| `ah-b3-cu01-dairy-hull-harbour` | a boat made of cheese | 0 / 4, 0 / 4 |
| `ah-b3-cu07-chapel-frozen-lectern` | a pulpit made of ice | 5 / 5, 4 / 5 |
| `ah-b3-cu08-periscope-matinee` | a cinema in a submarine | 0 / 3, 0 / 4 |
| `ah-b3-cu25-loaves-under-surgical-lamps` | a bakery inside an operating room | 0 / 5, 0 / 5 |
| `ah-b3-ob38-archivo-catedral-velo` | la mantilla | 5 / 0, 4 / 0 |

| dropped by rule 3, first run only | gold | first run: blind / described of 5, twice | second run |
|---|---|---|---|
| `ah-b1-cq17-boulanger-gluten` | un boulanger intolérant au gluten | 0 / 5, 3 / 5 | 2 / 0, 3 / 0 |
| `ah-b1-cu08-trading-floor-waddler` | a penguin at the stock exchange | 0 / 5, 0 / 5 | 0 / 3, 0 / 1 |
| `ah-b3-cq26-bank-vault-sofa-sagging` | a sagging sofa | 0 / 4, 0 / 4 | 0 / 0, 0 / 0 |
| `ah-b3-cu04-stage-gown-transparent` | a dress made of glass | 0 / 5, 0 / 5 | 0 / 1, 1 / 0 |

| dropped by rule 5 | gold | blind / described of 5, twice |
|---|---|---|
| `ah-b1-ob01-wind-strung-box-window` | an Aeolian harp | 5 / 0, 5 / 0 |
| `ah-b1-ob08-rattan-sphere-lab` | sepak takraw | 5 / 5, 5 / 5 |
| `ah-b1-ob14-seamstress-pool-gloves` | underwater hockey | 0 / 3, 0 / 3 |
| `ah-b1-ob42-priest-hiding-hole-archive` | a priest hole | 5 / 5, 5 / 5 |
| `ah-b2-ob01-tuned-steel-drum-yard` | a steelpan | 0 / 5, 0 / 5 |
| `ah-b2-ob03-cajon-flamenco-cocina` | un cajón flamenco | 1 / 5, 0 / 5 |
| `ah-b2-ob12-dispatcher-forest-checkpoints` | orienteering | 5 / 5, 5 / 5 |
| `ah-b2-ob13-analista-piscina-gol-flutuante` | o polo aquático | 5 / 1, 5 / 5 |
| `ah-b2-ob16-camp-knotted-cord-hanger` | macramé | 0 / 5, 0 / 3 |
| `ah-b2-ob32-antique-glass-clicking-box` | a Geiger counter | 5 / 2, 5 / 3 |
| `ah-b3-ob07-cloister-bird-lyre` | a lyrebird | 5 / 0, 5 / 0 |
| `ah-b3-ob18-buried-jars-winter-cabbage` | kimchi | 5 / 5, 5 / 5 |
| `ah-b3-ob19-abbey-cellar-hive-drink` | mead | 4 / 5, 5 / 5 |
| `ah-b3-ob36-overnight-train-piper` | a sporran | 0 / 5, 0 / 5 |

Several dropped items are ones the lenses find hard (a tidal bore, an astrolabe, a drowned
forest, a gargoyle); the rules are blind to that.

### Options: the bare head stays, the grid is symmetric

`obscure`: the gold and seven other things of its domain that an authoring model proposed for
it (the same fine category where the category has that many members; `a seismograph` sits among
a compass, a lie detector and a weather vane).

Complex kinds: the bare head of a compound gold is a distractor on purpose (a readout that
echoes the head and never the qualifier has not surfaced the concept), and the list is the full
grid of three qualifiers (or materials, or places) on two heads plus the two bare heads:

```
A+B (gold)   A'+B    C+B        B
A+B'         A'+B'   C+B'       B'
```

The candidate's lists held one off-grid option instead of one cell, which made the gold the only
option whose qualifier occurred in two options and whose head in three: a model-free reader
picking by that signature hit most complex golds. The grid pass
(`scripts/association_hard_grid.py`; run twice, see rule 3) parses each list into its
roles, has Opus 5.5 write the missing cell from the list's own parts, screens the new list on
the scene (gold 5 of 5) and runs the two options-only guessers. On the symmetric grid
`bank.structural_floor` is 1/6 (the only structure left: a bare head is never the gold). The
price is rule 3 above: on a symmetric grid an LLM guesser finds the most natural or most vivid
cell, so 21 of the 47 rebuilt complex lists are guessable in at least one run and leave the
bank.
`structural_floor` reads a part written in two words as one part; counting words instead, a
reader of word counts would be at 0.19 on the 11 `complex_qualified` items of the first build
(not recomputed on the 9 of bank v2).

Options are frozen in the bank (`mc.options`, the seeded order of `assoc-hard-v1|<name>`) and
are never shuffled at run time; `mc.gold_position` is the gold's 1-based place.

### Accepted forms

`mc.aliases` (the gold) and `mc.distractor_aliases` (each distractor): the candidate's forms
plus the forms pass (`scripts/association_hard_forms.py`, output `forms_v1.json`: for
every option, gold and distractor alike and never told which is which, Opus 5.5 lists the
standard English and Chinese names and a second call audits each as the same concept; 568
options, 2015 names kept). Every form is also listed without one leading article
(`a red tide` -> `red tide`), because a form is matched as whole words. A forms-pass name that
another option of the item also lists, or that the scene contains, is not listed; a single CJK
character is never a form. The forms pass never sees the scene, so it named some golds in
another sense of the word (`un banco` as a bench, `una chimenea` as a fireplace, `offbeat` as
eccentric); those forms, and forms that alone are an ordinary word for something else, are
dropped by table (`FORM_DROPS`; every kept item's forms were read against its scene after the
PR review, with a scene-aware Opus audit as the candidate list; items no longer in the bank
are listed too):

| item | form | why |
|---|---|---|
| `ah-b2-ob01-tuned-steel-drum-yard` | `a pan` | a pan is cookware |
| `ah-b2-ob01-tuned-steel-drum-yard` | `pan` | a pan is cookware |
| `ah-b1-ob04-aboriginal-tube-circular-breath` | `a mago` | a regional name that is an ordinary word in es / pt / it (a magician) |
| `ah-b1-ob04-aboriginal-tube-circular-breath` | `mago` | an ordinary word in es / pt / it (a magician) |
| `ah-b3-ob35-theatre-zeppelin-tour` | `飞船` | a spaceship, not an airship (飞艇) |
| `ah-b2-ob03-cajon-flamenco-cocina` | `cajón` | a crate or drawer in the scene's language (`a cajón` stays) |
| `ah-b2-cu10-cuentas-bajo-cubierta` | `bench in a submarine` | the scene's banco is a bank (cheques, savings), not a bench |
| `ah-b2-cu10-cuentas-bajo-cubierta` | `submarine bench` | a bench, not a bank |
| `ah-b2-cu10-cuentas-bajo-cubierta` | `潜艇里的长凳` | a bench, not a bank |
| `ah-b2-cu10-cuentas-bajo-cubierta` | `潜艇长椅` | a bench, not a bank |
| `ah-b3-cu17-granja-humo-pliegos` | `paper fireplace` | the scene's chimenea is a rooftop chimney, not a fireplace |
| `ah-b3-cu17-granja-humo-pliegos` | `纸壁炉` | a fireplace, not a chimney |
| `ah-b1-cq19-drummer-no-rhythm` | `quirky drummer` | offbeat as eccentric; the scene's drummer cannot keep time |
| `ah-b1-cq19-drummer-no-rhythm` | `eccentric drummer` | offbeat as eccentric, not out of time |
| `ah-b1-cq19-drummer-no-rhythm` | `古怪的鼓手` | eccentric, not out of time |
| `ah-b1-cq19-drummer-no-rhythm` | `另类鼓手` | unconventional, not out of time |
| `ah-b1-cq19-drummer-no-rhythm` | `怪异的鼓手` | weird, not out of time |
| `ah-b1-ob19-farmer-heated-pen-spoons` | `wood burning` | burning wood as fuel (`the smell of wood burning`) |
| `ah-b1-ob19-farmer-heated-pen-spoons` | `烫画` | commonly an iron-on heat-transfer print |
| `ah-b2-cu07-quarry-soft-tool` | `a rubber pick` | commonly a rubber guitar plectrum |
| `ah-b2-cu07-quarry-soft-tool` | `rubber pick` | commonly a rubber guitar plectrum |
| `ah-b2-cu07-quarry-soft-tool` | `a pick made of rubber` | a pick alone is also a plectrum |
| `ah-b2-cu07-quarry-soft-tool` | `pick made of rubber` | a pick alone is also a plectrum |
| `ah-b1-cu06-palco-de-marmore` | `石头窗帘` | 窗帘 is a window curtain; the scene's is a stage curtain |
| `ah-b1-cu06-palco-de-marmore` | `石制的窗帘` | 窗帘 is a window curtain; the scene's is a stage curtain |
| `ah-b3-ob42-bar-association-gala` | `腰封` | also a book's paper band or any waist girdle |
| `ah-b3-ob25-dialect-ferry-cliffs` | `峡江` | a river through a gorge, not a sea inlet |
| `ah-b3-cq12-plaza-basin-coins` | `干喷泉` | reads as a dry-deck (pool-less) jet fountain |
| `ah-b2-ob02-mouth-frame-twang` | `a mouth harp` | commonly a harmonica |
| `ah-b2-ob02-mouth-frame-twang` | `mouth harp` | commonly a harmonica |

### Known issues of bank v2 (its header's `known_issues`)

- items guessable in one measurement of two stay (authoring.guess records both); the options-only rates are conditioned on that selection and on the frozen option order
- the topic guesser (the item's fine category beside the options) picks about half the golds: mc.category is close to a definition of the gold; measured, not a floor
- no human review of scenes, golds or forms: every grader is claude-opus-5-5
- the bank is selected on Qwen3.6-27B's own gate
- gold positions are a seeded shuffle and not balanced: a reader who always picks the first option is right on the share of items the header's histogram shows for slot 1
- the judge's concept pool (header `concepts`) is the whole bank's: a successor bank that only drops items must carry this list unchanged for kept items' calls to replay
- the prompt-only reader is expected at the ceiling: the family separates lenses from each other and from token lenses, not a lens from a reader of the text


Found by review r2, after the bank was frozen (not in the header). **Bank v3 drops the four items
named here** (a refractometer, una zampogna, tie-dye, a solar halo); the described-guesser picks
of the first bullet were left as they are:

- `a refractometer` is guessable by the blind guesser in most replicate draws (14 of 20 over four
  measurements); it stays because one gating measurement was under 3 of 5, the rule as written.
  The described guesser picks `a lithophone`, `um quipu` and `a dead tree` 5 of 5, and
  `una zampogna` and `tie-dye` 3 of 5, on the frozen floor. No per-kind bar is missed.
- three golds list a form that also fits a distractor of the same item: `Italian bagpipe` /
  `意大利风笛` for una zampogna (the list holds `una piva`); `扎染` / `绞缬` for tie-dye (the
  list holds `shibori`); `a ring around the sun` for a solar halo (weakly, `a corona`). No stored
  verdict of any arm rests on one of them.

## Read sites

The same read as `association` (`docs/read_sites.md`): render `chat_summarize` (the scene, then
"Summarize the preceding story in one sentence.", thinking off), read at the 19 summarize-suffix
and chat-tail tokens, one contiguous run ending at the final token; scene positions are never
read. Layers 20, 24, ..., 60. `reads=lite` reads the same sites. 100 x 19 x 11 = 20900
cells per 11-layer arm.

## Scoring

Summary mode (the default): the digest of every read cell of an item, then ONE 8-way multiple
choice + cannot tell, asked in three independent draws. Each draw ends pass / fail / undecided
by the gate below, and the item's verdict is the majority of the three (a failed draw never
votes but counts in the half). Native mode (`opts=aggregate=native`): one MC per (item, layer),
one draw; the item passes if any layer passes.

**The compound rule** (the system prompt): a line states a compound option only if that ONE
line expresses every part of it; a line that states a compound is not a line for the bare
thing, and lines that name only the bare thing never outvote a line that states a listed
compound.

**Pins.** For every shown option that no digest line names, up to 2 raw prose samples that name
it are added to the digest (gold and distractors alike; plural-tolerant match on the option's
bank forms). The forms come from the concept pool frozen in the bank header (`concepts`).

**The gate of a gold pick** (`gate.py`, `gate-h2`; code only verifies a pick, it never
overrules the judge):

1. Not the gold: fail (distractor / cannot tell / invalid choice); a failed call: undecided.
2. The quote must verify inside one readout line (`digest.quote_ok`). A miss is re-asked ONCE
   and the retried answer is gated from step 1; a second miss fails (`gold_unverified`).
3. Token readouts: a quote whose every holding list also holds another shown option, or three
   more bank concepts, is void (`gold_flat_list`).
4. The quote holds a listed form of the gold: pass (`gold_listed_form`), whatever else the
   quote holds (as in `association`; the prompt tells the judge that a line holding two
   options singles out nothing, the code does not re-check it).
5. Else, unless the quote names another shown option (the gold's own bare head does not count
   here), the prose sample holding the quote (its sentence or a neighbour), or another
   evidence sentence, names a listed form of the gold, not after a negation, and no other
   shown option OUTSIDE the gold's own form: pass (`gold_listed_line`, `gold_listed_evidence`).
   The other options are tested with the gold's matched form blanked out, so "a submarine"
   inside "a submarine cinema" does not block `a cinema in a submarine`.
6. Otherwise ONE quote-only re-judge under the same system prompt: the gold again passes
   (`gold_description`), anything else fails (`gold_desc_rejected`).

`gate-h2` is the one revision the plan allowed, made after the first validation and its
review. `gate-h1` (a) skipped step 5 whenever the quote named the gold's own bare head, which
a compound's paraphrase nearly always does: on the NLA arm `a library in a helicopter` was
picked in every draw, another digest line held the listed form "helicopter library", and the
pick still went to the quote-only re-judge, which answered the bare head; and (b) failed a
quote without Latin letters and without a listed form before the re-judge, so a faithful
Chinese token pair (`枯萎 | 树木` for a dead tree) could never pass while `flat | tire` could.

`gate.py` is in no call fingerprint: any change to it bumps `GATE_VERSION` (a test pins the
file's sha256 beside it).

**Headline**: `pass_rate` over decided items with a bootstrap CI. Beside it: `by_kind`,
`by_lang`, `picked_bare_head` / `picked_sibling` (complex items whose majority pick is the bare
head / another cell of the grid), and `pass_rate_first_ask` (a draw that passed only after the
quote re-ask counted as a fail); `wsbench report` prints them under `## breakdowns`.

**Chance**: 1/8 uniform. A reader who knows the construction never picks a bare head: 1/6 on the
complex kinds (item-weighted over the bank: 0.144).

## Validation on bank v3 (plan 0116, 2026-11-23)

Reads: the 52 kept items' cells are the stored reads of plans 0108 / 0115 (their plan rows are
byte-identical in bank v3's plan); the new items were read on 2026-11-23 by the same driver, arm
by arm (plan-file mode on a pinned bank file: the 48 of the draft, then the 11 backfilled), and
merged into one file per arm on bank v3's `plan_sha` (20691 cells, 209 per item, no empty
sample). Judged by the registered instrument (`assoc-hard-v1+gate-h2+bank-v3`,
`layers=20,...,60`), every arm twice (digests shared, judge calls fresh; no call of bank v2
replays: the concept pool was rebuilt). 95% bootstrap CIs over items, first judging. The kept /
new split is of ONE judging of the 99-item bank; it is not bank v2's score.

| arm | all 99 [95% CI] | kept 52 [95% CI] | new 47 [95% CI] | second judging (all / kept / new) | items differing |
|---|---|---|---|---|---|
| Oracle lens (RL) `s3d-rl600` | 0.899 [0.838, 0.949] | 0.923 [0.846, 0.981] | 0.872 [0.766, 0.957] | 0.899 / 0.923 / 0.872 | 0 |
| Oracle lens (SFT) `s3d-sft251` | 0.889 [0.818, 0.939] | 0.885 [0.788, 0.962] | 0.894 [0.809, 0.979] | 0.889 / 0.865 / 0.915 | 2 |
| NLA `mlnla11-rl600` | 0.818 [0.727, 0.889] | 0.788 [0.673, 0.904] | 0.851 [0.745, 0.957] | 0.828 / 0.808 / 0.851 | 1 |
| J-lens `jlens-public` | 0.242 [0.162, 0.323] | 0.212 [0.115, 0.327] | 0.277 [0.149, 0.404] | 0.202 / 0.192 / 0.213 | 4 |
| prompt-only `po-opus-v1` (the frozen floor) | 0.970 [0.939, 1.000] | 1.000 [1.000, 1.000] | 0.936 [0.851, 1.000] | 0.970 / 1.000 / 0.936 | 0 |
| logit lens L63 (the frozen floor; one judging) | 0.040 [0.010, 0.081] | 0.038 [0.000, 0.096] | 0.043 [0.000, 0.106] |  | |

By kind (obscure / complex_qualified / complex_unnatural, first judging):

| arm | all | kept 52 | new 47 | bare head / sibling picked (of 46 compounds) |
|---|---|---|---|---|
| Oracle lens (RL) | 48 of 53 / 16 of 16 / 25 of 30 | 23 of 26 / 9 of 9 / 16 of 17 | 25 of 27 / 7 of 7 / 9 of 13 | 0 / 4 |
| Oracle lens (SFT) | 47 of 53 / 16 of 16 / 25 of 30 | 23 of 26 / 9 of 9 / 14 of 17 | 24 of 27 / 7 of 7 / 11 of 13 | 3 / 2 |
| NLA | 46 of 53 / 15 of 16 / 20 of 30 | 22 of 26 / 8 of 9 / 11 of 17 | 24 of 27 / 7 of 7 / 9 of 13 | 7 / 1 |
| J-lens | 16 of 53 / 6 of 16 / 2 of 30 | 7 of 26 / 3 of 9 / 1 of 17 | 9 of 27 / 3 of 7 / 1 of 13 | 24 / 1 |
| prompt-only | 53 of 53 / 14 of 16 / 29 of 30 | 26 of 26 / 9 of 9 / 17 of 17 | 27 of 27 / 5 of 7 / 12 of 13 | 0 / 0 |
| logit lens L63 (the frozen floor; one judging) | 3 of 53 / 0 of 16 / 1 of 30 | 1 of 26 / 0 of 9 / 1 of 17 | 2 of 27 / 0 of 7 / 0 of 13 | 19 / 0 |

The first-ask pass rate equals the headline on every arm except the NLA (0.808 against 0.818:
one pass came after the quote re-ask), no item is undecided, and at most 4 of 99 items change
verdict between two judgings. On the kept 52 the first judging differs from bank v2's first
judging in at most four items per arm (same reads; the judge calls are new): Oracle lens (RL)
48 and 48, Oracle lens (SFT) 46 and 46, NLA 43 then 41, J-lens 9 then 11, prompt-only 51 then
52, logit lens 2 and 2.

**The order is the same as on bank v2: prompt-only floor 0.970 > Oracle lens (RL) 0.899 > Oracle
lens (SFT) 0.889 > NLA 0.818 >> J-lens 0.242 > logit lens L63 0.040.** Paired on the first
judgings (arm only / other only, exact McNemar): Oracle lens (RL) against the floor 3 / 10, p =
0.09; Oracle lens (SFT) against the floor 3 / 11, p = 0.06; Oracle lens (RL) against (SFT) 4 / 3, p
= 1.0; NLA against the floor 3 / 18, p = 0.002; NLA against the Oracle lens (RL) 3 / 11, p =
0.06; NLA against (SFT) 3 / 10, p = 0.09. The two Oracle lenses are not separated from each
other, and each is 8 to 9 points under the floor without a significant paired difference on 99
items; the family still does not separate a strong prose lens from a reader of the text.

Fails of the first judging. Prompt-only (3, all new): `a blunt drill`, `a leaking kettle`, `a zoo
on an airplane`. Oracle lens (RL) (10): `Handschuhe aus Honig`, `a cinema inside a lighthouse`,
`a kalimba`, `a monkey puzzle tree`, `a sled made of wax`, `una sartoria su un tram` (new), `a
green flash`, `a pamonha`, `a red tide`, `ein Archiv in einem U-Boot` (kept). Logit lens L63
passes (4): `a mirage`, `a library in a helicopter` (kept), `tug of war`, `a magnetic compass`
(new).

**Options-only guessers** (`wsbench baseline`, 5 draws, bank order; the THIRD and final floor
measurement, on the 99 items, frozen in `evals/baselines/lucky_guessing.json`):

| guesser | all 99 [95% CI over items] | kept 52 | new 47 | obscure (bar 0.175) | complex_qualified (0.217) | complex_unnatural (0.217) | mean ± sd over the 5 draws |
|---|---|---|---|---|---|---|---|
| blind | 0.010 [0.000, 0.026] | 0.004 [0.000, 0.012] | 0.017 [0.000, 0.051] | 0.011 | 0.013 | 0.007 | 0.010 ± 0.007 |
| described (the floor of record) | 0.091 [0.042, 0.139] | 0.077 [0.027, 0.146] | 0.106 [0.038, 0.191] | 0.109 | 0.013 | 0.100 | 0.091 ± 0.016 |
| topic (diagnostic, `NOT_A_FLOOR`) | 0.394 [0.303, 0.485] | 0.423 [0.296, 0.554] | 0.362 [0.234, 0.489] | 0.453 | 0.463 | 0.253 | 0.394 ± 0.007 |
| uniform | 0.147 [0.117, 0.178] | 0.146 [0.104, 0.188] | 0.149 [0.102, 0.200] | 0.162 | 0.138 | 0.127 | 0.147 ± 0.020 |

**Every per-kind bar of plan 0108 (the kind's chance + 0.05) is met by the blind and the
described guesser**, and the family-level described rate (0.091) is under uniform chance. That
is after the gate was applied (step 6 of "The new items" above): the described rate was 0.134
on the 100-item draft (`complex_qualified` 0.225, over its bar) and 0.052 on floor run 2. The
bank was selected on those two measurements of the described guesser, whose examples change
with the item list, so **0.106 on the new items is an optimistic estimate**; on this final
run it again picks five new and five kept golds 3 times of 5 or more ("Found after the bank
was frozen" above). The topic guesser is a diagnostic and not gated on (owner decision).

Not done on bank v3: a hand read of verdicts (bank v2's hand read below covers its 56 items
and its arms), the owner's own read, an ATI panel.

## Validation of bank v2 (plans 0108 and 0115; 56 items)

Measured 2026-11-23 on the 56 items of bank v2, from stored readouts of Qwen3.6-27B (layers 20
to 60, the 19 sites; no new read) and judged by the registered instrument (`gate-h2`), every
arm twice (digests shared, judge calls fresh). 95% bootstrap CI of the first judging.

| arm | pass rate [95% CI] | second judging | obscure | complex_qualified | complex_unnatural | items differing |
|---|---|---|---|---|---|---|
| Oracle lens (RL) `s3d-rl600` | 0.929 [0.857, 0.982] | 0.929 | 28 / 30 | 9 / 9 | 15 / 17 | 2 |
| Oracle lens (SFT) `s3d-sft251` (read and judged 2026-11-23, plan 0115) | 0.893 [0.804, 0.964] | 0.893 | 27 / 30 | 9 / 9 | 14 / 17 | 2 |
| NLA `mlnla11-rl600` | 0.821 [0.714, 0.911] | 0.821 | 25 / 30 | 9 / 9 | 12 / 17 | 2 |
| J-lens `jlens-public` | 0.161 [0.071, 0.268] | 0.196 | 4 / 30 | 3 / 9 | 2 / 17 | 2 |
| prompt-only `po-opus-v1` (the frozen floor) | 0.982 [0.946, 1.000] | 0.982 | 30 / 30 | 9 / 9 | 16 / 17 | 0 |
| prompt-only, four bullets (pilot reader) | 0.982 [0.946, 1.000] | 0.982 | 30 / 30 | 9 / 9 | 16 / 17 | 0 |
| logit lens L63 (the frozen floor; read and judged 2026-11-23, plan 0115, one judging) | 0.036 [0.000, 0.089] | | 1 / 30 | 0 / 9 | 1 / 17 | |

The first-ask pass rate equals the headline on every arm (no pass needed the quote re-ask), no
item is undecided, and at most 2 of 56 items change verdict between two judgings. The J-lens
picks the bare head on 13 of the 26 compounds; the prose lenses on 0 and 3.

**Oracle lens (SFT)** (plan 0115, 2026-11-23). The one arm that was read anew: the 56 items on
the registered read plan (11704 cells, the same cells as the stored arms, no empty sample), by
the driver and on the layers of the Oracle lens (RL) read, and judged twice by the same
instrument with the same settings. 50 of 56 in both judgings; two items differ between them
(`a pamonha` fails the first, `a solar halo` the second), the first-ask rate equals the
headline and no item is undecided. Its majority pick is the bare head on 2 of the 26 compounds
and another cell of the grid on 1. Paired on the first judgings (arm only / other only, exact
McNemar): against the prompt-only floor 1 / 6, p = 0.125 (the one item only the lens passes is
`a library in a helicopter`); against the Oracle lens (RL) 1 / 3, p = 0.625 (`a red tide`
against korfball, a green flash and um trator de chocolate). On 56 items it is not separated
from the Oracle lens (RL), and like every lens it is under the floor.

**Logit lens L63** (plan 0115, 2026-11-23; `evals/baselines/logit_lens.json`). The 56 items read
at layer 63 by the bundled producer (`wsbench.produce`, method `logit_lens`, `layers=[63]`, one
Modal GPU; 1064 cells on the registered plan) and judged with `layers=63`: 2 of 56 (`a mirage`
on a listed form, `a library in a helicopter` on the token pair `library | helicopter` through
the quote-only re-judge), first-ask the same, no item undecided; the majority pick is the bare
head on 10 of the 26 compounds. Frozen with `wsbench freeze kind=logit_lens partial=True`.

**The prompt-only reader solves the family: its floor (0.982) is above every lens.** The
family separates a token lens (0.16; 0.04 for the final-layer logit lens) from prose lenses
(0.82, 0.89, 0.93) and the prose lenses from each other, mostly on `complex_unnatural`; it does not separate a lens from a reader of the
text, and a lens that paraphrased the scene would pass it.

**What `gate-h2` changed** against `gate-h1` on the same 56 items and the same cached judge
answers, all ten runs: one prose verdict (the NLA's `a library in a helicopter`, fail to pass
in both judgings: the case the revision was made for) and the J-lens's Chinese token pairs
that now reach the re-judge (a dead tree and an oxbow lake pass in both judgings, a
seismograph in one). No other verdict moved; the form drops of the review moved none.

**Options-only guessers** (`wsbench baseline`, 5 draws, bank order; bar = the kind's chance +
0.05):

| guesser | family | obscure (bar 0.175) | complex_qualified (0.217) | complex_unnatural (0.217) |
|---|---|---|---|---|
| blind | 0.021 | 0.033 | 0.022 | 0.000 |
| described (the floor of record) | 0.100 | 0.127 | 0.111 | 0.047 |
| topic (diagnostic, not a floor) | 0.411 | 0.473 | 0.422 | 0.294 |
| uniform | 0.139 | | | |

The blind and described values are below chance because items were selected on them (rules 1,
3 and 5): they bound leakage on this option order and with these examples, they are not an
unbiased estimate (the described guesser still picks five golds 3 times of 5 or more). The
**topic guesser** is shown the item's fine category (`mc.category`) beside the options and
picks 0.411 of the golds: the category was written for the distractor proposer and is close to
a definition of the gold ("Aboriginal wind instrument" for a didgeridoo). By the owner's
decision a topic guesser above chance is not gated on for this family: it is measured and
frozen as a diagnostic and is `lucky_guessing.NOT_A_FLOOR`.

**Hand read** (175 item verdicts of the first judging: every fail and every description credit
on a compound of the two prose arms and the prompt-only arm, 40 other passes per prose arm
stratified by kind, every J-lens pass and 40 J-lens fails; drawn with seed 108 on the 60-item
build and restricted to the 56 items; the labels are blind to the verdict, so the verdicts
that `gate-h2` changed keep theirs). Each verdict was labelled twice, blind to the judge's
verdict, with the full judged digest. **Both labellers are the judge's own model** (Opus 5.5
at default effort; an auditor prompt and a strict prompt that restate the judge's rule), so a
blind spot the judge and the labellers share cannot show; the plan's main-session and
subagent read was not done (the judged digests are 2 to 3.5 MB per arm). The label is the two
labellers' agreement; disagreements are left out, as pre-registered.

| arm | wrong among passes read [Wilson 95%] | wrong among fails read [Wilson 95%] | labellers disagree | error reweighted to the arm's mix |
|---|---|---|---|---|
| Oracle lens (RL) | 1 of 50 [0.004, 0.105] | 0 of 3 [0.000, 0.561] | 2 | 0.019 |
| NLA | 2 of 46 [0.012, 0.145] | 1 of 9 [0.020, 0.435] | 1 | 0.056 |
| J-lens | 0 of 6 [0.000, 0.390] | 2 of 35 [0.016, 0.186] | 4 | 0.048 |
| prompt-only | 0 of 18 [0.000, 0.176] | 0 of 1 [0.000, 0.793] | 0 | 0.000 |

Mean of the four arms 0.031. The plan's gates (under 0.05 pooled, no arm above 0.08, under 0.05
among the passes of each prose arm) are met on the point estimates, and only on them: the
intervals are wide, and **each gate can flip on one excluded disagreement**. Among the Oracle
lens passes, 1 of 50 is 2.0%, and 2 of 51 is 3.9% if the excluded green-flash pass (credited
on "ending with gold turning green") is wrong; among the NLA passes, 2 of 46 is 4.3%, and one
more wrong pass would be 6.4%; the NLA's reweighted error is 0.056, and 0.071 if the excluded
solar-halo fail is wrong (0.036 if the paper bell is a correct fail). The errors:

- False passes (3). Oracle lens: korfball (named as the answer in 5 raw lines, netball in 4;
  the implementer reads this one as a correct pass). NLA: un pájaro recién nacido (a cat is
  stated in as many lines as the chick) and a hospital inside a lighthouse (credited on
  "nautical/hospital lighthouse imagery").
- False fails (3). NLA: a bell made of paper. The judge picked the gold in every draw and
  quoted "paper lantern bell", which the quote-only re-judge refused in two draws of three.
  No digest sentence holds a listed form, and the same digest gives the bell other materials
  about as often (pine, wood, cheese), so this fail is arguable and probably correct; the
  labellers called it a pass. J-lens: a candle clock (`candle | timer | clock` refused by the
  quote re-judge) and a jaw harp (`jaw | mouth | har`; the implementer reads this one as a
  correct fail: no token says harp).
- **The artefact the instrument was built against did occur once under `gate-h1`** and is the
  reason for `gate-h2`: on the NLA arm `a library in a helicopter` was a stated compound lost
  to its bare head (gold picked in every draw, a digest line with the listed form "helicopter
  library", the quote-only re-judge answering `a library`). Under `gate-h2` it passes in both
  judgings, and no fail read is of that kind.

Not done: the owner's own read (30 verdicts set aside, verdict hidden), an ATI panel, a hand
read of the Oracle lens (SFT) and logit-lens verdicts (the hand read above covers the arms of
plan 0108 only). The logit-lens L63 floor and the Oracle lens (SFT) read were deferred by plan
0108 and are measured since plan 0115 (above).

## Versions

- Bank v3 (plan 0116, `+bank-v3`): bank v2 minus four items, plus 47 new items; the registered
  bank. Its first build, a 100-item draft, was judged and had floors frozen on the branch,
  missed the described-guesser bar and was never pushed; the bank of record is the 99-item
  build (plan 0116 §7, §8). The concept pool was rebuilt, so every arm was judged anew.
  **A named exception to the rule below ("a bank change after results is a new version")**:
  the 100-item draft was floored and judged locally under the `...+bank-v3` stamp before the
  99-item bank took it. The exception was decided by the reviewing main session (not by the
  owner) because no result of the draft left the branch. `v3/floor_run1/` and `v3/floor_run2/`
  are measurements of 100-item lists and say so in their `bank` field; a local result
  directory of the draft must not be reported as bank v3.
- Bank v1 was the first build, 74 items: registered on the branch, judged on every arm in
  validation, never merged. Its options-only gate failed in bank order (blind 0.154,
  described 0.211; obscure 0.236 and 0.305 against a bar of 0.175), so the bank changed after
  results existed, and by the plan's rule that is a new version: the bank of record is v2
  (`+bank-v2`). The kept items' verdicts are the same on v1 and on v2 for every arm under
  `gate-h1`.
- The judge's concept pool (the forms of every option of the bank, merged where two entries
  share a form) decides the pins, the other-option forms of the gate and the token-list void.
  It is frozen in the header (`concepts`, checked by V13) and read from there. A successor
  bank that only drops items must carry the list unchanged; then the kept items' judge calls
  replay from a `cells.jsonl`. A successor that adds items or forms rebuilds the pool, and
  calls of kept items can change.

## Judge prompts

`prompt_version`: `assoc-hard-v1+gate-h2+bank-v3`. Judge calls are keyed `assoc-hard-v1` (`CALL_VERSION`:
prompts + options); the stamp adds the code-side gate (`GATE_VERSION`, `gate-h2`) and the bank
(`BANK_TAG`, `bank-v3`). Summary results add `+maj3v` (nothing under
`opts=draws=1`, the single-draw diagnostic) and the digest tail. Judge: the repo default
(`claude-opus-5-5`). Output schema `readout_mc` / `quote_mc`: `{"choice": int, "quote": str}`.
`{READOUT_PHRASE}` and `{CANNOT}` of the plan are interpolated below. Token readouts get the
shared token-list rule (`digest.token_note_of`), never written in these prompts.

`SYSTEM_SUMMARY`

````text
You judge readouts of a language model's internal activations, recorded while the model read a passage you cannot see. You get a digest of those readouts across every read layer and token position (described in the note below) and ONE multiple-choice question: which listed concept do the readouts state? Some options are compounds: a thing with a qualifier ("a blunt knife"), a thing made of an unusual material ("a boat made of cheese"), or one place inside another ("a cinema in a submarine"); the list may also hold the bare thing ("a knife") and the same thing with another qualifier, material or place.

What states an option. Pick an option only if one readout line states that concept itself: the word in any case, inflection or spelling variant, an established synonym or alias, a faithful translation into any language, a narrower instance that necessarily entails it ("a puppy" names "dog"), or a description that depicts the concept itself. A line states a COMPOUND option only if that ONE line expresses every part of it, the thing and its qualifier, material or enclosing place, about the same object, in any wording, word order or language ("the knife was too dull to cut" states "a blunt knife"; "a fork ... described as made of chocolate" states "a pitchfork made of chocolate"). Parts found in different lines never add up, and a part the line denies is not expressed ("a metal fork that only smelled of chocolate" does not state a fork made of chocolate). Do NOT pick an option you can only infer from clues, scene details or evidence ("crayon drawings on the fridge" do not name "child"; "the blade crushed the tomatoes" does not state "blunt"); a broader category, the general topic, a merely related idea, a different word that contains the option's letters, and word fragments state nothing.

More specific wins. A line that states a compound states that compound only: it is not a line for the bare thing, nor for an option that shares only one part with it, and it does not count as a line holding two options. Lines that name only the bare thing say nothing for or against its compounds: however many they are, they never outvote a line that states a listed compound. Pick the bare thing only when lines name it and NO line states a listed compound of it. A line that gives the thing a qualifier, material or place found in no option states no compound.

Lists and conflicts. A single list or line that holds two or more DIFFERENT listed options (not a compound and its own parts) singles out none of them, whatever their order; a line that is a run of interchangeable words of one kind (animals, materials, places, names, ...) singles out none of them, whatever their rank, even when only one of them is a listed option. If lines state two or more options that exclude each other (different things, or the same thing with different qualifiers, materials or places), pick one only if it is stated as what the passage is about, or is stated by clearly more lines than any other; lines that state nothing never count toward this. If no line states an option, or no option wins, choose "cannot tell from the readout". Do not use world knowledge or plausibility to fill gaps.

Give a SHORT quote copied character for character from inside ONE readout line that states the option you picked; for a compound, the quote must contain every part of it.
````

`SYSTEM_NATIVE`

````text
You judge readouts of a language model's internal activations, recorded while the model read a passage you cannot see. You get the readouts at one layer, grouped by token position and ONE multiple-choice question: which listed concept do the readouts state? Some options are compounds: a thing with a qualifier ("a blunt knife"), a thing made of an unusual material ("a boat made of cheese"), or one place inside another ("a cinema in a submarine"); the list may also hold the bare thing ("a knife") and the same thing with another qualifier, material or place.

What states an option. Pick an option only if one readout line states that concept itself: the word in any case, inflection or spelling variant, an established synonym or alias, a faithful translation into any language, a narrower instance that necessarily entails it ("a puppy" names "dog"), or a description that depicts the concept itself. A line states a COMPOUND option only if that ONE line expresses every part of it, the thing and its qualifier, material or enclosing place, about the same object, in any wording, word order or language ("the knife was too dull to cut" states "a blunt knife"; "a fork ... described as made of chocolate" states "a pitchfork made of chocolate"). Parts found in different lines never add up, and a part the line denies is not expressed ("a metal fork that only smelled of chocolate" does not state a fork made of chocolate). Do NOT pick an option you can only infer from clues, scene details or evidence ("crayon drawings on the fridge" do not name "child"; "the blade crushed the tomatoes" does not state "blunt"); a broader category, the general topic, a merely related idea, a different word that contains the option's letters, and word fragments state nothing.

More specific wins. A line that states a compound states that compound only: it is not a line for the bare thing, nor for an option that shares only one part with it, and it does not count as a line holding two options. Lines that name only the bare thing say nothing for or against its compounds: however many they are, they never outvote a line that states a listed compound. Pick the bare thing only when lines name it and NO line states a listed compound of it. A line that gives the thing a qualifier, material or place found in no option states no compound.

Lists and conflicts. A single list or line that holds two or more DIFFERENT listed options (not a compound and its own parts) singles out none of them, whatever their order; a line that is a run of interchangeable words of one kind (animals, materials, places, names, ...) singles out none of them, whatever their rank, even when only one of them is a listed option. If lines state two or more options that exclude each other (different things, or the same thing with different qualifiers, materials or places), pick one only if it is stated as what the passage is about, or is stated by clearly more lines than any other; lines that state nothing never count toward this. If no line states an option, or no option wins, choose "cannot tell from the readout". Do not use world knowledge or plausibility to fill gaps.

Give a SHORT quote copied character for character from inside ONE readout line that states the option you picked; for a compound, the quote must contain every part of it.
````

`QUESTION`

````text
Which concept do the readouts state?
{listing}
````

`USER_SUMMARY`

````text
{note}

READOUTS:
{digest}

{question}
````

`USER_NATIVE`

````text
{note}

READOUTS:
{blocks}

{question}
````

`NATIVE_NOTE_PROSE`

````text
Each readout line below is one free-text sample.
````

`RETRY_LINE`

````text
Your quote was not found inside one readout line; copy it exactly from one line.
````

`QUOTE_USER`

````text
READOUT (one span quoted from the readouts):
{quote}

{question}
````

`QUOTE_USER_TOKENS`

````text
READOUT (tokens quoted from one ranked list, ' | ' separated):
{quote}

{question}
````

`DIGEST_TASK_NOTE`

````text
the model read a short scene (sometimes not in English) that evokes one thing without naming it (an object, an animal, a place, an instrument, a dish, a phenomenon or an activity, sometimes in an unusual state, made of an unusual material or set in an unusual place), and was then asked to summarize the story in one sentence; the thing, and what is unusual about it, may appear in only one or a few readouts
````

`SUMMARY_NOTE`

````text
The readout below is a digest of the readouts across every read layer and position: for each read layer, a note-taker who did not see the passage picked the most prominent readout samples, then samples carrying content seen in only one or a few samples, and the layers' picks are merged, the most-stated first. Each line is marked with how many readout samples state its content ([N samples], or [N samples, M layers] when it was seen at M read layers): counted per claim, so a sample that only lists the word among others of its kind, or only restates the question, is not counted; compare these counts when weighing lines against each other. Each line is one real readout sample (a free-text generation, or one ranked list of top tokens). Treat each line as a separate sample: pieces on different lines never combine. Any quote must be copied from inside one line, without the bracketed marker.
````

`SUMMARY_NOTE_ABSTRACTIVE`

````text
The readout below is a digest of the readouts across every read layer and position, written layer by layer by a note-taker who did not see the passage, most prominent first, then content seen in only one or a few samples. Each line is one statement in the note-taker's words, how many samples state it (counted per claim), and a verbatim evidence span from one real readout sample. The statements are not evidence: judge what the evidence spans show, treat each line as a separate sample (pieces on different lines never combine), and copy any quote from inside one evidence span.
````

## History

- 2026-11-23 (plan 0108): registered. Bank v2 = 56 of the authoring run's 109 candidates
  (16 two-measurement leakers, 1 off-grid list, 18 + 4 by the two runs of the grid pass, 14 by
  the bank-order pass); `gate-h2` and bank v2 after the first validation and the review of the
  PR; instrument `assoc-hard-v1+gate-h2+bank-v2`.
- 2026-11-23 (plan 0116): bank v3, `assoc-hard-v1+gate-h2+bank-v3`, 99 items = 52 of bank v2
  (the four known-issue items dropped) + 47 new items, each gated in one run, after the
  described-guesser bar was applied once as a gate (11 dropped, 11 backfilled, 1 dropped).
  Prompt-only floor 0.970 [0.939, 1.000], lucky blind 0.010, described 0.091 (every per-kind
  bar met), topic 0.394 (not a floor), logit lens L63 0.040 [0.010, 0.081]; Oracle lens (RL)
  0.899, Oracle lens (SFT) 0.889, NLA 0.818, J-lens 0.242. No prompt or gate change.
- 2026-11-23 (plan 0115): the two measurements plan 0108 deferred. Oracle lens (SFT)
  `s3d-sft251` 0.893 [0.804, 0.964] (second judging 0.893); logit lens L63 floor frozen at
  0.036 [0.000, 0.089] (2 of 56). No bank, stamp, prompt or gate change.
