#!/bin/bash
# The Bach version: the ricercar on the Norrfjärden organ, in one command.
#
#   score/music-voices.ly + plan.json (steadier tempo) + bach_organ.json (divisions, registration)
#     -> orchestrate.py     build/organ.mid, build/organ.registration.json, integrity check
#     -> articulate.py      baroque touch (key-ups only), integrity check again on the result
#     -> render_organ.py    ricercar_bach_organ.wav/.m4a (+ render report), with the church
#     -> qa_organ.py        measured on the audio: pitch, dropped and stuck notes, clicks, terraces
#     -> presence.py        every MIDI note on its stem (partials over their surroundings), ffmpeg loudness
#     -> levels.py          the shape on the audio: silent breaths, climax order, arioso solo, hinge, coda, entries
#     -> preview/final_bach_organ.m4a
#
# Stems go to a scratch folder (default /tmp) and are deleted after the QA. Nothing is played.
# usage: performance/bach_organ/render.sh [SCRATCH_DIR]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
R="$(cd "$HERE/../.." && pwd)"
SCRATCH="${1:-$(mktemp -d /tmp/bach_organ.XXXXXX)}"
SCORE="$R/score/music-voices.ly"
PLAN="$HERE/plan.json"
SPEC="$HERE/bach_organ.json"
B="$HERE/build"
OUT="$HERE/ricercar_bach_organ"
mkdir -p "$SCRATCH"

python3 "$R/tools/orchestrate.py" "$SCORE" "$PLAN" "$SPEC" "$B" --quiet
cp "$B/organ.mid" "$SCRATCH/organ_perform.mid"
python3 "$HERE/articulate.py" "$SCORE" "$PLAN" "$SCRATCH/organ_perform.mid" "$B/organ.mid" --json "$B/articulation.json"
python3 "$R/tools/orchestrate.py" "$SCORE" "$PLAN" "$SPEC" "$B" --check --quiet

python3 "$R/audio/organ/render_organ.py" "$B/organ.mid" --registration "$B/organ.registration.json" \
  -o "$OUT" --stems "$SCRATCH/stems" --json "$HERE/ricercar_bach_organ.render.json"
python3 "$R/audio/organ/qa/qa_organ.py" "$B/organ.mid" "$HERE/ricercar_bach_organ.render.json" \
  "$SCRATCH/stems" "$OUT.wav" -o "$HERE/ricercar_bach_organ.qa.json"
python3 "$HERE/presence.py" "$B/organ.mid" "$SCRATCH/stems" "$OUT.wav" "$OUT.m4a" \
  -o "$HERE/ricercar_bach_organ.presence.json"
python3 "$HERE/levels.py" "$B/organ.mid" "$PLAN" "$SCRATCH/stems" "$OUT.wav" \
  -o "$HERE/ricercar_bach_organ.levels.json"

cp "$OUT.m4a" "$R/preview/final_bach_organ.m4a"
rm -rf "$SCRATCH/stems" "$SCRATCH/organ_perform.mid"
rmdir "$SCRATCH" 2>/dev/null || true
echo "done: $OUT.wav, $OUT.m4a, $R/preview/final_bach_organ.m4a"
