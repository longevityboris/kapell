"""Output envelope and exit codes (C section 3; stable, extend but do not rename).

Success: {"version": "1", "status": "success"|"no_results"|"partial_success"|"fail", "data": {...}}
Error:   {"version": "1", "status": "error", "error": {"code", "message", "suggestion"}}

Exit codes: 0 ok; 1 transient; 2 config/env; 3 bad input; 4 rate limited; 5 musical check failed.
JSON is the output format whenever stdout is not a TTY, or with --json.
"""
import json
import sys

ENVELOPE_VERSION = "1"

EXIT_CODES = {
    "0": "ok",
    "1": "transient (retry)",
    "2": "config/env: run kapell doctor",
    "3": "bad input",
    "4": "rate limited",
    "5": "musical check failed: see data.violations",
}

STATUSES = ("success", "no_results", "partial_success", "fail")


def success(data: dict | None = None, status: str = "success") -> dict:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")
    return {"version": ENVELOPE_VERSION, "status": status, "data": data if data is not None else {}}


def error(code: str, message: str, suggestion: str = "") -> dict:
    return {"version": ENVELOPE_VERSION, "status": "error",
            "error": {"code": code, "message": message, "suggestion": suggestion}}


def exit_for(status: str) -> int:
    """Exit code for a non-error status: only a failed musical check exits non-zero (5)."""
    return 5 if status == "fail" else 0


def _human(value, indent: int = 0) -> list[str]:
    pad = "  " * indent
    lines = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.extend(_human(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {_scalar(v)}")
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, dict) and v:
                sub = _human(v, indent + 1)
                lines.append(f"{pad}- {sub[0].lstrip()}")
                lines.extend(sub[1:])
            else:
                lines.append(f"{pad}- {_scalar(v)}")
    else:
        lines.append(f"{pad}{_scalar(value)}")
    return lines


def _scalar(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def emit(env: dict, as_json: bool, quiet: bool = False, out=None, err=None) -> None:
    """Write an envelope. JSON mode: the whole envelope on stdout (errors too, so pipes parse them).
    Human mode: data as key: value lines on stdout; errors on stderr. --quiet silences successes."""
    out = out or sys.stdout
    err = err or sys.stderr
    is_error = env.get("status") == "error"
    if quiet and not is_error:
        return
    if as_json:
        out.write(json.dumps(env, ensure_ascii=False, default=str) + "\n")
        return
    if is_error:
        e = env["error"]
        err.write(f"error [{e['code']}]: {e['message']}\n")
        if e.get("suggestion"):
            err.write(f"hint: {e['suggestion']}\n")
        return
    if env["status"] != "success":
        out.write(f"status: {env['status']}\n")
    out.write("\n".join(_human(env.get("data", {}))) + "\n")


class Raw:
    """A command result printed verbatim on stdout, outside the envelope (the documented exception,
    used by `guide NAME` for raw markdown)."""

    def __init__(self, text: str):
        self.text = text
