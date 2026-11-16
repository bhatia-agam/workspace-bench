"""Run a global-workspace ccut v2 stage with an adapt subject in Qwen's place (plan 0084).

    HC_SUBJECT=glm-5.3 python subject_ccut.py <ccut_stages|ccut_frozen|ccut_exist4> variant=v2 \
        out_dir=<dir> stage=<stage> [...]

cwd = a gw source tree (``evals/chint_cutoff/bank_v2.json``); PYTHONPATH = gw ``src`` + the
cf_influence scripts dir + workspace-bench ``src``. The cwd must be a scratch copy holding only
``evals/chint_cutoff/`` (``bank`` and ``freeze`` write into it), never a gw checkout. The
substitutions, nothing else:
- ``ccut_stages._TOK`` = the subject's tokenizer with its pinned thinking-off template
  (``subjects.load_tokenizer``), so prompt lengths, the re-render check against the generated
  ``prompt_token_ids``, the reply-token count and every read position index the SUBJECT's
  render;
- ``ccut.TEMPLATES = ("metadata",)``: only the metadata hint is screened (gw #753 froze the
  metadata pairs only; the other two templates' read spans end before the hint);
- ``HC_P_WINDOW=lo,hi`` (optional) moves v2's probe window (``ccut.P_WINDOW``): the window the
  bank is drafted / filtered in (plan 0084 §1: the subject's fade-out lies later than Qwen's).
- ``HC_SURV=sI,sN,sI_screen,sN_screen`` (optional): the per-kind survivals v2's projection gates
  use (``ccut.V2_SURV_*``, Qwen v1's), replaced by the subject's measured pilot survivals;
- ``HC_CONFIRM_ALL=1`` (the pilot only, plan 0084 §2): ``confirm_gen`` confirms EVERY
  screen-passing condition of both kinds, not only the pairable I and their <= 4 N, so the
  pilot measures each stage's survival on all its candidates.
- ``HC_GUESS_GAP=<caliper>`` (plan 0084 R18): a fourth rating, ``guess`` (``guess_rate.py``,
  stored in the out dir's ``obscure.json``), joins ``ccut.RATINGS``: every v2 use of the ratings
  (the pairable caliper, the matching cost, the gate AUROC, attempt 1's halving, the scored
  AUROCs) then covers it, through a ``Cand`` / ``V2Match`` subclass with the extra field.
- a tokenizer with no ``offset_mapping`` (Kimi-K2's tiktoken) is wrapped by ``OffsetTok``
  (exact character offsets from each id's bytes); a fast tokenizer is passed through unchanged.
The ``[gen]`` step is ``subject_gen.py`` (the subject's adapt Modal app).
"""

import importlib
import os
import sys


def _add_guess(ccut, gap: float) -> None:
    """Plan 0084 R18: ``guess`` as a fourth v2 rating. ``Cand`` objects built without it (v2's
    ``_v2_cand`` passes the three named ratings) read it from the ``obscure.json`` of the
    ``out_dir=`` argument."""
    import dataclasses
    import json
    from pathlib import Path

    out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("out_dir="))
    table = {
        q: r.get("guess") for q, r in json.loads((Path(out) / "obscure.json").read_text()).items()
    }

    @dataclasses.dataclass(frozen=True)
    class Cand(ccut.Cand):
        guess: float | None = None

        def __post_init__(self) -> None:
            if self.guess is None:
                object.__setattr__(self, "guess", table.get(self.qid))

    @dataclasses.dataclass(frozen=True)
    class V2Match(ccut.V2Match):
        max_guess_gap: float = gap

    ccut.Cand, ccut.V2Match = Cand, V2Match
    ccut.RATINGS = (*ccut.RATINGS, "guess")


def _has_offsets(tok) -> bool:
    try:
        enc = tok("a", add_special_tokens=False, return_offsets_mapping=True)
        return enc["offset_mapping"] is not None
    except (KeyError, NotImplementedError, TypeError, ValueError):
        return False


