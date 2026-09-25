#!/usr/bin/env python3
"""Capture golden values for The Neighbour by running the VENDORED ORIGINAL scripts.

usage: python3 tests/golden/capture.py [FIXTURE_DIR]      rewrites tests/golden/expected_neighbour.json

Run this only when the fixture's music changes on purpose; the kit must then reproduce the new
values. The text dumps of the committed PDFs (expected/*.pdf.txt) are refreshed with pdftotext.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VENDOR = REPO / "vendor" / "fugue-jp"
RANGES = {"soprano": "60-84", "alto": "53-77", "tenor": "48-72", "bass": "36-62"}


def run(script, *argv, cwd=None):
    return subprocess.run([sys.executable, str(VENDOR / script), *map(str, argv)], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


def parse_check(out: str) -> dict:
    """check.py stdout -> totals line numbers and per-kind line counts."""
    last = [ln for ln in out.splitlines() if ln.startswith("-- totals:")][0]
    bars = dict(re.findall(r"'(\w)': '(\d+)'", last))
    nums ={k: int(v) for k, v in re.findall(r"(errors|parallels|beat-par|unjustified) (\d+)", last)}
    kinds = Counter(ln.split()[0] for ln in out.splitlines() if ln.strip() and not ln.startswith("--"))
    dis = [ln for ln in out.splitlines() if ln.startswith("DIS ")]
    return {"bars": {k: int(v) for k, v in bars.items()}, **nums, "lines_by_kind": dict(sorted(kinds.items())),
            "dissonances": len(dis), "dissonances_strong": sum(" strong " in ln for ln in dis),
            "dissonances_weak": sum(" weak " in ln for ln in dis), "unjustified_lines": sum("DIS!" in ln for ln in out.splitlines())}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    fx = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "KAPELL_FIXTURE_NEIGHBOUR", "/Users/biobook/Music/llm-music/fugue-jp/ricercar"))
    score = fx / "score" / "music-voices.ly"
    exp = {"fixture": "The Neighbour", "score": "score/music-voices.ly"}

    exp["check"] = parse_check(run("tools/check.py", score))
    rng = [a for v, r in RANGES.items() for a in ("--range", f"{v}={r}")]
    exp["check_with_ranges"] = parse_check(run("tools/check.py", score, *rng))
    exp["check_with_ranges"]["ranges"] = RANGES

    s = run("design/final-lab/suspensions.py", score)
    exp["suspensions"] = {"strong": int(re.search(r"prepared suspensions: (\d+)", s).group(1)),
                          "weak": int(re.search(r"weak-beat suspensions \(not counted\): (\d+)", s).group(1))}

    st = run("design/final-lab/strict.py", score)
    m = re.search(r"strict: clash (\d+), xrel (\d+), acc (\d+), acc2 (\d+)", st)
    exp["strict"] = dict(zip(["clash", "xrel", "acc", "acc2"], map(int, m.groups())))

    h = run("tools/harmony.py", score, "--stats").strip().splitlines()[-1]
    m = re.search(r"attacks (\d+); seventh-type (\d+)%; dim7 (\d+)%; chromatic-to-key (\d+)%; distinct labels (\d+)", h)
    exp["harmony_stats"] = dict(zip(["attacks", "seventh_type_pct", "dim7_pct", "chromatic_to_key_pct",
                                     "distinct_labels"], map(int, m.groups())))
    exp["harmony_stats"]["line"] = h

    lab = fx / "design" / "final-lab"
    with tempfile.TemporaryDirectory() as t:
        tl = Path(t) / "final-lab"
        shutil.copytree(lab, tl, ignore=shutil.ignore_patterns("__pycache__"))
        subprocess.run([sys.executable, "build_sk.py"], cwd=tl, check=True, capture_output=True)
        exp["skeleton"] = {"SK_final.ly": sha(tl / "SK_final.ly"), "plan.json": sha(tl / "plan.json"),
                           "matches_committed": (tl / "SK_final.ly").read_bytes() == (lab / "SK_final.ly").read_bytes()
                           and (tl / "plan.json").read_bytes() == (lab / "plan.json").read_bytes()}

    eng = {}
    for name in ("piano", "quartet"):
        pdf = fx / "score" / "out" / f"{name}.pdf"
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
        eng[name] = {"pages": int(re.search(r"Pages:\s+(\d+)", info).group(1))}
        subprocess.run(["pdftotext", "-layout", str(pdf), str(HERE / "expected" / f"{name}.pdf.txt")], check=True)
    exp["engrave"] = {"byte_deterministic": False, "compare": "page count + pdftotext -layout dump",
                      "note": "lilypond 2.26 PDFs embed CreationDate and differ in size run to run; text and pages match",
                      **eng}

    (HERE / "expected_neighbour.json").write_text(json.dumps(exp, indent=1, sort_keys=True) + "\n")
    print(json.dumps(exp, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
