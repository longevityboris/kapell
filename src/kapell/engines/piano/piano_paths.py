"""Shared locations for the piano renderer.

Large assets live outside the git repo, under ``kapell.config.lib_dir()`` ($KAPELL_LIB, else $PIANO_LIB; default
``~/Music/SampleLibraries``). ``setup_piano.sh`` fills that directory; the
other scripts only read from it.
"""

from __future__ import annotations

# Support direct script execution without changing sys.path on package import.
if not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_src = str(_BootstrapPath(__file__).resolve().parents[3])
    if _bootstrap_src not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _bootstrap_src)


import os
from pathlib import Path
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
