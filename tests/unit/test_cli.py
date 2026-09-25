"""CLI core: envelope, exit codes, discovery, agent-info schema, status/doctor/guide/version."""
import importlib
import io
import json
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

from kapell import __version__
from kapell import cli, envelope, manifest
from kapell.commands import version as version_cmd

SRC = Path(__file__).resolve().parents[2] / "src"

GOOD = '''
SPEC = {"name": "good", "effect": "read", "help": "returns a dict", "runtime_s": 0.1,
        "output_tokens_typ": 20, "examples": [["good", "x.ly"]]}
def add_arguments(p):
    p.add_argument("target", help="a score file")
    p.add_argument("--bars", help="A-B")
    p.add_argument("--full", action="store_true")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--version-name", dest="vname", choices=["organ", "piano"], required=False)
def run(args, ctx):
    return {"target": args.target, "full": args.full, "root": str(ctx.root) if ctx.root else None}
'''
FAILING = '''
from kapell.commands import Result
SPEC = {"name": "failing", "effect": "read", "help": "musical check fails", "runtime_s": 0.1,
        "output_tokens_typ": 20, "examples": [["failing"]]}
def add_arguments(p): pass
def run(args, ctx):
    return Result("fail", {"violations": [{"kind": "PAR!", "pos": "3:1"}]})
'''
BADINPUT = '''
from kapell.commands import KapellError
SPEC = {"name": "bad-input", "effect": "read", "help": "raises default KapellError", "runtime_s": 0.1,
        "output_tokens_typ": 20, "examples": [["bad-input"]]}
def add_arguments(p): pass
def run(args, ctx):
    raise KapellError("no_such_bar", "bar 99 does not exist", "use --bars 1-66")
'''
ENVERR = '''
from kapell.commands import KapellError
SPEC = {"name": "env-err", "effect": "execute", "help": "needs an engine", "runtime_s": 1,
        "output_tokens_typ": 20, "examples": [["env-err"]]}
def add_arguments(p): pass
def run(args, ctx):
    raise KapellError("engine_missing", "sfizz_render not built", "kapell doctor", 2)
'''
CRASH = '''
SPEC = {"name": "crash", "effect": "read", "help": "bug", "runtime_s": 0.1,
        "output_tokens_typ": 20, "examples": [["crash"]]}
def add_arguments(p): pass
def run(args, ctx):
    raise RuntimeError("boom")
'''
SUBVERBS = '''
SPEC = {"name": "find", "effect": "read", "help": "searches", "runtime_s": "1-60",
        "output_tokens_typ": 300, "examples": [["find", "cs", "--against", "S"]]}
def add_arguments(p):
    sub = p.add_subparsers(dest="what", required=True)
    cs = sub.add_parser("cs", help="countersubjects")
    cs.add_argument("--against", required=True)
def run(args, ctx):
    return {"what": args.what}
'''
BROKEN = 'import kapell_this_module_does_not_exist\nSPEC = {"name": "broken"}\n'
HELPER = 'def helper():\n    return 1\n'
DOCTOR = 'from kapell.commands.doctor import SPEC, add_arguments, run\n'


@pytest.fixture
def pkg(tmp_path, monkeypatch):
    """A throwaway commands package: good, failing, bad input, env error, crash, sub-verbs, broken, helper."""
    name = f"fakecmds_{uuid.uuid4().hex[:8]}"
    d = tmp_path / name
    d.mkdir()
    (d / "__init__.py").write_text("")
    files = {"good": GOOD, "failing": FAILING, "bad_input": BADINPUT, "env_err": ENVERR, "crash": CRASH,
             "find": SUBVERBS, "broken": BROKEN, "_private": GOOD.replace('"good"', '"private"'),
             "helper": HELPER, "doctor": DOCTOR}
    for f, src in files.items():
        (d / f"{f}.py").write_text(textwrap.dedent(src))
    monkeypatch.syspath_prepend(str(tmp_path))
    return importlib.import_module(name)


def call(argv, pkg=None, cwd=None, monkeypatch=None):
    out, err = io.StringIO(), io.StringIO()   # StringIO is not a TTY: JSON is automatic
    code = cli.main(argv, commands_pkg=pkg, stdout=out, stderr=err)
    text = out.getvalue()
    env = json.loads(text) if text.strip().startswith("{") else None
    return code, env, text, err.getvalue()


