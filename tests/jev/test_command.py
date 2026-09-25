"""kapell jev CLI command."""
import json

from kapell.commands import Context
from kapell.commands import jev as jev_cmd


def test_route_command_digest(tmp_path, monkeypatch):
    findings = [
        {"severity": "minor", "where": "1:1", "issue": "voice crossing", "fix": "swap alto and tenor"},
        {"severity": "major", "where": "listen", "issue": "pedal missing", "fix": "add sustain"},
    ]
    path = tmp_path / "f.json"
    path.write_text(json.dumps(findings), encoding="utf-8")

    decisions = [
        {"where": "1:1", "decision": "notes", "confidence": 0.95, "escalate": False},
        {"where": "listen", "decision": "performance", "confidence": 0.88, "escalate": True},
    ]
    calls = {"i": 0}

    def fake_decide(f, urlopen=None):
        d = decisions[calls["i"]]
        calls["i"] += 1
        return d

    monkeypatch.setattr("kapell.commands.jev.decide_route", fake_decide)
    import argparse
    parser = argparse.ArgumentParser()
    jev_cmd.add_arguments(parser)
    args = parser.parse_args(["route", str(path)])
    data = jev_cmd.run(args, Context())
    assert data["n"] == 2
    assert data["escalated"] == 1
    assert data["by_decision"]["notes"] == 1
    assert "findings" not in data
    assert len(data["sample"]) == 2


def test_bad_findings_file(tmp_path):
    import argparse

    parser = argparse.ArgumentParser()
    jev_cmd.add_arguments(parser)
    args = parser.parse_args(["park", str(tmp_path / "missing.json")])
    from kapell.commands import KapellError
    import pytest

    with pytest.raises(KapellError) as exc:
        jev_cmd.run(args, Context())
    assert exc.value.code == "bad_input"
