"""The KIT reproduces the golden values through its API and CLI (C section 10).

Imports happen inside each test: a module another lane has not landed yet makes that test FAIL
with 'not landed: ...', while the other golden tests still run.
"""
import importlib

import pytest

from _expected import EXPECTED, RANGES
from conftest import run_kit, run_vendor


def kit(module: str):
    try:
        return importlib.import_module(module)
    except ImportError as e:
        pytest.fail(f"not landed: {module} ({e})")


def need(mod, attr):
    if not hasattr(mod, attr):
        pytest.fail(f"not landed: {mod.__name__}.{attr}")
    return getattr(mod, attr)


GATES = ("errors", "parallels", "beat_parallels", "unjustified")


# ---- API -------------------------------------------------------------------------------------

def test_api_check_totals(neighbour_score):
    r = need(kit("kapell.analysis.check"), "run")(neighbour_score)
    t, e = r["totals"], EXPECTED["check"]
    assert tuple(t[k] for k in GATES) == (0, 0, 0, 0)
    assert {k: int(v) for k, v in t["voices"].items()} == e["bars"]
    assert len(r["dissonances"]) == e["dissonances"] == t["dissonances"]
    assert sum(bool(d.get("strong")) for d in r["dissonances"]) == e["dissonances_strong"]
    kinds = e["lines_by_kind"]
    assert (t["crossings"], t["directs"], t["melodic"], t["d4"]) == (kinds["CROS"], kinds["DIR"], kinds["MEL"], kinds["D4?"])
    assert r["violations"] == [], f"clean score must have no violations, got {r['violations'][:3]}"


def test_api_check_lines_match_original(neighbour_score):
    """Every line the original check.py prints, the kit reproduces (full output, same order)."""
    r = need(kit("kapell.analysis.check"), "run")(neighbour_score)
    want = run_vendor("tools/check.py", neighbour_score).splitlines()
    assert r["lines"] == want


def test_api_check_with_project_ranges(neighbour_score):
    r = need(kit("kapell.analysis.check"), "run")(neighbour_score, ranges=RANGES)
    t = r["totals"]
    assert tuple(t[k] for k in GATES) == (0, 0, 0, 0)
    assert t["dissonances"] == EXPECTED["check_with_ranges"]["dissonances"]
    assert r["violations"] == []


def test_api_suspensions(neighbour_score):
    r = need(kit("kapell.analysis.suspensions"), "count")(neighbour_score)
    assert (r["strong"], r["weak"]) == (EXPECTED["suspensions"]["strong"], EXPECTED["suspensions"]["weak"]) == (18, 13)


def test_api_strict(neighbour_score):
    r = need(kit("kapell.analysis.strict"), "run")(neighbour_score)
    assert {k: r[k] for k in ("clash", "xrel", "acc", "acc2")} == EXPECTED["strict"]


def test_api_harmony_attacks(neighbour_score):
    """harmony.analyse gives one chord per attack; the original --stats counted 360 attacks."""
    r = need(kit("kapell.analysis.harmony"), "analyse")(neighbour_score)
    attacks = r if isinstance(r, list) else (r.get("attacks") or r.get("chords") or r.get("items"))
    n = attacks if isinstance(attacks, int) else len(attacks)
    assert n == EXPECTED["harmony_stats"]["attacks"]
    if not (isinstance(r, dict) and "stats" in r):
        pytest.fail("not landed: harmony.analyse(...)['stats'] (the --stats summary)")
    st, e = r["stats"], EXPECTED["harmony_stats"]
    pct = lambda share: round(100 * share)
    want = {"seventh_share": ("seventh_type_pct", pct), "dim7_share": ("dim7_pct", pct),
            "chromatic_share": ("chromatic_to_key_pct", pct), "distinct": ("distinct_labels", int),
            "attacks": ("attacks", int)}
    for key, (ek, conv) in want.items():
        if key not in st:
            pytest.fail(f"not landed: harmony stats key {key!r} (have {sorted(st)})")
        assert conv(st[key]) == e[ek], f"harmony stats {key}: {st[key]} vs original {e[ek]}"


# ---- CLI -------------------------------------------------------------------------------------

def _envelope(rc, env, out, err, what):
    assert env is not None, f"{what}: no JSON envelope on stdout (rc {rc}); stderr: {err[-800:]}"
    assert env.get("version") == "1", env
    if env.get("status") == "error":
        pytest.fail(f"{what}: error envelope {env.get('error')}")
    return env


def test_cli_check_json_clean(neighbour):
    """`kapell check --json` in the project resolves the score, exits 0, digest shows 0/0/0/0."""
    rc, env, out, err = run_kit("check", cwd=neighbour)
    env = _envelope(rc, env, out, err, "kapell check")
    assert rc == 0, f"clean score must exit 0, got {rc}: {out[:600]}"
    assert env["status"] == "success"
    t = env["data"]["totals"]
    assert tuple(t[k] for k in GATES) == (0, 0, 0, 0)
    assert t["dissonances"] == EXPECTED["check"]["dissonances"]
    assert not env["data"].get("violations")
    assert "dissonances" not in env["data"] or isinstance(env["data"]["dissonances"], int), \
        "digest by default: dissonance lines only behind --full (C section 4)"
    assert len(out) < 4000, f"digest should be short by default, got {len(out)} chars"


def test_cli_check_json_explicit_path(neighbour, neighbour_score):
    rc, env, out, err = run_kit("check", neighbour_score, cwd=neighbour)
    env = _envelope(rc, env, out, err, "kapell check FILE")
    assert rc == 0 and env["data"]["totals"]["unjustified"] == 0
