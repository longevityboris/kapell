"""Virtual Playing Orchestra 3 solo strings as an alternative engine for
render_quartet.py (--lib vpo3), used for the library comparison.

VPO3 (Paul Battersby, https://virtualplaying.com/virtual-playing-orchestra/)
wave files 3.2 + performance scripts 3.3.  The solo string "PERF" patches
combine a looped vibrato sustain (No Budget Orchestra solo violin / viola /
cello, CC BY-SA 4.0, plus other free sources for the cello) with a
velocity-crossfaded spiccato / staccato layer (velocity 63-127).  CC1 is a
34 dB gain control (gain_cc1=34) on a single recorded dynamic: there is no
dynamic-layer crossfade in any VPO3 solo string patch.  Licence: VPO3 terms
(free for any music, including commercial; see Documentation/license.htm).

prepare() writes "ricercar-*.sfz" copies next to the originals with
hint_ram_based=1 (sfizz_render otherwise drops streamed notes at random).
"""
from __future__ import annotations

from pathlib import Path

from iowa_common import LIB_ROOT

VPO3_ROOT = LIB_ROOT / "VPO3" / "Virtual-Playing-Orchestra3"
STRINGS = VPO3_ROOT / "Strings"
SOURCE = {
    "violin": "1st-violin-SOLO-PERF.sfz",
    "violin2": "2nd-violin-SOLO-PERF.sfz",
    "viola": "viola-SOLO-PERF.sfz",
    "cello": "cello-SOLO-PERF.sfz",
    "bass": "bass-SOLO-sustain.sfz",
}
VPO3_SFZ = {k: STRINGS / f"ricercar-{v}" for k, v in SOURCE.items()}
VPO3_RANGE = {"violin": (55, 100), "violin2": (55, 100), "viola": (48, 91), "cello": (36, 81), "bass": (24, 67)}
# render_quartet instrument id -> VPO3 patch
INST_PATCH = {"vn1": "violin", "vn2": "violin2", "va": "viola", "vc": "cello", "cb": "bass"}


def available() -> bool:
    return (VPO3_ROOT / "libs" / "NoBudgetOrch").exists() and all((STRINGS / s).exists() for s in SOURCE.values())


def prepare() -> dict:
    for k, src in SOURCE.items():
        text = (STRINGS / src).read_text(errors="replace")
        hint = "hint_ram_based=1  // added by ricercar/audio/strings/vpo3.py\n"
        if "<control>" in text:
            i = text.index("<control>") + len("<control>")
            text = text[:i] + "\n" + hint + text[i:]
        else:
            text = "<control>\n" + hint + text
        VPO3_SFZ[k].write_text(text)
    return VPO3_SFZ


if __name__ == "__main__":
    for k, p in prepare().items():
        print(k, p)
