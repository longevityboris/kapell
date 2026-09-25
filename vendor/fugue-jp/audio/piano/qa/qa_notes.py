#!/usr/bin/env python3
"""Isolated-note QA of render_piano.py: onset latency, pitch, release, clicks, stereo, evenness.

Every key A0..C8 is struck alone at velocities 30, 70, 110 (raw scale, no reverb),
held 0.8 s and released, 2.2 s apart. Each rendered note is measured on the dry stem:

* onset latency: note-on -> first sample above -20 dB of the note's peak (ms)
* pitch: partial 1 (and partial 2 / 2) over 0.15-0.75 s after onset, cents vs 12-TET A440
* release: level 60-110 ms before note-off vs 150/300 ms after it, time to -20 dB
* note-off transient: peak in the 40 ms after note-off vs the 40 ms before (dB)
* stereo: L/R balance, correlation, mono fold-down loss
* evenness: RMS of the first 400 ms at a fixed velocity across the keyboard

Also a velocity sweep (every velocity 1..127) on A2, C4, C6: level and HF ratio per velocity.

    python3 qa/qa_notes.py        # writes qa/results/notes.json, audio under /tmp/pianoqa
"""

from __future__ import annotations

import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, SR, TMP, db, f0_estimate, kweight, read, render, rms_db, save, write_midi  # noqa: E402

HOLD = 0.8
STEP = 2.2
KEYS = list(range(21, 109))
VELS = [20, 30, 45, 70, 110]


def iso_midi(path: Path, vel: int) -> list[tuple[int, float, float]]:
    evs, notes = [], []
    for i, k in enumerate(KEYS):
        t = 0.2 + i * STEP
        evs.append((t, mido.Message("note_on", note=k, velocity=vel)))
        evs.append((t + HOLD, mido.Message("note_off", note=k, velocity=0)))
        notes.append((k, t, t + HOLD))
    write_midi(path, {"solo": evs})
    return notes


def analyse_iso(x: np.ndarray, notes) -> list[dict]:
    out = []
    for k, t_on, t_off in notes:
        a = int((t_on + LEAD_IN - 0.05) * SR)
        b = int((t_on + LEAD_IN + STEP - 0.1) * SR)
        seg = x[a:b]
        env = np.abs(seg).max(axis=1)
        pk = env.max()
        on_idx = int(np.argmax(env > pk * 0.1))
        lat_ms = (a + on_idx) / SR * 1000 - (t_on + LEAD_IN) * 1000
        # pitch
        s0 = int((t_on + LEAD_IN + 0.15) * SR)
        s1 = int((t_on + LEAD_IN + 0.75) * SR)
        f1 = f0_estimate(x[s0:s1], k, 1)
        f2 = f0_estimate(x[s0:s1], k, 2)
        fet = 440 * 2 ** ((k - 69) / 12)
        c1 = 1200 * np.log2(f1 / fet) if f1 else None
        c2 = 1200 * np.log2(f2 / fet) if f2 else None
        # release
        off = int((t_off + LEAD_IN) * SR)

        def lvl(t0, t1):
            return rms_db(x[off + int(t0 * SR): off + int(t1 * SR)])
        before = lvl(-0.110, -0.060)
        after150 = lvl(0.125, 0.175)
        after300 = lvl(0.275, 0.325)
        # time to -20 dB after note-off (10 ms frames)
        fr = int(0.010 * SR)
        tail = x[off: off + int(1.2 * SR)]
        nfr = len(tail) // fr
        e = np.array([rms_db(tail[i * fr:(i + 1) * fr]) for i in range(nfr)])
        ref = rms_db(x[off - fr: off])
        below = np.nonzero(e < ref - 20)[0]
        t20 = float(below[0] * 0.010) if len(below) else None
        # natural decay just before note-off (dB/s) from 0.45..0.75 s after onset
        pre_a = lvl(-(HOLD - 0.45), -(HOLD - 0.50))
        pre_b = lvl(-(HOLD - 0.70), -(HOLD - 0.75))
        natural = (pre_b - pre_a) / 0.25
        # note-off transient
        pk_before = 20 * np.log10(np.abs(x[off - int(0.04 * SR): off]).max() + 1e-20)
        pk_after = 20 * np.log10(np.abs(x[off: off + int(0.04 * SR)]).max() + 1e-20)
        # stereo over the first 600 ms
        st = x[a + on_idx: a + on_idx + int(0.6 * SR)]
        L, R = st[:, 0], st[:, 1]
        corr = float(np.corrcoef(L, R)[0, 1])
        bal = db(np.mean(L ** 2)) - db(np.mean(R ** 2))
        mono_loss = db(np.mean(((L + R) / 2) ** 2)) - db(np.mean((L ** 2 + R ** 2) / 2))
        rms400 = rms_db(st[: int(0.4 * SR)])
        k400 = rms_db(kweight(x[a + on_idx - int(0.05 * SR): a + on_idx + int(0.4 * SR)])[int(0.05 * SR):])
        out.append(dict(key=k, latency_ms=round(lat_ms, 2), peak_dbfs=round(20 * np.log10(pk), 2),
                        rms400_db=round(rms400, 2), k400_db=round(k400, 2),
                        cents_p1=None if c1 is None else round(float(c1), 1),
                        cents_p2=None if c2 is None else round(float(c2), 1),
                        rel_before_db=round(before, 1), rel_after150_db=round(after150, 1),
                        rel_after300_db=round(after300, 1), release_t20_s=t20,
                        natural_decay_db_s=round(natural, 1),
                        noteoff_peak_jump_db=round(float(pk_after - pk_before), 2),
                        lr_balance_db=round(bal, 2), lr_corr=round(corr, 3), mono_loss_db=round(mono_loss, 2)))
    return out


