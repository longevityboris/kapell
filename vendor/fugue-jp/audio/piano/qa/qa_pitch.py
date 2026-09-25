#!/usr/bin/env python3
"""Pitch QA: every key A0..C8 at velocity 70, held 3 s, dry. Partials 1..10 are located
(zero-padded FFT over 0.1-2.6 s, parabolic interpolation) and fitted with the stiff-string
model f_n = n f0 sqrt(1 + B n^2). Reports f0 in cents vs 12-TET (A4 = 440 Hz), B, the
deviation of every key from a smooth stretch curve, and semitone steps across sample-group
boundaries (each Salamander sample serves three keys). Also checks --transpose pedal=-12
moves a note by exactly 1200 cents.

    python3 qa/qa_pitch.py      # writes qa/results/pitch.json
"""
from __future__ import annotations

import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, SR, TMP, read, render, save, write_midi  # noqa: E402

N = mido.Message
HOLD, STEP = 3.0, 3.6


def partials(seg: np.ndarray, key: int, nmax: int = 10):
    m = seg.mean(axis=1)
    n = 1 << 22
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m)), n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    fet = 440 * 2 ** ((key - 69) / 12)
    out = []
    fprev = None
    for k in range(1, nmax + 1):
        # search around the inharmonic expectation from the previous partial
        guess = k * fet if fprev is None else fprev * k / (k - 1) * 1.0005
        if guess > 12000:
            break
        band = (freqs > guess * 2 ** (-45 / 1200)) & (freqs < guess * 2 ** (45 / 1200))
        i = int(np.argmax(np.where(band, spec, 0)))
        a, b, c = np.log(spec[i - 1: i + 2] + 1e-30)
        den = a - 2 * b + c
        p = 0.5 * (a - c) / den if den != 0 else 0.0
        f = (i + p) * SR / n
        # keep only clear peaks (>= 12 dB over the band median)
        if 20 * np.log10(spec[i] / (np.median(spec[band]) + 1e-30)) >= 12:
            out.append((k, f))
            fprev = f
    return out


def fit(ps):
    ks = np.array([k for k, _ in ps], float)
    fs = np.array([f for _, f in ps])
    # (f_n/n)^2 = f0^2 + f0^2 B n^2 -> linear in n^2
    y = (fs / ks) ** 2
    A = np.vstack([np.ones_like(ks), ks ** 2]).T
    (c0, c1), *_ = np.linalg.lstsq(A, y, rcond=None)
    f0 = np.sqrt(c0)
    return f0, c1 / c0


def main() -> None:
    keys = list(range(21, 109))
    evs = []
    for i, k in enumerate(keys):
        t = 0.2 + i * STEP
        evs += [(t, N("note_on", note=k, velocity=70)), (t + HOLD, N("note_off", note=k, velocity=0))]
    mid = TMP / "pitch_v70.mid"
    write_midi(mid, {"solo": evs})
    render(mid, TMP / "pitch_v70", "--no-reverb", "--no-m4a")
    x = read(TMP / "pitch_v70_stems" / "solo.wav")
    rows = []
    for i, k in enumerate(keys):
        t = 0.2 + i * STEP + LEAD_IN
        seg = x[int((t + 0.1) * SR): int((t + 2.6) * SR)]
        ps = partials(seg, k)
        fet = 440 * 2 ** ((k - 69) / 12)
        f0, B = fit(ps) if len(ps) >= 5 else (np.nan, np.nan)
        if not (B > 0) or k >= 89:  # few partials / undamped treble: the fit is unreliable, use partial 1
            p1 = next((f for n, f in ps if n == 1), None)
            if p1 is None:  # partial 1 outside the search band: fall back to the plain partial-1 search
                from qa_lib import f0_estimate
                p1 = f0_estimate(seg, k, 1)
            f0, B = p1, float("nan")
        c2 = next((1200 * np.log2(f / (2 * fet)) for n, f in ps if n == 2), None)
        c1 = next((1200 * np.log2(f / fet) for n, f in ps if n == 1), None)
        rows.append(dict(key=k, f0_cents=round(float(1200 * np.log2(f0 / fet)), 1), B=float(f"{B:.2e}"),
                         p1_cents=None if c1 is None else round(float(c1), 1),
                         p2_cents=None if c2 is None else round(float(c2), 1), n_partials=len(ps)))
    kk = np.array(keys, float)
    c = np.array([r["f0_cents"] for r in rows])
    ok = np.isfinite(c)
    smooth = np.polyval(np.polyfit(kk[ok], c[ok], 4), kk)
    for r, s in zip(rows, smooth):
        r["resid_from_smooth_cents"] = round(float(r["f0_cents"] - s), 1)
    steps = [dict(frm=keys[i], to=keys[i + 1], step_cents=round(float(c[i + 1] - c[i]), 1)) for i in range(len(keys) - 1)]
    big = sorted([s for s in steps if np.isfinite(s["step_cents"])], key=lambda s: -abs(s["step_cents"]))[:10]
    octaves = [dict(low=r["key"], p2_low=r["p2_cents"], p1_high=r2["p1_cents"],
                    octave_error_cents=round(r2["p1_cents"] - r["p2_cents"], 1))
               for r in rows for r2 in rows if r2["key"] == r["key"] + 12 and r["key"] >= 33 and r["key"] <= 72
               and r["p2_cents"] is not None and r2["p1_cents"] is not None]
    # transposition check
    evs = [(0.5, N("note_on", note=57, velocity=80)), (3.0, N("note_off", note=57, velocity=0))]
    tm = TMP / "transp.mid"
    write_midi(tm, {"pedal": evs})
    render(tm, TMP / "transp", "--no-reverb", "--no-m4a", "--transpose", "pedal=-12")
    y = read(TMP / "transp_stems" / "pedal.wav")
    ps = partials(y[int((0.6 + LEAD_IN) * SR): int((3.0 + LEAD_IN) * SR)], 45)
    f0t, _ = fit(ps)
    ref = next(r for r in rows if r["key"] == 45)
    res = dict(rows=rows, largest_semitone_steps=big,
               octaves_A1_to_C5={"worst": sorted(octaves, key=lambda o: -abs(o["octave_error_cents"]))[:6],
                                 "median_abs": float(np.median([abs(o["octave_error_cents"]) for o in octaves]))},
               mid_range_C3_C6={"max_abs_f0_cents": float(np.max(np.abs(c[(kk >= 48) & (kk <= 84)]))),
                                "max_abs_resid": float(np.nanmax(np.abs(c - smooth)[(kk >= 48) & (kk <= 84)]))},
               all_keys_max_abs_resid_from_smooth=float(np.nanmax(np.abs(c - smooth))),
               transpose_pedal_minus12={"A3_played_as": "A2", "measured_f0_cents_vs_A2": round(float(1200 * np.log2(f0t / 110.0)), 1),
                                        "direct_A2_f0_cents": ref["f0_cents"]})
    save("pitch", res)
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    for r in rows:
        k = r["key"]
        print(f"{names[k % 12]}{k // 12 - 1:<2d} f0 {r['f0_cents']:+6.1f}  p1 {r['p1_cents']!s:>6} p2 {r['p2_cents']!s:>6}  B {r['B']:.1e}  n {r['n_partials']:2d}  resid {r['resid_from_smooth_cents']:+5.1f}")
    print("largest steps", big)
    print(res["octaves_A1_to_C5"])
    print({k: res[k] for k in ("mid_range_C3_C6", "all_keys_max_abs_resid_from_smooth", "transpose_pedal_minus12")})


if __name__ == "__main__":
    main()
