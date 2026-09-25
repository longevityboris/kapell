#!/usr/bin/env python3
"""Velocity sweep (probe 'velsweep'): C2, C4, C6 struck at velocity 1, 3, ..., 127.

Per strike: level (energy of the first 300 ms), spectral centroid and HF ratio (>2 kHz) of the
first 300 ms, and pitch of partial 1 (C4, C6) or the energy-weighted partials 2-6 (C2).
Looks for: non-monotonic level, level steps between neighbouring velocities (a crescendo of
successive notes would step), timbre jumps at the sample-layer boundaries, layers tuned apart.
"""
import math
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import SR, db, midi_hz, midi_notes, read, write_json  # noqa: E402

LEAD = 0.3
P = Path("/tmp/pianoqa2")
SFZ = Path.home() / "Music/SampleLibraries/SalamanderGrandPiano/SalamanderGrandPiano-SFZ+FLAC-V3+20200602/SalamanderGrandPiano-Ricercar.sfz"


def layer_bounds(key):
    b = []
    for line in SFZ.read_text().splitlines():
        if not line.startswith("<region> sample=samples-aligned/"):
            continue
        d = dict(t.split("=", 1) for t in line.split()[1:] if "=" in t)
        if int(d["lokey"]) <= key <= int(d["hikey"]):
            b.append(int(d["lovel"]))
    return sorted(set(b))


def spec_stats(m, t0, t1):
    a, b = int(t0 * SR), int(t1 * SR)
    seg = m[a:b] * np.hanning(b - a)
    sp = np.abs(np.fft.rfft(seg, n=1 << 16)) ** 2
    fr = np.fft.rfftfreq(1 << 16, 1 / SR)
    tot = sp.sum()
    return float((fr * sp).sum() / tot), float(10 * np.log10(sp[fr > 2000].sum() / tot + 1e-30))


def pitch(m, t0, t1, key):
    a, b = int(t0 * SR), int(t1 * SR)
    seg = m[a:b] * np.hanning(b - a)
    nfft = 1 << 20
    sp = np.abs(np.fft.rfft(seg, n=nfft))
    fr = np.fft.rfftfreq(nfft, 1 / SR)
    ps = [1] if key >= 45 else [2, 3, 4, 5, 6]
    cs, ws = [], []
    for p in ps:
        fc = p * midi_hz(key)
        sel = np.nonzero((fr > fc * 2 ** (-60 / 1200)) & (fr < fc * 2 ** (60 / 1200)))[0]
        i = sel[np.argmax(sp[sel])]
        y0, y1, y2 = np.log(sp[i - 1:i + 2] + 1e-20)
        d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
        cs.append(1200 * math.log2((i + d) * SR / nfft / fc))
        ws.append(sp[i] ** 2)
    return float(np.sum(np.array(cs) * ws) / np.sum(ws))


def main():
    res = {}
    for nm in ("c2", "c4", "c6"):
        x = read(P / f"velsweep_stems/{nm}.wav")
        m = x.mean(axis=1)
        notes = [n for n in midi_notes(P / "velsweep.mid") if n["name"] == nm]
        key = notes[0]["key"]
        rows = []
        for n in notes:
            t = n["start"] + LEAD
            a, b = int(t * SR), int((t + 0.3) * SR)
            lvl = float(10 * np.log10(np.mean(m[a:b] ** 2) + 1e-30))
            c, hf = spec_stats(m, t, t + 0.3)
            rows.append(dict(vel=n["vel"], level_db=round(lvl, 2), centroid_hz=round(c, 1), hf_db=round(hf, 2),
                             cents=round(pitch(m, t + 0.05, t + 0.43, key), 2)))
        lv = np.array([r["level_db"] for r in rows])
        vel = np.array([r["vel"] for r in rows])
        ce = np.array([r["centroid_hz"] for r in rows])
        hf = np.array([r["hf_db"] for r in rows])
        cents = np.array([r["cents"] for r in rows])
        bounds = layer_bounds(key)
        dl = np.diff(lv)
        dhf = np.diff(hf)
        # timbre jump at a boundary vs the typical within-layer change per step
        at_b = [i for i in range(len(vel) - 1) if any(vel[i] < bb <= vel[i + 1] for bb in bounds[1:])]
        within = [i for i in range(len(vel) - 1) if i not in at_b]
        res[nm] = dict(
            key=int(key), layer_lovel=bounds,
            level_span_db=round(float(lv.max() - lv.min()), 1),
            level_v1_v31_v63_v95_v127=[float(lv[np.searchsorted(vel, v)]) for v in (1, 31, 63, 95, 127)],
            non_monotonic_steps=[(int(vel[i]), int(vel[i + 1]), round(float(dl[i]), 2)) for i in range(len(dl)) if dl[i] < -0.3],
            max_level_step_db=round(float(dl.max()), 2), max_level_step_at=[int(vel[int(np.argmax(dl))]), int(vel[int(np.argmax(dl)) + 1])],
            level_step_at_boundaries_db=[(int(vel[i + 1]), round(float(dl[i]), 2)) for i in at_b],
            hf_jump_at_boundaries_db=[(int(vel[i + 1]), round(float(dhf[i]), 2)) for i in at_b],
            hf_step_within_layers_median_abs_db=round(float(np.median(np.abs(dhf[within]))), 2),
            centroid_v1_v63_v127=[float(ce[0]), float(ce[np.searchsorted(vel, 63)]), float(ce[-1])],
            hf_v1_v63_v127=[float(hf[0]), float(hf[np.searchsorted(vel, 63)]), float(hf[-1])],
            corr_level_vs_velocity=round(float(np.corrcoef(vel, lv)[0, 1]), 4),
            corr_hf_vs_velocity=round(float(np.corrcoef(vel, hf)[0, 1]), 4),
            cents_range=[float(cents.min()), float(cents.max())],
            cents_by_layer={int(bb): round(float(np.median(cents[(vel >= bb) & (vel < (bounds + [128])[k + 1])])), 2)
                            for k, bb in enumerate(bounds) if ((vel >= bb) & (vel < (bounds + [128])[k + 1])).any()},
            rows=rows,
        )
    write_json(Path(__file__).parent / "results/velsweep.json", res)
    for nm, r in res.items():
        print(nm, {k: v for k, v in r.items() if k != "rows"})


if __name__ == "__main__":
    main()