def sweep_midi(path: Path, key: int) -> list[tuple[int, float]]:
    evs, notes = [], []
    for v in range(1, 128):
        t = 0.2 + (v - 1) * 1.0
        evs.append((t, mido.Message("note_on", note=key, velocity=v)))
        evs.append((t + 0.5, mido.Message("note_off", note=key, velocity=0)))
        notes.append((v, t))
    write_midi(path, {"solo": evs})
    return notes


def hf_ratio_db(seg: np.ndarray, fc: float = 2000.0) -> tuple[float, float]:
    m = seg.mean(axis=1)
    p = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2
    f = np.fft.rfftfreq(len(m), 1 / SR)
    sel = f > 30
    cen = float((f[sel] * p[sel]).sum() / p[sel].sum())
    return db(p[f > fc].sum() / p[sel].sum()), cen


def main() -> None:
    TMP.mkdir(exist_ok=True)
    res = {"iso": {}, "sweep": {}}
    for vel in VELS:
        mid = TMP / f"iso_v{vel}.mid"
        notes = iso_midi(mid, vel)
        rep = render(mid, TMP / f"iso_v{vel}", "--no-reverb", "--no-m4a")
        x = read(TMP / f"iso_v{vel}_stems" / "solo.wav")
        res["iso"][vel] = {"normalise_gain_db": rep["normalise_gain_db"], "notes": analyse_iso(x, notes)}
        print(f"iso v{vel}: done")
    for key in (45, 60, 84):
        mid = TMP / f"sweep_{key}.mid"
        notes = sweep_midi(mid, key)
        render(mid, TMP / f"sweep_{key}", "--no-reverb", "--no-m4a")
        x = read(TMP / f"sweep_{key}_stems" / "solo.wav")
        rows = []
        for v, t in notes:
            a = int((t + LEAD_IN) * SR)
            seg = x[a: a + int(0.4 * SR)]
            hf, cen = hf_ratio_db(seg)
            rows.append(dict(vel=v, rms_db=round(rms_db(seg), 2), hf_db=round(hf, 2), centroid_hz=round(cen, 1)))
        top = rows[-1]["rms_db"]
        for r in rows:
            r["rel127_db"] = round(r["rms_db"] - top, 2)
        res["sweep"][key] = rows
        print(f"sweep {key}: done")
    save("notes_raw", res)


if __name__ == "__main__":
    main()
