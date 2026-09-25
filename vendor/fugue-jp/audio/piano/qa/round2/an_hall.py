#!/usr/bin/env python3
"""How wet is the default hall, measured on program material rather than on a white impulse.

1. IR per octave band: T20, EDT, and C80 with the dry path added (dry band energy = the band
   filter's own impulse energy), at the default --wet-db -4.
2. The demo (dry stems summed, as render_piano.py does): reverb-to-dry energy per octave band and
   broadband, and program C80 (dry + first 80 ms of the IR vs the rest), per band.
3. fast16 probe rendered at --wet-db -4 (default), -8, -13 and without reverb: for every 16th,
   the rise of its own partials (not shared with the previous note) from the 50 ms before its
   onset to the 50 ms after (articulation contrast in the final file).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import SR, band_power, db, midi_hz, midi_notes, read, write_json  # noqa: E402

P = Path("/tmp/pianoqa2")
IR = Path.home() / "Music/SampleLibraries/IR/Detmold-Konzerthaus-S1R163-MS-48k.wav"
BANDS = (63, 125, 250, 500, 1000, 2000, 4000)
LEAD = 0.3


def octave(fc):
    return ss.butter(3, [fc / 2 ** 0.5, min(fc * 2 ** 0.5, 23000)], "band", fs=SR, output="sos")


def ir_bands(ir, g):
    imp = np.zeros(len(ir))
    imp[0] = 1
    n80 = int(0.08 * SR)
    out = {}
    for fc in BANDS:
        sos = octave(fc)
        ed = float(np.sum(ss.sosfilt(sos, imp) ** 2))
        e = (ss.sosfilt(sos, ir, axis=0) ** 2).sum(axis=1) / 2
        sch = np.cumsum(e[::-1])[::-1]
        sch = 10 * np.log10(sch / sch[0] + 1e-30)
        t = np.arange(len(sch)) / SR

        def tx(a, b):
            i = np.nonzero(sch <= a)[0][0]
            j = np.nonzero(sch <= b)[0][0]
            return -60 / np.polyfit(t[i:j], sch[i:j], 1)[0]
        out[fc] = dict(T20_s=round(float(tx(-5, -25)), 2), EDT_s=round(float(tx(-0.01, -10)), 2),
                       C80_with_dry_db=round(10 * math.log10((ed + g * g * e[:n80].sum()) / (g * g * e[n80:].sum())), 1),
                       wet_re_dry_white_db=round(10 * math.log10(g * g * e.sum() / ed), 1))
    return out


def program(stems_dir, names, ir, g):
    st = [read(stems_dir / f"{n}.wav") for n in names]
    n = max(len(s) for s in st)
    dry = sum(np.pad(s, ((0, n - len(s)), (0, 0))) for s in st)
    n80 = int(0.08 * SR)
    early = np.stack([ss.fftconvolve(dry[:, c], ir[:n80, c]) for c in range(2)], axis=1) * g
    late = np.stack([ss.fftconvolve(dry[:, c], ir[n80:, c]) for c in range(2)], axis=1) * g
    L = len(late) + n80
    dryp = np.pad(dry, ((0, L - len(dry)), (0, 0)))
    earlyp = np.pad(early, ((0, L - len(early)), (0, 0)))
    latep = np.pad(late, ((n80, 0), (0, 0)))[:L]
    e = lambda x: float(np.sum(x ** 2))  # noqa: E731
    res = {"broadband": dict(wet_re_dry_db=round(10 * math.log10((e(earlyp + latep)) / e(dryp)), 1),
                             C80_program_db=round(10 * math.log10(e(dryp + earlyp) / e(latep)), 1))}
    for fc in BANDS:
        sos = octave(fc)
        a, b, c = (ss.sosfilt(sos, y, axis=0) for y in (dryp, earlyp, latep))
        res[fc] = dict(wet_re_dry_db=round(10 * math.log10(e(b + c) / e(a)), 1),
                       C80_program_db=round(10 * math.log10(e(a + b) / e(c)), 1),
                       share_of_dry_energy_db=round(10 * math.log10(e(a) / e(dryp)), 1))
    return res


def articulation(path):
    meta = json.loads((P / "fast16.meta.json").read_text())
    notes = midi_notes(P / "fast16.mid")
    m = read(path).mean(axis=1)
    out = {}
    for lab, (t0, t1, d16) in meta["segments"].items():
        sn = [n for n in notes if t0 - 1e-6 <= n["start"] < t1]
        rises = []
        for a, b in zip(sn[:-1], sn[1:]):
            tb = b["start"] + LEAD
            pa = [midi_hz(a["key"]) * q for q in range(1, 16)]
            own = [f for f in (midi_hz(b["key"]) * q for q in range(1, 9)) if all(abs(f / h - 1) > 0.03 for h in pa)]
            rises.append(float(db(band_power(m, tb + 0.005, tb + 0.055, own)) - db(band_power(m, tb - 0.055, tb - 0.005, own))))
        out[lab] = dict(median_db=round(float(np.median(rises)), 1), min_db=round(float(np.min(rises)), 1))
    return out


def main():
    ir = read(IR)
    g = 10 ** (-4 / 20)
    res = {"ir_bands_at_wet_-4": ir_bands(ir, g)}
    rep = json.loads((P / "demo_j4.render.json").read_text())
    res["render_report_c80_db"] = rep["c80_db"]
    res["demo_program_at_wet_-4"] = program(P / "demo_j4_stems", list(rep["voices"]), ir, g)
    res["fast16_articulation_rise_db"] = {
        "no_reverb": articulation(P / "fast16_dry.wav"),
        "wet_-13": articulation(P / "fast16_w-13.wav"),
        "wet_-8": articulation(P / "fast16_w-8.wav"),
        "wet_-4 (default)": articulation(P / "fast16.wav"),
    }
    write_json(Path(__file__).parent / "results/hall.json", res)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
