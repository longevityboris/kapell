"""Unit tests for kapell.analysis on tiny inline fixtures, plus fixture checks on The Neighbour."""
import argparse
from pathlib import Path

import pytest

from kapell.analysis import check, harmony, parse_bars, parse_measure, splice, strict, suspensions
from kapell.commands import Context, KapellError, Result

NEIGHBOUR = Path("/Users/biobook/Music/llm-music/fugue-jp/ricercar")
needs_fixture = pytest.mark.skipif(not (NEIGHBOUR / "kapell.toml").is_file(), reason="The Neighbour fixture not present")


def ly(**voices):
    return "\n".join(f"{v} = \\absolute {{\n  {body}\n}}" for v, body in voices.items()) + "\n"


def kinds(items):
    return [i["kind"] for i in items]


# ---- check -----------------------------------------------------------------------------------

def test_parallel_fifth():
    src = ly(soprano="g'4 a'4 r2 |", bass="c'4 d'4 r2 |")
    r = check.run(src=src, voices="soprano,bass")
    assert r["totals"]["parallels"] == 1
    assert kinds(r["violations"]) == ["PAR!"]
    assert "P5 parallel G4/C4 -> A4/D4" in r["violations"][0]["line"]
    assert not check.ok(r)


def test_contrary_octaves_are_reported_too():
    src = ly(soprano="c''4 g'4 r2 |", bass="c'4 g4 r2 |")  # 8ve then 8ve, both voices moving
    r = check.run(src=src, voices="soprano,bass")
    assert r["totals"]["parallels"] == 1


def test_unprepared_fourth_over_bass_is_flagged_for_review():
    # F4 over the bass C4, leapt into and out of: no justification. The original tags it 'D4?'
    # (a review item), not DIS!, so it does not fail the check.
    src = ly(soprano="c''4 f'4 c''4 c''4 |", bass="c'1 |")
    r = check.run(src=src, voices="soprano,bass")
    d4 = [i for i in r["review"] if i["kind"] == "D4?"]
    assert len(d4) == 1 and "P4/bass" in d4[0]["line"] and "UNJUSTIFIED" in d4[0]["line"]
    assert r["totals"]["d4"] == 1 and r["violations"] == []


def test_unjustified_second_is_a_violation():
    src = ly(soprano="g'4 d''4 g'2 |", bass="c'1 |")  # D5 over C4 (M9), leapt in and out
    r = check.run(src=src, voices="soprano,bass")
    assert r["totals"]["unjustified"] == 1
    assert kinds(r["violations"]) == ["DIS!"]


def test_passing_tone_is_justified():
    src = ly(soprano="e'4 d'4 c'2 |", bass="c'1 |")  # D4 against C4 approached and left by step
    r = check.run(src=src, voices="soprano,bass")
    assert r["totals"]["unjustified"] == 0
    assert any("S:PT/NT" in d["line"] for d in r["dissonances"])


def test_crossing():
    src = ly(soprano="c'1 |", alto="e'1 |")
    r = check.run(src=src, voices="soprano,alto")
    assert kinds(r["review"]) == ["CROS"]
    assert r["totals"]["crossings"] == 1 and r["violations"] == []


def test_bar_check_range_and_length_errors():
    src = ly(soprano="c'2 d'4 | e'4 |", bass="c2 |")
    r = check.run(src=src, voices="soprano,bass", ranges={"bass": (50, 60)})  # c = C3 = 48
    lines = [v["line"] for v in r["violations"]]
    assert any("bar check failed" in l for l in lines)
    assert any("out of range" in l for l in lines)
    assert any("voice totals differ" in l for l in lines)


def test_bars_window_and_measure():
    src = ly(soprano="c''2. | g'4 a'4 r4 |", bass="c'2. | c'4 d'4 r4 |")
    assert check.run(src=src, voices="soprano,bass", measure="3/4")["totals"]["parallels"] == 1
    assert check.run(src=src, voices="soprano,bass", measure="3/4", bars="1-1")["totals"]["parallels"] == 0
    r = check.run(src=src, voices="soprano,bass", measure="3/4")
    assert r["violations"][0]["pos"] == "2:1" and r["totals"]["errors"] == 0


def test_no_import_side_effects_and_helpers():
    assert parse_bars("3-7") == (3, 7) and parse_bars("5") == (5, 5) and parse_bars(None) is None
    assert parse_measure("4/4") == 1 and parse_measure("3/4") == parse_measure("6/8")


# ---- suspensions, strict, harmony ---------------------------------------------------------

def test_suspension_7_6():
    src = ly(soprano="c''1~ | c''2 b'2 |", bass="c'1 | d'1 |")
    r = suspensions.count(src=src, voices="soprano,bass")
    assert (r["strong"], r["weak"]) == (1, 0)
    assert r["items"][0]["kind"] == "7-6" and r["items"][0]["pos"] == "2:1"


def test_held_chord_tone_is_not_a_suspension():
    src = ly(soprano="c''1~ | c''2 b'2 |", bass="c'1 | a1 |")  # C5 over A3 is consonant
    assert suspensions.count(src=src, voices="soprano,bass")["strong"] == 0


