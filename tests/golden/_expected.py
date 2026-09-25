"""Golden values captured from the vendored original scripts (see capture.py)."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPECTED = json.loads((HERE / "expected_neighbour.json").read_text())
RANGES = {v: tuple(map(int, r.split("-"))) for v, r in EXPECTED["check_with_ranges"]["ranges"].items()}
