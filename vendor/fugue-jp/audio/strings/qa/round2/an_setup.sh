#!/usr/bin/env bash
# Round-2 idempotency check of setup_strings.sh -> qa/round2/results/setup.json
#   1. hash + mtime of every built file (SFZ, tuning, meta, analysis, stamp, every sample WAV)
#   2. --check, install, install (timed; "...." lines = work done)
#   3. adversarial: touch iowa_build.py (what a fresh git checkout does to mtimes), install again:
#      the SFZ are regenerated -- are they byte-identical, and is the tuning stamp still valid?
#   4. hash + mtime again
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$(cd "$HERE/../.." && pwd)"
Q="${SAMPLE_LIBRARIES:-$HOME/Music/SampleLibraries}/IowaMIS/quartet"
T=/tmp/sqa2/setup; mkdir -p "$T"
snap() {  # label
  (cd "$Q" && shasum -a 256 ./*.sfz tuning_corrections.json samples/meta.json analysis.json verified.sha256) > "$T/$1.sha"
  (cd "$Q" && stat -f '%m %N' ./*.sfz tuning_corrections.json samples/meta.json analysis.json verified.sha256) > "$T/$1.mtime"
  (cd "$Q/samples" && find . -name '*.wav' -type f -exec stat -f '%m %z %N' {} + | sort -k3) > "$T/$1.wavs"
}
run() {  # label, args...
  local l="$1"; shift
  local t0 t1; t0=$(python3 -c 'import time; print(time.time())')
  (cd "$S" && ./setup_strings.sh "$@") > "$T/$l.log" 2>&1; local rc=$?
  t1=$(python3 -c 'import time; print(time.time())')
  printf '%s %s %s\n' "$l" "$rc" "$(python3 -c "print(round($t1-$t0,1))")" >> "$T/runs.txt"
}
: > "$T/runs.txt"
snap before
run check --check
run install1
run install2
snap mid
touch "$S/iowa_build.py"
run install_after_touch
snap after
python3 - "$T" "$HERE/results/setup.json" <<'PY'
import json, sys, pathlib
T, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
runs = []
for line in (T / "runs.txt").read_text().splitlines():
    if line.strip():
        l, rc, s = line.split()
        log = (T / f"{l}.log").read_text()
        runs.append(dict(run=l, returncode=int(rc), seconds=float(s),
                         work_lines=[x.strip() for x in log.splitlines() if x.startswith("  ....")],
                         warn_fail=[x.strip() for x in log.splitlines() if "FAIL" in x or "warn" in x],
                         last_line=log.strip().splitlines()[-1]))
r = lambda n: (T / n).read_text()
res = dict(runs=runs,
           hashes_identical_before_mid=r("before.sha") == r("mid.sha"),
           mtimes_identical_before_mid=r("before.mtime") == r("mid.mtime"),
           sample_wavs_untouched_before_mid=r("before.wavs") == r("mid.wavs"),
           hashes_identical_after_touch=r("mid.sha") == r("after.sha"),
           mtimes_changed_after_touch=[l.split()[-1] for l, m in zip(r("mid.mtime").splitlines(), r("after.mtime").splitlines()) if l != m],
           sample_wavs_untouched_after_touch=r("mid.wavs") == r("after.wavs"),
           n_sample_wavs=len(r("before.wavs").splitlines()))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
PY
