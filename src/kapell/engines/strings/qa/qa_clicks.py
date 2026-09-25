#!/usr/bin/env python3
"""Clicks / pops, independently of qa_render.py's detector.

  python3 qa_clicks.py [JOB_DIR ...]      (default: the kept dry job WAVs of the QA fugue)

Two detectors on every dry job WAV (one voice, untrimmed, t = MIDI time) and on
the final mix:
  hf_burst   0.5 ms frames of the >4 kHz band more than 18 dB above the median of
             the surrounding 40 ms and 10 dB above the frames 2 ms either side,
             and within 30 dB of the signal's own 100 ms level (audible)
  step       |second difference| more than 12x the local (10 ms) RMS of the
             second difference -- a waveform discontinuity (sample start at a
             non-zero value, a loop seam, a truncated release)
Each event is reported with the nearest note-on / note-off of that job.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import mido
import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import butter, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import SR, TMP, load, save, state  # noqa: E402


def frames_db(x, n):
    m = len(x) // n
    return 10 * np.log10(np.mean(x[: m * n].reshape(m, n) ** 2, axis=1) + 1e-20)


def detect(x, bounds):
    sos = butter(4, 4000, "highpass", fs=SR, output="sos")
    h = sosfilt(sos, x)
    e = frames_db(h, 24)                         # 0.5 ms
    full = frames_db(x, 24)
    full100 = 10 * np.log10(np.maximum(uniform_filter1d(10 ** (full / 10), 200), 0) + 1e-20)
    med = median_filter(e, size=81, mode="nearest")
    side = np.maximum(np.roll(e, 4), np.roll(e, -4))
    idx = np.flatnonzero((e > med + 18) & (e > side + 10) & (e > full100 - 30) & (full100 > full100.max() - 70))
    ev = []
    last = -1
    for i in idx:
        if i - last < 20:
            continue
        last = i
        t = i * 24 / SR
        near = float(bounds[np.argmin(np.abs(bounds - t))] - t) if len(bounds) else None
        ev.append(dict(t=round(t, 4), kind="hf_burst", db_over_median=round(float(e[i] - med[i]), 1),
                       db_re_level=round(float(e[i] - full100[i]), 1),
                       nearest_boundary_ms=None if near is None else round(1000 * near, 1)))
    d2 = np.abs(np.diff(x, 2))
    loc = np.sqrt(np.maximum(uniform_filter1d(d2 ** 2, 480), 0) + 1e-24)
    lvl = np.sqrt(np.maximum(uniform_filter1d(x[1:-1] ** 2, 4800), 0) + 1e-24)
    idx2 = np.flatnonzero((d2 > 12 * loc) & (lvl > np.sqrt(np.mean(x ** 2)) * 10 ** (-40 / 20)))
    last = -10 ** 9
    for i in idx2:
        if i - last < 480:
            continue
        last = i
        t = (i + 1) / SR
        near = float(bounds[np.argmin(np.abs(bounds - t))] - t) if len(bounds) else None
        ev.append(dict(t=round(t, 4), kind="step", ratio=round(float(d2[i] / loc[i]), 1),
                       nearest_boundary_ms=None if near is None else round(1000 * near, 1)))
    return ev


def main():
    dirs = [Path(p) for p in sys.argv[1:]] or [TMP / "jobs_fugue"]
    res = dict(state=state(), jobs={})
    for d in dirs:
        for wav in sorted(d.glob("j*.wav")):
            mid = wav.with_suffix(".mid")
            b = []
            if mid.exists():
                t = 0.0
                for m in mido.MidiFile(str(mid)):
                    t += m.time
                    if m.type in ("note_on", "note_off"):
                        b.append(t)
            x = load(wav)
            ev = detect(x, np.array(sorted(b)))
            res["jobs"][f"{d.name}/{wav.name}"] = dict(seconds=round(len(x) / SR, 1), events=len(ev),
                                                        hf_bursts=sum(e["kind"] == "hf_burst" for e in ev),
                                                        steps=sum(e["kind"] == "step" for e in ev), list=ev[:25])
            print(f"{d.name}/{wav.name}: {len(ev)} events", ev[:6])
    # detector self-test: plant a 1-sample step (0.3 % of full scale) and a 0.3 ms burst into the viola job
    x = load(TMP / "jobs_fugue" / "j1_va.wav").copy()
    rms = float(np.sqrt(np.mean(x[int(20 * SR): int(21 * SR)] ** 2)))
    x[int(20.5 * SR):] += 0.5 * rms * np.exp(-np.arange(len(x) - int(20.5 * SR)) / 2000.0)
    x[int(30.2 * SR): int(30.2 * SR) + 15] += 0.5 * rms * np.random.default_rng(1).standard_normal(15)
    ev = detect(x, np.array([]))
    res["self_test"] = dict(planted=[20.5, 30.2], found=[e["t"] for e in ev], rms=rms)
    print("self-test planted 20.5 / 30.2 s, found", [(e["t"], e["kind"]) for e in ev])
    mix = TMP / "fugue_qa.wav"
    if mix.exists():
        x = load(mix)
        rep = json.loads((TMP / "fugue_qa.json").read_text())
        b = np.array(sorted(v for j in rep["jobs"] for n in j["note_list"] for v in (n[0], n[1])))
        ev = detect(x, b - rep["offset_s"])
        res["mix"] = dict(events=len(ev), list=ev[:25])
        print("mix:", len(ev), ev[:6])
    p = save("clicks.json", res)
    print("->", p)


if __name__ == "__main__":
    main()