class OffsetTok:
    """A tokenizer whose ``__call__`` has no ``return_offsets_mapping`` (tiktoken) with exact
    character offsets rebuilt from each id's bytes (``model.decode_single_token_bytes``; special
    ids via ``decode``); the pieces must re-join to the text, and a token that ends inside a
    multi-byte character spans that character. Everything else is the wrapped tokenizer."""

    def __init__(self, tok) -> None:
        self._tok = tok

    def __getattr__(self, name):
        return getattr(self._tok, name)

    def _piece(self, i: int) -> bytes:
        try:
            return self._tok.model.decode_single_token_bytes(i)
        except Exception:
            return self._tok.decode([i]).encode("utf-8")

    def __call__(self, text, **kw):
        want = kw.pop("return_offsets_mapping", False)
        enc = self._tok(text, **kw)
        if want:
            enc["offset_mapping"] = self.offsets(text, list(enc["input_ids"]))
        return enc

    def offsets(self, text: str, ids: list[int]) -> list[tuple[int, int]]:
        pieces = [self._piece(i) for i in ids]
        raw = text.encode("utf-8")
        if b"".join(pieces) != raw:
            raise ValueError("token bytes do not re-join to the text")
        char_at = [0] * (len(raw) + 1)  # byte index -> the index of the character it belongs to
        b = 0
        for ci, ch in enumerate(text):
            for _ in ch.encode("utf-8"):
                char_at[b] = ci
                b += 1
        char_at[len(raw)] = len(text)
        out, b = [], 0
        for pc in pieces:
            e = b + len(pc)
            mid_char = e < len(raw) and char_at[e - 1] == char_at[e]
            end = char_at[e] + 1 if mid_char else char_at[e]
            out.append((char_at[b], max(end, char_at[b])))
            b = e
        return out


def with_offsets(tok):
    """``tok`` itself when it yields ``offset_mapping`` (fast tokenizers, unchanged), else
    ``OffsetTok(tok)``."""
    return tok if _has_offsets(tok) else OffsetTok(tok)


def main() -> None:
    mod_name = sys.argv.pop(1)
    from pathlib import Path

    cwd = Path.cwd()
    assert not (cwd / ".git").exists() and not (cwd / "src/global_workspace").exists(), (
        f"{cwd}: run in a scratch gw cwd, not a gw checkout (bank / freeze write into it)"
    )
    from global_workspace.olens_suite.cf_influence import ccut

    from wsbench.adapt import subjects

    ccut.TEMPLATES = ("metadata",)
    if w := os.environ.get("HC_P_WINDOW"):
        lo, hi = w.split(",")
        ccut.P_WINDOW = (lo, hi)
    if sv := os.environ.get("HC_SURV"):
        ccut.V2_SURV_I, ccut.V2_SURV_N, ccut.V2_SURV_I_SCREEN, ccut.V2_SURV_N_SCREEN = (
            float(x) for x in sv.split(",")
        )
    if gap := os.environ.get("HC_GUESS_GAP"):
        _add_guess(ccut, float(gap))
    s = subjects.get(os.environ.get("HC_SUBJECT", "glm-5.3"))
    tok = subjects.load_tokenizer(
        s.hf_id, s.revision, s.tokenizer_dir, s.chat_template, s.trust_remote_code
    )
    import ccut_stages

    ccut_stages._TOK = with_offsets(tok)
    if os.environ.get("HC_CONFIRM_ALL") == "1":

        def confirm_all(cfg, d, bnk, passed, keys, lens):
            return (
                [k for k in keys if passed[k]["kind"] == "I"],
                [k for k in keys if passed[k]["kind"] == "N"],
            )

        ccut_stages._confirm_pick_v2 = confirm_all
    mod = importlib.import_module(mod_name)
    mod.main()


if __name__ == "__main__":
    main()
