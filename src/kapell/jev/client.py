"""Minimal TypeSafe System One (Jev) HTTP client."""
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from kapell.commands import KapellError

JEV_MODEL = "jev-1.13.0"
JEV_API_URL = "https://api.typesafe.ai/v1/systemone"
_RETRYABLE = frozenset({429, 500, 502, 503})
_MAX_ATTEMPTS = 5


def _default_urlopen(req: urllib.request.Request, timeout: float = 60):
    return urllib.request.urlopen(req, timeout=timeout)


def api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise KapellError(
            "jev_key_missing",
            "TYPESAFE_API_KEY is not set",
            "akm run TYPESAFE_API_KEY -- kapell jev route FINDINGS.json",
            2,
        )
    return key


def system_one(
    state: str | dict[str, Any],
    questions: dict[str, dict],
    *,
    urlopen: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """POST to System One; returns the parsed JSON body (includes ``answers``)."""
    open_fn = urlopen or _default_urlopen
    body = json.dumps({"state": state, "model": JEV_MODEL, "questions": questions}).encode()
    key = api_key()
    last_code: int | None = None
    for attempt in range(_MAX_ATTEMPTS):
        req = urllib.request.Request(
            JEV_API_URL,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with open_fn(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            last_code = exc.code
            if exc.code in _RETRYABLE and attempt < _MAX_ATTEMPTS - 1:
                retry_after = exc.headers.get("retry-after") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except (TypeError, ValueError):
                    delay = 2 ** attempt
                time.sleep(delay)
                continue
            if exc.code == 429:
                raise KapellError(
                    "jev_rate_limited",
                    "TypeSafe API rate limited after retries",
                    "wait and retry, or reduce parallel jev calls",
                    4,
                ) from exc
            raise KapellError(
                "jev_api_error",
                f"TypeSafe API HTTP {exc.code}",
                "check network and api.typesafe.ai status",
                1,
            ) from exc
        except urllib.error.URLError as exc:
            raise KapellError(
                "jev_api_error",
                f"TypeSafe API request failed: {exc.reason}",
                "check network connectivity",
                1,
            ) from exc
        except json.JSONDecodeError as exc:
            raise KapellError(
                "jev_api_error",
                "TypeSafe API returned invalid JSON",
                "retry; contact TypeSafe if persistent",
                1,
            ) from exc
    if last_code == 429:
        raise KapellError(
            "jev_rate_limited",
            "TypeSafe API rate limited after retries",
            "wait and retry, or reduce parallel jev calls",
            4,
        )
    raise KapellError("jev_api_error", "TypeSafe API request failed", "retry", 1)