# ---- envelope ---------------------------------------------------------------------------------

def test_envelope_shapes():
    s = envelope.success({"a": 1})
    assert s == {"version": "1", "status": "success", "data": {"a": 1}}
    assert envelope.success(None, "no_results")["data"] == {}
    e = envelope.error("bad_input", "msg", "try this")
    assert e == {"version": "1", "status": "error", "error": {"code": "bad_input", "message": "msg", "suggestion": "try this"}}
    with pytest.raises(ValueError):
        envelope.success({}, "error")


def test_exit_for_statuses():
    assert [envelope.exit_for(s) for s in ("success", "no_results", "partial_success", "fail")] == [0, 0, 0, 5]
    assert set(envelope.EXIT_CODES) == {"0", "1", "2", "3", "4", "5"}


def test_human_output_when_tty():
    buf = io.StringIO()
    envelope.emit(envelope.success({"phase": "review", "open": ["sec01"]}), as_json=False, out=buf)
    assert "phase: review" in buf.getvalue() and "- sec01" in buf.getvalue()
    err = io.StringIO()
    envelope.emit(envelope.error("x", "broken", "fix it"), as_json=False, out=buf, err=err)
    assert "error [x]: broken" in err.getvalue() and "hint: fix it" in err.getvalue()


# ---- exit codes -------------------------------------------------------------------------------

def test_success_is_json_when_piped_exit_0(pkg):
    code, env, _, _ = call(["good", "score.ly"], pkg)
    assert code == 0 and env["status"] == "success" and env["data"]["target"] == "score.ly"


def test_musical_fail_exits_5_with_violations(pkg):
    code, env, _, _ = call(["failing"], pkg)
    assert code == 5 and env["status"] == "fail" and env["data"]["violations"]


def test_kapell_error_default_exit_3(pkg):
    code, env, _, _ = call(["bad-input"], pkg)
    assert code == 3
    assert env["status"] == "error" and env["error"] == {
        "code": "no_such_bar", "message": "bar 99 does not exist", "suggestion": "use --bars 1-66"}


def test_kapell_error_env_exit_2(pkg):
    code, env, _, _ = call(["env-err"], pkg)
    assert code == 2 and env["error"]["code"] == "engine_missing"


@pytest.mark.parametrize("argv", [["nosuchverb"], ["good"], ["good", "x.ly", "--n", "notint"],
                                  ["good", "x.ly", "--version-name", "harp"], ["find", "cs"]])
def test_argparse_errors_exit_3_not_2(pkg, argv):
    code, env, _, _ = call(argv, pkg)
    assert code == 3 and env["status"] == "error" and env["error"]["code"] == "bad_input"


def test_unexpected_exception_exit_1_with_envelope(pkg):
    code, env, _, err = call(["crash"], pkg)
    assert code == 1 and env["error"]["code"] == "internal" and "boom" in env["error"]["message"]
    assert "Traceback" in err


def test_broken_module_is_a_verb_that_exits_2(pkg):
    code, env, _, _ = call(["broken", "anything", "--x"], pkg)
    assert code == 2 and env["error"]["code"] == "command_unavailable"
    assert "kapell_this_module_does_not_exist" in env["error"]["message"]


def test_global_flags_anywhere_and_quiet(pkg):
    code, env, _, _ = call(["good", "x.ly", "--json"], pkg)
    assert code == 0 and env["data"]["target"] == "x.ly"
    code, env, text, _ = call(["--quiet", "good", "x.ly"], pkg)
    assert code == 0 and text == ""
    code, env, text, _ = call(["good", "x.ly", "--quiet"], pkg)
    assert code == 0 and text == ""
    code, env, _, _ = call(["failing", "--quiet"], pkg)          # quiet keeps the exit code
    assert code == 5
    code, env, _, _ = call(["bad-input", "-q"], pkg)             # errors still print
    assert code == 3 and env["status"] == "error"


def test_no_command_lists_verbs(pkg):
    code, env, _, _ = call([], pkg)
    assert code == 0 and "good" in env["data"]["commands"] and "agent-info" in env["data"]["commands"]


