#!/bin/sh
# Beethoven piano version of "The Neighbour": score + plan.json -> MIDI -> concert grand.
# Usage: ./render.sh [STEMS_DIR]     (STEMS_DIR: optional, dry per-voice stems for balance checks)
# Writes ricercar_beethoven_piano.{wav,m4a,render.json} here and copies the m4a to preview/.
# Plays nothing through the speakers.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
R=$(cd "$HERE/../.." && pwd)
OUT="$HERE/ricercar_beethoven_piano"
MID="${TMPDIR:-/tmp}/ricercar_beethoven_piano.mid"

python3 "$R/tools/perform.py" "$R/score/music-voices.ly" "$HERE/plan.json" "$MID" --target piano --cues

# --wet-db -1: the hall 1 dB under the dry piano, a little drier than the engine default so the
# four lines stay distinct in the tuttis while the apotheosis keeps its halo.
STEMS=""
if [ $# -ge 1 ]; then STEMS="--stems $1"; fi
(cd "$R/audio/piano" && python3 render_piano.py "$MID" -o "$OUT" --wet-db -1 \
    --json "$OUT.render.json" $STEMS)

cp "$OUT.m4a" "$R/preview/final_beethoven_piano.m4a"
rm -f "$MID"
echo "done: $OUT.wav, $OUT.m4a, $R/preview/final_beethoven_piano.m4a"
