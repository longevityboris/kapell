#!/usr/bin/env bash
# Run the whole strings QA suite against the installed instruments; results -> qa/results/*.json,
# logs -> /tmp/sqa/logs.  qa_chain first (qa_mix, qa_clicks and qa_edge's fermata check read its
# render), then the independent checks four at a time, then the setup idempotency check.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
L=/tmp/sqa/logs; mkdir -p "$L"
cd "$HERE/.."
run() { local n="$1"; shift; /usr/bin/time -p python3 "qa/$n.py" "$@" > "$L/$n${1:+_${1#--}}.log" 2>&1; echo "$n $* -> $?"; }
run qa_chain
run qa_mix
run qa_clicks
run qa_edge & run qa_variants & run qa_dynamics & run qa_attack_pitch & wait
run qa_layers & run qa_layers --interference & wait
bash qa/qa_setup.sh > "$L/qa_setup.log" 2>&1; echo "qa_setup -> $?"
