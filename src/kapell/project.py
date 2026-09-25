"""Project discovery (stable API; extend, do not rename).

A project is a directory containing kapell.toml. Commands walk up from the working directory
to find it, as git does, so prompts never need absolute paths.

find_root(start=None) -> Path | None
load(root) -> dict            parsed kapell.toml
path(root, cfg, key) -> Path   resolve cfg["paths"][key] relative to the project root
"""
import tomllib
from pathlib import Path


def find_root(start: Path | str | None = None) -> Path | None:
    p = Path(start or Path.cwd()).resolve()
    for d in (p, *p.parents):
        if (d / "kapell.toml").is_file():
            return d
    return None


def load(root: Path) -> dict:
    with open(Path(root) / "kapell.toml", "rb") as fh:
        return tomllib.load(fh)


def path(root: Path, cfg: dict, key: str) -> Path:
    return Path(root) / cfg["paths"][key]
