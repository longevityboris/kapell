"""Shared tables for the orchestra renderer: parts, compasses, seating, levels,
sample-library locations and name parsing.  See CONTRACT.md for the MIDI
interface and README.md for how the numbers were measured."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RICERCAR = HERE.parents[1]
STRINGS_DIR = RICERCAR / "audio" / "strings"
sys.path.insert(0, str(STRINGS_DIR))          # reuse (never edit) the quartet's helpers

LIB_ROOT = Path(os.environ.get("SAMPLE_LIBRARIES", Path.home() / "Music" / "SampleLibraries"))
ORCH_LIB = LIB_ROOT / "Orchestra"
VSCO_ROOT = ORCH_LIB / "VSCO-2-CE"
IOWA_WINDS = ORCH_LIB / "IowaMIS-winds"
VPO3_ROOT = LIB_ROOT / "VPO3" / "Virtual-Playing-Orchestra3"
BUILT = ORCH_LIB / "built"                     # built samples + SFZ (outside git)
IR_ROOT = LIB_ROOT / "IR"


def _sfizz_render() -> Path:
    env = os.environ.get("SFIZZ_RENDER")
    cands = [Path(env)] if env else []
    cands += [LIB_ROOT / "tools" / "sfizz" / "build" / "library" / "bin" / "sfizz_render",
              LIB_ROOT / "bin" / "sfizz_render"]
    for c in cands:
        if c.exists():
            return c
    return cands[-1]


SFIZZ_RENDER = _sfizz_render()
SR = 48000

# perform.py's scales
LEVELS = {"ppp": 1, "pp": 2, "p": 3, "mp": 4, "mf": 5, "f": 6, "ff": 7, "fff": 8}
VEL_AT = {1: 22, 2: 32, 3: 44, 4: 56, 5: 68, 6: 82, 7: 98, 8: 112}


def level_to_cc1(L: float) -> int:
    return int(max(0, min(127, round(36 + 13 * (L - 1)))))


def cc1_to_level(c: float) -> float:
    return 1 + (c - 36) / 13.0


NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_to_midi(name: str) -> int:
    """'Bb3', 'C#4', 'A#0', 'Db7' -> MIDI (C4 = 60)."""
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d)", name.strip())
    if not m:
        raise ValueError(name)
    pc = NOTE_PC[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)]
    return 12 * (int(m.group(3)) + 1) + pc


NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def midi_name(k: int) -> str:
    return f"{NAMES[k % 12]}{k // 12 - 1}"


def midi_to_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


# ---------------------------------------------------------------- the parts
# lo/hi: sounding compass (MIDI).  az: stage azimuth in degrees (+ = left, as
# the quartet's hall.place_dry), depth: metres behind the front of the stage,
# width: how much of the sample's own stereo image is kept.  american seating.
# family: winds | brass | strings | perc.  players: sample sets in the order
# player 1, player 2, ... (a2 uses the first two, a4 the first four).
PARTS = {
    "fl":   dict(name="Flute", family="winds", lo=60, hi=96, az=7.0, depth=6.5, width=0.25),
    "ob":   dict(name="Oboe", family="winds", lo=58, hi=91, az=-3.0, depth=6.5, width=0.25),
    "cl":   dict(name="Clarinet", family="winds", lo=50, hi=91, az=8.0, depth=8.0, width=0.25),
    "bn":   dict(name="Bassoon", family="winds", lo=34, hi=75, az=-4.0, depth=8.0, width=0.25),
    "hn":   dict(name="Horn", family="brass", lo=34, hi=77, az=24.0, depth=9.0, width=0.4),
    "tpt":  dict(name="Trumpet", family="brass", lo=54, hi=84, az=-5.0, depth=10.5, width=0.25),
    "tbn":  dict(name="Trombone", family="brass", lo=40, hi=72, az=-15.0, depth=10.5, width=0.25),
    "btbn": dict(name="Bass Trombone", family="brass", lo=31, hi=67, az=-20.0, depth=10.5, width=0.25),
    "tba":  dict(name="Tuba", family="brass", lo=26, hi=65, az=-25.0, depth=10.5, width=0.25),
    "timp": dict(name="Timpani", family="perc", lo=38, hi=57, az=10.0, depth=12.0, width=0.5),
    "vn1":  dict(name="Violins I", family="strings", lo=55, hi=100, az=30.0, depth=1.0, width=0.7),
    "vn2":  dict(name="Violins II", family="strings", lo=55, hi=96, az=13.0, depth=3.2, width=0.6),
    "va":   dict(name="Violas", family="strings", lo=48, hi=88, az=-9.0, depth=3.2, width=0.6),
    "vc":   dict(name="Cellos", family="strings", lo=36, hi=81, az=-27.0, depth=1.5, width=0.6),
    "cb":   dict(name="Double Basses", family="strings", lo=24, hi=67, az=-37.0, depth=5.0, width=0.6),
}
PART_IDS = list(PARTS)
GERMAN = {"vn2": dict(az=-30.0, depth=1.0), "va": dict(az=-13.0, depth=2.8),
          "vc": dict(az=10.0, depth=2.2), "cb": dict(az=22.0, depth=5.0)}

GM_PROGRAM = {73: "fl", 72: "fl", 68: "ob", 69: "ob", 71: "cl", 70: "bn", 60: "hn", 56: "tpt", 57: "tbn",
              58: "tba", 47: "timp", 41: "va", 42: "vc", 43: "cb"}
NAME_KEYS = [                                   # whole-word instrument names, most specific first
    ("btbn", ["bass trombone", "bass tbn", "btbn", "b. tbn"]),
    ("tbn", ["tenor trombone", "trombone", "tbn", "pos"]),
    ("vn1", ["violin 1", "violin i", "violins i", "vln 1", "vln. 1", "vn 1", "violino i", "1st violin",
             "first violin", "violins 1"]),
    ("vn2", ["violin 2", "violin ii", "violins ii", "vln 2", "vln. 2", "vn 2", "violino ii", "2nd violin",
             "second violin", "violins 2"]),
    ("cb", ["contrabass", "double bass", "double basses", "doublebass", "kontrabass", "contrabasso",
            "basses"]),
    ("va", ["viola", "violas", "vla"]),
    ("vc", ["violoncello", "cello", "cellos", "vlc"]),
    ("fl", ["flute", "flauto", "fl"]),
    ("ob", ["oboe", "hautbois", "ob"]),
    ("cl", ["clarinet", "clarinetto", "klarinette", "cl"]),
    ("bn", ["bassoon", "fagott", "fagotto", "bsn", "bn"]),
    ("hn", ["horn", "horns", "french horn", "corno", "cor", "hn"]),
    ("tpt", ["trumpet", "tromba", "trompete", "tpt", "trp"]),
    ("tba", ["tuba", "tba"]),
    ("timp", ["timpani", "timp", "pauken", "kettledrum", "kettledrums"]),
]
SATB = {"soprano": "vn1", "descant": "vn1", "alto": "vn2", "mezzo": "vn2", "tenor": "va",
        "baritone": "va", "bass": "vc", "pedal": "vc"}
PART_RE = re.compile(r"^(" + "|".join(sorted(PART_IDS, key=len, reverse=True)) + r")(?:[.:_\- ](\S.*))?$", re.I)


def part_of_name(name: str) -> tuple[str | None, str]:
    """Track name -> (part id, how it was recognised)."""
    nm = (name or "").strip()
    m = PART_RE.match(nm)
    if m:
        return m.group(1).lower(), "part id"
    low = " " + re.sub(r"[^a-z0-9. ]+", " ", nm.lower()) + " "
    for pid, keys in NAME_KEYS:
        for k in keys:
            if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", low):
                return pid, f"name '{k}'"
    return None, ""


def satb_part(name: str) -> str | None:
    low = (name or "").strip().lower()
    for k, v in SATB.items():
        if re.search(r"(?<![a-z])" + k + r"(?![a-z])", low):
            return v
    return None


# ---------------------------------------------------------------- levels
# Natural balance.  K-weighted loudness (dB, dry, at the stage front) of each
# part playing a sustained mid-register note at pp / mf / ff, relative to the
# violin section at ff.  From the published sound-power ranges of orchestral
# instruments (J. Meyer, Acoustics and the Performance of Music, 5th ed., tables
# of dynamic range per instrument) with 10 log10(n) for n unison players
# (14/12/10/8/6 strings), compressed by 25 % towards the strings so a tutti
# stays readable in a recording (a real hall does this with distance: brass sit
# 10 m further back).  Values between the three anchors are interpolated in
# dynamic level; ppp and fff extrapolate by half a step.
BALANCE = {
    #          pp     mf     ff
    "vn1":  (-21.0, -9.0, 0.0),
    "vn2":  (-21.5, -9.5, -0.5),
    "va":   (-22.0, -10.0, -1.5),
    "vc":   (-21.0, -9.0, 0.0),
    "cb":   (-21.0, -10.0, -1.5),
    "fl":   (-20.0, -11.0, -4.0),
    "ob":   (-19.0, -10.5, -4.0),
    "cl":   (-24.0, -11.0, -2.5),
    "bn":   (-20.0, -11.0, -4.5),
    "hn":   (-21.0, -8.5, 1.5),
    "tpt":  (-18.0, -6.5, 3.0),
    "tbn":  (-20.0, -7.0, 3.0),
    "btbn": (-20.0, -7.0, 3.0),
    "tba":  (-20.0, -8.0, 2.0),
    "timp": (-22.0, -8.0, 3.0),
}


def balance_db(part: str, level: float) -> float:
    """Loudness (dB re violins I at ff) of `part` at dynamic level 1..8."""
    pp, mf, ff = BALANCE[part]
    if level <= 2:
        return pp - (2 - level) * 0.5 * (mf - pp) / 3
    if level <= 5:
        return pp + (level - 2) * (mf - pp) / 3
    if level <= 7:
        return mf + (level - 5) * (ff - mf) / 2
    return ff + (level - 7) * 0.5 * (ff - mf) / 2
