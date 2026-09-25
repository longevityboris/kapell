"""Shared locations for the piano renderer.

Large assets live outside the git repo, under ``kapell.config.lib_dir()`` ($KAPELL_LIB, else $PIANO_LIB; default
``~/Music/SampleLibraries``). ``setup_piano.sh`` fills that directory; the
other scripts only read from it.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys as _sys
_SRC = str(Path(__file__).resolve().parents[3])   # .../src: lets kapell import when run as a script
if _SRC not in _sys.path:
    _sys.path.append(_SRC)
from kapell.config import lib_dir  # noqa: E402

LIB = lib_dir()   # $KAPELL_LIB, else $PIANO_LIB, else ~/Music/SampleLibraries

SALAMANDER_DIR = LIB / "SalamanderGrandPiano" / "SalamanderGrandPiano-SFZ+FLAC-V3+20200602"
SALAMANDER_SFZ = SALAMANDER_DIR / "SalamanderGrandPiano-V3+20200602.sfz"

# Derived instrument written by make_sfz.py (next to the original so that the
# relative "samples/..." paths keep working).
DERIVED_SFZ = SALAMANDER_DIR / "SalamanderGrandPiano-Ricercar.sfz"
DERIVED_SFZ_NO_PEDAL_NOISE = SALAMANDER_DIR / "SalamanderGrandPiano-Ricercar-nopedalnoise.sfz"
CALIBRATION_JSON = SALAMANDER_DIR / "SalamanderGrandPiano-Ricercar.calibration.json"

SFIZZ_RENDER = Path(
    os.environ.get("SFIZZ_RENDER", LIB / "tools" / "sfizz" / "build" / "library" / "bin" / "sfizz_render")
)

IR_DIR = LIB / "IR"
DETMOLD_DIR = IR_DIR / "DetmoldSRIR"
HALL_IR = IR_DIR / "Detmold-Konzerthaus-S1R163-MS-48k.wav"

SR = 48000
