#!/usr/bin/env bash
# Install, build and verify everything render_quartet.py needs.  Idempotent: whatever
# is already present and verified is left alone.  A second run re-checks files and
# hashes and renders a smoke test (under 30 s); the tuning verification (every key x
# layer, steady and attack, about 1 min) only reruns when the instruments changed.
#
#   ./setup_strings.sh              install what is missing, build, verify
#   ./setup_strings.sh --check      verify only (no downloads, no builds)
#   ./setup_strings.sh --force      additionally re-analyse and rebuild the Iowa instruments
#   ./setup_strings.sh --with-vpo3  also install Virtual Playing Orchestra 3 (only needed for
#                                   the library comparison, render_quartet.py --lib vpo3)
#
# Large assets live in $SAMPLE_LIBRARIES (default ~/Music/SampleLibraries), never in git:
#
#   IowaMIS/raw/{violin,viola,cello,bass}/*.aif   131 arco stereo recordings (2.2 GB)
#   IowaMIS/quartet/analysis.json                 note segmentation + pitch (iowa_analyze.py)
#   IowaMIS/quartet/samples/, {violin,violin2,viola,cello,bass}.sfz   built instruments (iowa_build.py;
#                                                 violin2 = Violin II, next lower string where recorded;
#                                                 attack pitch drift flattened by attack_tune.py)
#   IowaMIS/quartet/tuning_corrections.json       closed-loop tuning (verify_tuning.py + retune)
#   IowaMIS/quartet/tuning_verify.json, shape_verify.json, verified.sha256
#                                                 last verification and what it covered
#   tools/sfizz/build/library/bin/sfizz_render    pinned sfizz + float patch, shared with the piano
#   IR/Detmold-Konzerthaus-S1R163-MS-48k.wav      hall IR, shared with the piano (make_ir.py)
#   VPO3/                                         optional, --with-vpo3
#
# Sources and licences
#   University of Iowa Electronic Music Studios, Musical Instrument Samples (2012 strings):
#     https://theremin.music.uiowa.edu/MIS.html -- "freely available ... may be downloaded
#     and used for any projects, without restrictions".  Pages scraped for the arco stereo
#     files: MISviolin2012.html, MISviola2012.html, MIScello2012.html, MISdoublebass2012.html
#   Detmold SRIR database (Amengual Gari, Sahin, Eddy, Kob, AES 149, 2020), CC BY 4.0:
#     https://zenodo.org/records/4116247 (3 WAVs fetched by HTTP range requests)
#   sfizz, BSD-2-Clause: https://github.com/sfztools/sfizz (pinned commit, see below)
#   Virtual Playing Orchestra 3 (Paul Battersby), free for any music incl. commercial,
#     redistribution only with credit: https://virtualplaying.com/virtual-playing-orchestra/
#     wave files 3.2 (the site links a Google Drive copy), performance scripts 3.3.
#
# Iowa publishes no checksums; the file counts and per-instrument manifest hashes below
# were recorded from the installation the demo renders were made with.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIANO="$(cd "$HERE/../piano" && pwd)"
LIB="${SAMPLE_LIBRARIES:-$HOME/Music/SampleLibraries}"
export SAMPLE_LIBRARIES="$LIB" PIANO_LIB="$LIB"
MODE="install"; FORCE=0; VPO=0
for a in "$@"; do
  case "$a" in
    --check) MODE="check" ;;
    --force) FORCE=1 ;;
    --with-vpo3) VPO=1 ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

IOWA_BASE="https://theremin.music.uiowa.edu"
IOWA_PAGES=("violin MISviolin2012" "viola MISviola2012" "cello MIScello2012" "bass MISdoublebass2012")
IOWA_EXPECT=(
  "violin 36 6c8d45c99a24f18ca127803f6d9df3ea2d4fb2aca0087428d163c2d6ea9ff082"
  "viola 32 d349416fc04837e731e6ffe9984ff68b7701bcbe8571a475649ce001244a4960"
  "cello 24 3336ac1070007d24488059443cb342fed31e348106e23996df09393184e83a7b"
  "bass 39 cc911b97aab37c34783ba8f78d383dab2877fa3c47f290ee63d41d3514de84fc"
)
IOWA="$LIB/IowaMIS"
Q="$IOWA/quartet"

