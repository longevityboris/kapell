"""kapell jev: TypeSafe Jev routing and parking for review findings (orchestration glue)."""
import json
from pathlib import Path

from kapell.jev.questions import decide_park, decide_route

from . import KapellError

SPEC = {
    "name": "jev",
    "effect": "execute",
    "help": "Jev triage: route findings to notes vs performance, or park minor items (confidence-gated)",
    "runtime_s": "0.5-3",
    "output_tokens_typ": 120,
    "examples": [
        ["jev", "route", "findings.json"],
        ["jev", "park", "findings.json"],
        ["jev", "route", "findings.json", "--full"],
    ],
}

_FINDING_KEYS = ("severity", "where", "issue", "fix")


def add_arguments(parser):
    sub = parser.add_subparsers(dest="action", required=True)
    for name, help_ in (
        ("route", "composer (notes) vs performance lane for each finding"),
        ("park", "severity gate: only high-confidence minor can be parked; else escalate"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("findings", type=Path, help="JSON list of {severity, where, issue, fix}")
        p.add_argument("--full", action="store_true", help="per-finding decisions, not just the digest")


def _load_findings(path: Path) -> list[dict]:
    if not path.is_file():
        raise KapellError("bad_input", f"findings file not found: {path}", "kapell jev route FINDINGS.json", 3)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KapellError("bad_input", f"invalid JSON in {path}: {exc}", "use a UTF-8 JSON array of findings", 3)
    if isinstance(raw, dict) and "findings" in raw:
        raw = raw["findings"]
    if not isinstance(raw, list):
        raise KapellError("bad_input", "findings JSON must be a list", '[{"severity","where","issue","fix"}, ...]', 3)
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise KapellError("bad_input", f"finding {i} is not an object", "each finding is a JSON object", 3)
        for k in _FINDING_KEYS:
            if k not in item:
                raise KapellError(
                    "bad_input",
                    f"finding {i} missing key {k!r}",
                    "fields: severity, where, issue, fix (fix may be empty string)",
                    3,
                )
        out.append({k: item[k] for k in _FINDING_KEYS})
    return out


def _digest(action: str, results: list[dict]) -> dict:
    by_decision: dict[str, int] = {}
    escalated = 0
    for r in results:
        by_decision[r["decision"]] = by_decision.get(r["decision"], 0) + 1
        if r["escalate"]:
            escalated += 1
    return {
        "action": action,
        "n": len(results),
        "by_decision": by_decision,
        "escalated": escalated,
        "auto": len(results) - escalated,
    }


def run(args, ctx):
    findings = _load_findings(args.findings)
    decide = decide_route if args.action == "route" else decide_park
    results = [decide(f) for f in findings]
    data = _digest(args.action, results)
    if args.full:
        data["findings"] = results
    else:
        data["sample"] = results[:3]
        if len(results) > 3:
            data["sample_truncated"] = len(results) - 3
        data["hint"] = f"kapell jev {args.action} --full lists every decision"
    return data
