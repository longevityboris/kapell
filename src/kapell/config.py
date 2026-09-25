"""Machine-level configuration shared by every module (stable API; extend, do not rename).

lib_dir()      sample libraries: $KAPELL_LIB, else $PIANO_LIB (legacy alias), else ~/Music/SampleLibraries
renders_dir()  render outputs outside git: $KAPELL_RENDERS, else ~/Music/kapell-renders
"""
import os
from pathlib import Path


def lib_dir() -> Path:
    for var in ("KAPELL_LIB", "PIANO_LIB"):
        if os.environ.get(var):
            return Path(os.environ[var]).expanduser()
    return Path.home() / "Music" / "SampleLibraries"


def renders_dir(piece: str | None = None) -> Path:
    base = Path(os.environ.get("KAPELL_RENDERS", Path.home() / "Music" / "kapell-renders")).expanduser()
    return base / piece if piece else base
