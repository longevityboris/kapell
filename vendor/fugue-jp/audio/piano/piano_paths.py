"""Shared locations for the piano renderer.

Large assets live outside the git repo, under ``$PIANO_LIB`` (default
``~/Music/SampleLibraries``). ``setup_piano.sh`` fills that directory; the
other scripts only read from it.
"""

from __future__ import annotations

import os
from pathlib import Path

LIB = Path(os.environ.get("PIANO_LIB", Path.home() / "Music" / "SampleLibraries"))

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
