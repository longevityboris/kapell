#!/usr/bin/env python3
"""Round-2 tuning ladder: every key of every instrument's compass at pp / mf / ff (CC1 49 / 88 / 114),
1.2 s notes through render_quartet.py (normal strokes), pitch of the steady part (0.45-1.05 s after the
note-on) by the frame-harmonic and YIN estimators, plus the attack (40-200 ms).  Tolerance of the task: ~5 c.

  python3 an_ladder.py [--reuse]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import SR, TMP, cents, pitch_fft, pitch_yin, render, save  # noqa: E402

COMPASS = {"vn1": ("soprano", 0, 40, 53, 100), "vn2": ("alto", 1, 40, 53, 100), "va": ("tenor", 2, 41, 46, 91),
           "vc": ("bass", 3, 42, 34, 81)}
LAYERS = (("pp", 49), ("mf", 88), ("ff", 114))
STEP = 1.6
DUR = 1.2


def build(path):
    mf = mido.MidiFile(type=1, ticks_per_beat=960)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage("set_tempo", tempo=500000))
    mf.tracks.append(t0)
    plan = {}
    for inst, (name, ch, prog, lo, hi) in COMPASS.items():
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        tr.append(mido.Message("program_change", channel=ch, program=prog))
        tr.append(mido.Message("control_change", channel=ch, control=11, value=100))
        ev, rows = [], []
        t = 0.5
        for lay, c in LAYERS:
            for k in range(lo, hi + 1):
                ev.append((t - 0.3, 0, mido.Message("control_change", channel=ch, control=1, value=c)))
                ev.append((t, 2, mido.Message("note_on", channel=ch, note=k, velocity=80)))
                ev.append((t + DUR, 1, mido.Message("note_off", channel=ch, note=k, velocity=0)))
                rows.append((lay, k, t))
                t += STEP
        ev.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for tt, _, m in ev:
            tk = int(round(tt * 1920))
            tr.append(m.copy(time=tk - last))
            last = tk
        mf.tracks.append(tr)
        plan[inst] = rows
    mf.save(str(path))
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    TMP.mkdir(exist_ok=True)
    mid = TMP / "ladder.mid"
    plan = build(mid)
    out = TMP / "ladder"
    if not (a.reuse and Path(f"{out}.json").exists()):
        render(mid, out, "--keep-start", keep_temp=False)
    rep = json.loads(Path(f"{out}.json").read_text())
    res = dict(per_inst={}, worst=[], log=rep["notes"])
    allrows = []
    for inst, rows in plan.items():
        x, _ = sf.read(f"{out}_stem_{inst}.wav", always_2d=True)
        x = x.mean(axis=1)
        vals = []
        for lay, k, t in rows:
            seg = x[int((t + 0.45) * SR): int((t + 1.05) * SR)]
            att = x[int((t + 0.04) * SR): int((t + 0.2) * SR)]
            c1, c2 = cents(pitch_fft(seg, k), k), cents(pitch_yin(seg, k), k)
            ca = cents(pitch_yin(att, k), k)
            c = 0.5 * (c1 + c2) if c1 is not None and c2 is not None else (c1 if c1 is not None else c2)
            r = dict(inst=inst, layer=lay, key=k, c_fft=None if c1 is None else round(c1, 1),
                     c_yin=None if c2 is None else round(c2, 1), c=None if c is None else round(c, 1),
                     attack_c=None if ca is None else round(ca, 1),
                     level_db=round(float(10 * np.log10(np.mean(seg ** 2) + 1e-20)), 1))
            vals.append(r)
            allrows.append(r)
        cs = np.array([abs(r["c"]) for r in vals if r["c"] is not None])
        ats = np.array([abs(r["attack_c"]) for r in vals if r["attack_c"] is not None])
        res["per_inst"][inst] = dict(n=len(vals), measured=len(cs), median_abs_c=round(float(np.median(cs)), 2),
                                     p95_abs_c=round(float(np.percentile(cs, 95)), 2), max_abs_c=round(float(cs.max()), 1),
                                     over5=int(np.sum(cs > 5)), over10=int(np.sum(cs > 10)), over15=int(np.sum(cs > 15)),
                                     attack_median_abs_c=round(float(np.median(ats)), 1), attack_over15=int(np.sum(ats > 15)),
                                     attack_over30=int(np.sum(ats > 30)),
                                     estimator_disagree_gt3=int(sum(1 for r in vals if r["c_fft"] is not None and r["c_yin"] is not None
                                                                    and abs(r["c_fft"] - r["c_yin"]) > 3)),
                                     unmeasured=[(r["layer"], r["key"]) for r in vals if r["c"] is None])
    res["worst"] = sorted([r for r in allrows if r["c"] is not None], key=lambda r: -abs(r["c"]))[:25]
    res["worst_attack"] = sorted([r for r in allrows if r["attack_c"] is not None], key=lambda r: -abs(r["attack_c"]))[:15]
    res["rows"] = allrows
    save("ladder.json", res)
    print(json.dumps(res["per_inst"], indent=1))
    for r in res["worst"][:15]:
        print(r)


if __name__ == "__main__":
    main()