def test_strict_clash_and_acc2():
    src = ly(soprano="g'4 r2. |", bass="ges4 r2. |")
    r = strict.run(src=src, voices="soprano,bass")
    assert r["clash"] == 1
    src = ly(soprano="d''2 c''2 |", bass="c'2 c'2 |")  # D5/C4 struck together on beat 1
    assert strict.run(src=src, voices="soprano,bass")["acc2"] == 1


def test_harmony_key_syntax_and_roman():
    assert harmony.parse_key("bes") == [(None, None, "B-", "minor")]
    assert harmony.parse_key("bes minor") == [(None, None, "B-", "minor")]
    assert harmony.parse_key("1-20=bb,21-30=F") == [(1, 20, "Bb", "minor"), (21, 30, "F", "major")]
    with pytest.raises(ValueError):
        harmony.parse_key("x")
    src = ly(soprano="g'1 |", alto="e'1 |", bass="c1 |")
    r = harmony.analyse(src=src, voices="soprano,alto,bass", key="C")
    assert r["attacks"][0]["roman"] == "I" and r["attacks"][0]["pos"] == "1:1"


# ---- splice ---------------------------------------------------------------------------------

def test_splice_bar_helpers():
    sc = splice.read_bars(ly(soprano="c'1 | R1*2 | d'1 |"), "soprano")
    assert sc["soprano"] == ["c'1", "r1", "r1", "d'1"]
    out = splice.splice_bars(sc, {"soprano": ["e'1"]}, 2)
    assert out["soprano"] == ["c'1", "e'1", "r1", "d'1"]
    assert splice.section_bars("% bars 13-19\n") == (13, 19)


# ---- fixture: The Neighbour -----------------------------------------------------------------

@needs_fixture
def test_fixture_check_and_suspensions():
    score = NEIGHBOUR / "score/music-voices.ly"
    cfg_ranges = {"soprano": [60, 84], "alto": [53, 77], "tenor": [48, 72], "bass": [36, 62]}
    r = check.run(score, ranges=cfg_ranges)
    t = r["totals"]
    assert (t["errors"], t["parallels"], t["beat_parallels"], t["unjustified"]) == (0, 0, 0, 0)
    assert r["violations"] == [] and len(r["lines"]) == 323
    s = suspensions.count(score)
    assert (s["strong"], s["weak"]) == (18, 13)
    st = strict.run(score)
    assert (st["clash"], st["xrel"], st["acc"], st["acc2"]) == (0, 7, 7, 31)


@needs_fixture
def test_fixture_splice_pass_and_lock_failure(tmp_path):
    lab = NEIGHBOUR / "design/final-lab"
    sec = NEIGHBOUR / "score/sections/sec01_expo.ly"
    r = splice.check_section(str(sec), str(lab / "SK_final.ly"), str(lab / "plan.json"))
    assert r["pass"] and r["bars"] == [1, 12] and r["checked"] == "1-13"
    # change the subject's first note (locked): the splice must fail on LOCK
    bad = tmp_path / "sec01_bad.ly"
    bad.write_text(sec.read_text().replace("bes'2. bes'8 a'8", "c''2. bes'8 a'8", 1))
    r = splice.check_section(str(bad), str(lab / "SK_final.ly"), str(lab / "plan.json"))
    assert not r["pass"] and "LOCK" in {f["kind"] for f in r["failures"]}


# ---- commands --------------------------------------------------------------------------------

def _ns(**kw):
    base = dict(score=None, section=None, voices=None, bars=None, measure=None, range=None, full=False)
    return argparse.Namespace(**{**base, **kw})


def test_command_check_exit_5_on_violation(tmp_path):
    from kapell.commands import check as cmd
    f = tmp_path / "par.ly"
    f.write_text(ly(soprano="g'4 a'4 r2 |", bass="c'4 d'4 r2 |"))
    out = cmd.run(_ns(score=str(f), voices="soprano,bass"), Context())
    assert isinstance(out, Result) and out.status == "fail"
    assert out.data["totals"]["parallels"] == 1 and len(out.data["violations"]) == 1
    with pytest.raises(KapellError) as e:
        cmd.run(_ns(), Context())
    assert e.value.exit_code == 3


@needs_fixture
def test_command_check_and_splice_on_fixture():
    from kapell import project
    from kapell.commands import check as cmd, splice as scmd
    ctx = Context(root=NEIGHBOUR, cfg=project.load(NEIGHBOUR))
    out = cmd.run(_ns(), ctx)
    assert isinstance(out, dict) and out["violations"] == [] and out["totals"]["unjustified"] == 0
    assert "dissonance_lines" not in out
    full = cmd.run(_ns(full=True), ctx)
    assert len(full["dissonance_lines"]) == 299 and len(full["review"]) == 23
    sec = scmd.run(argparse.Namespace(section="4", base=None, skeleton=None, plan=None, voices=None, full=False), ctx)
    assert isinstance(sec, dict) and sec["pass"] and sec["bars"] == [30, 34]
