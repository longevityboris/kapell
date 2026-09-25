#!/usr/bin/env bash
# Install and verify everything render_piano.py needs. Idempotent: whatever is
# already present and verified is left alone, so a second run is a quick check.
#
#   ./setup_piano.sh            install what is missing, verify everything
#   ./setup_piano.sh --check    verify only; also HEAD the download URLs (no downloads)
#   ./setup_piano.sh --force    additionally rebuild the derived SFZ and the hall IR
#
# Large assets go to $PIANO_LIB (default ~/Music/SampleLibraries), never into git:
#
#   SalamanderGrandPiano/SalamanderGrandPiano-SFZ+FLAC-V3+20200602/   samples + stock SFZ
#       + SalamanderGrandPiano-Ricercar*.sfz, *.calibration.json      (make_sfz.py)
#       + samples-aligned/  L/R time-aligned copies of the note samples (make_sfz.py, 670 MB)
#   IR/DetmoldSRIR/SetC_DenseKH_LSOrchestra/Data/{Omni,Fig8,DummyHead}/S1R163.wav
#   IR/Detmold-Konzerthaus-S1R163-MS-48k.{wav,json}                  (make_ir.py)
#   tools/sfizz/  (source at a pinned commit + sfizz_render_float32.patch)
#       build/library/bin/sfizz_render                                ($SFIZZ_RENDER overrides)
#
# Sources and licences
#   Salamander Grand Piano V3 (Yamaha C5), Alexander Holm, CC-BY 3.0;
#     FLAC/SFZ packaging by FreePats:
#     https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html
#   Open Database of Spatial Room Impulse Responses at Detmold University of Music,
#     Amengual Gari, Sahin, Eddy, Kob (AES 149, 2020), CC-BY 4.0:
#     https://zenodo.org/records/4116247  (only 3 small WAVs are fetched from the 986 MB zip,
#     by HTTP range requests, see fetch_zip_members.py)
#   sfizz, BSD-2-Clause: https://github.com/sfztools/sfizz
#
# FreePats publishes no checksum for the Salamander tarball, so the script checks its
# length and, after extraction, the SHA-256 of the stock SFZ plus a manifest hash over all
# 641 sample files (values recorded from the installation these renders were made with).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${PIANO_LIB:-$HOME/Music/SampleLibraries}"
MODE="install"
FORCE=0
for a in "$@"; do
  case "$a" in
    --check) MODE="check" ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

SAL_URL="https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SFZ+FLAC-V3+20200602.tar.gz"
SAL_BYTES=741757374
SAL_NAME="SalamanderGrandPiano-SFZ+FLAC-V3+20200602"
SAL_DIR="$LIB/SalamanderGrandPiano/$SAL_NAME"
SAL_SFZ="$SAL_DIR/SalamanderGrandPiano-V3+20200602.sfz"
SAL_SFZ_SHA256="91a273d53390c84a855437b4f37a734afac5cb0e4063b3ef59ccf0e63d909506"
SAL_SAMPLES=641
SAL_MANIFEST_SHA256="7ea4f8893504d0c6470627cb1096d249467b36c6fa6b342eaf40e11ca52ce4f4"

DET_URL="https://zenodo.org/api/records/4116247/files/DetmoldSRIR_v01.zip/content"
DET_BYTES=985710535  # md5 dce94799dbab211b72f537395b3b4e47 (Zenodo); we never fetch all of it
DET_DIR="$LIB/IR/DetmoldSRIR"
DET_FILES=(
  "SetC_DenseKH_LSOrchestra/Data/Omni/S1R163.wav 3db37707d7f7720e0c886ebbc3f8bcc64e617f35cd08362c4cc366fde6786a6c"
  "SetC_DenseKH_LSOrchestra/Data/Fig8/S1R163.wav 342ab50b632f4f52a2c34ef6639fd3c4eb01dc0af8ca36fc59c980bd65d3a560"
  "SetC_DenseKH_LSOrchestra/Data/DummyHead/S1R163.wav b7000263aeb5edc44b307cc72a3c8725bdee4abbf42595c60105cc60129a1010"
)
HALL_IR="$LIB/IR/Detmold-Konzerthaus-S1R163-MS-48k.wav"
HALL_IR_JSON="$LIB/IR/Detmold-Konzerthaus-S1R163-MS-48k.json"

SFIZZ_GIT="https://github.com/sfztools/sfizz.git"
SFIZZ_COMMIT="f5c6e29f23b8057867c08e88f5f6ac6738baa30b"
SFIZZ_SRC="$LIB/tools/sfizz"
SFIZZ_BIN="${SFIZZ_RENDER:-$SFIZZ_SRC/build/library/bin/sfizz_render}"
PATCH="$HERE/sfizz_render_float32.patch"

