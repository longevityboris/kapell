#!/usr/bin/env python3
"""Round-2: loop seams of 20 s held notes (the SFZ loops each sample over its last 2.5 s with a 0.12 s
crossfade; the test music's fermata chords hold up to 11.5 s, past the first seam).

  python3 an_loop.py

an_edge.py's 'long' MIDI (one note per instrument, 0.5-20.5 s, CC1 = CC11 = 88: the mf layer, normal
stroke) rendered --keep-start --hall none.  Per dry stem:
  * every loop pass: the seam times from the SFZ region the note plays (loop_start / loop_end / offset,
    first pass at loop_end, then every loop length), the level step across each seam (50 ms RMS 30-80 ms
    before vs after) and the largest level step anywhere else in the sustain;
  * an_mix.py's gated click detector (>6 kHz residual 1 ms peak > 15 dB above its local RMS and above
    -30 dB re the full-band local RMS) on a 25 ms grid over the whole note, hits listed with their
    distance to the nearest seam.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import SR, TMP, db, render, rms_env, save  # noqa: E402
from an_mix import click_scan  # noqa: E402
from an_samples import Q, SFZ, regions  # noqa: E402
import an_edge  # noqa: E402

KEYS = {"vn1": 81, "vn2": 62, "va": 48, "vc": 36}
ON, OFF = 0.5, 20.5


def main():
    an_edge.E = TMP / "loop"
    an_edge.E.mkdir(parents=True, exist_ok=True)
    mid = an_edge.build("long")
    out = an_edge.E / "long"
    render(mid, out, "--keep-start", "--hall", "none", keep_temp=False)
    res = {}
    for inst, key in KEYS.items():
        r = next(r for r in regions(Q / SFZ[inst]) if r["layer"] == "mf" and r["art"] == "normal" and r["lokey"] <= key <= r["hikey"])
        line = next(l for l in (Q / SFZ[inst]).read_text().splitlines()
                    if l.startswith("<region>") and f"sample={r['sample']}" in l and f"offset={r['offset']}" in l)
        kv = dict(p.split("=", 1) for p in line.split("//")[0].split()[1:])
        ls, le = int(kv["loop_start"]), int(kv["loop_end"])
        ratio = 2 ** ((key - r["center"]) / 12)
        first = ON + (le - r["offset"]) / SR / ratio
        period = (le - ls) / SR / ratio
        seams = list(np.arange(first, OFF - 0.1, period))
        x = sf.read(str(out) + f"_stem_{inst}.wav", always_2d=True)[0].mean(axis=1)
        t, e = rms_env(x, 0.05, 0.005)
        steps = []
        for s in seams:
            b = float(np.mean(e[(t >= s - 0.08) & (t <= s - 0.03)]))
            a = float(np.mean(e[(t >= s + 0.03) & (t <= s + 0.08)]))
            steps.append(round(a - b, 2))
        # level steps elsewhere in the sustain (same 50 ms-apart comparison)
        m = (t >= 1.5) & (t <= OFF - 0.3)
        ee = e[m]
        k = int(0.11 / 0.005)
        other = np.abs(ee[k:] - ee[:-k])
        hits = click_scan(x, list(np.arange(ON + 0.05, OFF - 0.05, 0.025)))
        hits = list({h["t"]: h for h in hits}.values())
        for h in hits:
            h["to_nearest_seam_s"] = round(float(min(abs(h["t"] - s) for s in seams)), 3) if seams else None
        res[inst] = dict(key=key, sample=r["sample"], seams_s=[round(s, 3) for s in seams], seam_level_step_db=steps,
                         sustain_step_p99_db=round(float(np.percentile(other, 99)), 2),
                         sustain_step_max_db=round(float(other.max()), 2),
                         gated_click_hits=len(hits), hits_within_60ms_of_a_seam=sum(1 for h in hits if h["to_nearest_seam_s"] is not None and h["to_nearest_seam_s"] < 0.06),
                         hits=sorted(hits, key=lambda h: -h["re_fullband_db"])[:8])
    save("loop_long.json", res)
    print(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