def test_help_exits_0(pkg, capsys):
    code, _, _, _ = call(["good", "--help"], pkg)
    assert code == 0


# ---- discovery --------------------------------------------------------------------------------

def test_discovery_skips_private_and_helpers_reports_broken(pkg):
    found = {d.name: d for d in manifest.discover(pkg)}
    assert {"good", "failing", "bad-input", "env-err", "crash", "find", "broken", "doctor"} <= set(found)
    assert "private" not in found and "helper" not in found
    assert found["broken"].module is None and "ModuleNotFoundError" in found["broken"].error
    assert found["good"].error is None and found["good"].spec["effect"] == "read"


def test_discovery_of_the_real_package():
    found = {d.name: d for d in manifest.discover()}
    for name in ("status", "doctor", "guide", "version"):
        assert name in found and found[name].error is None, found.get(name)


# ---- agent-info -------------------------------------------------------------------------------

REQUIRED = ("effect", "runtime_s", "output_tokens_typ", "examples", "args", "options")


def test_agent_info_schema(pkg):
    code, env, _, _ = call(["agent-info"], pkg)
    assert code == 0
    m = env["data"]
    assert m["name"] == "kapell" and m["version"] == __version__
    assert m["envelope"]["version"] == "1"
    assert m["exit_codes"]["5"].startswith("musical check failed")
    assert {o["name"] for o in m["global_options"]} == {"--json", "--quiet", "--project"}
    assert isinstance(m["breaking_changes"], dict)
    cmds = m["commands"]
    for name in ("good", "failing", "find", "agent-info"):
        for key in REQUIRED:
            assert key in cmds[name], (name, key)
        assert cmds[name]["effect"] in manifest.EFFECTS
    g = cmds["good"]
    assert g["args"] == [{"name": "target", "kind": "positional", "description": "a score file"}]
    opts = {o["name"]: o for o in g["options"]}
    assert opts["--full"]["type"] == "bool" and opts["--bars"]["type"] == "string"
    assert opts["--n"] == {"name": "--n", "type": "int", "default": 3}
    assert opts["--version-name"]["values"] == ["organ", "piano"]
    assert "--json" not in opts and "--help" not in opts
    assert cmds["find"]["subcommands"]["cs"]["options"][0] == {"name": "--against", "type": "string", "required": True}
    assert "unavailable" in cmds["broken"]


def test_agent_info_single_command(pkg):
    code, env, _, _ = call(["agent-info", "--command", "good"], pkg)
    assert code == 0 and env["data"]["command"] == "good" and env["data"]["effect"] == "read"
    code, env, _, _ = call(["agent-info", "--command", "nope"], pkg)
    assert code == 3 and env["error"]["code"] == "unknown_command"


def test_agent_info_real_package_every_spec_complete():
    code, env, _, _ = call(["agent-info"])
    assert code == 0
    for name, entry in env["data"]["commands"].items():
        if "unavailable" in entry:
            continue  # reported by doctor; the schema check is for loaded commands
        for key in REQUIRED:
            assert key in entry, (name, key)
        assert entry["effect"] in manifest.EFFECTS, name


# ---- commands ---------------------------------------------------------------------------------

def test_version_and_pin():
    assert version_cmd.pin_matches("0.1", "0.1.0") is True
    assert version_cmd.pin_matches("0.3", "0.1.0") is False
    assert version_cmd.pin_matches(None) is None
    code, env, _, _ = call(["version"])
    assert code == 0 and env["data"]["kit"] == __version__


def test_doctor_reports_missing_libs_and_broken_modules(pkg, tmp_path, monkeypatch):
    import kapell.commands.doctor as doc
    monkeypatch.setattr(doc, "check_lilypond", lambda: doc._check("lilypond", True, "stub", "engrave"))
    monkeypatch.setattr(doc, "check_jev_key", lambda: doc._check("jev.key", False, "stub", "jev", required=False))
    monkeypatch.setenv("KAPELL_LIB", str(tmp_path / "nolib"))
    code, env, _, _ = call(["doctor"], pkg)
    assert code == 0 and env["status"] == "partial_success" and env["data"]["ok"] is False
    failed = env["data"]["failed"]
    assert "sfizz_render" in failed and "lib.piano.salamander" in failed and "cmd.broken" in failed
    assert "jev.key" in env["data"]["warnings"] and "checks" not in env["data"]
    code, env, _, _ = call(["doctor", "--full"], pkg)
    assert any(c["name"] == "py.numpy" and c["ok"] for c in env["data"]["checks"])


