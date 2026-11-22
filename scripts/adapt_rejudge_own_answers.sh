#!/bin/bash
# Re-judge the three own-answer evals (poetry, basic_readout_st, moral_rationale) of a subject's
# lens runs with the subject's own golds. It waits for each tag's ordinary judging to finish,
# seeds the new judge directory with that run's judge cache, and calls
# scripts/adapt_gated_rescore.py judge.
#
# usage: scripts/adapt_rejudge_own_answers.sh SUBJECT MODEL_DIR TAG [TAG...]
#
# Inputs:  $WSB_OLENS_CKPTS/MODEL_DIR/wsb/TAG/{readouts,judged_opus} (default root:
#          $WSB_DATA_ROOT/agam/olens_ckpts), and the banks adapt_gated_rescore.py prepare wrote.
# Outputs: $WSB_GATED_OUT/SUBJECT/judged/TAG/<eval>/ (default outputs/normal_gated).
# Settings: WSB_ENV_FILE (a file of credentials to source), WSB_PYTHON (default: python),
#           RPM (judge requests per minute, default 420), MODAL_ENVIRONMENT (default: agam).
case "${1:-}" in -h|--help|"") sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; [ -n "${1:-}" ]; exit $? ;; esac
[ $# -ge 3 ] || { echo "usage: $0 SUBJECT MODEL_DIR TAG [TAG...]" >&2; exit 2; }
if [ -n "${WSB_ENV_FILE:-}" ]; then set -a; . "$WSB_ENV_FILE"; set +a; fi
export MODAL_ENVIRONMENT=${MODAL_ENVIRONMENT:-agam}; unset ANTHROPIC_API_KEY
cd "$(dirname "$0")/.." || exit 1
CKPTS=${WSB_OLENS_CKPTS:-${WSB_DATA_ROOT:-/workspace}/agam/olens_ckpts}
OUT=${WSB_GATED_OUT:-outputs/normal_gated}
PY=${WSB_PYTHON:-python}
S=$1; C=$2; shift 2
for T in "$@"; do
  TD=$CKPTS/$C/wsb/$T
  until [ -s "$TD/judged_opus/moral_rationale/results.json" ] && [ -s "$TD/readouts/moral_rationale.jsonl" ]; do sleep 30; done
  for F in poetry basic_readout_st moral_rationale; do
    D=$OUT/$S/judged/$T/$F; mkdir -p "$D"
    [ -s "$D/cells.jsonl" ] || cp "$TD/judged_opus/$F/cells.jsonl" "$D/cells.jsonl" 2>/dev/null
    [ -s "$D/results.json" ] && continue
    "$PY" scripts/adapt_gated_rescore.py judge "$S" "$TD" "$F" "${RPM:-420}"
  done
  echo "DONE $S $T"
done
