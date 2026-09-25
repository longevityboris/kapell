"""Routing, safe fallbacks, and real LilyPond integration for additional layouts."""
import json
import re
import shutil
import subprocess
from fractions import Fraction as F
from types import SimpleNamespace

import pytest

from kapell.commands import Context, KapellError
from kapell.commands import engrave
from kapell.piece.engrave import (music_line, prepare_layout, read_voices,
                                  registration_music, route_notes)
from kapell.project import load


MUSIC = "\n".join(f"{v} = \\absolute {{\n c'2~ c'2 | d'1 |\n}}" for v in
                  ("soprano", "alto", "tenor", "bass"))


def test_route_handoff_keeps_tied_note_with_first_player():
    voices = read_voices(MUSIC, F(1))
    assignments = [
        {"voice": "soprano", "part": "vn1", "at": "1:1", "until": "1:3"},
        {"voice": "soprano", "part": "ob", "at": "1:3", "until": "end"},
    ]
    assert route_notes(voices, assignments, {"vn1"}, F(1), F(2)) == [(0, 1, "c'")]
    assert route_notes(voices, assignments, {"ob"}, F(1), F(2)) == [(1, 2, "d'")]


def test_octaves_and_family_doublings():
    voices = read_voices(MUSIC, F(1))
    assignments = [{"voice": "bass", "part": "vc"},
                   {"voice": "bass", "part": "cb", "octave": -12}]
    sounding = route_notes(voices, assignments, {"vc", "cb"}, F(1), F(2))
    assert set(p for _, _, p in sounding) == {"c'", "c", "d'", "d"}
    collapsed = route_notes(voices, assignments, {"vc", "cb"}, F(1), F(2), octaves=False)
    assert len(collapsed) == 2


def test_music_line_rests_barlines_and_individual_chord_ties():
    line = music_line([(F(1), F(5, 2), "c"), (F(1), F(2), "g")], F(3), F(1))
    assert line == "\\absolute { R1*1/1 |\n <c~ g>1 |\n c2 r2 |\n }"


def test_reader_refuses_syntax_it_cannot_route():
    with pytest.raises(ValueError, match="plain absolute"):
        read_voices(MUSIC.replace("c'2~ c'2", "\\tuplet 3/2 { c'4 d'4 e'4 }"), F(1))


def test_registration_positions_include_fractional_beats():
    spec = {"groups": {"organ": {"options": {"registration": {
        "changes": [{"at": "1:1", "HW": "principal8"}, {"at": "3:1.5", "POS": "flute8"}],
        "manual_changes": [{"at": "3:2", "voice": "tenor", "division": "HW"}],
    }}}}}
    result = registration_music(spec, F(1))
    assert '"1:1  HW: principal8"' in result
    assert '"3:1.5  POS: flute8"' in result
    assert '"3:2  tenor -> HW"' in result
    assert "s1*1/1 s1*1/1" in result  # skip bar 2, annotate bar 3


@pytest.mark.parametrize("layout", ["organ", "ensemble", "orchestra"])
def test_missing_spec_fallback_and_escaped_titles(tmp_path, layout):
    cfg = {"piece": {"name": 'A "quoted" \\ title', "subtitle": "Ricercar, for piano"}}
    template = (engrave.TEMPLATES / f"{layout}.ly").read_text()
    source, notes = prepare_layout(tmp_path, cfg, layout, template)
    assert 'title = "A \\"quoted\\" \\\\ title"' in source
    assert "Ricercar, for piano, for" not in source
    assert not re.search(r"@[A-Z]+@", source)
    assert any("spec unavailable" in n for n in notes)
    if layout != "organ":
        assert "Unfiltered study score" in source
        assert any("all four voices printed" in n for n in notes)


def test_project_layout_overrides_template(tmp_path):
    (tmp_path / "score").mkdir()
    custom = tmp_path / "score/organ.ly"
    custom.write_text("project layout")
    assert engrave.sources(tmp_path, {})["organ"] == ("project", custom)
    assert engrave.sources(tmp_path, {})["orchestra"][0] == "template"
    assert engrave.sources(tmp_path, {})["ensemble"][0] == "template"


