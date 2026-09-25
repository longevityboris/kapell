#!/usr/bin/env python3
"""Round-2: are the lines followable in the final mix of the test music?  an_mix.py's clarity measure
(new note's own partials vs the previous note's own partials at the note's middle; partials shared with
each other or with any note sounding within 0.3 s excluded) applied to EVERY pitch change in every voice
(SK_final has no notes under 0.26 s, so an_mix's short-note class is empty there), in the dry stem, the dry
sum of the four stems, the final mix, --hall none and --wet -8.  Split by note length.

  python3 an_clarity.py [--tag sk_final]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import TMP, Spec, midi_voices, save  # noqa: E402

NAMES = {"soprano": "vn1", "alto": "vn2", "tenor": "va", "pedal": "vc", "bass": "vc"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="sk_final")
    ap.add_argument("--compare", nargs="*", default=["hall_none=_dryhall", "wet_minus8=_wet8"],
                    help="LABEL=SUFFIX renders of the same MIDI to compare with the default mix")
    a = ap.parse_args()
    base = TMP / f"{a.tag}_def"
    rep = json.loads(Path(str(base) + ".json").read_text())
    off = rep["offset_s"]
    x, SR = sf.read(str(base) + ".wav", always_2d=True)
    stems = {i: sf.read(f"{base}_stem_{i}.wav", always_2d=True)[0].mean(axis=1) for i in ("vn1", "vn2", "va", "vc")}
    sigs = {"mix": x.mean(axis=1), "dry_sum": sum(stems.values())}
    for nm, suf in (c.split("=", 1) for c in a.compare):
        p = TMP / f"{a.tag}{suf}.wav"
        z, _ = sf.read(str(p), always_2d=True)
        rz = json.loads((TMP / f"{a.tag}{suf}.json").read_text())
        d = int(round((rz["offset_s"] - off) * SR))
        zz = z.mean(axis=1)
        sigs[nm] = np.concatenate([np.zeros(d), zz])[: len(sigs["mix"])] if d >= 0 else zz[-d:]
    midi = midi_voices(TMP / f"chain_{a.tag}.mid")
    allnotes = [n for v in midi.values() for n in v["notes"]]
    specs = {}
    out = {}
    for v in midi.values():
        inst = NAMES.get(v["name"])
        notes = v["notes"]
        for i, nt in enumerate(notes[1:], 1):
            p = notes[i - 1]
            if p["key"] == nt["key"] or nt["on"] - p["off"] > 0.1:
                continue
            dur = nt["off"] - nt["on"]
            cls = "lt0p5s" if dur < 0.5 else "0p5_1s" if dur < 1.0 else "ge1s"
            tm = nt["on"] + min(0.5 * dur, 0.25) - off            # middle of short notes, 0.25 s into long ones
            others = [o["key"] for o in allnotes if o is not nt and o is not p and o["on"] - off < tm + 0.02
                      and o["off"] - off + 0.3 > tm]
            w = 0.08 if nt["key"] < 50 else 0.05
            for nm, sig in dict(dry_stem=stems[inst], **sigs).items():
                key = (nm if nm != "dry_stem" else "stem_" + inst, w)
                if key not in specs:
                    specs[key] = Spec(sig, win=w)
                sp = specs[key]
                bn = sp.band_energy(nt["key"], exclude_keys=[p["key"]] + others)
                bo = sp.band_energy(p["key"], exclude_keys=[nt["key"]] + others)
                if bn is None or bo is None:
                    continue
                j = int(np.argmin(np.abs(sp.t - tm)))
                out.setdefault(cls, {}).setdefault(nm, []).append(float(bn[j] - bo[j]))
                if nm == "mix":
                    out.setdefault("by_voice_mix", {}).setdefault(inst, []).append(float(bn[j] - bo[j]))
    res = {k: {nm: dict(n=len(v), new_dominates=round(float(np.mean(np.array(v) > 0)), 3),
                        median_db=round(float(np.median(v)), 1), p10_db=round(float(np.percentile(v, 10)), 1))
               for nm, v in d.items() if v} for k, d in out.items()}
    save(f"clarity_{a.tag}.json", res)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
