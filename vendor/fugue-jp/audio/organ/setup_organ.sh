#!/bin/bash
# Set up the pipe-organ renderer (idempotent: every step checks what is already there).
#
# 1. wavpack (the sample files are WavPack-compressed), python packages
# 2. the Norrfjärden Church sample set by Lars Palo (CC BY-SA 4.0, 2.05 GB download, 1.9 GB
#    installed): download, verify size and sha256, extract, delete the archive
# 3. the church impulse response: OpenAIR Lady Chapel, St Albans Cathedral, ORTF position A
#    (CC BY 4.0), from audEERING's public mirror of the OpenAIR library (the York site is offline)
# 4. measure every pipe (pitch, loops, cue, speech) -> data/norrfjarden_pipes.json (committed; only
#    re-measured when missing or with --reanalyse)
#
# usage: ./setup_organ.sh [--reanalyse]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB=/Users/biobook/Music/SampleLibraries
ORG="$LIB/Organ"
SET="$ORG/NorrfjardenChurch"
URL=http://www.familjenpalo.se/sites/default/files/sampleset/packages/NorrfjardenChurch.orgue
BYTES=2045915742
SHA=f330a8f9f67ffa6b04d72098fc340db817f680421a51cea4e35a77618f3085eb
IRDIR="$LIB/IR/OpenAIR"
IRWAV=lady_chapel_st_albans_cathedral__stereo__stalbans_a_ortf.wav
IRURL=https://s3.dualstack.eu-north-1.amazonaws.com/audb-public/openair/media/1.0.0/8b50a145-8ea6-8b65-e56b-4f6e832b0011.zip
IRMD5=1e57722d6edfe8f121ab3f110adb3d45

echo "== tools"
command -v wvunpack >/dev/null || brew install wavpack
python3 -c "import numpy, scipy, soundfile, mido, soxr" 2>/dev/null || python3 -m pip install --user numpy scipy soundfile mido soxr
command -v afconvert >/dev/null || { echo "afconvert (macOS) is required for the .m4a"; exit 1; }

echo "== sample set"
if [ -f "$SET/NorrfjardenChurch.organ" ] && [ "$(find "$SET" -type f | wc -l | tr -d ' ')" -ge 4837 ]; then
  echo "present: $SET"
else
  df -h ~ | tail -1
  mkdir -p "$ORG/_dl"
  curl -fL -C - -o "$ORG/_dl/NorrfjardenChurch.orgue" "$URL"
  [ "$(stat -f %z "$ORG/_dl/NorrfjardenChurch.orgue")" = "$BYTES" ] || { echo "size mismatch"; exit 1; }
  echo "$SHA  $ORG/_dl/NorrfjardenChurch.orgue" | shasum -a 256 -c -
  mkdir -p "$SET"
  unzip -q -o "$ORG/_dl/NorrfjardenChurch.orgue" -d "$SET"
  rm -f "$ORG/_dl/NorrfjardenChurch.orgue"
  echo "installed: $SET ($(du -sh "$SET" | cut -f1))"
fi

echo "== impulse response"
if [ -f "$IRDIR/$IRWAV" ] && [ "$(md5 -q "$IRDIR/$IRWAV")" = "$IRMD5" ]; then
  echo "present: $IRDIR/$IRWAV"
else
  mkdir -p "$IRDIR"
  tmp=$(mktemp -d)
  curl -fL -o "$tmp/ir.zip" "$IRURL"
  unzip -q -o "$tmp/ir.zip" -d "$tmp"
  f=$(find "$tmp" -name "$IRWAV" | head -1)
  [ "$(md5 -q "$f")" = "$IRMD5" ] || { echo "IR checksum mismatch"; exit 1; }
  mv "$f" "$IRDIR/$IRWAV"
  rm -rf "$tmp"
  echo "installed: $IRDIR/$IRWAV"
fi

echo "== pipe model"
if [ ! -f "$HERE/data/norrfjarden_pipes.json" ] || [ "${1:-}" = "--reanalyse" ]; then
  python3 "$HERE/analyze_organ.py" --jobs 8
else
  echo "present: $HERE/data/norrfjarden_pipes.json (--reanalyse to measure again)"
fi
echo "ready: python3 $HERE/render_organ.py IN.mid --registration REG.json -o OUT"
