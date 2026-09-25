#!/usr/bin/env python3
"""Measure loudness and timbre per segment of a dynamics-test render.

Usage:
  python3 measure_dynamics.py RENDER.wav SEGMENTS.json [--voice "Violin I"] [--label NAME]

SEGMENTS.json is the sidecar written by make_test_midi.py.  Prints, per
segment (pp / mf / ff phrase and the 0-127-0 CC1 swell):
  RMS dBFS, A-weighted dB, spectral centroid (Hz) and the share of energy
  above 2 kHz (HF %).  A gain-only instrument keeps centroid and HF % constant
  across pp/mf/ff; real dynamic layers make both rise with loudness.
For the swell it also samples the sliding 0.5 s level/centroid at the CC1
values of pp, p, mp, mf, f, ff (rising, then falling) and reports the
correlation of level and centroid with CC1.  --json prints machine-readable output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import bilinear, lfilter


def a_weight(sr):
    f1, f2, f3, f4, a1000 = 20.598997, 107.65265, 737.86223, 12194.217, 1.9997
    nums = [(2 * np.pi * f4) ** 2 * (10 ** (a1000 / 20)), 0, 0, 0, 0]
    dens = np.polymul([1, 4 * np.pi * f4, (2 * np.pi * f4) ** 2], [1, 4 * np.pi * f1, (2 * np.pi * f1) ** 2])
    dens = np.polymul(np.polymul(dens, [1, 2 * np.pi * f3]), [1, 2 * np.pi * f2])
    return bilinear(nums, dens, sr)


def k_weight(x, sr=48000):
    """ITU-R BS.1770 K-weighting (48 kHz coefficients)."""
    assert sr == 48000
    y = lfilter([1.53512485958697, -2.69169618940638, 1.19839281085285],
                [1.0, -1.69065929318241, 0.73248077421585], x)
    return lfilter([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621], y)


def stats(x, sr, aw):
    m = x.mean(axis=1) if x.ndim == 2 else x
    rms = 10 * np.log10(np.mean(m ** 2) + 1e-20)
    a = lfilter(*aw, m)
    adb = 10 * np.log10(np.mean(a ** 2) + 1e-20)
    n = 1 << 14
    # Welch-style average spectrum
    frames = [m[i:i + n] * np.hanning(n) for i in range(0, max(1, len(m) - n), n // 2)]
    P = np.mean([np.abs(np.fft.rfft(f, n)) ** 2 for f in frames], axis=0)
    fr = np.fft.rfftfreq(n, 1 / sr)
    cen = float((P * fr).sum() / (P.sum() + 1e-20))
    hf = float(P[fr > 2000].sum() / (P.sum() + 1e-20) * 100)
    return dict(rms_db=round(float(rms), 2), a_db=round(float(adb), 2), centroid_hz=round(cen), hf_pct=round(hf, 2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", type=Path)
    ap.add_argument("segments", type=Path)
    ap.add_argument("--voice")
    ap.add_argument("--label", default="")
    ap.add_argument("--offset", type=float, default=0.0, help="seconds to add to segment times")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    x, sr = sf.read(str(a.wav), dtype="float64", always_2d=True)
    segs = json.loads(a.segments.read_text())
    voice = a.voice or next(iter(segs))
    aw = a_weight(sr)
    rows = []
    swell = None
    for s in segs[voice]:
        i0, i1 = int((s["start"] + a.offset) * sr), int((s["end"] + a.offset) * sr)
        st = stats(x[i0:i1], sr, aw)
        rows.append(dict(segment=s["label"], cc1=s["cc1"], **st))
        if s["label"] == "swell":
            swell = (i0, i1, s.get("lo", 0), s.get("hi", 127))
    res = dict(label=a.label or a.wav.stem, voice=voice, segments=rows)
    if swell:
        i0, i1, lo, hi = swell
        win, hop = int(0.5 * sr), int(0.1 * sr)
        pts = []
        for c in range(i0, i1 - win, hop):
            frac = (c + win / 2 - i0) / (i1 - i0)
            cc = lo + (hi - lo) * (1 - abs(2 * frac - 1))
            st = stats(x[c:c + win], sr, aw)
            pts.append((frac, cc, st["rms_db"], st["centroid_hz"], st["hf_pct"]))
        pts = np.array(pts)
        samples = []
        marks = [49, 62, 75, 88, 101, 114]                  # pp p mp mf f ff on perform.py's scale
        for target, rising in [(m, True) for m in marks] + [(hi, True)] + [(m, False) for m in marks[::-1]]:
            sel = pts[(pts[:, 0] <= 0.5) == rising] if target != hi else pts
            j = int(np.argmin(np.abs(sel[:, 1] - target)))
            samples.append(dict(cc1=target, dir="up" if rising else "down", rms_db=round(sel[j, 2], 1),
                                centroid_hz=int(sel[j, 3]), hf_pct=round(sel[j, 4], 2)))
        res["swell"] = dict(samples=samples,
                            corr_level_cc1=round(float(np.corrcoef(pts[:, 1], pts[:, 2])[0, 1]), 3),
                            corr_centroid_cc1=round(float(np.corrcoef(pts[:, 1], pts[:, 3])[0, 1]), 3),
                            corr_hf_cc1=round(float(np.corrcoef(pts[:, 1], pts[:, 4])[0, 1]), 3),
                            hf_pct_at_lo_hi=(round(float(np.median(pts[pts[:, 1] < lo + 8, 4])), 2),
                                             round(float(np.median(pts[pts[:, 1] > hi - 8, 4])), 2)),
                            level_range_db=round(float(pts[:, 2].max() - pts[:, 2].min()), 1))
    if a.json:
        print(json.dumps(res))
        return
    print(f"== {res['label']} ({voice})")
    print(f"{'segment':8s} {'cc1':>7s} {'RMS dBFS':>9s} {'A dB':>7s} {'centroid':>9s} {'HF>2k %':>8s}")
    for r in rows:
        print(f"{r['segment']:8s} {str(r['cc1']):>7s} {r['rms_db']:9.1f} {r['a_db']:7.1f} {r['centroid_hz']:9d} {r['hf_pct']:8.2f}")
    if swell:
        sw = res["swell"]
        print("swell  " + "  ".join(f"{s['cc1']}{'^' if s['dir'] == 'up' else 'v'}:{s['rms_db']:.1f}dB/{s['centroid_hz']}Hz"
                                    for s in sw["samples"]))
        print(f"swell  level range {sw['level_range_db']} dB, corr(level,CC1) {sw['corr_level_cc1']}, "
              f"corr(centroid,CC1) {sw['corr_centroid_cc1']}, corr(HF%,CC1) {sw['corr_hf_cc1']}, "
              f"HF% at ends/top {sw['hf_pct_at_lo_hi'][0]} -> {sw['hf_pct_at_lo_hi'][1]}")


if __name__ == "__main__":
    main()
