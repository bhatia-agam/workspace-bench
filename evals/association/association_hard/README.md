# association_hard: an uncommon or compound thing a scene implies but never names

In-house items (no external source). Plan: `plans/0108-association-hard.md`.

A short scene (1 to 3 sentences, sometimes not in English) evokes one thing without naming it,
and the model is asked to summarize the story in one sentence. The thing is either uncommon (an
didgeridoo, a red tide, a quipu: kind `obscure`) or an ordinary thing in an unusual state (`a
dead tree`: kind `complex_qualified`), made of an unusual material or set in an unusual place
(`a violin made of ice`, `a gym inside a courtroom`: kind `complex_unnatural`). The question is
whether a lens, read at the summarize-request positions, states the WHOLE concept: a readout
that says "a soloist playing the violin" has not surfaced `a violin made of ice`.

It is the hard sibling of [`association`](../association/README.md), whose files, stamps,
floors and read plan it leaves untouched: a separate package with its own prompts, judge, gate
and bank.

**Status.** Registered in the `full` tier only: not in core, no fast cut, no ATI entry, no
adapted set. The prompt-only reader solves nearly every item, so the family separates lenses
from each other (and prose lenses from token lenses); it does not separate a lens from a reader
of the text.

## Bank v2 (`items.json`, 56 items)

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

### Known issues (the header's `known_issues`)

- items guessable in one measurement of two stay (authoring.guess records both); the options-only rates are conditioned on that selection and on the frozen option order
- the topic guesser (the item's fine category beside the options) picks about half the golds: mc.category is close to a definition of the gold; measured, not a floor
- no human review of scenes, golds or forms: every grader is claude-opus-5-5
- the bank is selected on Qwen3.6-27B's own gate
- gold positions are a seeded shuffle and not balanced: a reader who always picks the first option is right on the share of items the header's histogram shows for slot 1
- the judge's concept pool (header `concepts`) is the whole bank's: a successor bank that only drops items must carry this list unchanged for kept items' calls to replay
- the prompt-only reader is expected at the ceiling: the family separates lenses from each other and from token lenses, not a lens from a reader of the text


Found by review r2, after the bank was frozen (not in the header; to be taken with the next bank
version, since a fix moves the bank and its floors):

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
read. Layers 20, 24, ..., 60. `reads=lite` reads the same sites. 56 x 19 x 11 = 11704
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

## Validation

Measured 2026-11-23 on the 56 items of bank v2, from stored readouts of Qwen3.6-27B (layers 20
to 60, the 19 sites; no new read) and judged by the registered instrument (`gate-h2`), every
arm twice (digests shared, judge calls fresh). 95% bootstrap CI of the first judging.

| arm | pass rate [95% CI] | second judging | obscure | complex_qualified | complex_unnatural | items differing |
|---|---|---|---|---|---|---|
| Oracle lens (RL) `s3d-rl600` | 0.929 [0.857, 0.982] | 0.929 | 28 / 30 | 9 / 9 | 15 / 17 | 2 |
| NLA `mlnla11-rl600` | 0.821 [0.714, 0.911] | 0.821 | 25 / 30 | 9 / 9 | 12 / 17 | 2 |
| J-lens `jlens-public` | 0.161 [0.071, 0.268] | 0.196 | 4 / 30 | 3 / 9 | 2 / 17 | 2 |
| prompt-only `po-opus-v1` (the frozen floor) | 0.982 [0.946, 1.000] | 0.982 | 30 / 30 | 9 / 9 | 16 / 17 | 0 |
| prompt-only, four bullets (pilot reader) | 0.982 [0.946, 1.000] | 0.982 | 30 / 30 | 9 / 9 | 16 / 17 | 0 |

The first-ask pass rate equals the headline on every arm (no pass needed the quote re-ask), no
item is undecided, and at most 2 of 56 items change verdict between two judgings. The J-lens
picks the bare head on 13 of the 26 compounds; the prose lenses on 0 and 3.

**The prompt-only reader solves the family: its floor (0.982) is above every lens.** The
family separates a token lens (0.16) from prose lenses (0.82, 0.93) and the prose lenses from
each other, mostly on `complex_unnatural`; it does not separate a lens from a reader of the
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

Not done: the owner's own read (30 verdicts set aside, verdict hidden), the logit-lens L63
floor and Oracle lens (SFT) reads (GPU), an ATI panel.

## Versions

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

`prompt_version`: `assoc-hard-v1+gate-h2+bank-v2`. Judge calls are keyed `assoc-hard-v1` (`CALL_VERSION`:
prompts + options); the stamp adds the code-side gate (`GATE_VERSION`, `gate-h2`) and the bank
(`BANK_TAG`, `bank-v2`). Summary results add `+maj3v` (nothing under
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
