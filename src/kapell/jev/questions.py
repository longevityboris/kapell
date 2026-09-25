"""Gated Jev decisions calibrated on fugue-jp review findings (jev_probe, t3)."""
from typing import Any

from .client import system_one

# t3_route: 0.90 accuracy @ 84% coverage when confidence >= 0.9 (D_jev_probe.md gate table).
ROUTE_MIN_CONFIDENCE = 0.9

# t3_severity_full: Jev "minor" calls were 36/37 true minor (NPV 0.97); only auto-park minor at high conf.
PARK_MINOR_MIN_CONFIDENCE = 0.9

ROUTE_QUESTION = {
    "type": "choice",
    "instructions": "Who has to act on this finding?",
    "criteria": {
        "notes": "the composer: change the written notes, voice leading or harmony in the score",
        "performance": "the performance/audio engineer: change dynamics, articulation, instrument "
        "rendering, mixing or the audio file",
    },
}

SEVERITY_QUESTION = {
    "type": "choice",
    "instructions": "How severe is this review finding about a composed fugue or its recording?",
    "criteria": {
        "major": "major: a real defect a listener or expert would notice, or a broken rule of the style; must be fixed",
        "minor": "minor: a nuance, polish item, or optional improvement",
    },
}


def finding_text(finding: dict[str, Any]) -> str:
    issue = (finding.get("issue") or "").strip()
    fix = (finding.get("fix") or "").strip()
    if fix:
        return issue + "\nSuggested fix: " + fix
    return issue


def _choice_answer(resp: dict[str, Any], key: str) -> tuple[str, float]:
    ans = resp["answers"][key]
    return ans["choice"], float(ans["confidence"])


def escalate_route(decision: str, confidence: float) -> bool:
    return confidence < ROUTE_MIN_CONFIDENCE


def escalate_park(decision: str, confidence: float) -> bool:
    if decision != "minor":
        return True
    return confidence < PARK_MINOR_MIN_CONFIDENCE


def decide_route(finding: dict[str, Any], *, urlopen=None) -> dict[str, Any]:
    resp = system_one(finding_text(finding), {"route": ROUTE_QUESTION}, urlopen=urlopen)
    decision, confidence = _choice_answer(resp, "route")
    return {
        "where": finding.get("where", ""),
        "decision": decision,
        "confidence": confidence,
        "escalate": escalate_route(decision, confidence),
    }


def decide_park(finding: dict[str, Any], *, urlopen=None) -> dict[str, Any]:
    resp = system_one(finding_text(finding), {"severity": SEVERITY_QUESTION}, urlopen=urlopen)
    decision, confidence = _choice_answer(resp, "severity")
    return {
        "where": finding.get("where", ""),
        "decision": decision,
        "confidence": confidence,
        "escalate": escalate_park(decision, confidence),
    }
