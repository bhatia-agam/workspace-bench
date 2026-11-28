# Template for an eval's page

Every eval has a page at `evals/<category>/<family>/README.md`. New and revised pages follow
this shape, in this order. The first five sections are what a reader needs to trust a score;
keep them short and current. History goes last. Existing pages are moved to this shape when
the eval is next revised.

Rules that tests enforce: every prompt in the family's `prompts.py` appears verbatim in a fenced
block of the page, and the page names the current `PROMPT_VERSION`
(`tests/test_prompts_in_readme.py`); every repository path written in the page exists
(`tests/test_family_paths.py`).

Copy from the line below.

---

# <eval key>

One paragraph: what the model is asked, what hidden thing it must hold to answer, and what the
lens is expected to surface. One example question with its expected answer.

| | |
|---|---|
| Category | `<category>` |
| Sets | core / full / fast |
| Questions | <n>, bank `<items file>` |
| Stamp | `<PROMPT_VERSION>` |
| Scored by | <judge model>, <one phrase: multiple choice, free recall, ...> |

## What it measures

What a pass means in one or two sentences, and what it does not mean (the known way a readout
can pass without reading the model, if there is one).

## The exact prompt

What the model is given: the render (plain text, chat template, prefill), one full example as
the model sees it, and where the lens reads: which token positions and which layers.

## Note-taker

How an item's readouts become the notes the judge reads: the summarizer settings this eval
uses and its task note, or "none: the judge reads the readouts directly".

## Judge

The judge model, what it is shown (and what it is not shown), and every prompt verbatim:

```text
<SYSTEM prompt, verbatim from prompts.py>
```

```text
<USER prompt, verbatim from prompts.py>
```

## Pass rule

How judge answers become a question's verdict and how verdicts become the score: the unit that
is scored (a question, a pair, a slot), what counts as a pass, what is undecided, and the
metric.

## Checks and gates

One plain sentence per row. A build-time gate decides which questions are in the bank. A
scoring-time check is applied by code to the judge's answer and can change a verdict. A
report-only number is shown beside the score and never changes it.

| kind | name | what it does |
|---|---|---|
| build-time gate | | |
| scoring-time check | | |
| report-only number | | |

## Floors

Which floors apply (lucky guessing, prompt only, logit lens), where they are frozen, and what
they say about how much of the score needs the readouts.

## Running it

```bash
uv run wsbench try family=<family> dry_run=True
uv run wsbench judge family=<family> readouts=<file> out=<dir>
```

Options specific to this eval, if any.

## Bank and provenance

How the questions were built and gated, the bank versions and what each changed, the source
and license of external material.

## History

Dated entries, newest first: what changed, why, and the stamp it produced.
