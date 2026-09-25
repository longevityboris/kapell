"""Shared pytest fixtures for the kapell test tiers.

The golden tier runs on The Neighbour (the fugue-jp ricercar). Its location comes from
KAPELL_FIXTURE_NEIGHBOUR, default /Users/biobook/Music/llm-music/fugue-jp/ricercar. Golden tests
skip only when that directory is missing; a kit feature that has not landed yet makes its test
fail with a message naming the missing piece.
"""
import hashlib
import io
import tarfile
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
KIT_SRC = REPO / "src"
VENDOR = REPO / "vendor" / "fugue-jp"
DEFAULT_NEIGHBOUR = "/Users/biobook/Music/llm-music/fugue-jp/ricercar"

# Test the working tree, not whatever kapell happens to be installed.
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))


@pytest.fixture(scope="session")
def neighbour(tmp_path_factory) -> Path:
    """Immutable snapshot of the original known-gap fixture; never write to its checkout."""
    root = Path(os.environ.get("KAPELL_FIXTURE_NEIGHBOUR", DEFAULT_NEIGHBOUR))
    if not root.is_dir():
        pytest.skip(f"fixture The Neighbour not found at {root} (set KAPELL_FIXTURE_NEIGHBOUR)")
    # The live piece continues to evolve; golden numbers refer to this exact revision.
    revision = os.environ.get("KAPELL_FIXTURE_REVISION", "9b343c0ce827389007127f0ccb1da090e15b782c")
    repo = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=True).stdout.strip()
    archive = subprocess.run(["git", "-C", repo, "archive", revision + ":ricercar"],
                             capture_output=True, check=True)
    snapshot = tmp_path_factory.mktemp("neighbour-golden")
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(snapshot, filter="data")
    def fingerprint():
        return {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in snapshot.rglob("*") if p.is_file() and "__pycache__" not in p.parts}

    before = fingerprint()
    yield snapshot
    assert fingerprint() == before, "tests modified the pinned fixture snapshot"


@pytest.fixture(scope="session")
def neighbour_score(neighbour) -> Path:
    return neighbour / "score" / "music-voices.ly"


def kit_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(KIT_SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def run_kit(*argv, cwd=None, timeout=300):
    """Run the kit CLI as `python -m kapell.cli --json ARGV` from src/ (no PATH binary needed).

    Returns (returncode, parsed JSON envelope or None, stdout, stderr).
    """
    cmd = [sys.executable, "-m", "kapell.cli", "--json", *map(str, argv)]
    p = subprocess.run(cmd, cwd=cwd, env=kit_env(), capture_output=True, text=True, timeout=timeout)
    env = None
    try:
        env = json.loads(p.stdout)
    except (json.JSONDecodeError, ValueError):
        pass
    return p.returncode, env, p.stdout, p.stderr


def run_vendor(script: str, *argv, cwd=None, timeout=120) -> str:
    """Run a vendored original script (path relative to vendor/fugue-jp) and return stdout."""
    p = subprocess.run([sys.executable, str(VENDOR / script), *map(str, argv)], cwd=cwd,
                       capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0, f"vendored {script} failed (rc {p.returncode}): {p.stderr[-2000:]}"
    return p.stdout
