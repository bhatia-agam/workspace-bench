# workspace-bench

WorkspaceBench tests whether an activation-reading lens surfaces what a model computes but never
writes. Each eval pairs a fixed set of questions, built so that the model must hold a specific
hidden thing (a bridge fact, an intermediate number, a user's trait), with a judge that checks
whether the lens's readout at that point carries it. You hand over one JSONL file of readouts
per eval and `wsbench` scores it.

**A score** is the share of an eval's questions on which the judge finds the hidden thing in the
readouts (0 to 1, with a 95% interval), shown beside two floors: what a guesser gets without the
readouts, and what a reader gets from the prompt alone. The macro is the mean over evals.

Write-up: [WorkspaceBench: Evaluating Interpretability Methods for the Global Workspace](https://www.lesswrong.com/posts/Zeg2JztbdhguL48uH/workspacebench-evaluating-interpretability-methods-for-the).
This README says "eval" for what the code calls a family.

## Requirements

| | what you need |
|---|---|
| Software | Python 3.12 or newer and [`uv`](https://docs.astral.sh/uv/). |
| Judge access | An Anthropic credential: `ANTHROPIC_API_KEY`, or `ANTHROPIC_PROFILE=<name>` (an `ant auth login` profile), or `ANTHROPIC_AUTH_TOKEN` (an OAuth bearer token). The judges are `claude-opus-5-5` and, for the two safety evals, `claude-sonnet-5` ([docs/judges.md](docs/judges.md)). Nothing else is needed to judge. |
| Hardware to judge | None beyond a laptop: judging is API calls. |
| Hardware to produce readouts | Only if you run a lens here. The reference model is Qwen3.6-27B: about 54 GB of weights at 16-bit precision (an estimate from its size, not a measurement). The timings below were measured on NVIDIA B200 GPUs (183 GiB), where a served reader with 768 requests in flight used 174 GiB. |
| Disk | 0.8 GB for the checkout. Readouts and judge caches of a full run were not measured; plan for tens of GB. |
| Network | The Anthropic API. Two evals fetch pinned public data: `nyt_connections` its puzzles when it plans or judges, `knowledge_cutoff` part of its questions when it plans. Producing readouts downloads the model from Hugging Face. |

## Time and cost

One prose lens on the reference model, 11 layers, measured on NVIDIA B200 GPUs with a served
reader and 176 to 352 judge calls in flight. Your numbers depend on your reader and your API
rate limits. Judging dominates both time and cost.

| what you run | questions / cells | GPU-hours to read | wall-clock to read | judge calls | judge wall-clock | judge cost | time to a score |
|---|---|---|---|---|---|---|---|
| The two-question try-out | 2 / 4 | none (shipped example readouts) | none | 4 | 20 s | under $0.10 (estimate) | under a minute |
| The fast subset (`--fast`) | 2,160 / 657,690 | 1.95 | 12 min on 12 GPUs | 31,280 | 36 min | $1,863 | 1 h 1 min as run; about 45 min (estimate) without a scheduling stall in that run |
| The core evals (default) | 4,541 / 2,885,822 | about 8.2 (estimate) | not measured | 63,172 | not measured on its own | $3,556 | not measured |
| Every eval (`--full`) | 6,099 / 3,261,846 | 9.26 | 48 min on up to 32 GPUs | 81,218 | ended 101 min after the read | $4,574 | 2 h 29 min as run |

Reading also needs the model's activations captured once: 0.3 GPU-hours for the fast subset,
0.8 for every eval. The core row's judge calls and cost are the core evals' share of the full
run. A cell is one (question, layer, position) readout.

## Install

```bash
git clone https://github.com/camilablank/workspace-bench && cd workspace-bench
uv sync --extra dev
uv run wsbench check judge_dry_run   # offline, no key: every eval builds its first judge prompt
```

Use the package from this checkout: the question banks live in `evals/` beside `src/`.

## Try it on two questions

```bash
uv run wsbench try family=multihop dry_run=True   # no key, no GPU: shows the judge prompt
uv run wsbench try family=multihop                # judges for real: 4 calls
```

```text
== wsbench try: multihop, 2 item(s), readouts <checkout>/examples/readouts/multihop.jsonl
[1] mh2-coeur-de-lion-brother-charter-q2
    question: Fact: the crusader monarch nicknamed 'Cœur de Lion', who first licensed jousting ...
    expected: Magna Carta | Magna Carta Libertatum
    looks for: Richard I of England | John of England
    read at: positions all, layers 20..60
...
== judge (live judge)
== report
== outputs
  read plan (what to read for each item): outputs/try/multihop/plan/multihop.jsonl
  results (score, CI, per-item rows): outputs/try/multihop/judged/multihop/results.json
  report table: outputs/try/multihop/judged/summary.md
== see it in the viewer (uv sync --extra dev --extra viewer)
```

It shows each question with its expected answer, runs the ordinary judge and report on the
shipped example readouts, and lists every file it wrote under `outputs/try/multihop/`. A
two-question run is marked `complete=False` and left out of the macro; that is expected. Pass
`readouts=<your file>` to try your own lens and `n=` for more questions; any eval from
`wsbench list` works.

## Run it

```bash
# 1. what to read: per eval, one row per question (how to render it, which positions and layers)
uv run wsbench plan out=outputs/plan

# 2. readouts: run your lens on those cells and write one JSONL per eval (the contract below)

# 3. judge every eval that has a file; here one eval of the shipped example, first without calls
uv run wsbench run readouts_root=examples/readouts families=multihop allow_missing=True out=outputs/judged/example dry_run=True
uv run wsbench run readouts_root=examples/readouts families=multihop allow_missing=True out=outputs/judged/example

# 4. one table: score, interval, n and the floors beside each eval, plus the macro
uv run wsbench report dir=outputs/judged/example
```

With your own lens, point `readouts_root=` at your directory and drop `families=` and
`allow_missing=True` (the example has readouts for two questions only, which `run` otherwise
refuses to score).

A readouts file has one row per cell, all prose or all tokens; `id` is the question id, `pos`
the read position:

```json
{"id": "ec-ransom-chat_tf", "layer": 36, "pos": 33, "samples": ["The model is weighing ...", "..."]}
{"id": "ec-ransom-chat_tf", "layer": 36, "pos": 33, "tokens": [" ransom", " incentive", "..."], "scores": [10.8, 9.9, 1.2]}
```

`plan` and `run` choose their evals in one of these ways (a choice only selects; it changes no
score):

| you pass | what runs |
|---|---|
| nothing, or `--core` | The 17 core evals, the set a method is reported on. |
| `--full` | Every eval: 31. |
| `--fast` | The fast subset: 22 evals on fewer questions, for quick iteration. Also on `judge` and `report`. |
| `--fast-safety` | The fast subset with the two safety evals: 24. |
| `group=<category>` | The evals of one category from [the table below](#the-evals), for example `group=safety`. `group=association` also takes `role_bound_association`; `--show` prints what a group resolves to. |
| `families=a,b` | The evals you name. |
| `items=id1,id2` | Only these questions (on `judge` and `run`). |
| `anti_text_inversion=True` | Only the questions that no text-only reader answers from the prompt (on `judge` and `run`). |

Every command takes `key=value` arguments; `--help` lists a command's keys and `--show` prints
the resolved settings without running. Producing readouts with a bundled lens, the read plan's
format and all options of `judge` and `run`: [docs/producing_readouts.md](docs/producing_readouts.md),
[docs/running.md](docs/running.md).

## Where outputs go

Everything is written under the `out=` you pass, and every command prints the paths it wrote.

| file | what it holds |
|---|---|
| `<out>/<eval>/results.json` | The result: score, interval, counts, one row per question. |
| `<out>/<eval>/cells.jsonl` | Every judge call, so a re-run only pays for what is missing. |
| `<out>/summary.md` | The table `run` and `report` print. |
| `<out>/run.json` | Per-eval status and spend of a `run`. |
| `outputs/plan/<eval>.jsonl` | The read plan. |
| `outputs/try/<eval>/` | Everything the try-out writes. |

**Reading a result.** In `summary.md` each row is one eval: `value` is the score, `95% CI` its
interval, `n` the questions judged (with how many stayed undecided), `chance` the guessing
floor, and `complete` says whether every planned question was judged with the pinned judge. Only
complete rows enter the macro. The fields of `results.json`:
[docs/results_contract.md](docs/results_contract.md).

## Checks

```bash
uv run wsbench check        # list every check, what it guards and the options it takes
uv run wsbench check all    # run the five that need no option: offline, no key
```

`check all` covers the frozen question-bank hashes, that every judge prompt in the code is
verbatim in its eval's page, and a judge dry run of every eval. It lists the three checks that
need an argument as SKIP. Details: [docs/checks.md](docs/checks.md).

## Viewer

```bash
uv sync --extra dev --extra viewer
uv run wsbench viewer ingest examples/viewer_toy adapter=wsb lens=toy-olens store=outputs/viewer_store
uv run wsbench viewer serve store=outputs/viewer_store     # http://127.0.0.1:8600
```

A local page for reading results question by question: scores with floors, how each eval is
judged, and every lens's readouts beside the judge's decision. `ingest` takes any judged
directory; a live `wsbench try` prints the two commands for its own output. It also reads
HallucinationBench results. More: [src/wsbench/viewer/README.md](src/wsbench/viewer/README.md).

## The evals

31 evals in eight categories; `core` marks the default set. Each eval's page states its
questions, read sites, prompts and pass rule; [docs/evals.md](docs/evals.md) has one example and
the judging rule of each.

| category | eval | what it tests | questions |
|---|---|---|---|
| Basic | [`basic_readout`](evals/basic/basic_readout/README.md) | The multi-word answer to a factual question the model has read but not yet answered. | 90 |
| Basic | [`basic_readout_st`](evals/basic/basic_readout_st/README.md) | The same with a one-word answer. | 100 |
| Basic | [`directed_modulation`](evals/basic/directed_modulation/README.md) | A concept the model was told to think about, not think about, or hide while copying a sentence. | 100 |
| Basic | [`multi_concept_directed_modulation`](evals/basic/multi_concept_directed_modulation/README.md) (core) | Up to three concepts, or who does what to whom, held in mind while writing a dictated sentence. | 116 |
| Basic | [`multihop`](evals/basic/multihop/README.md) | The unstated multi-word bridge of a two- or three-hop fact. | 70 |
| Basic | [`multihop_st`](evals/basic/multihop_st/README.md) | The unstated one-word bridge of a two-hop fact. | 98 |
| Basic | [`multilingual`](evals/basic/multilingual/README.md) | The multi-word answer to a non-English prompt, in the prompt's language. | 100 |
| Basic | [`multilingual_multihop`](evals/basic/multilingual_multihop/README.md) | The bridge of a non-English two-hop prompt. | 98 |
| Basic | [`multilingual_st`](evals/basic/multilingual_st/README.md) | The one-word answer to a non-English prompt. | 99 |
| Basic | [`multilingual_typo`](evals/basic/multilingual_typo/README.md) | The intended word behind a misspelling in a non-English sentence. | 100 |
| Basic | [`poetry`](evals/basic/poetry/README.md) (core) | The rhyme word the model plans at the end of a couplet's first line. | 100 |
| Basic | [`typo`](evals/basic/typo/README.md) | The intended multi-word term behind a misspelling. | 85 |
| Basic | [`typo_st`](evals/basic/typo_st/README.md) | The intended word behind a misspelling. Replaced by `typo`: runs only when named. | 85 |
| Computational | [`arithmetic_intermediates`](evals/computational/arithmetic_intermediates/README.md) (core) | The intermediate values of an expression answered with no working shown. | 480 |
| Computational | [`buggy_code`](evals/computational/buggy_code/README.md) (core) | The bug in a short program, and no bug in its clean twin. | 143 |
| Computational | [`chain_intermediates`](evals/computational/chain_intermediates/README.md) (core) | The running value of a two- or three-step arithmetic chain. | 120 |
| Association | [`association`](evals/association/association/README.md) | A concept a scene implies but never names. | 93 |
| Association | [`conjunctive_association`](evals/association/conjunctive_association/README.md) | A compound state a vignette implies: what is felt, about what, towards whom. | 100 |
| Association | [`user_modeling`](evals/association/user_modeling/README.md) | An attribute of the user that a chat implies. | 126 |
| Safety | [`agentic_misalignment`](evals/safety/agentic_misalignment/README.md) (core) | The model's plan to take a misaligned action before it writes it, and none on the clean twin. | 54 |
| Safety | [`jailbreak_recognition`](evals/safety/jailbreak_recognition/README.md) (core) | The model noticing that a turn is a jailbreak, and not on harmless role-play. | 172 |
| Anti-bag-of-features | [`relational_multihop`](evals/anti_bag_of_features/relational_multihop/README.md) (core) | The relation between two people across two hops, which a bag of words cannot express. | 100 |
| Anti-bag-of-features | [`role_bound_association`](evals/anti_bag_of_features/role_bound_association/README.md) (core) | Who does what to whom in a scene: the direction, not just the words. | 100 |
| Logical processing | [`moral_rationale`](evals/logical_processing/moral_rationale/README.md) (core) | The reason behind a one-token answer to a hard dilemma. | 195 |
| Logical processing | [`nyt_connections`](evals/logical_processing/nyt_connections/README.md) (core) | The grouping the model has in mind before it answers a word puzzle. | 335 |
| Model-specific | [`hinted_cutoff`](evals/model_specific/hinted_cutoff/README.md) (core) | That the model uses a hint in the prompt which its reply never mentions. | 236 |
| Model-specific | [`introspection`](evals/model_specific/introspection/README.md) (core) | A concept injected into the model's activations. | 1,762 |
| Model-specific | [`knowledge_cutoff`](evals/model_specific/knowledge_cutoff/README.md) (core) | The stable wrong answer the model gives about things it does not know. | 147 |
| Model-specific | [`model_multihop`](evals/model_specific/model_multihop/README.md) (core) | A bridge that only this model believes. | 283 |
| Model-specific | [`model_specific_directed_modulation`](evals/model_specific/model_specific_directed_modulation/README.md) (core) | An obscure concept the model was told to think about. | 98 |
| Model-specific | [`wrong_intermediate`](evals/model_specific/wrong_intermediate/README.md) (core) | The wrong bridge the model resolves on its way to a wrong answer. | 100 |
| J-lens comparison | [`jlens_concept_pr`](evals/jlens_comparison/jlens_concept_pr/README.md) | Whether the concepts a lens states agree with the J-lens tokens at the same activation. In no macro. | 299 |

Older results and readouts may use earlier names for eight evals; `wsbench` reads both and
[docs/history.md](docs/history.md) has the table.

## More documentation

- [docs/evals.md](docs/evals.md): every eval with an example and its judging rule.
- [docs/producing_readouts.md](docs/producing_readouts.md): the read plan, positions, producing readouts with a bundled lens.
- [docs/running.md](docs/running.md): every option of `judge` and `run`, throughput, waiting on a producer.
- [docs/tiers.md](docs/tiers.md): the core, full and fast sets and their macros.
- [docs/fast_subset.md](docs/fast_subset.md): how the fast subset was chosen and how it relates to the full bench.
- [docs/baselines.md](docs/baselines.md): the floors, and the anti-text-inversion subset.
- [docs/judges.md](docs/judges.md): which model judges each eval, with which prompt, and why.
- [docs/judge_backends.md](docs/judge_backends.md): live calls or Message Batches, sizing concurrency.
- [docs/results_contract.md](docs/results_contract.md): the fields of `results.json` and the macro row.
- [docs/porting.md](docs/porting.md), [AGENTS.md](AGENTS.md), [adapted/README.md](adapted/README.md): running the bench on another model.
- [docs/hallucinationbench.md](docs/hallucinationbench.md): the HallucinationBench index that `report` shows.
- [docs/checks.md](docs/checks.md): the checks and how to add one.
- [docs/open_work.md](docs/open_work.md): open work.
- [CLAUDE.md](CLAUDE.md): conventions for contributors and agents.
- [docs/history.md](docs/history.md): renamed and removed evals.

## Credits

- **Qwen3.6-27B** (Alibaba) — the model being read; every bank's rollouts and responses are its
  outputs (see the model card for its licence).
- **Judge models** — Claude Opus 5.5 (Anthropic; the judge of every family since 2026-10-11;
  earlier results used Gemini 3.8 Flash via OpenRouter and Claude Sonnet 5). API terms only; no model outputs are
  redistributed as data.
- **Agentic misalignment** — Lynch et al. 2025, *Agentic Misalignment: How LLMs Could Be Insider
  Threats* (Anthropic, arXiv:2510.05179); code and prompt templates from
  `anthropic-experimental/agentic-misalignment` (MIT). 18 of the 32 scenarios are that repo's
  18-condition grid.
- **WildChat** — Zhao et al. 2024, *WildChat: 1M ChatGPT Interaction Logs in the Wild* (ICLR 2024,
  arXiv:2405.01470; HF `allenai/WildChat-1M`, ODC-BY). All jailbreak_recognition items are
  verbatim WildChat conversations or deletion-only rewrites of them (the twin controls). Transcript render contract from CHIVE — Karvonen et al.
  (arXiv:2608.16747, `adamkarvonen/chive`).
- **Transluce** — Choi et al. 2025, *Scalably Extracting Latent Representations of Users*
  (Choi, Huang, Schwettmann, Steinhardt). The user_modeling items are SelfDescribe rows and
  SynthSysPre system prompts from their release (the registered bank v3 keeps only the
  SelfDescribe rows, plus 79 `um-sd2-*` items written in-house in the SelfDescribe style); see
  that release for its data terms.
- **J-lens** — *Verbalizable Representations Form a Global Workspace in Language Models*
  (Anthropic / Transformer Circuits, 2026, arXiv:2607.15495); code `anthropics/jacobian-lens`
  (Apache-2.0); reference top-10 tokens from the `neuronpedia/jacobian-lens` n1000 wikitext
  artifact.
- **Chat and text corpora** — LMSYS-Chat-1M (Zheng et al. 2023, HF `lmsys/lmsys-chat-1m`; the
  LMSYS-Chat-1M Dataset License Agreement), DailyDialog (Li et al. 2017, HF `ConvLab/dailydialog`;
  CC BY-NC-SA 4.0), `NeelNanda/pile-10k` and `HuggingFaceFW/fineweb-edu` sample-10BT (ODC-BY):
  the jlens_concept_pr items were seeded from these corpora (the seed text is not shipped, only
  labels and read positions). No chat turns are shipped since 2026-10-30 (plan 0040).
- **NYT Connections** — the puzzles are The New York Times' (NYT Connections), read from the
  community mirror `Eyefyre/NYT-Connections-Answers` (pinned commit; the mirror carries no
  licence). The nyt_connections bank holds puzzle ids, member indices and Qwen's own labels only;
  the puzzle text is fetched at run time and never redistributed.

## License

Code and the in-house items are MIT (see [`LICENSE`](LICENSE)). Third-party data and code carry
their own terms, restated in [`NOTICE.md`](NOTICE.md).

## Cite as

If you use workspace-bench, please cite the repo and the write-up
([`CITATION.cff`](CITATION.cff) carries the same metadata for GitHub's citation widget):

```bibtex
@misc{blank2026workspacebench,
  author       = {Blank, Camila and Bhatia, Agam and Ong, Euan and Nanda, Neel},
  title        = {WorkspaceBench: Evaluating Interpretability Methods for the Global Workspace},
  year         = {2026},
  howpublished = {\url{https://www.lesswrong.com/posts/Zeg2JztbdhguL48uH/workspacebench-evaluating-interpretability-methods-for-the}}
}
```
