"""Measurement helpers for the orchestra QA and library comparison (pitch per
note, K-weighted level, spectral centroid, envelopes, onsets, clicks)."""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from orch_common import SR, midi_to_hz
from iowa_build import k_level_db          # noqa: F401  (re-exported)
from verify_tuning import yin              # noqa: F401  the strings' YIN (read-only import)


def mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def pitch_cents(seg: np.ndarray, key: int) -> float | None:
    """Median pitch error (cents) of a steady segment against `key`, YIN with the
    search limited to key +-1.2 semitones (deepest dip), so a neighbour note in
    the tail cannot be mistaken for this one."""
    f = midi_to_hz(key)
    if len(seg) < 4096:
        return None
    W = int(min(4096, max(1024, 6 * SR / f)))
    tr = yin(mono(seg), SR, f * 2 ** (-1.2 / 12), f * 2 ** (1.2 / 12), W=W, hop=max(256, W // 4), thr=0.3,
             global_min=True)
    tr = tr[np.isfinite(tr)]
    if len(tr) < 2:
        return None
    return float(np.median(1200 * np.log2(tr / f)))


def centroid(seg: np.ndarray) -> float:
    m = mono(seg)
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    fr = np.fft.rfftfreq(len(m), 1 / SR)
    return float((spec * fr).sum() / (spec.sum() + 1e-12))


def band_share(seg: np.ndarray, lo: float = 2000.0) -> float:
    """Share of energy above `lo` Hz (dB re total)."""
    m = mono(seg)
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2
    fr = np.fft.rfftfreq(len(m), 1 / SR)
    return float(10 * np.log10(spec[fr >= lo].sum() / (spec.sum() + 1e-20) + 1e-20))


def env_db(x: np.ndarray, win: float = 0.02, hop: float = 0.005) -> tuple[np.ndarray, float]:
    m = mono(x).astype(np.float64)
    w, h = int(win * SR), int(hop * SR)
    p = np.convolve(m ** 2, np.ones(w) / w, mode="same")[::h]
    return 10 * np.log10(p + 1e-20), hop


def level_db(seg: np.ndarray) -> float:
    return float(10 * np.log10(np.mean(mono(seg).astype(np.float64) ** 2) + 1e-20))


def band_env_db(x: np.ndarray, key: int, hop: float = 0.005) -> np.ndarray:
    """Envelope of the note's fundamental and 2nd harmonic (+-3 %), for onsets of
    one note inside a sounding texture."""
    m = mono(x).astype(np.float64)
    f = midi_to_hz(key)
    out = np.zeros(len(m))
    for h in (1, 2):
        lo, hi = f * h * 0.97, min(f * h * 1.03, SR / 2 - 100)
        sos = butter(2, [lo, hi], btype="bandpass", fs=SR, output="sos")
        out += sosfilt(sos, m) ** 2
    w = int(0.02 * SR)
    p = np.convolve(out, np.ones(w) / w, mode="same")[:: int(hop * SR)]
    return 10 * np.log10(p + 1e-20)


def clicks(x: np.ndarray, thr_db: float = 30.0) -> list[float]:
    """Times (s) where the high-passed (>6 kHz) signal jumps thr_db above its
    local (50 ms) RMS within 1 ms: discontinuities from splices, loops or cut
    notes.  Returns event times, merged within 20 ms."""
    m = mono(x).astype(np.float64)
    sos = butter(4, 6000, btype="highpass", fs=SR, output="sos")
    h = sosfilt(sos, m)
    a = np.abs(h)
    w = int(0.05 * SR)
    loc = np.sqrt(np.convolve(h ** 2, np.ones(w) / w, mode="same") + 1e-18)
    full = np.sqrt(np.mean(m ** 2) + 1e-18)
    hit = np.flatnonzero((a > loc * 10 ** (thr_db / 20)) & (a > full * 10 ** (-40 / 20)))
    ev = []
    for i in hit:
        t = i / SR
        if not ev or t - ev[-1] > 0.02:
            ev.append(t)
    return ev


def harmonic_richness(seg: np.ndarray, key: int, fmax: float = 8000.0) -> float | None:
    """Energy of harmonics 3.. (up to fmax, at most 20) re harmonics 1-2 (dB).
    Each harmonic = its spectral peak (+-1.5 %) minus 3x the median noise
    between the harmonics around it, so breath or bow noise (a pp flute) does
    not count as brightness.  Louder playing = richer = higher."""
    m = mono(seg)
    if len(m) < 4096:
        return None
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2
    df = SR / len(m)
    f = midi_to_hz(key)
    amp = []
    for k in range(1, 21):
        if k * f * 1.3 >= min(fmax, SR / 2):
            break
        i0, i1 = int(k * f * 0.985 / df), int(k * f * 1.015 / df) + 1
        j0, j1 = int(k * f * 0.75 / df), int(k * f * 1.25 / df) + 1
        band = np.concatenate([spec[j0:int(k * f * 0.97 / df)], spec[int(k * f * 1.03 / df) + 1:j1]])
        noise = float(np.median(band)) if len(band) else 0.0
        amp.append(max(0.0, float(spec[i0:i1].max()) - 3 * noise))
    if len(amp) < 4:
        return None
    return float(10 * np.log10((sum(amp[2:]) + 1e-20) / (sum(amp[:2]) + 1e-20)))


def pitch_cents_harmonic(seg: np.ndarray, key: int, harmonics=(2, 3, 4, 5)) -> float | None:
    """Pitch error (cents) of a steady low note from its harmonics 2-5: zero-padded
    FFT peak (parabolic) within +-1.2 semitones of each harmonic, median over the
    harmonics that stand 20 dB above their window's median.  For fundamentals below
    about 80 Hz, where YIN's 85 ms window holds only a few periods and a weak
    fundamental biases it (a tuba's Eb1 measured in tune by YIN sounded 22 cents
    flat on its harmonics)."""
    m = mono(seg).astype(np.float64)
    if len(m) < int(0.15 * SR):
        return None
    f = midi_to_hz(key)
    n = len(m) * 8
    sp = np.abs(np.fft.rfft(m * np.hanning(len(m)), n)) + 1e-20
    df = SR / n
    out = []
    for h in harmonics:
        lo, hi = int(h * f * 2 ** (-1.2 / 12) / df), int(h * f * 2 ** (1.2 / 12) / df) + 1
        if hi >= len(sp) - 1:
            break
        w = sp[lo:hi]
        j = int(np.argmax(w))
        if w[j] < 10 * np.median(w) or j == 0 or j == len(w) - 1:
            continue
        a, b, c = np.log(w[j - 1]), np.log(w[j]), np.log(w[j + 1])
        d = 0.5 * (a - c) / (a - 2 * b + c)
        out.append(1200 * np.log2((lo + j + d) * df / (h * f)))
    return float(np.median(out)) if out else None