DET_URL="https://zenodo.org/api/records/4116247/files/DetmoldSRIR_v01.zip/content"
DET_DIR="$LIB/IR/DetmoldSRIR"
DET_FILES=(
  "SetC_DenseKH_LSOrchestra/Data/Omni/S1R163.wav 3db37707d7f7720e0c886ebbc3f8bcc64e617f35cd08362c4cc366fde6786a6c"
  "SetC_DenseKH_LSOrchestra/Data/Fig8/S1R163.wav 342ab50b632f4f52a2c34ef6639fd3c4eb01dc0af8ca36fc59c980bd65d3a560"
  "SetC_DenseKH_LSOrchestra/Data/DummyHead/S1R163.wav b7000263aeb5edc44b307cc72a3c8725bdee4abbf42595c60105cc60129a1010"
)
HALL_IR="$LIB/IR/Detmold-Konzerthaus-S1R163-MS-48k.wav"

SFIZZ_GIT="https://github.com/sfztools/sfizz.git"
SFIZZ_COMMIT="f5c6e29f23b8057867c08e88f5f6ac6738baa30b"
SFIZZ_SRC="$LIB/tools/sfizz"
SFIZZ_BIN="${SFIZZ_RENDER:-$SFIZZ_SRC/build/library/bin/sfizz_render}"
PATCH="$PIANO/sfizz_render_float32.patch"

VPO_DIR="$LIB/VPO3"
VPO_WAVE_URL="https://drive.usercontent.google.com/download?id=17bY90ybtA5CyNJMnQ4KK9i5YO3tCN7HR&export=download&confirm=t"
VPO_WAVE_PAGE="https://virtualplaying.com/go/virtual-playing-orchestra-v3-2-wave-files-gdrive/"
VPO_WAVE_ZIP="Virtual-Playing-Orchestra3-2-wave-files.zip"
VPO_WAVE_BYTES=616114842
VPO_WAVE_SHA256="ca8f1e0b56eede35314994646e5f1f307ec349616c967fbecf627c43aa646e90"
VPO_PERF_URL="https://virtualplaying.com/vp-downloads/Virtual-Playing-Orchestra3-3-performance-scripts.zip"
VPO_PERF_ZIP="Virtual-Playing-Orchestra3-3-performance-scripts.zip"
VPO_PERF_SHA256="7543e64585ef28022bcf9759f127d12ee2d51a831f3bfba9fbb584a8bb993bfd"

