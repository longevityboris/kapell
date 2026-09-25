"""Jev HTTP client (mocked; no network)."""
import io
import json
import urllib.error

import pytest

from kapell.commands import KapellError
from kapell.jev.client import JEV_MODEL, system_one


def _mock_response(payload: dict):
    def urlopen(req, timeout=60):
        assert JEV_MODEL.encode() in req.data or JEV_MODEL in req.data.decode()
        body = json.dumps(payload).encode()
        return io.BytesIO(body)

    return urlopen


def test_system_one_parses_answers(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    payload = {
        "model": JEV_MODEL,
        "answers": {"route": {"choice": "notes", "confidence": 0.95, "probabilities": {"notes": 0.95, "performance": 0.05}}},
        "usage": {"input_tokens": 10},
    }
    out = system_one("finding text", {"route": {"type": "choice", "instructions": "x", "criteria": {"notes": "n", "performance": "p"}}},
                     urlopen=_mock_response(payload))
    assert out["answers"]["route"]["choice"] == "notes"


def test_key_missing(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(KapellError) as exc:
        system_one("x", {"q": {"type": "choice", "instructions": "i", "criteria": {"a": "a"}}})
    assert exc.value.code == "jev_key_missing"
    assert exc.value.exit_code == 2


def test_retries_then_success(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    calls = {"n": 0}
    good = json.dumps({"answers": {"route": {"choice": "notes", "confidence": 0.9, "probabilities": {}}}}).encode()

    def urlopen(req, timeout=60):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", hdrs=None, fp=io.BytesIO(b""))
        return io.BytesIO(good)

    monkeypatch.setattr("kapell.jev.client.time.sleep", lambda _: None)
    system_one("s", {"route": {"type": "choice", "instructions": "i", "criteria": {"notes": "n", "performance": "p"}}},
               urlopen=urlopen)
    assert calls["n"] == 2


def test_rate_limited_exit_4(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    def urlopen(req, timeout=60):
        raise urllib.error.HTTPError(req.full_url, 429, "limit", hdrs=None, fp=io.BytesIO(b""))

    monkeypatch.setattr("kapell.jev.client.time.sleep", lambda _: None)
    with pytest.raises(KapellError) as exc:
        system_one("s", {"route": {"type": "choice", "instructions": "i", "criteria": {"notes": "n", "performance": "p"}}},
                   urlopen=urlopen)
    assert exc.value.code == "jev_rate_limited"
    assert exc.value.exit_code == 4
