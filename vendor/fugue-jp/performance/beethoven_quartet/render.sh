#!/bin/sh
# The Neighbour, string quartet (Beethoven): score + plan + spec -> WAV + m4a, then the preview copy.
#   plan.json     the performance (tempo, rubato, dynamics, voicing of the entries)
#   quartet.json  the scoring (who plays what, the viola hand-off, sforzandi, mix and hall)
#   bowing.py     bow lifts into the breaths (a taper of 2 levels into the general pause at 30:1, 1 at
#                 35:1 and 46:1); hinted parts' auto notes articulated at the render's --short-ms
#   swell.py      deepens perform.py's swell on long notes in the quartet MIDI (not on the C7 chord 61:3-63:1)
# Usage: sh render.sh [--keep-build]   (from anywhere; nothing is played through the speakers)
set -e
D=$(cd "$(dirname "$0")" && pwd)
R=$(cd "$D/../.." && pwd)
python3 "$R/tools/orchestrate.py" "$R/score/music-voices.ly" "$D/plan.json" "$D/quartet.json" "$D/build"
python3 "$D/bowing.py" "$D/build/quartet.mid" --orchestration "$D/build/orchestration.json" \
  --breath 30:1=2 --breath 35:1=1 --breath 46:1=1 --taper-s 0.3 --report "$D/build/bowing.json"
python3 "$D/swell.py" "$D/build/quartet.mid" --extra 0.75 --no-extra 61:3-63:1 --report "$D/build/swell.json"
python3 "$R/tools/orchestrate.py" "$R/score/music-voices.ly" "$D/plan.json" "$D/quartet.json" "$D/build" --check
python3 "$R/tools/mix.py" "$D/build/manifest.json"
cp "$D/ricercar_beethoven_quartet.m4a" "$R/preview/final_beethoven_quartet.m4a"
if [ "$1" != "--keep-build" ]; then
  # keep the reports, drop the stems and intermediate MIDI (disk)
  rm -rf "$D/build/render" "$D/build/perform"
fi
echo "done: $D/ricercar_beethoven_quartet.wav, .m4a; preview/final_beethoven_quartet.m4a"
