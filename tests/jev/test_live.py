"""Optional live TypeSafe API smoke test."""
import json
import os

import pytest

from kapell.jev.questions import decide_route

pytestmark = pytest.mark.skipif(
    not os.environ.get("TYPESAFE_API_KEY"),
    reason="set TYPESAFE_API_KEY for live Jev test",
)


def test_live_route_smoke():
    finding = {
        "severity": "minor",
        "where": "sec01_expo 5:1",
        "issue": "The soprano line is slightly sharp in the render; adjust velocity or tuning in the mix.",
        "fix": "Lower soprano velocity 2 dB in plan.json.",
    }
    r = decide_route(finding)
    assert r["decision"] in ("notes", "performance")
    assert 0 <= r["confidence"] <= 1
    assert isinstance(r["escalate"], bool)
    print(json.dumps(r, indent=2))
