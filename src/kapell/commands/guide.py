"""kapell guide [NAME]: print guides/NAME.md raw (the documented envelope exception), or list guides.

Guides live in the kit repo's guides/ folder (editable install) or in kapell/guides inside an
installed package; $KAPELL_GUIDES overrides both.
"""
import os
from pathlib import Path

from . import KapellError
from ..envelope import Raw

SPEC = {
    "name": "guide",
    "effect": "read",
    "help": "print a guide as raw markdown (method, counterpoint, orchestration, performance, recipes); list when no name",
    "runtime_s": 0.05,
    "output_tokens_typ": 100,
    "examples": [["guide"], ["guide", "counterpoint"]],
    "output": "raw markdown on stdout for `guide NAME` (envelope exception); envelope for the list",
}


def add_arguments(parser):
    parser.add_argument("name", nargs="?", help="guide name (without .md); omit to list")


def guide_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("KAPELL_GUIDES"):
        dirs.append(Path(os.environ["KAPELL_GUIDES"]).expanduser())
    pkg = Path(__file__).resolve().parents[1]          # src/kapell
    dirs.append(pkg / "guides")                        # packaged copy
    dirs.append(pkg.parents[1] / "guides")             # repo root, editable install
    return [d for d in dirs if d.is_dir()]


def available() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in guide_dirs():
        for f in sorted(d.glob("*.md")):
            found.setdefault(f.stem, f)
    return found


def _title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return line.lstrip("# ").strip()[:100]
    except OSError:
        pass
    return ""


def run(args, ctx):
    guides = available()
    if not args.name:
        data = {"guides": {name: _title(p) for name, p in guides.items()},
                "usage": "kapell guide NAME prints raw markdown"}
        if not guides:
            data["note"] = "no guides installed yet (looked in: KAPELL_GUIDES, kapell/guides, <kit>/guides)"
            from . import Result
            return Result("no_results", data)
        return data
    name = args.name.removesuffix(".md")
    if name not in guides:
        raise KapellError("unknown_guide", f"no guide {name!r}",
                          ("available: " + ", ".join(guides)) if guides else "no guides are installed yet", 3)
    return Raw(guides[name].read_text(encoding="utf-8"))