ok()   { printf '  ok    %s\n' "$*"; }
doing(){ printf '  ....  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*" >&2; FAILED=1; }
FAILED=0
sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
fsize() { stat -f %z "$1" 2>/dev/null || stat -c %s "$1"; }
ncpu() { sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4; }

echo "strings setup ($MODE) in $LIB"
mkdir -p "$LIB"

# ---------------------------------------------------------------------------------------
echo "[1/7] tools"
for t in python3 curl git unzip; do command -v "$t" >/dev/null && ok "$t" || fail "$t not found"; done
if python3 -c "import numpy, scipy, soundfile, mido" 2>/dev/null; then ok "python: numpy scipy soundfile mido"
else fail "python modules missing: pip3 install numpy scipy soundfile mido"; fi
command -v afconvert >/dev/null && ok "afconvert (AAC .m4a)" || \
  { command -v ffmpeg >/dev/null && ok "ffmpeg (AAC .m4a fallback)" || fail "neither afconvert nor ffmpeg found"; }

# ---------------------------------------------------------------------------------------
echo "[2/7] University of Iowa MIS 2012 solo strings, arco, stereo (free for any use)"
mkdir -p "$IOWA/raw"
URLS="$IOWA/arco_urls.txt"
if [[ "$MODE" == "install" ]]; then
  tmpu="$(mktemp)"
  for pg in "${IOWA_PAGES[@]}"; do
    inst="${pg%% *}"; page="${pg##* }"
    curl -s --fail --retry 3 --max-time 120 "$IOWA_BASE/$page.html" |
      grep -o 'href="[^"]*arco[^"]*stereo[^"]*\.aif"' | sed 's/^href="//; s/"$//' | sort -u |
      while read -r rel; do printf '%s\t%s/%s\n' "$inst" "$IOWA_BASE" "${rel// /%20}"; done >> "$tmpu" || true
  done
  if [[ -s "$tmpu" ]]; then mv "$tmpu" "$URLS"; else rm -f "$tmpu"; echo "  warn  could not read the Iowa pages; using $URLS"; fi
  if [[ -f "$URLS" ]]; then
    while IFS=$'\t' read -r inst url; do
      [[ "$url" == *.stereo.aif ]] || continue
      f="$IOWA/raw/$inst/$(basename "${url//%20/ }")"
      if [[ ! -s "$f" ]]; then
        mkdir -p "$IOWA/raw/$inst"
        doing "downloading $(basename "$f")"
        curl -s -L --fail --retry 3 -C - -o "$f.part" "$url" && mv "$f.part" "$f"
      fi
    done < "$URLS"
  fi
fi
for e in "${IOWA_EXPECT[@]}"; do
  read -r inst n want <<<"$e"
  d="$IOWA/raw/$inst"
  have="$(ls "$d"/*.aif 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$have" != "$n" ]]; then fail "$inst: $have of $n files in $d"; continue; fi
  m="$(cd "$d" && LC_ALL=C ls *.aif | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256 | cut -d' ' -f1)"
  [[ "$m" == "$want" ]] && ok "$inst: $n files, manifest sha256 matches" || \
    echo "  warn  $inst: $n files, manifest differs from the recorded one (Iowa may have re-uploaded; the build re-verifies pitch)"
done

