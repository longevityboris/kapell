#!/usr/bin/env python3
"""Pitch during the first 250 ms of every stroke (what short notes consist of).

verify_tuning.py measures the median pitch over the steady part of a 2 s note,
which is what long notes hear.  A 16th note at 64 bpm lasts 0.23 s and is made
only of the sample's attack.  This renders every key x layer (CC1 49 / 88 / 114)
x stroke (CC20 short 112 / normal 0) of each built instrument straight through
sfizz (the renderer's engine and SFZ), 0.25 s notes 1.2 s apart, and measures
the pitch in 50 ms frames (5 periods for low notes) centred at 40, 80, 120, 160
and 200 ms after the note-on, plus the median over 40-200 ms.

  python3 qa_attack_pitch.py [--inst violin,violin2,viola,cello,bass]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import QUARTET, SR, TMP, hz, load, pitch_spectral, save, state  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iowa_common import INSTRUMENTS, SFIZZ_RENDER  # noqa: E402

LAYERS = [("pp", 49), ("mf", 88), ("ff", 114)]
STROKES = [("short", 112, 6), ("normal", 0, 18)]       # CC20, CC21 as render_quartet sets them
NOTE_S, STEP_S = 0.25, 1.2
FRAMES_MS = [40, 80, 120, 160, 200]


def make_midi(keys, cc20, cc21, path):
    mf = mido.MidiFile(type=0, ticks_per_beat=960)
    tr = mido.MidiTrack()
    mf.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000))      # 1920 ticks / s
    ev, sched = [], []
    t = 0.2
    for lname, cc1 in LAYERS:
        for k in keys:
            ev += [(t - 0.05, 0, mido.Message("control_change", control=1, value=cc1)),
                   (t - 0.01, 1, mido.Message("control_change", control=20, value=cc20)),
                   (t - 0.01, 1, mido.Message("control_change", control=21, value=cc21)),
                   (t, 3, mido.Message("note_on", note=k, velocity=64)),
                   (t + NOTE_S, 2, mido.Message("note_off", note=k, velocity=0))]
            sched.append((lname, k, t))
            t += STEP_S
    ev.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for s, _, m in ev:
        tk = int(round(s * 1920))
        tr.append(m.copy(time=tk - last))
        last = tk
    mf.save(str(path))
    return sched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", default="violin,violin2,viola,cello,bass")
    a = ap.parse_args()
    d = TMP / "attack"
    d.mkdir(parents=True, exist_ok=True)
    res = dict(state=state(), frames_ms=FRAMES_MS, instruments={})
    for inst in a.inst.split(","):
        lo, hi = INSTRUMENTS[inst]["lo"], INSTRUMENTS[inst]["hi"]
        keys = list(range(lo - 2, hi + 1))
        ir = res["instruments"][inst] = {}
        for sname, cc20, cc21 in STROKES:
            mid = d / f"{inst}_{sname}.mid"
            wav = d / f"{inst}_{sname}.wav"
            sched = make_midi(keys, cc20, cc21, mid)
            subprocess.run([str(SFIZZ_RENDER), "--sfz", str(QUARTET / f"{inst}.sfz"), "--midi", str(mid),
                            "--wav", str(wav), "-s", str(SR), "-q", "3"], check=True, capture_output=True)
            x = load(wav)
            rows = []
            for lname, k, t in sched:
                W = int(max(0.05 * SR, 5 * SR / hz(k)))
                cs = []
                for fm in FRAMES_MS:
                    c = int((t + fm / 1000) * SR)
                    m, _ = pitch_spectral(x[c - W // 2: c + W // 2], k, span=3)
                    cs.append(round(100 * (m - k), 1))
                seg = x[int((t + 0.04) * SR): int((t + 0.2) * SR)]
                m, _ = pitch_spectral(seg, k, span=3)
                rows.append(dict(layer=lname, key=k, frames_cents=cs, median_40_200_cents=round(100 * (m - k), 1)))
            bad = [r for r in rows if abs(r["median_40_200_cents"]) > 25]
            worst = sorted(rows, key=lambda r: -abs(r["median_40_200_cents"]))[:10]
            ir[sname] = dict(notes=len(rows),
                             median_abs_cents=round(float(np.median([abs(r["median_40_200_cents"]) for r in rows])), 1),
                             p90_abs_cents=round(float(np.percentile([abs(r["median_40_200_cents"]) for r in rows], 90)), 1),
                             over_25c=len(bad), over_50c=sum(abs(r["median_40_200_cents"]) > 50 for r in rows),
                             worst=worst, rows=rows)
            print(f"{inst:8s} {sname:6s} n={len(rows)} median|c|={ir[sname]['median_abs_cents']} "
                  f"p90={ir[sname]['p90_abs_cents']} >25c: {len(bad)} >50c: {ir[sname]['over_50c']}  worst: "
                  + ", ".join(f"{w['layer']}/{w['key']}:{w['median_40_200_cents']:+.0f}" for w in worst[:6]))
    p = save("attack_pitch.json", res)
    print("->", p)


if __name__ == "__main__":
    main()
