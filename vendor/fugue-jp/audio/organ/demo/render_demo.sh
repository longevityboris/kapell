#!/bin/bash
# The organ demo: the ricercar skeleton through perform.py (--target piano: tracks soprano, alto,
# tenor, bass) and the registration plan in this folder -> out/skeleton_organ.wav/.m4a, dry stems,
# the render report, and the measurement QA (qa/results/).
#
# usage: demo/render_demo.sh [SCORE.ly] [PLAN.json]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
R="$(cd "$HERE/../.." && pwd)"
SCORE="${1:-$R/design/final-lab/SK_final.ly}"
PLAN="${2:-$R/design/final-lab/plan.json}"
mkdir -p "$HERE/out" "$HERE/qa/results"
python3 "$R/tools/perform.py" "$SCORE" "$PLAN" "$HERE/out/skeleton.mid" --target piano
python3 "$HERE/render_organ.py" "$HERE/out/skeleton.mid" --registration "$HERE/demo/skeleton_registration.json" \
  -o "$HERE/out/skeleton_organ" --stems "$HERE/out/stems" --json "$HERE/out/skeleton_organ.json"
cp "$HERE/out/skeleton_organ.json" "$HERE/qa/results/skeleton_render_report.json"
python3 "$HERE/qa/qa_organ.py" "$HERE/out/skeleton.mid" "$HERE/out/skeleton_organ.json" "$HERE/out/stems" \
  "$HERE/out/skeleton_organ.wav" -o "$HERE/qa/results/skeleton_qa.json"
