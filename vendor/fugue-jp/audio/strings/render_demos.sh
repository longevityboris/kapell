#!/usr/bin/env bash
# Re-render the string-quartet demos and the dynamics proof into out/ (gitignored).
#
#   ./render_demos.sh            fugue (perform.py -> render_quartet), bass-doubling variant,
#                                VPO3 comparison (if installed), dynamics test + measurements
#
# Outputs
#   out/demo/fugue_strings.mid                 perform.py --target strings, demo/fugue_plan.json
#   out/demo/fugue_quartet_iowa.{wav,m4a,json} the demo (report: --report), stems *_stem_*.wav
#   out/demo/fugue_quartet_iowa_bassdouble.*   --bass-double auto (contrabass 8vb in the ff climax)
#   out/demo/fugue_quartet_vpo3.*              the same MIDI on VPO3 solo strings (comparison)
#   out/demo/sk_final_quartet.{wav,m4a,json}   the final renders' test music (design/final-lab SK_final + plan)
#   out/demo/qa_*.json                         qa_render.py: balance, clicks, onsets, legato dips
#   out/verify/dynamics_{iowa,vpo3}.json       verify_dynamics.py: CC1 ladder, timbre ratio (library choice)
#   out/test/dyn_quartet.*                     pp / mf / ff phrase + held-note swell per instrument
#   out/test/dynamics_report.json              measure_dynamics.py per instrument (dry stems)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$HERE"
mkdir -p out/demo out/test

python3 ../../tools/perform.py "$ROOT/fugue.ly" demo/fugue_plan.json out/demo/fugue_strings.mid --target strings
python3 render_quartet.py out/demo/fugue_strings.mid -o out/demo/fugue_quartet_iowa --stems \
  --report out/demo/fugue_quartet_iowa.json
python3 qa_render.py out/demo/fugue_quartet_iowa --json out/demo/qa_iowa.json
mkdir -p out/verify
python3 verify_dynamics.py violin violin2 viola cello --json out/verify/dynamics_iowa.json
python3 render_quartet.py out/demo/fugue_strings.mid -o out/demo/fugue_quartet_iowa_bassdouble --bass-double auto \
  --stems --report out/demo/fugue_quartet_iowa_bassdouble.json
if python3 -c "import vpo3, sys; sys.exit(0 if vpo3.available() else 1)" 2>/dev/null; then
  python3 render_quartet.py out/demo/fugue_strings.mid -o out/demo/fugue_quartet_vpo3 --lib vpo3 --stems \
    --report out/demo/fugue_quartet_vpo3.json
  python3 qa_render.py out/demo/fugue_quartet_vpo3 --json out/demo/qa_vpo3.json
  python3 verify_dynamics.py violin viola cello --lib vpo3 --json out/verify/dynamics_vpo3.json
fi

python3 make_test_midi.py out/test >/dev/null
python3 render_quartet.py out/test/dyn_quartet.mid -o out/test/iowa_dyn_quartet --stems --keep-start \
  --report out/test/iowa_dyn_quartet.json
python3 - <<'PY'
import json, subprocess, sys
seg = "out/test/dyn_quartet.json"
out = {}
for name, tag in (("Violin I", "vn1"), ("Violin II", "vn2"), ("Viola", "va"), ("Cello", "vc")):
    r = subprocess.run([sys.executable, "measure_dynamics.py", f"out/test/iowa_dyn_quartet_stem_{tag}.wav", seg,
                        "--voice", name, "--json"], capture_output=True, text=True, check=True)
    out[name] = json.loads(r.stdout)
json.dump(out, open("out/test/dynamics_report.json", "w"), indent=1)
for name, r in out.items():
    s = {x["segment"]: x for x in r["segments"]}
    print(f"{name:10s} " + "  ".join(f"{k}: {s[k]['rms_db']:+.1f} dB {s[k]['centroid_hz']:.0f} Hz" for k in ("pp", "mf", "ff")))
PY
# the final renders' test music (66 bars), when the design lab is checked out
FL="$ROOT/ricercar/design/final-lab"
if [[ -f "$FL/SK_final.ly" && -f "$FL/plan.json" ]]; then
  python3 ../../tools/perform.py "$FL/SK_final.ly" "$FL/plan.json" out/demo/sk_final_strings.mid --target strings
  python3 render_quartet.py out/demo/sk_final_strings.mid -o out/demo/sk_final_quartet --stems \
    --report out/demo/sk_final_quartet.json
  python3 qa_render.py out/demo/sk_final_quartet --json out/demo/qa_sk_final.json
fi
echo "demos rendered into $HERE/out"