DERIVED_SFZ="$SAL_DIR/SalamanderGrandPiano-Ricercar.sfz"
DERIVED_SFZ_NP="$SAL_DIR/SalamanderGrandPiano-Ricercar-nopedalnoise.sfz"
CALIB="$SAL_DIR/SalamanderGrandPiano-Ricercar.calibration.json"
ALIGNED="$SAL_DIR/samples-aligned"

ok()   { printf '  ok    %s\n' "$*"; }
doing(){ printf '  ....  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*" >&2; FAILED=1; }
FAILED=0
sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
ncpu() { sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4; }

remote_len() {  # Content-Length after redirects, via a HEAD request
  curl -sIL --max-time 60 "$1" | tr -d '\r' | awk 'tolower($1)=="content-length:"{n=$2} END{print n}'
}

echo "piano setup ($MODE) in $LIB"
mkdir -p "$LIB"

# ---------------------------------------------------------------------------------------
echo "[1/6] tools"
for t in python3 curl git; do command -v "$t" >/dev/null && ok "$t" || fail "$t not found"; done
if python3 -c "import numpy, scipy, soundfile, mido" 2>/dev/null; then ok "python: numpy scipy soundfile mido"
else fail "python modules missing: pip3 install numpy scipy soundfile mido"; fi
command -v afconvert >/dev/null && ok "afconvert (AAC .m4a)" || echo "  warn  afconvert not found: use render_piano.py --no-m4a"
command -v ffmpeg >/dev/null && ok "ffmpeg (loudness report)" || echo "  warn  ffmpeg not found: render reports will lack LUFS/true-peak of the files"

# ---------------------------------------------------------------------------------------
echo "[2/6] Salamander Grand Piano V3 (CC-BY 3.0)"
if [[ ! -f "$SAL_SFZ" ]]; then
  if [[ "$MODE" == "check" ]]; then
    fail "missing $SAL_SFZ"
  else
    mkdir -p "$LIB/_downloads" "$LIB/SalamanderGrandPiano"
    TGZ="$LIB/_downloads/$SAL_NAME.tar.gz"
    if [[ ! -f "$TGZ" || "$(stat -f %z "$TGZ" 2>/dev/null || stat -c %s "$TGZ")" != "$SAL_BYTES" ]]; then
      doing "downloading $SAL_URL (742 MB)"
      curl -L --fail --retry 3 -C - -o "$TGZ" "$SAL_URL"
    fi
    size="$(stat -f %z "$TGZ" 2>/dev/null || stat -c %s "$TGZ")"
    [[ "$size" == "$SAL_BYTES" ]] || { fail "tarball is $size bytes, expected $SAL_BYTES"; exit 1; }
    doing "extracting"
    TMPX="$(mktemp -d "$LIB/_downloads/x.XXXX")"
    tar -xzf "$TGZ" -C "$TMPX"
    found="$(find "$TMPX" -name 'SalamanderGrandPiano-V3+20200602.sfz' | head -1)"
    [[ -n "$found" ]] || { fail "stock SFZ not found in the tarball"; exit 1; }
    mv "$(dirname "$found")" "$SAL_DIR"
    rm -rf "$TMPX" "$TGZ"
  fi
fi
if [[ -f "$SAL_SFZ" ]]; then
  [[ "$(sha256 "$SAL_SFZ")" == "$SAL_SFZ_SHA256" ]] && ok "stock SFZ sha256" || fail "stock SFZ checksum differs: $SAL_SFZ"
  n="$(find "$SAL_DIR/samples" -name '*.flac' | wc -l | tr -d ' ')"
  [[ "$n" == "$SAL_SAMPLES" ]] && ok "$n FLAC samples" || fail "$n FLAC samples, expected $SAL_SAMPLES"
  m="$(cd "$SAL_DIR/samples" && LC_ALL=C ls | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256 | cut -d' ' -f1)"
  [[ "$m" == "$SAL_MANIFEST_SHA256" ]] && ok "sample manifest sha256" || fail "sample manifest checksum differs ($m)"
fi

# ---------------------------------------------------------------------------------------
echo "[3/6] Detmold Konzerthaus impulse responses (CC-BY 4.0)"
for entry in "${DET_FILES[@]}"; do
  rel="${entry%% *}"; want="${entry##* }"; f="$DET_DIR/$rel"
  if [[ ! -f "$f" && "$MODE" == "install" ]]; then
    doing "fetching $rel from the Zenodo zip (range requests)"
    python3 "$HERE/fetch_zip_members.py" "$DET_URL" "$DET_DIR" "$rel" >/dev/null
  fi
  if [[ ! -f "$f" ]]; then fail "missing $f"
  elif [[ "$(sha256 "$f")" == "$want" ]]; then ok "$rel"
  else fail "checksum differs: $f"; fi
done

# ---------------------------------------------------------------------------------------
echo "[4/6] sfizz_render (BSD-2-Clause), pinned commit + 32-bit float output patch"
float_test() {  # 0 if the binary renders and writes IEEE float WAV
  local d; d="$(mktemp -d)"
  printf '<region> sample=*sine\n' > "$d/t.sfz"
  python3 - "$d/t.mid" <<'PY'
import sys, mido
mf = mido.MidiFile(type=0, ticks_per_beat=480); tr = mido.MidiTrack(); mf.tracks.append(tr)
tr += [mido.Message("note_on", note=69, velocity=100, time=0), mido.Message("note_off", note=69, velocity=0, time=240)]
mf.save(sys.argv[1])
PY
  "$1" --sfz "$d/t.sfz" --midi "$d/t.mid" --wav "$d/t.wav" -s 48000 >/dev/null 2>&1 || { rm -rf "$d"; return 1; }
  python3 -c "import soundfile as sf, sys; i = sf.info(sys.argv[1]); sys.exit(0 if (i.subtype == 'FLOAT' and i.samplerate == 48000 and sf.read(sys.argv[1])[0].any()) else 1)" "$d/t.wav"
  local r=$?; rm -rf "$d"; return $r
}
if [[ -x "$SFIZZ_BIN" ]] && float_test "$SFIZZ_BIN"; then
  ok "$SFIZZ_BIN renders 32-bit float"
elif [[ "$MODE" == "check" ]]; then
  fail "sfizz_render missing or not float-patched: $SFIZZ_BIN"
elif [[ -n "${SFIZZ_RENDER:-}" ]]; then
  fail "\$SFIZZ_RENDER=$SFIZZ_RENDER is not a working float-patched sfizz_render"
else
  for t in cmake c++; do command -v "$t" >/dev/null || { fail "$t is needed to build sfizz"; exit 1; }; done
  if [[ ! -d "$SFIZZ_SRC/.git" ]]; then
    doing "cloning $SFIZZ_GIT"
    mkdir -p "$(dirname "$SFIZZ_SRC")"
    git clone --quiet "$SFIZZ_GIT" "$SFIZZ_SRC"
  fi
  if [[ "$(git -C "$SFIZZ_SRC" rev-parse HEAD)" != "$SFIZZ_COMMIT" ]]; then
    git -C "$SFIZZ_SRC" fetch --quiet origin
    git -C "$SFIZZ_SRC" checkout --quiet "$SFIZZ_COMMIT"
  fi
  git -C "$SFIZZ_SRC" submodule update --init --recursive --quiet
  if git -C "$SFIZZ_SRC" apply --reverse --check "$PATCH" 2>/dev/null; then
    ok "float32 patch already applied"
  else
    git -C "$SFIZZ_SRC" apply "$PATCH" && ok "applied $(basename "$PATCH")"
  fi
  doing "building sfizz_render (a few minutes; log in $SFIZZ_SRC/build/setup_build.log)"
  # Recent Apple clang (Xcode 16+) turns the bundled atomic_queue's "template keyword
  # without argument list" into a hard error; the code is fine, so demote it.
  mkdir -p "$SFIZZ_SRC/build"
  BLOG="$SFIZZ_SRC/build/setup_build.log"
  if ! { cmake -S "$SFIZZ_SRC" -B "$SFIZZ_SRC/build" -DCMAKE_BUILD_TYPE=Release \
           -DCMAKE_CXX_FLAGS="-Wno-error=missing-template-arg-list-after-template-kw -Wno-missing-template-arg-list-after-template-kw" \
           -DSFIZZ_RENDER=ON -DSFIZZ_JACK=OFF -DSFIZZ_LV2=OFF -DSFIZZ_LV2_UI=OFF -DSFIZZ_VST=OFF \
           -DSFIZZ_AU=OFF -DSFIZZ_SHARED=OFF -DSFIZZ_TESTS=OFF -DSFIZZ_DEMOS=OFF \
           -DSFIZZ_BENCHMARKS=OFF -DSFIZZ_DEVTOOLS=OFF &&
         cmake --build "$SFIZZ_SRC/build" --target sfizz_render -j "$(ncpu)"; } >"$BLOG" 2>&1; then
    grep -m 5 -E "error:" "$BLOG" >&2 || tail -20 "$BLOG" >&2
    fail "sfizz build failed, see $BLOG"; exit 1
  fi
  float_test "$SFIZZ_BIN" && ok "$SFIZZ_BIN renders 32-bit float" || fail "freshly built sfizz_render fails the float test"
fi

# ---------------------------------------------------------------------------------------
echo "[5/6] derived instrument (make_sfz.py) and hall IR (make_ir.py)"
# The derived SFZ records the SHA-256 of the make_sfz.py that wrote it; a different
# make_sfz.py (a newer checkout) means the instrument on disk is stale.
GEN_SHA="$(sha256 "$HERE/make_sfz.py")"
current() { [[ -f "$1" ]] && head -20 "$1" | grep -q "make_sfz.py sha256=$GEN_SHA"; }
n_aligned() { find "$ALIGNED" -maxdepth 1 -name '*.flac' 2>/dev/null | wc -l | tr -d ' '; }
# The hall IR's JSON records the SHA-256 of the make_ir.py that wrote it, in the same way.
IR_SHA="$(sha256 "$HERE/make_ir.py")"
ir_current() { [[ -f "$HALL_IR" && -f "$HALL_IR_JSON" ]] && grep -q "\"make_ir.py sha256\": \"$IR_SHA\"" "$HALL_IR_JSON"; }
if [[ "$MODE" == "install" && -f "$SAL_SFZ" ]]; then
  if [[ "$FORCE" == 1 || ! -f "$CALIB" || "$(n_aligned)" != 480 ]] || ! current "$DERIVED_SFZ" || ! current "$DERIVED_SFZ_NP"; then
    doing "make_sfz.py (aligns and analyses the 480 note samples; about 1 min when it writes the aligned copies, 30 s otherwise)"
    (cd "$HERE" && python3 make_sfz.py >/dev/null)
  fi
  if [[ "$FORCE" == 1 ]] || ! ir_current; then
    doing "make_ir.py (hall IR, about 5 s)"
    (cd "$HERE" && python3 make_ir.py >/dev/null)
  fi
fi
for f in "$DERIVED_SFZ" "$DERIVED_SFZ_NP"; do
  if current "$f"; then ok "$(basename "$f") (current make_sfz.py)"
  elif [[ -f "$f" ]]; then fail "$(basename "$f") was written by another make_sfz.py (run ./setup_piano.sh)"
  else fail "missing $f (run ./setup_piano.sh)"; fi
done
for f in "$CALIB" "$ALIGNED/alignment.json"; do
  [[ -f "$f" ]] && ok "$(basename "$f")" || fail "missing $f (run ./setup_piano.sh)"
done
if ir_current; then ok "$(basename "$HALL_IR") (current make_ir.py)"
elif [[ -f "$HALL_IR" ]]; then fail "$(basename "$HALL_IR") was written by another make_ir.py (run ./setup_piano.sh)"
else fail "missing $HALL_IR (run ./setup_piano.sh)"; fi
[[ "$(n_aligned)" == 480 ]] && ok "480 L/R-aligned note samples" || fail "$(n_aligned) aligned samples in $ALIGNED, expected 480 (run ./setup_piano.sh)"

# ---------------------------------------------------------------------------------------
echo "[6/6] end-to-end smoke test"
if [[ "$FAILED" == 0 ]]; then
  d="$(mktemp -d)"
  python3 - "$d/smoke.mid" <<'PY'
import sys, mido
mf = mido.MidiFile(type=1, ticks_per_beat=480)
for name, notes in (("soprano", [70, 72, 74]), ("bass", [46, 41, 46])):
    tr = mido.MidiTrack(); mf.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name=name, time=0))
    for i, k in enumerate(notes):
        tr.append(mido.Message("note_on", note=k, velocity=40 + 30 * i, time=0))
        tr.append(mido.Message("note_off", note=k, velocity=0, time=440))
