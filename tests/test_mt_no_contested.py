"""``norival-v1``: basic_readout_mt and multihop_mt_v2 no longer overrule a judge pick
with code support counting: ``contested_verdict`` (the judge's unaudited rival_quote, every other
listed option's best digest line, the hidden rivals) and the option-audit call are gone. The
judge's rival_quote is reported, never scored; the MC calls keep their cached key."""

from test_basic_readout_mt import NAME, _gold, _item, _run

from wsbench import registry, rival
from wsbench.evals.multihop_mt_v2 import prompts as mh2p
from wsbench.multitoken import family as fam
from wsbench.multitoken import prompts as mp


def test_the_contested_machinery_is_gone():
    for name in ("contested_verdict", "hidden_rivals", "run_option_audits", "option_audit_lines",
                 "option_rival_entries", "dismissed_lines", "OPTION_RIVAL_VERSION"):  # fmt: skip
        assert not hasattr(fam, name), name
    for name in ("contest", "holders", "Margin", "MORE_THAN", "FAR_MORE", "AT_LEAST"):
        assert not hasattr(rival, name), name
    for name in ("OPTION_AUDIT_SYSTEM", "OPTION_AUDIT_USER", "OPTION_AUDIT_SCHEMA"):
        assert not hasattr(mp, name), name
    assert not any(k.startswith("OPTION_AUDIT") for k in mh2p.PROMPTS)
    assert not (registry.REPO_ROOT / "evals/basic_readout_mt/hidden_rivals.json").exists()


def test_stamps_move_and_call_keys_do_not(real_families):
    assert mp.BRMT_PROMPT_VERSION == "mc-brmt-2026-10-31r+norival-v1+qline-v2+bank-v6"
    assert fam.call_pv("basic_readout_mt", mp.BRMT_PROMPT_VERSION + "+digest-v5") == (
        "mc-brmt-2026-10-31r+rv-2026-10-31e+optrv-v1+bank-v4+digest-v5"
    )
    assert mh2p.MH2_PROMPT_VERSION == "mh2-mc-2026-11-01+norival-v1+qline-v2+bank-v6"
    assert fam.call_pv("multihop_mt_v2", mh2p.MH2_PROMPT_VERSION) == (
        "mh2-mc-2026-11-01+rv-2026-10-31e+optrv-v1+bank-v4"
    )
    assert fam.call_pv("multilingual", "x+y") == "x+y"  # other families: unchanged
    # the rival sentence is still in the prompts, byte-identical (cached answers stay valid)
    assert mp.BRMT_RIVAL_RULE in mp.BRMT_SYSTEM and mh2p.MH2_RIVAL_RULE in mh2p.SYSTEM


def test_a_gold_pick_beside_a_stronger_option_line_now_passes(tmp_path, monkeypatch, real_families):
    """The drakensberg / tippecanoe shape: the digest states another option on 13 samples and the
    gold on 1. Under the old contested rule the summary run sent an option-audit call and failed
    the pick as ``contested``; now the judge's pick stands (the MC options and cannot tell already
    decide)."""
    from summary_fakes import FakeLLM

    from wsbench.multitoken.options import option_sets

    it = _item("brh-ent-drakensberg")  # its id does not name its gold (Thabana Ntlenyana)
    gold = _gold(it)
    opts, g = option_sets([it], cannot=fam.mc_family(NAME).cannot)[it["id"]]["readout"]
    other = next(o for k, o in enumerate(opts[:-1]) if k != g)
    gold_line = f"R:{it['id']} the answer is {gold}"
    other_line = f"R:{it['id']} it is {other}"

    def text_of(_it, _layer, pos):
        return [gold_line if pos == -1 else other_line]

    def digest(_user):
        return {
            "items": [
                {"statement": "S-other", "where": "", "evidence": other_line, "count": 13},
                {"statement": "S-gold", "where": "", "evidence": gold_line, "count": 1},
            ]
        }

    real = FakeLLM.install

    def install(mp, judge, digest_fn=None):
        return real(mp, judge, digest=digest)

    monkeypatch.setattr(FakeLLM, "install", staticmethod(install))
    r, fake = _run(tmp_path, monkeypatch, {it["id"]: {"readout": "gold"}}, items=[it["id"]],
                   text_of=text_of, extra={"aggregate": "summary"}, layers=(44,))  # fmt: skip
    assert fake.n("option_rivals") == 0  # no audit call
    row = r.rows[0]
    assert row["pass"] is True, row
    assert "contested" not in r.extras["kinds"] and "n_contested" not in r.extras
