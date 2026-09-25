"""Engines lane: the moved engines, perform/render/engrave/setup.

Fast tests always run. Audio renders (8-bar smoke on The Neighbour) are opt-in:
KAPELL_ENGINE_TESTS=1 pytest tests/engines. They write to a temporary KAPELL_RENDERS and play
nothing.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import mido
import pytest

from conftest import KIT_SRC, run_kit, kit_env

KAPELL = KIT_SRC / "kapell"
ENGINE_TREES = [KAPELL / "engines", KAPELL / "perform", KAPELL / "mix"]
engines_opt_in = pytest.mark.skipif(os.environ.get("KAPELL_ENGINE_TESTS") != "1",
                                    reason="audio renders are opt-in: KAPELL_ENGINE_TESTS=1")


def _code_files():
    for tree in ENGINE_TREES:
        for f in tree.rglob("*"):
            if f.suffix in (".py", ".sh") and "__pycache__" not in f.parts:
                yield f


def test_no_hardcoded_machine_paths():
    bad = []
    for f in _code_files():
        for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            code = line.split("#", 1)[0] if f.suffix == ".sh" else line
            if re.search(r"/Users/|vendor/fugue-jp|RICERCAR\s*/|\"SAMPLE_LIBRARIES\", Path", code):
                bad.append(f"{f.relative_to(KIT_SRC)}:{i}: {line.strip()[:100]}")
    assert not bad, "hardcoded paths:\n" + "\n".join(bad)


def test_never_imports_vendor():
    for f in _code_files():
        assert "vendor" not in f.read_text(errors="replace").replace("vendored", ""), f


@pytest.mark.parametrize("module,attr", [("engines/organ/organ_paths.py", "LIB"), ("engines/piano/piano_paths.py", "LIB"),
                                         ("engines/strings/iowa_common.py", "LIB_ROOT"),
                                         ("engines/orchestra/orch_common.py", "LIB_ROOT")])
def test_library_paths_follow_kapell_lib(tmp_path, module, attr):
    """Run as the renderers run them (a script's own folder on sys.path, no PYTHONPATH)."""
    f = KAPELL / module
    code = (f"import sys; sys.path.insert(0, {str(f.parent)!r}); import importlib.util as u; "
            f"s = u.spec_from_file_location('m', {str(f)!r}); m = u.module_from_spec(s); sys.modules['m'] = m; "
            f"s.loader.exec_module(m); print(m.{attr})")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "KAPELL_LIB": str(tmp_path)}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd="/", timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip() == str(tmp_path)


@pytest.mark.parametrize("module", ["engines/organ/render_organ.py", "engines/piano/render_piano.py",
                                    "engines/strings/render_quartet.py", "engines/orchestra/render_orchestra.py",
                                    "perform/perform.py", "perform/articulate.py", "perform/levels.py",
                                    "perform/presence.py", "perform/bowing.py", "perform/swell.py",
                                    "mix/orchestrate.py", "mix/mix.py", "mix/qa_mix.py"])
def test_moved_modules_import_as_scripts(module):
    f = KAPELL / module
    code = (f"import sys; sys.path.insert(0, {str(f.parent)!r}); import importlib.util as u; "
            f"s = u.spec_from_file_location('m', {str(f)!r}); m = u.module_from_spec(s); sys.modules['m'] = m; "
            f"s.loader.exec_module(m)")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd="/", timeout=60)
    assert r.returncode == 0, r.stderr[-800:]


# ------------------------------------------------------------------------------ pipeline units
from kapell.commands import Context, KapellError  # noqa: E402
from kapell.engines import pipeline  # noqa: E402


def test_parse_bars():
    assert pipeline.parse_bars("1-8") == (1, 8)
    assert pipeline.parse_bars("12") == (12, 12)
    assert pipeline.parse_bars(None) is None
    for bad in ("0-3", "8-1", "a-b"):
        with pytest.raises(KapellError):
            pipeline.parse_bars(bad)


def _midi(path, notes, tpq=480):
    m = mido.MidiFile(type=1, ticks_per_beat=tpq)
    tt = mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=500000, time=0)])
    m.tracks.append(tt)
    tr = mido.MidiTrack([mido.MetaMessage("track_name", name="soprano", time=0)])
    ev = []
    for start, dur, key in notes:
        ev += [(start, 1, mido.Message("note_on", note=key, velocity=80)), (start + dur, 0, mido.Message("note_off", note=key))]
    ev += [(0, 2, mido.Message("control_change", control=64, value=127)),
           (40 * tpq, 2, mido.Message("control_change", control=64, value=0))]
    t = 0
    for at, _, msg in sorted(ev, key=lambda e: (e[0], e[1])):
        tr.append(msg.copy(time=at - t))
        t = at
    m.tracks.append(tr)
    m.save(str(path))


