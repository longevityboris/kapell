"""kapell command line: discovery, argparse tree, envelope and exit codes (C section 3).

    kapell [--json] [--quiet] [--project DIR] <command> [args]

Global flags are accepted anywhere on the line (`kapell check --json` works). Output is JSON when
stdout is not a TTY. Commands are discovered from kapell.commands (see its docstring for the
plug-in contract); a module that fails to import still appears as a verb that exits 2 with the
import error, and `kapell doctor` lists it.
"""
import argparse
import os
import sys
import tomllib
import traceback
from pathlib import Path

from . import __version__, project
from .commands import Context, KapellError, Result
from .envelope import Raw, emit, error, exit_for, success
from .manifest import Discovered, build, command_entry, discover

AGENT_INFO_SPEC = {
    "name": "agent-info",
    "effect": "read",
    "help": "machine-readable manifest of every command (or one with --command X)",
    "runtime_s": 0.1,
    "output_tokens_typ": 1700,          # full manifest with ~8 commands; grows with the kit
    "output_tokens_command": 150,       # agent-info --command X
    "examples": [["agent-info"], ["agent-info", "--command", "check"]],
}

# Commands that must work without a (valid) project file.
LENIENT = {"agent-info", "doctor", "version", "guide", "status"}


class KapellArgumentParser(argparse.ArgumentParser):
    """argparse exits 2 on bad arguments; kapell reserves 2 for config/env, so bad input is 3."""

    def error(self, message):
        raise KapellError("bad_input", f"{self.prog}: {message}",
                          f"run `{self.prog} --help` or `kapell agent-info --command <name>`", 3)


def _extract_globals(argv: list[str]) -> tuple[list[str], dict]:
    """Pull --json/--quiet/--project out of argv wherever they appear (before a literal `--`)."""
    flags = {"json": False, "quiet": False, "project": None}
    rest, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            rest.extend(argv[i:])
            break
        if a == "--json":
            flags["json"] = True
        elif a in ("--quiet", "-q"):
            flags["quiet"] = True
        elif a == "--project":
            if i + 1 >= len(argv):
                raise KapellError("bad_input", "--project needs a directory", "kapell --project DIR <command>", 3)
            flags["project"] = argv[i + 1]
            i += 1
        elif a.startswith("--project="):
            flags["project"] = a.split("=", 1)[1]
        else:
            rest.append(a)
        i += 1
    return rest, flags


def _stub_runner(d: Discovered):
    def run(args, ctx):
        raise KapellError("command_unavailable", f"command {d.name!r} failed to load: {d.error}",
                          "run `kapell doctor` for details; reinstall the kit if a file is missing", 2)
    return run


def build_parser(found: list[Discovered]):
    """Return (parser, handlers, subparsers, discovered-with-duplicates-marked)."""
    parser = KapellArgumentParser(prog="kapell", description="composition kit for agent-written counterpoint")
    parser.add_argument("--json", action="store_true", help="JSON envelope (automatic when piped)")
    parser.add_argument("--quiet", "-q", action="store_true", help="print nothing on success")
    parser.add_argument("--project", help="project directory (default: walk up to kapell.toml)")
    parser.add_argument("--version", action="version", version=f"kapell {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", parser_class=KapellArgumentParser)
    handlers, parsers, seen = {}, {}, {}

    ap = sub.add_parser("agent-info", help=AGENT_INFO_SPEC["help"], description=AGENT_INFO_SPEC["help"])
    ap.add_argument("--command", dest="target", help="describe one command only")
    handlers["agent-info"], parsers["agent-info"] = None, ap  # filled in by main (needs the whole tree)
    seen["agent-info"] = "builtin"

    for d in found:
        if d.name in seen:
            d.error = d.error or f"verb {d.name!r} already defined by {seen[d.name]}"
            d.module = None
            continue
        seen[d.name] = d.module_name
        if d.module is None:
            p = sub.add_parser(d.name, help=f"(unavailable: {d.error})")
            p.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
            handlers[d.name], parsers[d.name] = _stub_runner(d), None
            continue
        spec = d.spec
        p = sub.add_parser(d.name, help=spec.get("help", ""), description=spec.get("help", ""))
        add = getattr(d.module, "add_arguments", None)
        if add is not None:
            try:
                add(p)
            except Exception as exc:  # noqa: BLE001 - a broken add_arguments must not take down the CLI
                d.error = f"add_arguments failed: {type(exc).__name__}: {exc}"
                d.module = None
                handlers[d.name], parsers[d.name] = _stub_runner(d), None
                continue
        handlers[d.name], parsers[d.name] = d.module.run, p
    return parser, handlers, parsers


