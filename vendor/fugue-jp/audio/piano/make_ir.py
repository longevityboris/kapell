#!/usr/bin/env python3
"""Build the stereo concert-hall impulse response used by render_piano.py.

Usage::

    python3 make_ir.py [--width 1.0] [--out PATH]

Source: *Open Database of Spatial Room Impulse Responses at Detmold University
of Music*, set C ("Dense KH"), Detmold Konzerthaus (a concert hall of about
600 seats), stage source S1, audience seat 163 (row 7, centre block).
Amengual Gari, Sahin, Eddy and Kob, AES 149th Convention (2020).
Zenodo record 4116247, licence CC-BY 4.0. ``setup_piano.sh`` extracts the
files.

At that seat the database has an omni (``Omni/S1R163.wav``) and a lateral
figure-8 (``Fig8/S1R163.wav``, a Schoeps CCM8) measured together. Together
they form a coincident Mid/Side pair, which this script decodes to L/R:

* **Polarity.** Band-passed to 200-1500 Hz, the direct sound in the figure-8
  correlates with the omni at +0.98. The dummy head at the same seat hears
  the direct sound 9.7 dB louder in the left ear, so S1 is on the listener's
  left and the figure-8's positive lobe points left. S = +fig8.
* **Side gain.** In a diffuse field a figure-8 captures 1/3 of an omni's
  energy (-4.8 dB). The side gain is set so that the late tail (0.4-1.4 s)
  of S sits 4.8 dB below M, which gives matched sensitivities without trusting
  the dataset's mic gains. ``--width`` scales S further. L = M + S, R = M - S.
* **Direct sound removed.** The dry close-miked piano supplies the direct
  sound, so the IR starts 1 ms before the direct peak and the first 2.5 ms
  after it are faded out. What remains is the hall's own reflections and
  tail, keeping their natural delay relative to the direct sound.
* **Clean-up.** 25 Hz high-pass for rumble and measurement noise, and scaling
  to unit energy (render_piano.py calibrates ``--wet-db`` against the piano's
  long-term spectrum, not against this white-impulse normalisation).
* **Late tail extended.** The source files are only 1.5 s long, but the hall's
  low-frequency reverberation is longer (T60 about 2.2 s at 63 Hz, 1.8 s at
  125 Hz): the bass tail is still only about 40 dB down where the file ends,
  and a fade there cut it off audibly after a staccato ff chord. Each octave
  band (complementary raised-cosine crossovers, zero phase, summing exactly to
  the original) is continued with noise that decays at the band's own measured
  rate, starting from the level and the left/right correlation of the measured
  tail. The decay rate is a straight-line fit to the band's energy envelope
  (50 ms smoothing) from 5 dB below its peak down to where the measurement ends
  or approaches the band's noise floor (the high bands reach their measurement
  floor at 0.6-1 s, and there the synthetic tail also replaces that noise).
  Measured and synthetic tails are crossfaded at equal power over 200 ms. The
  IR runs until every band is more than 80 dB below the IR's loudest 10 ms and
  at least 3 s, and only then fades out (100 ms). The fit per band, the
  crossfade times and the length are recorded in the IR's JSON.

The JSON also records the SHA-256 of this script; ``setup_piano.sh`` rebuilds
the IR when the script has changed.

Measured on the source (Schroeder T20 of the omni): about 1.7 s at 125 Hz,
1.5 s at 500 Hz-2 kHz and 1.3 s at 4 kHz. This is a warm, clear chamber-music
hall acoustic, suitable for Bach on a grand piano.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import scipy.signal as ss
import soundfile as sf

from piano_paths import DETMOLD_DIR, HALL_IR, SR

OMNI = DETMOLD_DIR / "SetC_DenseKH_LSOrchestra/Data/Omni/S1R163.wav"
FIG8 = DETMOLD_DIR / "SetC_DenseKH_LSOrchestra/Data/Fig8/S1R163.wav"
DUMMY = DETMOLD_DIR / "SetC_DenseKH_LSOrchestra/Data/DummyHead/S1R163.wav"


def band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return ss.sosfiltfilt(ss.butter(4, [lo, hi], "band", fs=SR, output="sos"), x, axis=0)


def t20(x: np.ndarray) -> float:
    """Broadband-ish Schroeder T20 (500 Hz-2 kHz) in seconds."""
    y = band(x, 500, 2000)
    e = y**2
    edc = np.cumsum(e[::-1])[::-1]
    edc_db = 10 * np.log10(edc / edc.max() + 1e-30)
    i5 = int(np.argmax(edc_db < -5))
    i25 = int(np.argmax(edc_db < -25))
    return 3 * (i25 - i5) / SR


# Octave-band split for the tail extension: crossovers at the octave-band edges, each a
# raised-cosine transition half an octave wide (log frequency). Adjacent transitions do not
# overlap, so the masks are non-negative and sum to exactly 1 (zero phase).
EDGES = (88.4, 176.8, 353.6, 707.1, 1414.2, 2828.4, 5656.9, 11313.7)
CENTRES = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
FRAME = 480  # 10 ms
SMOOTH_FRAMES = 5  # 50 ms envelope smoothing
MEASURED_END = 1.25  # s after the IR start: the source file ends at ~1.44 s here
XFADE = 0.20  # s, measured -> synthetic
MIN_LENGTH = 3.0  # s
FLOOR_DB = -80.0  # re the loudest 10 ms frame: the tail must be below this before the fade
FADE = 0.10  # s
GENERATOR_TAG = "make_ir.py sha256"


def generator_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def band_masks(nfft: int) -> list[np.ndarray]:
    f = np.fft.rfftfreq(nfft, 1 / SR)
    with np.errstate(divide="ignore"):
        lf = np.log2(np.maximum(f, 1e-9))
    lps = []
    for fe in EDGES:
        x = np.clip((lf - np.log2(fe)) / 0.5 + 0.5, 0, 1)  # 0 at fe/2^0.25, 1 at fe*2^0.25
        lps.append(0.5 + 0.5 * np.cos(np.pi * x))  # 1 below the edge, 0 above
    masks = [lps[0]] + [lps[k] - lps[k - 1] for k in range(1, len(lps))] + [1 - lps[-1]]
    return masks


def split(x: np.ndarray, masks: list[np.ndarray], nfft: int) -> list[np.ndarray]:
    X = np.fft.rfft(x, nfft, axis=0)
    return [np.fft.irfft(X * m[:, None], nfft, axis=0)[: len(x)] for m in masks]


def frame_energy(y: np.ndarray) -> np.ndarray:
    """Energy per 10 ms frame (both channels), smoothed over 50 ms."""
    e = (y**2).sum(axis=1)
    n = len(e) // FRAME
    fe = e[: n * FRAME].reshape(n, FRAME).mean(axis=1)
    return np.convolve(fe, np.ones(SMOOTH_FRAMES) / SMOOTH_FRAMES, mode="same") + 1e-30


def extend_tail(ir: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    """Continue every octave band of the measured IR with noise decaying at its measured rate
    (see the module docstring). Returns the extended IR and a per-band report."""
    n_meas = int(MEASURED_END * SR)
    top_db = 10 * np.log10(frame_energy(ir).max())
    # the longest tail we could need, before trimming to the -80 dB point
    n_out = int(6.0 * SR)
    nfft = 1 << int(np.ceil(np.log2(n_out + SR)))
    masks = band_masks(nfft)
    meas_bands = split(np.pad(ir, ((0, n_out - len(ir)), (0, 0))), masks, nfft)
    hp = ss.butter(2, 25, "high", fs=SR, output="sos")
    noise = ss.sosfilt(hp, rng.standard_normal((n_out, 2)), axis=0)
    noise_bands = split(noise, masks, nfft)
    t = np.arange(n_out) / SR
    out = np.zeros((n_out, 2))
    report, ends = {}, []
    for fc, mb, nb in zip(CENTRES, meas_bands, noise_bands):
        env = 10 * np.log10(frame_energy(mb[:n_meas]))
        tf = (np.arange(len(env)) + 0.5) * FRAME / SR
        ipk = int(np.argmax(env))
        rel = env - env[ipk]
        i5 = ipk + int(np.argmax(rel[ipk:] < -5))
        i25 = ipk + int(np.argmax(rel[ipk:] < -25)) if (rel[ipk:] < -25).any() else len(env) - 1
        k, c = np.polyfit(tf[i5:i25], env[i5:i25], 1)
        # Measurement floor: the last 150 ms sit well above the extrapolated decay line.
        floor = float(np.median(env[-15:]))
        has_floor = floor - (k * tf[-8] + c) > 5.0
        t_end = MEASURED_END
        if has_floor:
            t_end = min(MEASURED_END, max(tf[i25], (floor + 10 - c) / k))
        iend = int(np.searchsorted(tf, t_end))
        if iend - i5 > 10:  # refit over everything the measurement supports
            k, c = np.polyfit(tf[i5:iend], env[i5:iend], 1)
        k = min(k, -60 / 4.0)  # T60 at most 4 s
        k = max(k, -60 / 0.3)
        t0, t1 = t_end - XFADE, t_end
        a, b = int(t0 * SR), int(t1 * SR)
        # stereo: left/right correlation and levels of the measured tail before the crossfade end
        seg = mb[max(0, a - int(0.3 * SR)) : b]
        rho = float(np.sum(seg[:, 0] * seg[:, 1]) / np.sqrt(np.sum(seg[:, 0] ** 2) * np.sum(seg[:, 1] ** 2)))
        rho = float(np.clip(rho, -0.95, 0.95))
        cm, cs = np.sqrt((1 + rho) / 2), np.sqrt((1 - rho) / 2)
        syn = np.stack([cm * nb[:, 0] + cs * nb[:, 1], cm * nb[:, 0] - cs * nb[:, 1]], axis=1)
        syn *= (10 ** (k * (t - t1) / 20))[:, None]  # decays k dB/s (energy), 0 dB at t1
        for ch in range(2):  # match each channel's energy in the crossfade window
            syn[:, ch] *= np.sqrt(np.sum(mb[a:b, ch] ** 2) / (np.sum(syn[a:b, ch] ** 2) + 1e-30))
        u = np.clip((t - t0) / (t1 - t0), 0, 1)
        out += mb * np.cos(0.5 * np.pi * u)[:, None] + syn * np.sin(0.5 * np.pi * u)[:, None]
        # where this band's tail passes -80 dB re the IR's loudest frame
        lvl_t1 = 10 * np.log10(np.mean((mb[a:b] ** 2).sum(axis=1)) + 1e-30) - top_db
        ends.append(t1 + (FLOOR_DB - lvl_t1) / k if lvl_t1 > FLOOR_DB else t1)
        report[str(fc)] = {"t60_fit_s": round(-60 / k, 2), "fit_s": [round(float(tf[i5]), 2), round(float(t_end), 2)],
                           "measurement_floor": bool(has_floor), "crossfade_s": [round(t0, 2), round(t1, 2)],
                           "lr_correlation": round(rho, 3), "level_at_crossfade_end_db_re_ir_peak": round(float(lvl_t1), 1)}
    length = min(max(MIN_LENGTH, max(ends)) + FADE, n_out / SR)
    n = int(length * SR)
    out = out[:n]
    nf = int(FADE * SR)
    out[-nf:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, nf)))[:, None]
    fade_db = 10 * np.log10(frame_energy(out[n - nf - 10 * FRAME : n - nf]).mean()) - top_db
    return out, {"bands": report, "measured_until_s": MEASURED_END, "length_s": round(length, 3),
                 "level_where_fade_starts_db_re_ir_peak": round(float(fade_db), 1)}


def band_t20(ir: np.ndarray) -> dict:
    """Schroeder T20 per octave band (6th-order Butterworth band-pass), both channels."""
    out = {}
    for fc in CENTRES[:7]:
        sos = ss.butter(3, [fc / 2**0.5, fc * 2**0.5], "band", fs=SR, output="sos")
        e = (ss.sosfilt(sos, ir, axis=0) ** 2).sum(axis=1)
        sch = 10 * np.log10(np.cumsum(e[::-1])[::-1] / e.sum() + 1e-30)
        i, j = int(np.argmax(sch <= -5)), int(np.argmax(sch <= -25))
        tt = np.arange(len(sch)) / SR
        out[str(fc)] = round(float(-60 / np.polyfit(tt[i:j], sch[i:j], 1)[0]), 2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the M/S hall IR (see module docstring).")
    ap.add_argument("--width", type=float, default=1.0, help="extra side gain (1.0 = matched M/S)")
    ap.add_argument("--out", default=str(HALL_IR))
    args = ap.parse_args()

    m, sr_m = sf.read(OMNI, dtype="float64")
    f, sr_f = sf.read(FIG8, dtype="float64")
    d, sr_d = sf.read(DUMMY, dtype="float64")
    assert sr_m == sr_f == sr_d == SR

    p = int(np.argmax(np.abs(m)))

    # Which side is the source on? (dummy head, direct sound)
    pd = int(np.argmax(np.abs(d).max(axis=1)))
    w = slice(pd - 48, pd + 96)
    lr_db = 10 * np.log10(np.sum(d[w, 0] ** 2) / np.sum(d[w, 1] ** 2))
    source_left = lr_db > 0
    # Polarity of the figure-8 relative to the omni for the direct sound.
    mb, fb = band(m, 200, 1500), band(f, 200, 1500)
    w = slice(p - 50, p + 100)
    lags = range(-8, 9)
    corr = [np.sum(mb[w] * np.roll(fb, k)[w]) / np.sqrt(np.sum(mb[w] ** 2) * np.sum(np.roll(fb, k)[w] ** 2)) for k in lags]
    c = corr[int(np.argmax(np.abs(corr)))]
    pos_lobe_left = (c > 0) == source_left
    s = f if pos_lobe_left else -f

    tail = slice(int(0.4 * SR), int(1.4 * SR))
    g = np.sqrt(np.sum(m[tail] ** 2) / (3.0 * np.sum(s[tail] ** 2))) * args.width

    left = m + g * s
    right = m - g * s
    ir = np.stack([left, right], axis=1)

    # Start 1 ms before the direct sound; fade the direct sound itself out.
    ir = ir[p - 48 :]
    n = np.arange(len(ir))
    t0, t1 = 48 + int(0.0005 * SR), 48 + int(0.0025 * SR)
    win = np.clip((n - t0) / (t1 - t0), 0, 1)
    win = 0.5 - 0.5 * np.cos(np.pi * win)
    ir *= win[:, None]

    ir = ss.sosfilt(ss.butter(2, 25, "high", fs=SR, output="sos"), ir, axis=0)
    source_len = len(ir) / SR
    t20_before = band_t20(ir)
    ir, tail = extend_tail(ir, np.random.default_rng(163))
    ir /= np.sqrt(np.sum(ir**2) / 2)

    sf.write(args.out, ir.astype(np.float32), SR, subtype="FLOAT")
    corr_lr = np.corrcoef(ir[int(0.3 * SR) : int(1.2 * SR), 0], ir[int(0.3 * SR) : int(1.2 * SR), 1])[0, 1]
    info = {
        "source": "Detmold SRIR database, set C, Konzerthaus, S1R163 (Omni + Fig8 -> M/S)",
        "zenodo": "https://zenodo.org/records/4116247",
        "licence": "CC-BY 4.0",
        "citation": "Amengual Gari, S. V.; Sahin, B.; Eddy, D.; Kob, M.: Open Database of Spatial Room Impulse "
        "Responses at Detmold University of Music, AES 149th Convention, 2020.",
        "source_side_db_dummy_head": round(float(lr_db), 2),
        "fig8_vs_omni_direct_corr": round(float(c), 3),
        "fig8_positive_lobe": "left" if pos_lobe_left else "right",
        "side_gain": round(float(g), 4),
        "t20_500_2k_s": round(t20(m[p:]), 2),
        "tail_lr_correlation": round(float(corr_lr), 3),
        "length_s": round(len(ir) / SR, 3),
        "measured_length_s": round(source_len, 3),
        "tail_extension": tail,
        "t20_octave_bands_s": {"measured_ir": t20_before, "extended_ir": band_t20(ir)},
        GENERATOR_TAG: generator_sha256(),
    }
    with open(str(args.out).rsplit(".", 1)[0] + ".json", "w") as fh:
        json.dump(info, fh, indent=1)
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
