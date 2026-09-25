"""Regressions from the phase-1 command and package audit."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from kapell import cli
from kapell.analysis import parse_bars, parse_measure
from kapell.commands import Context, KapellError, Result


def call(*args):
    out, err = io.StringIO(), io.StringIO()
    rc = cli.main(list(args), stdout=out, stderr=err)
    return rc, json.loads(out.getvalue()), err.getvalue()


@pytest.mark.parametrize("bars", ["0", "8-1", "-1", "1-2-3", (3, 2)])
def test_reject_invalid_bar_ranges(bars):
    with pytest.raises(ValueError):
        parse_bars(bars)


@pytest.mark.parametrize("measure", ["0", "-3/4", "4/0"])
def test_reject_invalid_meters(measure):
    with pytest.raises(ValueError):
        parse_measure(measure)


def test_check_full_keeps_all_violations(monkeypatch, tmp_path):
    from kapell.analysis import check
    p = tmp_path / "score.ly"
    p.write_text("")
    rows = [{"line": f"ERR {i}"} for i in range(60)]
    monkeypatch.setattr(check, "run", lambda *a, **k: dict(totals={"errors": 60}, violations=rows,
                                                        review=[], dissonances=[]))
    rc, env, _ = call("check", str(p), "--full")
    assert rc == 5 and len(env["data"]["violations"]) == 60
    rc, env, _ = call("check", str(p))
    assert len(env["data"]["violations"]) == 40 and env["data"]["violations_truncated"] == 20


def test_xray_full_keeps_all_findings(monkeypatch, tmp_path):
    from kapell.analysis import check, strict, quotas, resolution
    rows = [{"line": f"ERR {i}"} for i in range(30)]
    totals = dict(errors=30, parallels=0, beat_parallels=0, unjustified=0, crossings=0, directs=0, melodic=0)
    monkeypatch.setattr(check, "run", lambda *a, **k: dict(totals=totals, violations=rows, review=[]))
    monkeypatch.setattr(strict, "run", lambda *a, **k: dict(clash=30, xrel=0, acc=0, acc2=0,
                       items=[dict(kind="CLASH", line=f"CLASH {i}") for i in range(30)]))
    monkeypatch.setattr(quotas, "suspensions", lambda *a, **k: dict(strong=0, weak=0))
    monkeypatch.setattr(resolution, "check", lambda *a, **k: [dict(code="DIS7", at=str(i), message="unresolved") for i in range(30)])
    p = tmp_path / "score.ly"
    p.write_text("")
    from kapell.commands import xray
    args = argparse.Namespace(score=str(p), section=None, bars=None, voices=None, measure=None, full=True)
    result = xray.run(args, Context())
    assert result.status == "fail" and len(result.data["violations"]) == 90
    args.full = False
    result = xray.run(args, Context())
    assert result.data["check"]["violations"] == 30
    assert len(result.data["violations"]) == 24
    assert result.data["violations_truncated"] == 66


def test_xray_section_and_bad_ranges(neighbour):
    rc, env, err = call("--project", str(neighbour), "xray", "--section", "7")
    assert rc == 5 and not err
    assert env["data"]["bars"] == "54-66" and "spliced into" in env["data"]["file"]
    for command in ("check", "xray"):
        rc, env, err = call("--project", str(neighbour), command, "--bars", "8-1")
        assert rc == 3 and env["error"]["code"] == "bad_input" and not err


def test_perform_flags_missing_cues(neighbour, tmp_path, monkeypatch):
    monkeypatch.setenv("KAPELL_RENDERS", str(tmp_path))
    rc, env, err = call("--project", str(neighbour), "perform", "--version", "beethoven_piano")
    assert rc == 5 and not err and env["data"]["notes"] == 741
    violations = env["data"]["violations"]
    assert all(v["version"] == "beethoven_piano" for v in violations)
    assert any("lament" in v["label"] for v in violations)
    assert Path(env["data"]["midi"]).is_relative_to(tmp_path)


def test_imports_are_quiet_and_do_not_write_or_change_sys_path(tmp_path):
    src = Path(__file__).resolve().parents[2] / "src"
    script = r'''
import importlib, pathlib, sys, os
root = pathlib.Path(sys.argv[1])

def audit(event, args):
    if event in ('subprocess.Popen', 'os.chdir', 'os.mkdir', 'os.remove', 'os.rename', 'socket.connect'):
        raise AssertionError((event, args))
    if event == 'open':
        path, mode, flags = args
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError(('file write on import', path))
sys.addaudithook(audit)
for p in sorted((root / 'kapell').rglob('*.py')):
    name = '.'.join(p.relative_to(root).with_suffix('').parts).removesuffix('.__init__')
    before = sys.path[:]
    importlib.import_module(name)
    assert sys.path == before, name
'''
    p = subprocess.run([sys.executable, "-B", "-c", script, str(src)], cwd=tmp_path,
                       env=dict(os.environ, PYTHONPATH=str(src)), capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert not p.stdout and not p.stderr


def test_encoder_falls_back_after_afconvert_failure(tmp_path, monkeypatch):
    from kapell.engines import encoding
    monkeypatch.setattr(encoding.shutil, "which", lambda name: name)
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd[0])
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"aac")
        return subprocess.CompletedProcess(cmd, 1 if cmd[0] == "afconvert" else 0, "", "no codec")
    monkeypatch.setattr(encoding.subprocess, "run", run)
    encoding.encode_aac(tmp_path / "a.wav", tmp_path / "a.m4a")
    assert commands == ["afconvert", "ffmpeg"]


def test_missing_encoder_is_environment_error(tmp_path, monkeypatch):
    from kapell.engines import encoding
    monkeypatch.setattr(encoding.shutil, "which", lambda name: None)
    with pytest.raises(KapellError) as err:
        encoding.encode_aac(tmp_path / "a.wav", tmp_path / "a.m4a")
    assert err.value.exit_code == 2


def test_stale_engine_assets_are_environment_error(tmp_path):
    from kapell.engines.pipeline import Steps
    with pytest.raises(KapellError) as err:
        Steps(tmp_path / "render.log").run("render", [sys.executable, "-c",
            "raise SystemExit('different make_sfz.py -- run ./setup_piano.sh')"])
    assert err.value.exit_code == 2


def test_permission_failure_is_environment_error(monkeypatch):
    from kapell.commands import version
    def denied(*args):
        raise PermissionError("read-only output")
    monkeypatch.setattr(version, "run", denied)
    rc, env, err = call("version")
    assert rc == 2 and env["error"]["code"] == "environment" and not err


def test_no_hardcoded_user_paths():
    src = Path(__file__).resolve().parents[2] / "src"
    for p in src.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".sh", ".md"):
            assert "/Users/" not in p.read_text(), p


def test_stretto_does_not_replace_required_inversion():
    from kapell.analysis.coverage import form_check
    def occurrence(theme, voice, level, start):
        return dict(theme=theme, voice=voice, level=level, start=str(level), form="prime",
                    scale="1", at="1:1", _t0=start, _t1=start + 4)
    occurrences = [occurrence("S1", "bass", 48, 0), occurrence("S2", "alto", 60, 0),
                   occurrence("S2", "soprano", 67, 1)]
    assert form_check(occurrences, "double-fugue", ["S1", "S2"])[0]["missing"] == ["inversion"]


def test_quiet_guide_suppresses_raw_markdown(tmp_path, monkeypatch):
    (tmp_path / "test.md").write_text("# Test guide")
    monkeypatch.setenv("KAPELL_GUIDES", str(tmp_path))
    out = io.StringIO()
    assert cli.main(["guide", "test", "--quiet"], stdout=out) == 0
    assert out.getvalue() == ""