# ---------------------------------------------------------------------------------------
echo "[3/7] sfizz_render (BSD-2-Clause), pinned commit + float output patch (shared with the piano)"
float_test() {
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
else
  for t in cmake c++; do command -v "$t" >/dev/null || { fail "$t is needed to build sfizz"; exit 1; }; done
  if [[ ! -d "$SFIZZ_SRC/.git" ]]; then
    doing "cloning $SFIZZ_GIT"; mkdir -p "$(dirname "$SFIZZ_SRC")"; git clone --quiet "$SFIZZ_GIT" "$SFIZZ_SRC"
  fi
  if [[ "$(git -C "$SFIZZ_SRC" rev-parse HEAD)" != "$SFIZZ_COMMIT" ]]; then
    git -C "$SFIZZ_SRC" fetch --quiet origin; git -C "$SFIZZ_SRC" checkout --quiet "$SFIZZ_COMMIT"
  fi
  git -C "$SFIZZ_SRC" submodule update --init --recursive --quiet
  git -C "$SFIZZ_SRC" apply --reverse --check "$PATCH" 2>/dev/null || git -C "$SFIZZ_SRC" apply "$PATCH"
  doing "building sfizz_render (a few minutes)"
  mkdir -p "$SFIZZ_SRC/build"; BLOG="$SFIZZ_SRC/build/setup_build.log"
  if ! { cmake -S "$SFIZZ_SRC" -B "$SFIZZ_SRC/build" -DCMAKE_BUILD_TYPE=Release \
           -DCMAKE_CXX_FLAGS="-Wno-error=missing-template-arg-list-after-template-kw -Wno-missing-template-arg-list-after-template-kw" \
           -DSFIZZ_RENDER=ON -DSFIZZ_JACK=OFF -DSFIZZ_LV2=OFF -DSFIZZ_LV2_UI=OFF -DSFIZZ_VST=OFF \
           -DSFIZZ_AU=OFF -DSFIZZ_SHARED=OFF -DSFIZZ_TESTS=OFF -DSFIZZ_DEMOS=OFF \
           -DSFIZZ_BENCHMARKS=OFF -DSFIZZ_DEVTOOLS=OFF &&
         cmake --build "$SFIZZ_SRC/build" --target sfizz_render -j "$(ncpu)"; } >"$BLOG" 2>&1; then
    fail "sfizz build failed, see $BLOG"; exit 1
  fi
  float_test "$SFIZZ_BIN" && ok "$SFIZZ_BIN renders 32-bit float" || fail "freshly built sfizz_render fails the float test"
fi

# ---------------------------------------------------------------------------------------
echo "[4/7] hall impulse response: Detmold Konzerthaus (CC BY 4.0), shared with the piano"
if [[ ! -f "$HALL_IR" && "$MODE" == "install" ]]; then
  for entry in "${DET_FILES[@]}"; do
    rel="${entry%% *}"; want="${entry##* }"; f="$DET_DIR/$rel"
    if [[ ! -f "$f" ]]; then
      doing "fetching $rel from the Zenodo zip (range requests)"
      python3 "$PIANO/fetch_zip_members.py" "$DET_URL" "$DET_DIR" "$rel" >/dev/null
    fi
    [[ "$(sha256 "$f")" == "$want" ]] || { fail "checksum differs: $f"; exit 1; }
  done
  doing "make_ir.py"
  (cd "$PIANO" && python3 make_ir.py >/dev/null)
fi
[[ -f "$HALL_IR" ]] && ok "$(basename "$HALL_IR")" || fail "missing $HALL_IR"

# ---------------------------------------------------------------------------------------
echo "[5/7] Iowa quartet instruments (analyse, build, tune, verify)"
if [[ "$MODE" == "install" && "$FAILED" == 0 ]]; then
  if [[ "$FORCE" == 1 || ! -f "$Q/analysis.json" ]]; then
    doing "iowa_analyze.py (segments 131 recordings into notes, about 1 min)"
    (cd "$HERE" && python3 iowa_analyze.py --jobs "$(ncpu)" >/dev/null)
  fi
  need_build=0
  # every instrument built, with the attack-pitch correction (meta 'attack') and the current
  # sustain pitch / level flattening (meta 'flat_v' == iowa_build.FLATTEN_VERSION)
  (cd "$HERE" && python3 -c "import json,sys; from iowa_build import FLATTEN_VERSION as V; m=json.load(open(sys.argv[1])); sys.exit(0 if all(i in m and all('attack' in s and s.get('flat_v') == V for s in m[i]) for i in ('violin','violin2','viola','cello','bass')) else 1)" \
    "$Q/samples/meta.json") 2>/dev/null || need_build=1
  if [[ "$FORCE" == 1 || "$need_build" == 1 ]]; then
    doing "iowa_build.py (trims, flattens, extends and calibrates about 680 samples, about 5 min)"
    rm -f "$Q/tuning_corrections.json"
    (cd "$HERE" && python3 iowa_build.py --jobs "$(ncpu)" >/dev/null)
  fi
  if [[ ! -f "$Q/tuning_corrections.json" ]]; then
    doing "closed-loop tuning: measure every key and layer through sfizz, fold the errors into the SFZ"
    (cd "$HERE" && python3 verify_tuning.py violin violin2 viola cello bass --json "$Q/tuning_pass1.json" >/dev/null || true)
    (cd "$HERE" && python3 iowa_build.py --retune "$Q/tuning_pass1.json" >/dev/null)
  fi
  # SFZ files are cheap to regenerate from samples/meta.json: do it whenever the
  # builder or the tuning corrections are newer than any of them
  stale=0
  for i in violin violin2 viola cello bass; do
    if [[ ! -f "$Q/$i.sfz" || "$HERE/iowa_build.py" -nt "$Q/$i.sfz" || "$Q/tuning_corrections.json" -nt "$Q/$i.sfz" ]]; then
      stale=1
    fi
  done
  if [[ "$stale" == 1 ]]; then
    doing "iowa_build.py --sfz-only (SFZ older than the builder or the tuning corrections)"
    (cd "$HERE" && python3 iowa_build.py --sfz-only >/dev/null)
  fi
fi
for i in violin violin2 viola cello bass; do
  [[ -f "$Q/$i.sfz" ]] && ok "$i.sfz ($(grep -c '<region>' "$Q/$i.sfz") regions)" || fail "missing $Q/$i.sfz"
done
# the verification covers these files; its stamp lets a second run skip it
stamp() { (cd "$Q" && cat violin.sfz violin2.sfz viola.sfz cello.sfz bass.sfz tuning_corrections.json samples/meta.json
           cat "$HERE/verify_tuning.py" "$HERE/verify_shape.py") 2>/dev/null | shasum -a 256 | cut -d' ' -f1; }
TUNE_TOL=5
if [[ "$FAILED" == 0 ]]; then
  if [[ -f "$Q/verified.sha256" && "$(cat "$Q/verified.sha256")" == "$(stamp)" && -f "$Q/tuning_verify.json" ]]; then
    ok "tuning and sample shape: verified earlier for exactly these instruments (steady and attack pitch, every key x layer)"
  else
    if [[ "$MODE" == "install" ]]; then
      # closed loop: measure every key x layer (0.45-1.05 s and 1.05-1.9 s, YIN and harmonic peaks), fold
      # the errors into the tuning corrections, repeat until every figure is within TUNE_TOL cents
      for pass in 2 3 4; do
        if (cd "$HERE" && python3 verify_tuning.py violin violin2 viola cello bass --tol "$TUNE_TOL" \
              --json "$Q/tuning_pass$pass.json" >/dev/null); then break; fi
        doing "closed-loop tuning, pass $pass: folding the measured errors into the SFZ"
        (cd "$HERE" && python3 iowa_build.py --retune "$Q/tuning_pass$pass.json" >/dev/null)
      done
    fi
    if (cd "$HERE" && python3 verify_tuning.py violin violin2 viola cello bass --tol "$TUNE_TOL" --attack --attack-tol 30 \
          --json "$Q/tuning_verify.json" >/dev/null); then
      tune_ok=1
      ok "tuning: every key x layer within $TUNE_TOL cents through sfizz in both windows by both estimators, attacks (40-200 ms) within 30 ($(python3 -c "
import json,sys; r=json.load(open(sys.argv[1])); c=[abs(x['worst']) for i in r['steady'].values() for l in i.values() for x in l]
a=[abs(x['cents']) for i in r['attack'].values() for l in i.values() for s in l.values() for x in s if x['cents'] is not None]
print(f'steady worst {max(c):.1f} c, median {sorted(c)[len(c)//2]:.1f} c; attack median {sorted(a)[len(a)//2]:.1f} c, {sum(v > 15 for v in a)} of {len(a)} over 15 c')" "$Q/tuning_verify.json"))"
    else
      tune_ok=0
      fail "tuning check failed, see $Q/tuning_verify.json (silent notes show as cents=null)"
    fi
    if (cd "$HERE" && python3 verify_shape.py --json "$Q/shape_verify.json" >/dev/null); then
      shape_ok=1
      ok "sample shape: no normal or slurred region sits low, dips and jumps back in its first second (verify_shape.py)"
    else
      shape_ok=0
      fail "sample shape check failed, see $Q/shape_verify.json"
    fi
    if [[ "$tune_ok" == 1 && "$shape_ok" == 1 ]]; then stamp > "$Q/verified.sha256"; else rm -f "$Q/verified.sha256"; fi
  fi
fi

# ---------------------------------------------------------------------------------------
echo "[6/7] Virtual Playing Orchestra 3 (optional, comparison only)"
if [[ "$VPO" == 1 ]]; then
  mkdir -p "$VPO_DIR/_zips"
  if [[ "$MODE" == "install" ]]; then
    zw="$VPO_DIR/_zips/$VPO_WAVE_ZIP"
    if [[ ! -f "$zw" || "$(fsize "$zw")" != "$VPO_WAVE_BYTES" ]]; then
      doing "downloading $VPO_WAVE_ZIP (616 MB; link from $VPO_WAVE_PAGE)"
      curl -L --fail --retry 5 -C - -o "$zw" "$VPO_WAVE_URL"
    fi
    zp="$VPO_DIR/_zips/$VPO_PERF_ZIP"
    [[ -f "$zp" ]] || curl -s -L --fail --retry 3 -o "$zp" "$VPO_PERF_URL"
    [[ "$(sha256 "$zw")" == "$VPO_WAVE_SHA256" ]] || { fail "checksum differs: $zw"; exit 1; }
    [[ "$(sha256 "$zp")" == "$VPO_PERF_SHA256" ]] || echo "  warn  performance scripts zip differs from the recorded version"
    if [[ ! -d "$VPO_DIR/Virtual-Playing-Orchestra3/libs/NoBudgetOrch" ]]; then
      doing "unzipping wave files"; (cd "$VPO_DIR" && unzip -q -n "_zips/$VPO_WAVE_ZIP")
    fi
    if [[ ! -f "$VPO_DIR/Virtual-Playing-Orchestra3/Strings/1st-violin-SOLO-PERF.sfz" ]]; then
      doing "unzipping performance scripts"; (cd "$VPO_DIR" && unzip -q -n "_zips/$VPO_PERF_ZIP")
    fi
    (cd "$HERE" && python3 vpo3.py >/dev/null)
  fi
  (cd "$HERE" && python3 -c "import vpo3, sys; sys.exit(0 if vpo3.available() and all(p.exists() for p in vpo3.VPO3_SFZ.values()) else 1)") \
    && ok "VPO3 solo strings ready (render_quartet.py --lib vpo3)" || fail "VPO3 incomplete in $VPO_DIR"
else
  echo "  skip  (pass --with-vpo3)"
fi

# ---------------------------------------------------------------------------------------
echo "[7/7] end-to-end smoke test"
if [[ "$FAILED" == 0 ]]; then
  d="$(mktemp -d)"
  python3 - "$d/smoke.mid" <<'PY'
import sys, mido
mf = mido.MidiFile(type=1, ticks_per_beat=480)
for ch, (name, notes) in enumerate((("soprano", [72, 74, 76, 77]), ("tenor", [55, 53, 52, 48]), ("bass", [48, 43, 45, 41]))):
    tr = mido.MidiTrack(); mf.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name=name, time=0))
    tr.append(mido.Message("control_change", channel=ch, control=1, value=75, time=0))
    for i, k in enumerate(notes):
        tr.append(mido.Message("note_on", channel=ch, note=k, velocity=70, time=0))
        tr.append(mido.Message("note_off", channel=ch, note=k, velocity=0, time=480))
mf.save(sys.argv[1])
PY
  if (cd "$HERE" && python3 render_quartet.py "$d/smoke.mid" -o "$d/smoke" --report "$d/r.json" >/dev/null) &&
     python3 -c "
import json, sys, soundfile as sf
r = json.load(open(sys.argv[1])); x, sr = sf.read(sys.argv[2])
ok = sr == 48000 and x.shape[1] == 2 and r['duration_s'] > 3 and -1.2 < r['true_peak_dbtp'] < -0.8 \
     and {j['inst'] for j in r['jobs']} == {'vn1', 'va', 'vc'}
sys.exit(0 if ok else 1)" "$d/r.json" "$d/smoke.wav" && [[ -s "$d/smoke.m4a" ]]; then
    ok "render_quartet.py rendered a three-voice test (48 kHz stereo WAV + m4a, true peak -1 dBTP)"
  else
    fail "render_quartet.py smoke test"
  fi
  rm -rf "$d"
else
  echo "  skip  (fix the failures above first)"
fi

[[ "$FAILED" == 0 ]] && echo "strings setup: all checks passed" || { echo "strings setup: FAILED" >&2; exit 1; }
