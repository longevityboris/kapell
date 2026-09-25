"""kapell doctor: is this machine ready to engrave, render and call Jev? (C section 3)

Checks lilypond, sfizz_render at <lib>/bin, the sample libraries and IRs each engine reads,
audio encoders, the Jev key's presence in akm (names only: the value is never read), the
Python dependencies, and command modules that failed to load. Reports; never fails the shell:
status is partial_success when something is missing, and exit is 0.
"""
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess

from .. import config

SPEC = {
    "name": "doctor",
    "effect": "read",
    "help": "check lilypond, sfizz_render, sample libraries, IRs, Jev key, Python deps, command modules",
    "runtime_s": 2.5,
    "output_tokens_typ": 200,
    "examples": [["doctor"], ["doctor", "--full"]],
}

PY_DEPS = ("numpy", "scipy", "mido", "soundfile", "music21")
JEV_KEY = "TYPESAFE_API_KEY"

# (check name, path relative to lib_dir(), what needs it)
LIBRARIES = [
    ("lib.piano.salamander", "SalamanderGrandPiano", "render --version piano"),
    ("lib.organ.norrfjarden", "Organ/NorrfjardenChurch", "render --version organ"),
    ("lib.strings.iowa_quartet", "IowaMIS/quartet", "render --version quartet|ensemble"),
    ("lib.orchestra.built", "Orchestra/built", "render --version orchestra|ensemble"),
    ("lib.orchestra.vsco2", "Orchestra/VSCO-2-CE", "setup --engine orchestra"),
    ("lib.orchestra.vpo3", "VPO3/Virtual-Playing-Orchestra3", "setup --engine orchestra"),
    ("ir.detmold", "IR/Detmold-Konzerthaus-S1R163-MS-48k.wav", "render --version quartet|orchestra|ensemble"),
    ("ir.st_albans", "IR/OpenAIR/lady_chapel_st_albans_cathedral__stereo__stalbans_a_ortf.wav",
     "render --version organ|piano"),
]


def add_arguments(parser):
    parser.add_argument("--full", action="store_true", help="every check with its detail, not just the failures")


def _check(name, ok, detail="", needed_for="", required=True):
    return {"name": name, "ok": bool(ok), "detail": detail, "needed_for": needed_for, "required": required}


def _tool_version(exe: str, args=("--version",)) -> str:
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=15)
        line = (p.stdout or p.stderr).strip().splitlines()
        return line[0][:80] if line else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def check_lilypond():
    exe = shutil.which("lilypond")
    if not exe:
        return _check("lilypond", False, "not on PATH (brew install lilypond)", "engrave")
    return _check("lilypond", True, _tool_version(exe) or exe, "engrave")


def check_sfizz(lib):
    exe = lib / "bin" / "sfizz_render"
    ok = exe.is_file() and os.access(exe, os.X_OK)
    return _check("sfizz_render", ok, str(exe) if ok else f"missing or not executable: {exe} (kapell setup)",
                  "render --version piano|organ|quartet|orchestra|ensemble")


def check_encoders():
    out = []
    for exe, need, req in (("ffmpeg", "render (m4a, mixing)", True), ("ffprobe", "qa", False),
                           ("afconvert", "render (m4a on macOS)", False)):
        path = shutil.which(exe)
        out.append(_check(exe, path, path or "not on PATH", need, req))
    return out


def check_jev_key():
    """Presence only: `akm list --json` returns key names; the value is never requested."""
    akm = shutil.which("akm")
    if not akm:
        return _check("jev.key", False, "akm not on PATH", "jev", required=False)
    try:
        p = subprocess.run([akm, "list", "--json"], capture_output=True, text=True, timeout=10)
        names = json.loads(p.stdout).get("data", {}).get("keys", [])
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError) as exc:
        return _check("jev.key", False, f"akm list failed: {type(exc).__name__}", "jev", required=False)
    present = JEV_KEY in names
    return _check("jev.key", present,
                  f"{JEV_KEY} {'present' if present else 'absent'} in akm", "jev", required=False)


def check_python():
    out = []
    for mod in PY_DEPS:
        found = importlib.util.find_spec(mod) is not None
        ver = ""
        if found:
            try:
                ver = importlib.metadata.version(mod)
            except importlib.metadata.PackageNotFoundError:
                ver = "installed"
        out.append(_check(f"py.{mod}", found, ver or "not installed", "analysis, perform, render"))
    return out


def check_commands(ctx):
    found = getattr(ctx, "discovered", None)
    if found is None:
        from ..manifest import discover
        found = discover()
    out = []
    for d in found:
        if d.error:
            out.append(_check(f"cmd.{d.name}", False, f"{d.module_name}: {d.error}", d.name))
        elif d.warnings:
            out.append(_check(f"cmd.{d.name}", True, "; ".join(d.warnings), d.name, required=False))
    loaded = [d.name for d in found if not d.error]
    out.append(_check("commands", True, f"{len(loaded)} loaded: {', '.join(loaded)}", "", required=False))
    return out


def run(args, ctx):
    lib = config.lib_dir()
    checks = [check_lilypond(), check_sfizz(lib)]
    for name, rel, need in LIBRARIES:
        p = lib / rel
        checks.append(_check(name, p.exists(), str(p) if p.exists() else f"missing: {p}", need))
    checks += check_encoders()
    checks.append(check_jev_key())
    checks += check_python()
    checks += check_commands(ctx)

    failed = [c for c in checks if not c["ok"] and c["required"]]
    warned = [c for c in checks if not c["ok"] and not c["required"]]
    data = {
        "ok": not failed,
        "lib_dir": str(lib),
        "renders_dir": str(config.renders_dir()),
        "passed": sum(c["ok"] for c in checks),
        "failed": {c["name"]: f"{c['detail']} (needed for: {c['needed_for']})" for c in failed},
        "warnings": {c["name"]: c["detail"] for c in warned},
    }
    if getattr(args, "full", False):
        data["checks"] = checks
    else:
        data["hint"] = "--full lists every check"
    if failed:
        from . import Result
        return Result("partial_success", data)
    return data