mf.save(sys.argv[1])
PY
  if (cd "$HERE" && python3 render_piano.py "$d/smoke.mid" -o "$d/smoke" --no-m4a --json "$d/r.json" >/dev/null) &&
     python3 -c "import json,sys; r=json.load(open(sys.argv[1])); sys.exit(0 if r['duration_s'] > 1 and set(r['voices']) == {'soprano','bass'} else 1)" "$d/r.json"; then
    ok "render_piano.py rendered a two-voice test ($(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['duration_s'])" "$d/r.json") s)"
  else
    fail "render_piano.py smoke test"
  fi
  rm -rf "$d"
else
  echo "  skip  (fix the failures above first)"
fi

if [[ "$MODE" == "check" ]]; then
  echo "[--check] download sources"
  n="$(remote_len "$SAL_URL")"; [[ "$n" == "$SAL_BYTES" ]] && ok "Salamander tarball reachable, $n bytes" || fail "Salamander URL: length '$n', expected $SAL_BYTES"
  n="$(remote_len "$DET_URL")"; [[ "$n" == "$DET_BYTES" ]] && ok "Detmold zip reachable, $n bytes" || fail "Detmold URL: length '$n', expected $DET_BYTES"
  git ls-remote --exit-code "$SFIZZ_GIT" HEAD >/dev/null 2>&1 && ok "sfizz git reachable" || fail "sfizz git not reachable"
fi

if [[ "$FAILED" == 0 ]]; then echo "piano setup: all good"; else echo "piano setup: FAILED (see above)" >&2; exit 1; fi