def test_doctor_never_reads_the_key_value():
    src = (SRC / "kapell" / "commands" / "doctor.py").read_text()
    assert "akm\", \"get" not in src and "--raw" not in src and "\"run\"" not in src


def test_guide_list_raw_and_unknown(tmp_path, monkeypatch):
    g = tmp_path / "guides"
    g.mkdir()
    (g / "counterpoint.md").write_text("# Counterpoint\n\nPrepare, strike, resolve.\n")
    monkeypatch.setenv("KAPELL_GUIDES", str(g))
    code, env, _, _ = call(["guide"])
    assert code == 0 and env["data"]["guides"]["counterpoint"] == "Counterpoint"
    code, env, text, _ = call(["guide", "counterpoint", "--json"])
    assert code == 0 and env is None and text.startswith("# Counterpoint")
    code, env, _, _ = call(["guide", "nope"])
    assert code == 3 and env["error"]["code"] == "unknown_guide"


def test_status_outside_a_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KAPELL_PROJECT", raising=False)
    code, env, _, _ = call(["status"])
    assert code == 0 and env["status"] == "no_results" and env["data"]["phase"] == "none"


def test_status_degrades_on_a_bare_project(tmp_path):
    (tmp_path / "kapell.toml").write_text('[piece]\nname = "Bare"\n[quotas]\nstrong_suspensions = 4\n')
    code, env, _, _ = call(["--project", str(tmp_path), "status"])
    d = env["data"]
    assert code == 0 and d["phase"] == "materials" and d["last_check"] is None
    assert d["quotas"]["strong_suspensions"] == {"target": 4, "actual": None, "ok": None}
    assert any("[paths]" in w for w in d["warnings"])


def test_status_reports_invalid_toml(tmp_path):
    (tmp_path / "kapell.toml").write_text("bad = [\n")
    code, env, _, _ = call(["status", "--project", str(tmp_path)])
    assert code == 0 and any("unreadable" in w for w in env["data"]["warnings"])


def test_status_reads_sections_without_executing_piece_model(tmp_path):
    (tmp_path / "design").mkdir()
    (tmp_path / "score" / "sections").mkdir(parents=True)
    (tmp_path / "design" / "piece.py").write_text(
        "raise SystemExit('must not run')\n"
        "SECTIONS = [dict(id='sec01_a', title='A', bars=4), dict(id='sec02_b', title='B', bars=6)]\n")
    (tmp_path / "design" / "SK.ly").write_text("")
    (tmp_path / "score" / "sections" / "sec01_a.ly").write_text("")
    (tmp_path / "kapell.toml").write_text(
        '[paths]\npiece_model = "design/piece.py"\nsections = "score/sections"\nskeleton = "design/SK.ly"\n'
        'score = "score/music-voices.ly"\n')
    code, env, _, _ = call(["status", "--project", str(tmp_path)])
    s = env["data"]["sections"]
    assert (s["total"], s["done"], s["open"], s["bars"]) == (2, 1, ["sec02_b"], 10)
    assert env["data"]["phase"] == "compose" and "sec02_b" in env["data"]["next"]["command"]


def test_status_under_2k_tokens_on_fixture():
    fixture = Path("/Users/biobook/Music/llm-music/fugue-jp/ricercar")
    if not (fixture / "kapell.toml").is_file():
        pytest.skip("fixture missing")
    code, env, text, _ = call(["status", "--project", str(fixture)])
    assert code == 0 and len(text) / 4 < 2000
    d = env["data"]
    assert d["sections"]["total"] == 7 and d["sections"]["open"] == []
    assert "organ" in d["layouts"]["missing"]


def test_python_dash_m_kapell():
    p = subprocess.run([sys.executable, "-m", "kapell", "version"], capture_output=True, text=True,
                       env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"}, timeout=60)
    assert p.returncode == 0 and json.loads(p.stdout)["data"]["kit"] == __version__
