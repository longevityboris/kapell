"""Confidence gates and decision helpers."""
from kapell.jev.questions import (
    PARK_MINOR_MIN_CONFIDENCE,
    ROUTE_MIN_CONFIDENCE,
    escalate_park,
    escalate_route,
)


def test_route_escalate_below_threshold():
    assert escalate_route("notes", ROUTE_MIN_CONFIDENCE - 0.01) is True
    assert escalate_route("performance", ROUTE_MIN_CONFIDENCE) is False


def test_park_only_trusts_minor_at_high_confidence():
    assert escalate_park("major", 1.0) is True
    assert escalate_park("minor", PARK_MINOR_MIN_CONFIDENCE - 0.01) is True
    assert escalate_park("minor", PARK_MINOR_MIN_CONFIDENCE) is False


def test_decide_route_mocked(monkeypatch):
    from kapell.jev.questions import decide_route

    def fake_system_one(state, questions, urlopen=None):
        assert "route" in questions
        return {"answers": {"route": {"choice": "performance", "confidence": 0.92, "probabilities": {}}}}

    monkeypatch.setattr("kapell.jev.questions.system_one", fake_system_one)
    r = decide_route({"severity": "minor", "where": "bar 1", "issue": "too loud", "fix": ""})
    assert r["decision"] == "performance"
    assert r["escalate"] is False
