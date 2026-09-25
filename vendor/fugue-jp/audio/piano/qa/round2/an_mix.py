#!/usr/bin/env python3
"""Final-file checks: WAV and M4A of one render.

usage: an_mix.py OUT_BASE ORIG.mid OUT.json      (OUT_BASE.wav, OUT_BASE.m4a)

* level: sample peak, 4x-oversampled true peak, samples at or above -0.1 dBFS, runs of equal
  full-scale samples (hard clipping), DC per channel, 18 Hz-and-below energy
* noise: level of the lead-in (before the first note) and spectrum above 8 kHz in the quietest
  second of music; noise between notes in the pp opening
* tail: time from the last key-up to the end of the file, level of the last 0.5 s before the
  50 ms fade, and the decay slope there (a tail cut while still decaying at the hall's rate
  would end well above -80 dB)
* stereo: L/R correlation, balance, polarity per band
* clicks: second-difference outliers in the final mix away from note onsets
* M4A: decoded with afconvert, lag against the WAV, true peak, duration, difference level
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import SR, click_scan, db, frame_energy, midi_notes, read, true_peak, write_json  # noqa: E402

LEAD = 0.3


def main():
    base, orig, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    x = read(base.with_suffix(".wav"))
    notes = midi_notes(orig)
    first_on = min(n["start"] for n in notes) + LEAD
    last_off = max(n["end"] for n in notes) + LEAD
    m = x.mean(axis=1)
    res = {"file": str(base.with_suffix(".wav")), "duration_s": round(len(x) / SR, 3)}
    # level
    sp = float(np.abs(x).max())
    tp = true_peak(x)
    full_runs = 0
    for c in range(2):
        a = np.abs(x[:, c]) >= sp - 1e-6
        full_runs += int(np.sum(a[1:] & a[:-1]))
    res["level"] = dict(sample_peak_dbfs=round(20 * math.log10(sp), 3), true_peak_dbtp_4x=round(20 * math.log10(tp), 3),
                        n_samples_above_m0p1dbfs=int((np.abs(x) > 10 ** (-0.1 / 20)).sum()),
                        consecutive_peak_samples=full_runs,
                        dc=[float(x[:, 0].mean()), float(x[:, 1].mean())],
                        dc_dbfs=[round(20 * math.log10(abs(float(x[:, c].mean())) + 1e-12), 1) for c in range(2)],
                        rms_dbfs=round(float(10 * np.log10(np.mean(x ** 2))), 2))
    sos = ss.butter(4, 18, "low", fs=SR, output="sos")
    sub = ss.sosfilt(sos, x, axis=0)
    res["level"]["below_18hz_re_total_db"] = round(float(10 * np.log10(np.mean(sub ** 2) / np.mean(x ** 2))), 1)
    # noise
    lead = x[: int((first_on - 0.01) * SR)]
    res["noise"] = dict(lead_in_s=round(first_on, 3),
                        lead_in_rms_dbfs=round(float(10 * np.log10(np.mean(lead ** 2) + 1e-30)), 1) if len(lead) else None)
    # quietest 1 s window during the music (between first onset and last key-up)
    e = frame_energy(m, 1000.0)
    a, b = int(first_on) + 1, int(last_off) - 1
    w = a + int(np.argmin(e[a:b]))
    seg = m[w * SR:(w + 1) * SR]
    f, pxx = ss.welch(seg, SR, nperseg=8192)
    hf = pxx[f > 8000].sum() * (f[1] - f[0])
    res["noise"]["quietest_second_s"] = w
    res["noise"]["quietest_second_rms_dbfs"] = round(float(10 * np.log10(e[w] + 1e-30)), 1)
    res["noise"]["quietest_second_above_8k_dbfs"] = round(float(10 * np.log10(hf + 1e-30)), 1)
    # tail
    env = db(frame_energy(m, 10.0))
    top = env.max()
    t_end = len(m) / SR
    last05 = env[int((t_end - 0.55) * 100): int((t_end - 0.05) * 100)]
    k = np.arange(len(last05)) / 100
    slope = np.polyfit(k, last05, 1)[0] if len(last05) > 5 else float("nan")
    # time for the envelope after the last key-up to fall 60 dB below its level at the key-up
    i0 = int(last_off * 100)
    lvl0 = env[i0]
    below = np.nonzero(env[i0:] < lvl0 - 60)[0]
    res["tail"] = dict(last_keyup_s=round(last_off, 3), file_end_s=round(t_end, 3),
                       end_minus_last_keyup_s=round(t_end - last_off, 2),
                       last_0p5s_level_db_re_peak=round(float(last05.mean() - top), 1) if len(last05) else None,
                       last_0p5s_slope_db_per_s=round(float(slope), 1),
                       t60_after_last_keyup_s=round(float(below[0]) / 100, 2) if len(below) else None,
                       level_at_last_keyup_db_re_peak=round(float(lvl0 - top), 1))
    # stereo
    L, R = x[:, 0], x[:, 1]
    bands = {}
    for lo, hi in ((40, 160), (160, 640), (640, 2500), (2500, 10000)):
        s2 = ss.butter(4, [lo, hi], "band", fs=SR, output="sos")
        l, r = ss.sosfilt(s2, L), ss.sosfilt(s2, R)
        bands[f"{lo}-{hi}"] = round(float(np.sum(l * r) / math.sqrt(np.sum(l * l) * np.sum(r * r))), 3)
    res["stereo"] = dict(lr_corr=round(float(np.sum(L * R) / math.sqrt(np.sum(L * L) * np.sum(R * R))), 3),
                         lr_corr_by_band=bands,
                         balance_r_minus_l_db=round(float(10 * np.log10(np.sum(R * R) / np.sum(L * L))), 2))
    # clicks
    ons = [n["start"] + LEAD for n in notes]
    cl = click_scan(x, protect=ons, k=14.0, protect_ms=10.0)
    res["clicks"] = dict(n=len(cl), first=cl[:12])
    # m4a
    m4a = base.with_suffix(".m4a")
    if m4a.exists():
        dec = Path("/tmp/pianoqa2") / (base.name + ".m4a_decoded.wav")
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEF32@48000", str(m4a), str(dec)], check=True)
        y = read(dec)
        n = min(len(x), len(y))
        cc = ss.correlate(y[:SR * 20, 0], x[:SR * 20, 0], mode="full", method="fft")
        lag = int(np.argmax(cc)) - (SR * 20 - 1)
        ya = y[lag: lag + n] if lag >= 0 else np.pad(y, ((-lag, 0), (0, 0)))[:n]
        n2 = min(len(ya), n)
        diff = ya[:n2] - x[:n2]
        res["m4a"] = dict(decoded_duration_s=round(len(y) / SR, 3), lag_samples=lag,
                          sample_peak_dbfs=round(20 * math.log10(float(np.abs(y).max())), 3),
                          true_peak_dbtp_4x=round(20 * math.log10(true_peak(y)), 3),
                          diff_re_signal_db=round(float(10 * np.log10(np.mean(diff ** 2) / np.mean(x[:n2] ** 2))), 1))
    write_json(out, res)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