def test_crop_bars_keeps_time_positions(tmp_path):
    bar = 4 * 480
    src, dst = tmp_path / "a.mid", tmp_path / "b.mid"
    # one note per bar in bars 1..6, the bar-3 note humanised 5 ticks early
    notes = [(0, 400, 60), (bar, 400, 62), (2 * bar - 5, 400, 64), (3 * bar, 2 * bar, 65), (4 * bar, 400, 67), (5 * bar, 400, 69)]
    _midi(src, notes)
    res = pipeline.crop_bars(src, dst, (3, 4))
    assert res["notes_kept"] == 2
    m = mido.MidiFile(str(dst))
    t, ons = 0, []
    for msg in m.tracks[1]:
        t += msg.time
        if msg.type == "note_on" and msg.velocity:
            ons.append((t, msg.note))
    assert ons == [(2 * bar - 5, 64), (3 * bar, 65)]           # not shifted
    assert pipeline.note_counts(dst) == {"soprano": 2}
    # the pedal-up at bar 11 is past one bar after the last release (bar 6): dropped, so the render ends
    assert m.length < mido.MidiFile(str(src)).length


def test_seconds_at_tick():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.mid"
        _midi(p, [(0, 100, 60)])
        assert pipeline.seconds_at_tick(p, 960) == pytest.approx(1.0)   # 120 bpm, 2 beats


# ------------------------------------------------------------------------------ fixture: versions
@pytest.fixture()
def ctx(neighbour):
    from kapell import project
    return Context(root=neighbour, cfg=project.load(neighbour))


@pytest.mark.parametrize("kind,folder", [("organ", "bach_organ"), ("piano", "beethoven_piano"),
                                         ("quartet", "beethoven_quartet"), ("orchestra", "symphonic"),
                                         ("ensemble", "quintet")])
def test_version_kinds_resolve(ctx, kind, folder):
    v = pipeline.resolve_version(ctx.root, ctx.cfg, kind)
    assert v["name"] == folder and v["kind"] == kind
    assert pipeline.resolve_version(ctx.root, ctx.cfg, folder)["kind"] == kind


def test_unknown_version(ctx):
    with pytest.raises(KapellError) as e:
        pipeline.resolve_version(ctx.root, ctx.cfg, "harpsichord")
    assert e.value.code == "version_not_found"


def test_quartet_helper_args_from_legacy_render_sh(ctx, tmp_path):
    v = pipeline.resolve_version(ctx.root, ctx.cfg, "quartet")
    b = pipeline.helper_args(ctx.root, ctx.cfg, v, "bowing", tmp_path)
    assert b[:2] == ["--orchestration", str(tmp_path / "orchestration.json")]
    assert "30:1=2" in b and "--report" in b
    s = pipeline.helper_args(ctx.root, ctx.cfg, v, "swell", tmp_path)
    assert s[:2] == ["--extra", "0.75"] and "61:3-63:1" in s


def test_perform_organ_writes_outside_the_project(ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("KAPELL_RENDERS", str(tmp_path))
    from kapell.commands import perform
    d = perform.run(argparse.Namespace(version="organ"), ctx)
    assert d["version"] == "bach_organ" and d["notes"] == 741      # the fixture's full organ MIDI
    assert Path(d["midi"]).is_relative_to(tmp_path)


# ------------------------------------------------------------------------------ setup, engrave
def test_setup_refuses_install(ctx):
    from kapell.commands import setup
    with pytest.raises(KapellError) as e:
        setup.run(argparse.Namespace(engine="organ", check=False), ctx)
    assert e.value.exit_code == 2


def test_setup_check_reports_missing_library(ctx, monkeypatch, tmp_path):
    from kapell.commands import setup
    monkeypatch.setenv("KAPELL_LIB", str(tmp_path))
    with pytest.raises(KapellError) as e:
        setup.run(argparse.Namespace(engine="organ", check=True), ctx)
    assert e.value.code == "engine_not_ready" and e.value.exit_code == 2


def _strip_pdf_dates(b: bytes) -> bytes:
    b = re.sub(rb"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", b"", b)
    b = re.sub(rb"D:\d{14}[+-]\d\d'\d\d'", b"", b)
    b = re.sub(rb"/ID \[<[0-9A-F]+><[0-9A-F]+>\]", b"", b)
    return re.sub(rb"uuid:[0-9a-f-]+", b"", b)


@pytest.mark.skipif(not __import__("shutil").which("lilypond"), reason="lilypond not installed")
def test_engrave_all_matches_committed_pdfs(ctx, tmp_path):
    from kapell.commands import engrave
    d = engrave.run(argparse.Namespace(layout="all", out=str(tmp_path)), ctx)
    assert {"piano", "quartet", "organ"} <= set(d["printed"])
    for name in ("piano", "quartet"):
        committed = ctx.root / "score" / "out" / f"{name}.pdf"
        if committed.exists():
            assert _strip_pdf_dates((tmp_path / f"{name}.pdf").read_bytes()) == _strip_pdf_dates(committed.read_bytes())


# ------------------------------------------------------------------------------ opt-in audio
@engines_opt_in
@pytest.mark.parametrize("version", ["piano", "organ"])
def test_render_8_bars_note_count_matches_midi(neighbour, tmp_path, version):
    env = kit_env()
    env["KAPELL_RENDERS"] = str(tmp_path)
    cmd = [sys.executable, "-m", "kapell.cli", "--json", "render", "--version", version, "--bars", "1-8"]
    p = subprocess.run(cmd, cwd=neighbour, env=env, capture_output=True, text=True, timeout=900)
    envl = json.loads(p.stdout)
    assert envl["status"] == "success", envl
    d = envl["data"]
    assert d["notes_match"] and d["notes_midi"] == d["notes_rendered"] > 0
    assert Path(d["wav"]).is_file() and Path(d["wav"]).is_relative_to(tmp_path)
