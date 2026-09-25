#!/usr/bin/env python3
"""Articulation of every note of the demo in the FINAL file at three hall levels.

For each note: rise of its own partials (those not shared, within 2 %, with the previous note of
the same voice) from the 150 ms before its onset to the 150 ms after (0.6 % bands). Computed on
the final mix, where the other voices and the hall can mask it. Renders: --no-reverb, --wet-db
-13 and the default -4 (all with --transpose pedal=-12).
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import band_power, db, midi_hz, midi_notes, read, write_json  # noqa: E402

P = Path("/tmp/pianoqa2")
LEAD = 0.3
TR = {"pedal": -12}


def main():
    notes = midi_notes(P / "demo.mid")
    byv = {}
    for n in notes:
        byv.setdefault(n["name"], []).append(n)
    out = {}
    for lab, f in (("no_reverb", "demo_dry.wav"), ("wet_-13", "demo_w13.wav"), ("wet_-4_default", "demo_j4.wav")):
        m = read(P / f).mean(axis=1)
        res = {}
        for v, lst in byv.items():
            r = []
            for i, n in enumerate(lst):
                k = n["key"] + TR.get(v, 0)
                t = n["start"] + LEAD
                prev = [p for p in lst[:i] if p["end"] > n["start"] - 0.45]
                pp = [midi_hz(p["key"] + TR.get(v, 0)) * q for p in prev for q in range(1, 21)]
                own = [x for x in (midi_hz(k) * q for q in range(1, 11)) if all(abs(x / g - 1) > 0.02 for g in pp)]
                if not own:
                    continue
                W = 0.15
                r.append(float(db(band_power(m, t + 0.01, t + 0.01 + W, own, rel_bw=0.006)) -
                               db(band_power(m, t - 0.01 - W, t - 0.01, own, rel_bw=0.006))))
            r = np.array(r)
            res[v] = dict(n=len(r), median_db=round(float(np.median(r)), 1), p10_db=round(float(np.percentile(r, 10)), 1),
                          n_below_3db=int((r < 3).sum()))
        out[lab] = res
    write_json(Path(__file__).parent / "results/demo_clarity.json", out)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
