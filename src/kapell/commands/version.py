"""kapell version: installed kit version, and whether it matches the project's pin (C section 9)."""
import platform

from .. import __version__

SPEC = {
    "name": "version",
    "effect": "read",
    "help": "kit version, Python version, and the project's kit pin",
    "runtime_s": 0.05,
    "output_tokens_typ": 40,
    "examples": [["version"]],
}


def add_arguments(parser):
    pass


def pin_matches(pin, installed: str = __version__) -> bool | None:
    """kapell.toml pins `kit = "0.1"`; it matches when every component it names agrees."""
    if not pin:
        return None
    want = str(pin).split(".")
    return installed.split(".")[: len(want)] == want


def run(args, ctx):
    pin = (ctx.cfg.get("kapell") or {}).get("kit") if ctx.cfg else None
    data = {"kit": __version__, "python": platform.python_version()}
    if ctx.root is not None:
        data["project"] = str(ctx.root)
        data["project_pin"] = pin
        data["pin_ok"] = pin_matches(pin)
    return data
