#!/usr/bin/env bash
# Idempotency check of setup_strings.sh: hash the built instruments, run --check and the
# install mode twice, hash again, and record timings and any "...." (work done) lines.
#   ./qa_setup.sh   -> qa/results/setup.json
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/.."
Q="${SAMPLE_LIBRARIES:-$HOME/Music/SampleLibraries}/IowaMIS/quartet"
T=/tmp/sqa/setup; mkdir -p "$T"
hashes() { (cd "$Q" && shasum -a 256 ./*.sfz tuning_corrections.json samples/meta.json analysis.json); }
hashes > "$T/before.sha"
run() {  # label, args...
  local l="$1"; shift
  local t0; t0=$(python3 -c 'import time; print(time.time())')
  (cd "$S" && ./setup_strings.sh "$@") > "$T/$l.log" 2>&1; local rc=$?
  local t1; t1=$(python3 -c 'import time; print(time.time())')
  printf '%s %s %s\n' "$l" "$rc" "$(python3 -c "print(round($t1-$t0,1))")" >> "$T/runs.txt"
}
: > "$T/runs.txt"
run check --check
run install1
run install2
hashes > "$T/after.sha"
python3 - "$T" "$HERE/results/setup.json" "$S/setup_strings.sh" <<'PY'
import json, sys, pathlib
T, out, sh = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
runs = []
for line in (T / "runs.txt").read_text().split("\n"):
    if line.strip():
        l, rc, s = line.split()
        log = (T / f"{l}.log").read_text()
        runs.append(dict(run=l, returncode=int(rc), seconds=float(s),
                         work_lines=[x for x in log.splitlines() if x.startswith("  ....")],
                         fail_lines=[x for x in log.splitlines() if "FAIL" in x],
                         last_line=log.strip().splitlines()[-1]))
b, a = (T / "before.sha").read_text(), (T / "after.sha").read_text()
help_tail = sh.read_text().splitlines()[35]          # line 36, printed by --help (sed -n '2,36p')
out.write_text(json.dumps(dict(runs=runs, hashes_identical=a == b, hashes=b.splitlines(),
                               help_prints_line_36=help_tail), indent=1))
print(json.dumps(dict(runs=runs, hashes_identical=a == b, help_prints_line_36=help_tail), indent=1))
PY
