"""kapell setup: verify (and, in a later phase, install) an engine's sample libraries and tools.

This phase only verifies: `--check` is required, and nothing is downloaded or built. Piano,
strings and orchestra run their own setup_*.sh --check (SHA-256 / manifest pins, the pinned
sfizz_render build). setup_organ.sh has no check mode, so the organ is checked here: the
Norrfjärden sample set and its ODF, the church IR, the measured pipe model and wvunpack.
"""
import os
import re
import shutil
import subprocess
import time

from kapell.commands import KapellError
from kapell.config import lib_dir
from kapell.engines import ENGINES

SPEC = {
    "name": "setup",
    "effect": "execute",
    "help": "verify an engine's libraries and tools under lib_dir() (--check; no downloads in this phase)",
    "runtime_s": 6,
    "output_tokens_typ": 120,
    "examples": [["setup", "--engine", "all", "--check"], ["setup", "--engine", "organ", "--check"]],
}
ENGINE_NAMES = ("piano", "organ", "strings", "orchestra")
SCRIPTS = {"piano": ENGINES / "piano" / "setup_piano.sh", "strings": ENGINES / "strings" / "setup_strings.sh",
           "orchestra": ENGINES / "orchestra" / "setup_orchestra.sh", "organ": ENGINES / "organ" / "setup_organ.sh"}


def add_arguments(p):
    p.add_argument("--engine", required=True, choices=ENGINE_NAMES + ("all",))
    p.add_argument("--check", action="store_true", help="verify only (required in this phase)")


def check_organ() -> dict:
    lib = lib_dir()
    set_dir = lib / "Organ" / "NorrfjardenChurch"
    items = {
        "sample_set": (set_dir / "NorrfjardenChurch.organ").is_file(),
        "ir": (lib / "IR" / "OpenAIR" / "lady_chapel_st_albans_cathedral__stereo__stalbans_a_ortf.wav").is_file(),
        "pipe_model": (ENGINES / "organ" / "data" / "norrfjarden_pipes.json").is_file(),
        "wvunpack": bool(shutil.which("wvunpack") or os.path.exists("/opt/homebrew/bin/wvunpack")),
        "afconvert": shutil.which("afconvert") is not None,
    }
    if items["sample_set"]:
        n = sum(1 for _ in set_dir.rglob("*") if _.is_file())
        items["sample_files"] = n >= 4837
    missing = [k for k, ok in items.items() if not ok]
    return {"ok": not missing, "missing": missing}


def check_script(engine: str) -> dict:
    r = subprocess.run(["bash", str(SCRIPTS[engine]), "--check"], capture_output=True, text=True, timeout=600,
                       cwd=SCRIPTS[engine].parent)
    lines = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
    bad = [ln.strip()[:160] for ln in lines if re.search(r"\b(FAIL|MISSING|missing|differs|not found|error)\b", ln)]
    return {"ok": r.returncode == 0, "missing": bad[:8], "last": lines[-1][:160] if lines else ""}


def run(args, ctx):
    if not args.check:
        raise KapellError("setup_check_only", "this kit phase verifies only; installing is not enabled",
                          f"run kapell setup --engine {args.engine} --check, or the engine's setup script by hand: "
                          f"{SCRIPTS.get(args.engine, ENGINES)}", exit_code=2)
    engines = ENGINE_NAMES if args.engine == "all" else (args.engine,)
    out = {}
    for e in engines:
        t0 = time.time()
        res = check_organ() if e == "organ" else check_script(e)
        res["s"] = round(time.time() - t0, 1)
        out[e] = res
    data = {"lib_dir": str(lib_dir()), "engines": out, "ok": all(r["ok"] for r in out.values())}
    if not data["ok"]:
        bad = [e for e, r in out.items() if not r["ok"]]
        raise KapellError("engine_not_ready", f"not ready: {', '.join(bad)} ({out})",
                          f"run the engine's setup script without --check to install: {[str(SCRIPTS[b]) for b in bad]}",
                          exit_code=2)
    return data
