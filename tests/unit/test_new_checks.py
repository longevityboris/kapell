"""Unit tests for the new checks on tiny fixtures: resolution (DIS7, LT), coverage (theme ledger and
form claim), roles (featured role without a cue), quotas, and the xray gate (exit 5)."""
import io
import json
from fractions import Fraction as F

import pytest

from kapell.analysis import coverage, quotas, resolution, roles

V4 = ["soprano", "alto", "tenor", "bass"]


def score(**voices):
    return "\n".join(f"{v} = \\absolute {{\n  {body}\n}}\n" for v, body in voices.items())


# ------------------------------------------------------------------ resolution

def G7(soprano_next):
    """G7 (G B D F, the F in the soprano) going to C major; the soprano's F goes to soprano_next."""
    return score(soprano=f"f'1 | {soprano_next}1 |", alto="b1 | c'1 |", tenor="d1 | e1 |", bass="g,1 | c,1 |")


def test_resolved_seventh_is_clean():
    assert resolution.check(G7("e'"), V4) == []


def test_unresolved_seventh_rising():
    out = resolution.check(G7("g'"), V4)
    assert [f["code"] for f in out] == ["DIS7"]
    f = out[0]
    assert (f["at"], f["voice"], f["note"], f["to"]) == ("1:1", "soprano", "F4", "G4")
    assert "G Mm7" in f["chord"]


def test_seventh_left_by_rest():
    src = score(soprano="f'1 | r1 |", alto="b1 | c'1 |", tenor="d1 | e1 |", bass="g,1 | c,1 |")
    out = resolution.check(src, V4)
    assert out and out[0]["code"] == "DIS7" and out[0]["to"] is None


def test_seventh_handed_off_resolves():
    # the soprano leaps away from F while the alto takes the E below it: resolution handed off
    src = score(soprano="f'1 | c''1 |", alto="b1 | e'1 |", tenor="d1 | g1 |", bass="g,1 | c,1 |")
    assert resolution.check(src, V4) == []


def test_leading_tone_in_top_voice_must_rise():
    src = score(soprano="b'1 | g'1 |", alto="f'1 | e'1 |", tenor="d'1 | c'1 |", bass="g,1 | c,1 |")
    codes = [f["code"] for f in resolution.check(src, V4)]
    assert codes == ["LT"]


def test_seventh_chord_recognition():
    from kapell.analysis.lyparse import parse_voice
    src = score(a="g,4 b,4 d4 f4 |")
    notes = parse_voice(src, "a")
    ch = resolution.seventh_chord(notes)
    assert ch is not None and ch[3] == "Mm7"
    assert resolution.seventh_chord(parse_voice(score(a="c4 e4 g4 |"), "a")) is None


# ------------------------------------------------------------------ coverage

MATS = score(sOne="bes'4 a'4 bes'4 c''4 | des''4 c''4 bes'4 f'4 |",
             sTwo="c''4 a'4 f'4 d''4 | bes'4 c''4 f''4 g''4 |")
THEMES = {"S1": "sOne", "S2": "sTwo"}


def test_theme_at_one_pitch_fails_double_fugue():
    src = score(soprano="c''4 a'4 f'4 d''4 | bes'4 c''4 f''4 g''4 | r1 | r1 | r1 | r1 |",
                alto="r1 | r1 | c''4 a'4 f'4 d''4 | bes'4 c''4 f''4 g''4 | r1 | r1 |",
                bass="r1 | r1 | bes,4 a,4 bes,4 c4 | des4 c4 bes,4 f,4 | r1 | r1 |")
    occ = coverage.ledger(src, THEMES, ["soprano", "alto", "bass"], F(1), MATS)
    s2 = [o for o in occ if o["theme"] == "S2"]
    assert [(o["voice"], o["at"]) for o in s2] == [("soprano", "1:1"), ("alto", "3:1")]
    viol = coverage.form_check(occ, "double-fugue", ["S1", "S2"])
    assert len(viol) == 1 and viol[0]["theme"] == "S2"
    assert "answer" in viol[0]["missing"] and "inversion_or_stretto" in viol[0]["missing"]
    assert "one pitch" in viol[0]["message"]


def test_developed_second_subject_passes():
    # S2 at pitch, answered a fifth lower (on f'), inverted, and combined with S1 in the bass
    src = score(soprano="c''4 a'4 f'4 d''4 | bes'4 c''4 f''4 g''4 | r1 | r1 | c''4 ees''4 g''4 bes'4 | d''4 c''4 g'4 f'4 |",
                alto="r1 | r1 | f'4 d'4 bes4 g'4 | ees'4 f'4 bes'4 c''4 | r1 | r1 |",
                bass="r1 | r1 | bes,4 a,4 bes,4 c4 | des4 c4 bes,4 f,4 | r1 | r1 |")
    occ = coverage.ledger(src, THEMES, ["soprano", "alto", "bass"], F(1), MATS)
    tr = coverage.treatment(occ, "S2", "S1")
    assert tr["answer"] and tr["inversion"] and tr["combination"]
    assert coverage.form_check(occ, "double-fugue", ["S1", "S2"]) == []


def test_augmentation_is_recognised():
    src = score(bass="bes,2 a,2 | bes,2 c2 | des2 c2 | bes,2 f,2 |")
    occ = coverage.ledger(src, {"S1": "sOne"}, ["bass"], F(1), MATS)
    assert [(o["form"], o["scale"]) for o in occ] == [("prime", "2")]


