"""Engraving and skeleton goldens. Both run in a temporary copy: never write into the fixture.

LilyPond 2.26 PDFs are not byte-deterministic (CreationDate, and the size differs run to run), so
engraving is compared by page count and a `pdftotext -layout` dump against the committed PDFs
(dumps in expected/). Engraving takes about 1 s per layout with a warm font cache (the first
run after a LilyPond install can take minutes while fontconfig builds its cache).
"""
import re
import shutil
import subprocess

import pytest

from _expected import EXPECTED, HERE
from conftest import run_kit

LAYOUTS = ("piano", "quartet")


def copy_project(neighbour, dst, parts):
    shutil.copy2(neighbour / "kapell.toml", dst / "kapell.toml")
    for p in parts:
        shutil.copytree(neighbour / p, dst / p, ignore=shutil.ignore_patterns("__pycache__", "out"))
    return dst


def pdf_facts(pdf):
    if not (shutil.which("pdfinfo") and shutil.which("pdftotext")):
        pytest.skip("environment: poppler (pdfinfo/pdftotext) not installed")
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", info).group(1)), txt


def assert_matches_committed(pdf, name):
    pages, txt = pdf_facts(pdf)
    assert pages == EXPECTED["engrave"][name]["pages"], f"{name}: {pages} pages"
    assert txt == (HERE / "expected" / f"{name}.pdf.txt").read_text(), f"{name}: text dump differs from the committed PDF"


def test_committed_pdfs_match_expected_dumps(neighbour):
    """Fast: the fixture's committed PDFs are the ones the expected dumps came from."""
    for name in LAYOUTS:
        assert_matches_committed(neighbour / "score" / "out" / f"{name}.pdf", name)


@pytest.mark.parametrize("name", LAYOUTS)
def test_lilypond_reproduces_committed_pdf(neighbour, tmp_path, name):
    """Baseline: plain lilypond on a copy of score/ gives the committed pages and text."""
    if not shutil.which("lilypond"):
        pytest.skip("environment: lilypond not installed")
    copy_project(neighbour, tmp_path, ["score"])
    subprocess.run(["lilypond", "-s", "-o", str(tmp_path / name), f"{name}.ly"], cwd=tmp_path / "score",
                   check=True, capture_output=True, timeout=300)
    assert_matches_committed(tmp_path / f"{name}.pdf", name)


@pytest.mark.parametrize("name", LAYOUTS)
def test_kit_engrave_reproduces_committed_pdf(neighbour, tmp_path, name):
    """`kapell engrave --layout NAME` in a copy of the project matches the committed PDF."""
    if not shutil.which("lilypond"):
        pytest.skip("environment: lilypond not installed")
    copy_project(neighbour, tmp_path, ["score"])
    rc, env, out, err = run_kit("engrave", "--layout", name, cwd=tmp_path, timeout=600)
    assert env is not None, f"kapell engrave: no JSON envelope (rc {rc}); stderr: {err[-800:]}"
    if env.get("status") == "error":
        pytest.fail(f"not landed or broken: kapell engrave -> {env.get('error')}")
    assert rc == 0, out[:600]
    pdfs = sorted(tmp_path.rglob(f"{name}.pdf"))
    assert pdfs, f"kapell engrave wrote no {name}.pdf under the project copy (expected score/out/{name}.pdf)"
    assert_matches_committed(pdfs[0], name)


@pytest.mark.xfail(strict=True, reason="`kapell skeleton build` is phase 3 (piece model); remove this marker when it lands")
def test_kit_skeleton_build_byte_identical(neighbour, tmp_path):
    copy_project(neighbour, tmp_path, ["design/final-lab", "score"])
    lab = tmp_path / "design" / "final-lab"
    for f in ("SK_final.ly", "plan.json"):
        (lab / f).unlink()
    rc, env, out, err = run_kit("skeleton", "build", cwd=tmp_path)
    assert env is not None and env.get("status") != "error", f"kapell skeleton build: {(env or {}).get('error') or err[-400:]}"
    for f in ("SK_final.ly", "plan.json"):
        assert (lab / f).read_bytes() == (neighbour / "design" / "final-lab" / f).read_bytes(), f"{f} differs"