def test_stale_pdf_does_not_count_as_success(tmp_path, monkeypatch):
    score = tmp_path / "score"
    score.mkdir()
    (score / "piano.ly").write_text("bad score")
    out = tmp_path / "out"
    out.mkdir()
    (out / "piano.pdf").write_bytes(b"stale PDF")
    monkeypatch.setattr(engrave.shutil, "which", lambda _: "lilypond")
    monkeypatch.setattr(engrave.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    with pytest.raises(KapellError, match="lilypond failed"):
        engrave.run(SimpleNamespace(out=str(out), layout="piano"), Context(root=tmp_path, cfg={}))
    assert (out / "piano.pdf").read_bytes() == b"stale PDF"


def test_fixture_ensemble_assignments(neighbour):
    cfg = load(neighbour)
    spec = json.loads((neighbour / "performance/quintet/ricercar_quintet.json").read_text())
    voices = read_voices((neighbour / "score/music-voices.ly").read_text(), F(1))
    piano = route_notes(voices, spec["assignments"], {"soprano", "alto", "tenor", "bass", "soprano_8va", "bass_8vb"}, F(1), F(66))
    assert min(a for a, _, _ in piano) == 34  # first piano attack: bar 35
    vn1 = route_notes(voices, spec["assignments"], {"vn1"}, F(1), F(66))
    assert not any(34 <= a < 45 for a, _, _ in vn1)
    viola = route_notes(voices, spec["assignments"], {"va"}, F(1), F(66))
    assert min(a for a, _, _ in viola) == F(35, 4)  # alto handoff: 9:4
    source, notes = prepare_layout(neighbour, cfg, "ensemble", (engrave.TEMPLATES / "ensemble.ly").read_text())
    assert "Unfiltered" not in source
    assert not any("fallback" in n for n in notes)


def test_fixture_orchestra_family_handoff(neighbour):
    spec = json.loads((neighbour / "performance/symphonic/symphonic.json").read_text())
    voices = read_voices((neighbour / "score/music-voices.ly").read_text(), F(1))
    soprano = [a for a in spec["assignments"] if a["voice"] == "soprano"]
    strings = route_notes(voices, soprano, {"vn1"}, F(1), F(66), octaves=False)
    winds = route_notes(voices, soprano, {"ob"}, F(1), F(66), octaves=False)
    assert (F(19, 4), F(5), "c''") in winds  # oboe takes CS1 at 5:4
    assert not any(F(19, 4) <= a < 9 for a, _, _ in strings)


@pytest.mark.skipif(not shutil.which("lilypond"), reason="LilyPond unavailable")
@pytest.mark.parametrize("layout", ["organ", "ensemble", "orchestra"])
def test_fallback_layout_compiles(neighbour, tmp_path, layout):
    shutil.copytree(neighbour / "score", tmp_path / "score", ignore=shutil.ignore_patterns("out"))
    data = engrave.run(SimpleNamespace(out=str(tmp_path / "out"), layout=layout), Context(root=tmp_path, cfg=load(neighbour)))
    result = data["printed"][layout]
    assert result["pages"] > 0
    assert any("spec unavailable" in n for n in result["notes"])
    assert not result["warnings"]


@pytest.mark.skipif(not shutil.which("lilypond"), reason="LilyPond unavailable")
def test_all_layouts_compile_without_errors(neighbour, tmp_path):
    data = engrave.run(SimpleNamespace(out=str(tmp_path), layout="all"), Context(root=neighbour, cfg=load(neighbour)))
    assert set(data["printed"]) == set(engrave.LAYOUTS)
    for name, result in data["printed"].items():
        assert result["pages"] > 0
        assert (tmp_path / f"{name}.pdf").read_bytes().startswith(b"%PDF")
        assert "error:" not in (tmp_path / f"{name}.log").read_text().lower()
        assert not result["warnings"]
        assert not any("fallback" in n for n in result["notes"])
        if shutil.which("pdfinfo"):
            info = subprocess.run(["pdfinfo", str(tmp_path / f"{name}.pdf")], capture_output=True, text=True, check=True).stdout
            assert result["pages"] == int(re.search(r"Pages:\s+(\d+)", info)[1])
        if name in ("organ", "ensemble", "orchestra") and shutil.which("pdftotext"):
            text = subprocess.run(["pdftotext", str(tmp_path / f"{name}.pdf"), "-"], capture_output=True, text=True, check=True).stdout
            assert "The Neighbour" in text
            assert "Ricercar a 4 on the Theme from Jurassic Park, for" in text