def test_positions():
    assert coverage.pos(F(53) + F(3, 4)) == "54:4"
    assert coverage.parse_pos("30:4.5") == F(29) + F(7, 8)


# ------------------------------------------------------------------ roles

def project(tmp_path, plan_roles=None, spec_assign=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "kapell.toml").write_text(
        '[piece]\nmeasure = "4/4"\nvoices = ["soprano", "alto", "tenor", "bass"]\n'
        '[paths]\nscore = "score.ly"\nperformance = "performance"\n'
        '[versions]\nrender = ["v"]\n[checks]\nfeatured_roles = []\n'
        '[[features]]\nlabel = "tenor lament"\nvoice = "tenor"\nat = "3:1"\nuntil = "5:1"\n')
    vd = tmp_path / "performance" / "v"
    vd.mkdir(parents=True)
    if plan_roles is not None:
        (vd / "plan.json").write_text(json.dumps({"voices": V4, "roles": plan_roles,
                                                  "role_boost": {"subject": 9, "cs": 2, "free": -4}}))
    if spec_assign is not None:
        (vd / "spec.json").write_text(json.dumps({"assignments": spec_assign}))
    from kapell import project as proj
    return proj.load(tmp_path)


def test_featured_role_without_cue_fails(tmp_path):
    cfg = project(tmp_path, plan_roles=[{"voice": "soprano", "at": "1:1", "until": "5:1", "role": "subject"}])
    r = roles.lint(tmp_path, cfg)
    assert not r["ok"] and len(r["violations"]) == 1
    assert "tenor lament" in r["violations"][0]["message"] and "no cue" in r["violations"][0]["message"]


def test_featured_role_with_cue_passes(tmp_path):
    cfg = project(tmp_path, plan_roles=[{"voice": "tenor", "at": "3:1", "until": "5:1", "role": "cs"}])
    assert roles.lint(tmp_path, cfg)["ok"]


def test_free_role_is_not_a_cue(tmp_path):
    cfg = project(tmp_path, plan_roles=[{"voice": "tenor", "at": "3:1", "until": "5:1", "role": "free"}])
    assert not roles.lint(tmp_path, cfg)["ok"]


def test_spec_blanket_assignment_is_not_a_cue(tmp_path):
    cfg = project(tmp_path, spec_assign=[{"voice": "tenor", "part": "va", "at": "1:1", "until": "9:1", "level": 1}])
    assert not roles.lint(tmp_path, cfg)["ok"]
    cfg = project(tmp_path / "b", spec_assign=[{"voice": "tenor", "part": "va", "at": "3:1", "until": "5:1", "level": 0.5}])
    assert roles.lint(tmp_path / "b", cfg)["ok"]


# ------------------------------------------------------------------ quotas

def test_quotas():
    r = quotas.evaluate({"strong_suspensions": 20, "max_dis7": 0, "unknown": 3},
                        {"strong_suspensions": 18, "dis7": 0})
    rows = {q["name"]: q for q in r["quotas"]}
    assert rows["strong_suspensions"]["status"] == "below" and not rows["strong_suspensions"]["ok"]
    assert rows["max_dis7"]["ok"] and rows["unknown"]["status"] == "not measured"
    assert not r["ok"] and [v["name"] for v in r["violations"]] == ["strong_suspensions"]
    assert quotas.evaluate({"strong_suspensions": 2}, {"strong_suspensions": 2})["ok"]


# ------------------------------------------------------------------ xray gate

def test_xray_exits_5_on_unresolved_seventh(tmp_path, monkeypatch):
    project(tmp_path, plan_roles=[{"voice": "tenor", "at": "3:1", "until": "5:1", "role": "cs"}])
    (tmp_path / "score.ly").write_text(G7("g'"))
    monkeypatch.chdir(tmp_path)
    from kapell import cli
    out = io.StringIO()
    rc = cli.main(["xray", "--json"], stdout=out, stderr=io.StringIO())
    env = json.loads(out.getvalue())
    assert rc == 5 and env["status"] == "fail"
    assert "resolution" in env["data"]["failed"] and "roles" not in env["data"]["failed"]
    assert any(isinstance(v, str) and v.startswith("DIS7 1:1") for v in env["data"]["violations"])


# ------------------------------------------------------------------ the fixture (skips without it)

def test_neighbour_known_gaps(neighbour):
    from kapell import project as proj
    cfg = proj.load(neighbour)
    res = resolution.run_project(neighbour, cfg)
    hits = [f for f in res["violations"] if f["code"] == "DIS7" and f["at"] == "54:1"]
    assert hits and hits[0]["note"] == "Eb2" and hits[0]["to"] == "Gb2"
    assert len(res["violations"]) <= 9, "resolution false positives crept up on the fixture (7 when tuned)"
    cov = coverage.run_project(neighbour, cfg)
    assert cov["themes"]["S2"]["levels"] == ["C5"] and cov["themes"]["S2"]["statements"] == 3
    assert [v["theme"] for v in cov["violations"]] == ["S2"]
    msgs = " | ".join(v["message"] for v in roles.lint(neighbour, cfg)["violations"])
    for version in ("bach_organ", "beethoven_piano", "beethoven_quartet"):
        assert f"{version}: tenor arioso tenor lament" in msgs and f"{version}: bass arioso bass head" in msgs
    assert "quintet:" not in msgs
