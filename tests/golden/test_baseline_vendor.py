"""Safety net: the VENDORED ORIGINAL scripts still give the golden values on The Neighbour.

If these fail, the fixture or vendor/ changed, not the kit: re-run capture.py only if the change
is intended.
"""
import shutil
import subprocess
import sys

import capture
from _expected import EXPECTED
from conftest import run_vendor


def test_vendor_check_totals(neighbour_score):
    got = capture.parse_check(run_vendor("tools/check.py", neighbour_score))
    assert got == EXPECTED["check"]
    assert (got["errors"], got["parallels"], got["beat-par"], got["unjustified"]) == (0, 0, 0, 0)


def test_vendor_check_with_project_ranges(neighbour_score):
    rng = [a for v, r in EXPECTED["check_with_ranges"]["ranges"].items() for a in ("--range", f"{v}={r}")]
    got = capture.parse_check(run_vendor("tools/check.py", neighbour_score, *rng))
    exp = {k: v for k, v in EXPECTED["check_with_ranges"].items() if k != "ranges"}
    assert got == exp


def test_vendor_suspensions(neighbour_score):
    out = run_vendor("design/final-lab/suspensions.py", neighbour_score)
    assert "prepared suspensions: 18" in out
    assert "weak-beat suspensions (not counted): 13" in out


def test_vendor_strict(neighbour_score):
    out = run_vendor("design/final-lab/strict.py", neighbour_score)
    e = EXPECTED["strict"]
    assert f"strict: clash {e['clash']}, xrel {e['xrel']}, acc {e['acc']}, acc2 {e['acc2']}" in out


def test_vendor_harmony_stats(neighbour_score):
    out = run_vendor("tools/harmony.py", neighbour_score, "--stats")
    assert out.strip().splitlines()[-1] == EXPECTED["harmony_stats"]["line"]


def test_vendor_build_sk_byte_identical(neighbour, tmp_path):
    """build_sk.py, run in a temporary copy of final-lab, reproduces SK_final.ly and plan.json."""
    lab = neighbour / "design" / "final-lab"
    tl = tmp_path / "final-lab"
    shutil.copytree(lab, tl, ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run([sys.executable, "build_sk.py"], cwd=tl, check=True, capture_output=True)
    for name in ("SK_final.ly", "plan.json"):
        assert (tl / name).read_bytes() == (lab / name).read_bytes(), f"{name} differs from the committed file"
        assert capture.sha(tl / name) == EXPECTED["skeleton"][name]
