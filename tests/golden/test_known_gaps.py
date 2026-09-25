"""KNOWN GAPS in The Neighbour that the kit's new checks must find (C section 5).

`kapell xray --json` on the fixture must fail (exit 5) and report:
  * the bar-54 unresolved seventh (DIS7: the E-flat of V4/2 that never resolves);
  * the S2 coverage failure (double fugue, but S2 is only heard at one pitch);
  * strong suspensions below the quota (18 against strong_suspensions = 20);
  * missing performance cues for the arioso tenor lament and the bass head imitation.
Key names are the new-checks lane's choice, so items are matched by content with a recursive walk.
"""
import json
import re

import pytest

from conftest import run_kit


def walk(x):
    """Yield every dict and every string inside x."""
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from walk(v)
    elif isinstance(x, str):
        yield x


def text(x) -> str:
    return x if isinstance(x, str) else json.dumps(x, sort_keys=True)


FAILED = re.compile(r'"(ok|pass|passed|met)": false|"status": "(fail|failed|below)"|FAIL|BELOW|MISSING|missing', re.I)


NOCUE = re.compile(r"no (performance )?cue|uncued|NOCUE|MISSING_CUE|lacks? a cue|without a cue", re.I)


@pytest.fixture(scope="module")
def xray(neighbour):
    rc, env, out, err = run_kit("xray", cwd=neighbour)
    assert env is not None, f"kapell xray: no JSON envelope (rc {rc}); stderr: {err[-800:]}"
    if env.get("status") == "error":
        pytest.fail(f"not landed or broken: kapell xray -> {env.get('error')}")
    return rc, env


def test_xray_fails_gate(xray):
    rc, env = xray
    assert rc == 5, f"xray must exit 5 when a gate fails on the fixture, got {rc}"
    assert env["status"] == "fail"


def test_xray_keeps_golden_check_totals(xray):
    """The bundle still carries the clean check totals (0/0/0/0) and suspension counts 18/13."""
    _, env = xray
    s = text(env["data"])
    for d in walk(env["data"]):
        if isinstance(d, dict) and {"errors", "parallels", "unjustified"} <= d.keys():
            assert (d["errors"], d["parallels"], d["unjustified"]) == (0, 0, 0)
            break
    else:
        pytest.fail(f"xray bundle has no check totals (errors/parallels/unjustified): {s[:400]}")
    assert any(isinstance(d, dict) and d.get("strong") == 18 and d.get("weak") == 13 for d in walk(env["data"])), \
        "xray bundle has no suspensions {strong: 18, weak: 13}"


def test_xray_bar54_unresolved_seventh(xray):
    _, env = xray
    hits = [d for d in walk(env["data"]) if "DIS7" in text(d) and re.search(r'(?<![\d.])54(:|\b)', text(d))
            and (isinstance(d, str) or any(isinstance(v, str) and v.startswith("DIS7") for v in d.values()))]
    assert hits, "xray must report DIS7 (unresolved chordal seventh) at bar 54 (the V4/2 E-flat)"
    assert any(re.search(r'[Ee]b|E-flat|ees|Eb\d', text(h)) for h in hits), \
        f"the bar-54 DIS7 should name the E-flat: {text(hits[0])[:300]}"


def test_xray_s2_coverage_failure(xray):
    _, env = xray
    hits = [d for d in walk(env["data"]) if isinstance(d, dict) and d.get("theme") == "S2" and FAILED.search(text(d))]
    hits += [d for d in walk(env["data"]) if isinstance(d, str) and "S2" in d and re.search(r"double.fugue|FORM|one pitch", d)]
    assert hits, "xray must report that S2 lacks its answer / inversion or stretto (form claim double-fugue fails)"


def test_xray_suspension_quota_below(xray):
    _, env = xray
    hits = [d for d in walk(env["data"]) if isinstance(d, dict) and "strong_suspensions" in text(d)
            and re.search(r'\b18\b', text(d)) and re.search(r'\b20\b', text(d)) and FAILED.search(text(d))]
    assert hits, "xray must report quota strong_suspensions: 18 against target 20, failing"


@pytest.mark.parametrize("feature", ["lament", "head"])
def test_xray_missing_performance_cues(xray, feature):
    _, env = xray
    hits = [d for d in walk(env["data"]) if feature in text(d).lower() and (FAILED.search(text(d)) or NOCUE.search(text(d)))
            and (isinstance(d, str) or any(feature in str(v).lower() for v in d.values() if isinstance(v, str)))]
    assert hits, (f"xray must report a missing performance cue for the arioso "
                  f"{'tenor lament' if feature == 'lament' else 'bass head imitation'}")
