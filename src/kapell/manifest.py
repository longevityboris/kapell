"""Command discovery and the agent-info manifest (C section 3).

discover(pkg)            -> list[Discovered]: every module in kapell.commands, including ones that
                            failed to import (error set, module None), sorted by verb.
describe_parser(parser)  -> {"args": [...], "options": [...], "subcommands": {...}} from argparse.
build(parsers, found)    -> the full manifest dict; command_entry(...) for `agent-info --command X`.
"""
import argparse
import importlib
import pkgutil
from dataclasses import dataclass, field
from types import ModuleType

from . import __version__
from .envelope import ENVELOPE_VERSION, EXIT_CODES

EFFECTS = ("read", "write", "execute")

# Kit version -> list of breaking changes introduced in that version (C section 9).
BREAKING_CHANGES: dict[str, list[str]] = {}

GLOBAL_OPTIONS = [
    {"name": "--json", "type": "bool", "default": False,
     "description": "JSON envelope on stdout (automatic when stdout is not a TTY)"},
    {"name": "--quiet", "type": "bool", "default": False,
     "description": "print nothing on success; errors still print"},
    {"name": "--project", "type": "string",
     "description": "project directory (default: walk up from the working directory to kapell.toml)"},
]


@dataclass
class Discovered:
    name: str                       # CLI verb
    module_name: str                # kapell.commands.<x>
    module: ModuleType | None = None
    spec: dict | None = None
    error: str | None = None        # import or contract failure, one line
    warnings: list[str] = field(default_factory=list)


def discover(pkg: ModuleType | None = None) -> list[Discovered]:
    """Import every non-underscore module in the commands package. A module that fails to import,
    or that breaks the plug-in contract, is returned with .error set so the CLI can still register
    the verb (as a stub that exits 2) and doctor can report it. Modules without SPEC are helpers."""
    if pkg is None:
        from . import commands as pkg
    found: list[Discovered] = []
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_"):
            continue
        full = f"{pkg.__name__}.{info.name}"
        verb = info.name.replace("_", "-")
        try:
            mod = importlib.import_module(full)
        except Exception as exc:  # noqa: BLE001 - any import failure is reported, never fatal
            found.append(Discovered(verb, full, error=f"{type(exc).__name__}: {exc}".splitlines()[0][:300]))
            continue
        spec = getattr(mod, "SPEC", None)
        if spec is None:
            continue
        if not isinstance(spec, dict) or not spec.get("name"):
            found.append(Discovered(verb, full, error="SPEC must be a dict with a 'name'"))
            continue
        if not callable(getattr(mod, "run", None)):
            found.append(Discovered(spec["name"], full, error="module defines SPEC but no run(args, ctx)"))
            continue
        d = Discovered(spec["name"], full, module=mod, spec=spec)
        if spec.get("effect") not in EFFECTS:
            d.warnings.append(f"SPEC effect {spec.get('effect')!r} is not one of {EFFECTS}")
        for key in ("help", "runtime_s", "output_tokens_typ", "examples"):
            if key not in spec:
                d.warnings.append(f"SPEC lacks {key!r}")
        found.append(d)
    return sorted(found, key=lambda d: d.name)


def _type_name(action: argparse.Action) -> str:
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction,
                           argparse.BooleanOptionalAction)):
        return "bool"
    if isinstance(action, argparse._CountAction):
        return "int"
    t = action.type
    if t is int:
        return "int"
    if t is float:
        return "float"
    if action.nargs in ("*", "+") or isinstance(action, argparse._AppendAction):
        return "list"
    return "string"


def describe_parser(parser: argparse.ArgumentParser) -> dict:
    args, options, subs = [], [], {}
    for a in parser._actions:
        if isinstance(a, (argparse._HelpAction, argparse._VersionAction)):
            continue
        if a.dest in ("json", "quiet", "project") and a.default is argparse.SUPPRESS:
            continue  # global flags repeated on subparsers
        if isinstance(a, argparse._SubParsersAction):
            helps = {c.dest: c.help for c in a._choices_actions}
            for name, sp in a.choices.items():
                entry = {"help": helps.get(name, "")}
                entry.update({k: v for k, v in describe_parser(sp).items() if v})
                subs[name] = entry
            continue
        if not a.option_strings:
            item = {"name": a.dest, "kind": "positional", "description": a.help or ""}
            if a.nargs in ("?", "*"):
                item["required"] = False
            if a.choices:
                item["values"] = list(a.choices)
            args.append(item)
            continue
        item = {"name": max(a.option_strings, key=len), "type": _type_name(a)}
        if a.choices:
            item["values"] = list(a.choices)
        if a.required:
            item["required"] = True
        if a.default not in (None, False, argparse.SUPPRESS, []):
            item["default"] = a.default
        if a.help and a.help != argparse.SUPPRESS:
            item["description"] = a.help
        options.append(item)
    return {"args": args, "options": options, "subcommands": subs}


def command_entry(spec: dict, parser: argparse.ArgumentParser | None, error: str | None = None) -> dict:
    entry = {k: spec[k] for k in ("effect", "help", "runtime_s", "output_tokens_typ") if k in spec}
    if parser is not None:
        desc = describe_parser(parser)
        entry["args"] = desc["args"]
        entry["options"] = desc["options"]
        if desc["subcommands"]:
            entry["subcommands"] = desc["subcommands"]
    entry["examples"] = spec.get("examples", [])
    for k, v in spec.items():  # extensions a lane adds to its SPEC travel through unchanged
        if k not in entry and k != "name":
            entry[k] = v
    if error:
        entry["unavailable"] = error
    return entry


def build(entries: dict[str, dict]) -> dict:
    return {
        "name": "kapell",
        "version": __version__,
        "envelope": {"version": ENVELOPE_VERSION,
                     "success": {"version": "1", "status": "success|no_results|partial_success|fail", "data": {}},
                     "error": {"version": "1", "status": "error", "error": {"code": "", "message": "", "suggestion": ""}},
                     "exceptions": {"guide NAME": "raw markdown on stdout"}},
        "exit_codes": dict(EXIT_CODES),
        "global_options": GLOBAL_OPTIONS,
        "project_discovery": "walk up from the working directory to kapell.toml (or --project DIR)",
        "breaking_changes": dict(BREAKING_CHANGES),
        "commands": entries,
    }
