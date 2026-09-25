"""Command plug-in contract (stable; every lane writes its commands against this).

Each module kapell/commands/<name>.py defines:

    SPEC = {
        "name": "check",                    # CLI verb (sub-verbs: use argparse subparsers inside add_arguments)
        "effect": "read",                   # read | write | execute
        "help": "one line",
        "runtime_s": 0.1,                   # typical, number or "17-240"
        "output_tokens_typ": 150,           # typical JSON size an agent pays to read the result
        "examples": [["check", "score/music-voices.ly"]],
    }
    def add_arguments(parser: argparse.ArgumentParser) -> None
    def run(args, ctx) -> dict | Result

ctx is a Context: ctx.root (project root Path or None), ctx.cfg (kapell.toml dict or {}),
ctx.json (bool), ctx.quiet (bool).

Return a plain dict for status "success", or Result(status, data) for "no_results" |
"partial_success" | "fail". A musical check that finds violations returns
Result("fail", {..., "violations": [...]}) and the CLI exits 5.
Raise KapellError(code, message, suggestion, exit_code) for errors (exit 1 transient,
2 config/env, 3 bad input, 4 rate limited).

The CLI (kapell/cli.py) discovers modules in this package, builds the argparse tree, wraps results
in the envelope {version:"1", status, data} / {version:"1", status:"error", error:{code, message,
suggestion}}, and builds `kapell agent-info` from the SPECs. Keep outputs short by default
(digests); put everything else behind --full.
"""
from dataclasses import dataclass, field
from pathlib import Path


class KapellError(Exception):
    def __init__(self, code: str, message: str, suggestion: str = "", exit_code: int = 3):
        super().__init__(message)
        self.code, self.message, self.suggestion, self.exit_code = code, message, suggestion, exit_code


@dataclass
class Result:
    status: str
    data: dict = field(default_factory=dict)


@dataclass
class Context:
    root: Path | None = None
    cfg: dict = field(default_factory=dict)
    json: bool = False
    quiet: bool = False