def manifest_entries(found: list[Discovered], parsers: dict) -> dict:
    entries = {"agent-info": command_entry(AGENT_INFO_SPEC, parsers["agent-info"])}
    for d in found:
        if d.name in entries:
            continue
        spec = d.spec or {"effect": "unknown", "help": "unavailable: failed to load"}
        entries[d.name] = command_entry(spec, parsers.get(d.name), d.error)
    return dict(sorted(entries.items()))


def _context(flags: dict, verb: str, as_json: bool) -> Context:
    start = flags["project"] or os.environ.get("KAPELL_PROJECT")
    if start and not Path(start).expanduser().is_dir():
        raise KapellError("bad_input", f"--project {start}: not a directory", "", 3)
    root = project.find_root(Path(start).expanduser() if start else None)
    cfg: dict = {}
    cfg_error = None
    if root is not None:
        try:
            cfg = project.load(root)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            if verb not in LENIENT:
                raise KapellError("config_invalid", f"{root / 'kapell.toml'}: {exc}",
                                  "fix the TOML syntax in kapell.toml", 2) from exc
            cfg_error = f"kapell.toml unreadable: {exc}"
    ctx = Context(root=root, cfg=cfg, json=as_json, quiet=flags["quiet"])
    ctx.cfg_error = cfg_error  # lenient commands (status, doctor, ...) report it instead of failing
    return ctx


def _normalise(result) -> dict | Raw:
    if isinstance(result, Raw):
        return result
    if result is None:
        return success({})
    if isinstance(result, Result):
        return success(result.data, result.status)
    if isinstance(result, dict):
        return success(result)
    raise TypeError(f"command returned {type(result).__name__}; expected dict or Result")


def main(argv: list[str] | None = None, *, commands_pkg=None, stdout=None, stderr=None) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    flags = {"json": False, "quiet": False, "project": None}
    as_json = not _isatty(out)
    try:
        argv, flags = _extract_globals(argv)
        as_json = flags["json"] or not _isatty(out)
        found = discover(commands_pkg)
        parser, handlers, parsers = build_parser(found)
        if not argv:
            emit(success({"commands": sorted(handlers), "hint": "kapell agent-info, or kapell <command> --help"}),
                 as_json, flags["quiet"], out, err)
            return 0
        # A missing dependency is an environment error even when the unavailable verb
        # was called with options that cannot be registered until its module imports.
        unavailable = next((d for d in found if d.name == argv[0]), None)
        if unavailable is not None and unavailable.module is None and "--help" not in argv:
            _stub_runner(unavailable)(None, None)
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:  # --help / --version
            return int(exc.code or 0)
        verb = args.command
        ctx = _context(flags, verb, as_json)
        ctx.discovered = found  # doctor reads import failures from here
        ctx.manifest = lambda: manifest_entries(found, parsers)
        if verb == "agent-info":
            entries = manifest_entries(found, parsers)
            if args.target:
                if args.target not in entries:
                    raise KapellError("unknown_command", f"no command {args.target!r}",
                                      "known: " + ", ".join(entries), 3)
                res = success({"name": "kapell", "version": __version__, "command": args.target,
                               **entries[args.target]})
            else:
                res = success(build(entries))
        else:
            res = _normalise(handlers[verb](args, ctx))
    except KapellError as exc:
        emit(error(exc.code, exc.message, exc.suggestion), as_json, flags["quiet"], out, err)
        return exc.exit_code
    except OSError as exc:
        emit(error("environment", str(exc), "check file permissions and run kapell doctor"),
             as_json, flags["quiet"], out, err)
        return 2
    except KeyboardInterrupt:
        emit(error("interrupted", "interrupted", "re-run the command"), as_json, flags["quiet"], out, err)
        return 130
    except Exception as exc:  # noqa: BLE001 - every failure leaves an envelope
        if not flags["quiet"]:
            traceback.print_exc(file=err)
        emit(error("internal", f"{type(exc).__name__}: {exc}",
                   "this is a kapell bug; re-run with the same inputs and report the traceback"),
             as_json, flags["quiet"], out, err)
        return 1
    if isinstance(res, Raw):
        if flags["quiet"]:
            return 0
        out.write(res.text if res.text.endswith("\n") else res.text + "\n")
        return 0
    emit(res, as_json, flags["quiet"], out, err)
    return exit_for(res["status"])


def _isatty(stream) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


if __name__ == "__main__":
    sys.exit(main())
