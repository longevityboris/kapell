"""Measurement helpers for the round-2 adversarial QA (independent of render_piano.py and qa/qa_lib.py)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss
import soundfile as sf

SR = 48000


# ---------------------------------------------------------------------------------------------
# MIDI (own parser: tempo map from every track, FIFO pairing per track/channel/key)
# ---------------------------------------------------------------------------------------------
def tempo_map(mf: mido.MidiFile):
    tempos = []
    for tr in mf.tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "set_tempo":
                tempos.append((t, m.tempo))
    tempos.sort()
    if not tempos or tempos[0][0] != 0:
        tempos.insert(0, (0, 500000))
    pts = []
    sec, lt, lu = 0.0, 0, tempos[0][1]
    for t, u in tempos:
        sec += (t - lt) * lu / 1e6 / mf.ticks_per_beat
        pts.append((t, sec, u))
        lt, lu = t, u

    def f(tick):
        i = max(j for j in range(len(pts)) if pts[j][0] <= tick)
        t0, s0, u = pts[i]
        return s0 + (tick - t0) * u / 1e6 / mf.ticks_per_beat
    return f


def midi_notes(path) -> list[dict]:
    """[{track, name, ch, key, start, end, vel}] in seconds; also returns ccs via midi_ccs."""
    mf = mido.MidiFile(path)
    sec = tempo_map(mf)
    out = []
    for ti, tr in enumerate(mf.tracks):
        t = 0
        name = None
        pend = {}
        evs = []
        for m in tr:
            t += m.time
            if m.type == "track_name" and name is None:
                name = m.name
            if m.type in ("note_on", "note_off"):
                evs.append((t, 0 if (m.type == "note_off" or m.velocity == 0) else 1, m))
        evs.sort(key=lambda e: (e[0], e[1]))
        for t, isoff, m in evs:
            k = (m.channel, m.note)
            if isoff == 1:
                pend.setdefault(k, []).append((t, m.velocity))
            elif pend.get(k):
                st, v = pend[k].pop(0)
                out.append(dict(track=ti, name=name, ch=m.channel, key=m.note, start=sec(st), end=sec(t), vel=v,
                                start_tick=st, end_tick=t))
    out.sort(key=lambda n: (n["start"], n["key"]))
    return out


def midi_ccs(path) -> list[dict]:
    mf = mido.MidiFile(path)
    sec = tempo_map(mf)
    out = []
    for ti, tr in enumerate(mf.tracks):
        t = 0
        for m in tr:
            t += m.time
            if m.type == "control_change":
                out.append(dict(track=ti, ch=m.channel, cc=m.control, val=m.value, t=sec(t)))
    return out


# ---------------------------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------------------------
def read(path) -> np.ndarray:
    x, sr = sf.read(str(path), dtype="float64", always_2d=True)
    assert sr == SR, (path, sr)
    return x


def db(x):
    return 10 * np.log10(np.maximum(x, 1e-30))


def frame_energy(m: np.ndarray, ms: float = 1.0) -> np.ndarray:
    fr = int(SR * ms / 1000)
    n = len(m) // fr
    return (m[: n * fr].reshape(n, fr) ** 2).mean(axis=1)


def true_peak(x: np.ndarray, os_: int = 4) -> float:
    up = ss.resample_poly(x, os_, 1, axis=0)
    return float(np.abs(up).max())


def midi_hz(k: float) -> float:
    return 440.0 * 2 ** ((k - 69) / 12)


def onset_near(m_hp_db: np.ndarray, t: float, lo=-0.03, hi=0.05) -> tuple[float, float]:
    """Attack time near t: frame (1 ms) of the steepest 4 ms rise of the high-passed energy.
    Returns (onset_s, slope_db)."""
    a, b = int((t + lo) * 1000), int((t + hi) * 1000)
    a, b = max(a, 3), min(b, len(m_hp_db) - 4)
    if b <= a:
        return float("nan"), float("nan")
    idx = np.arange(a, b)
    slope = m_hp_db[idx + 2] - m_hp_db[idx - 2]
    i = int(idx[np.argmax(slope)])
    return i / 1000.0, float(slope.max())


def hp_energy_db(m: np.ndarray, fc=2000.0) -> np.ndarray:
    sos = ss.butter(4, fc, "high", fs=SR, output="sos")
    return db(frame_energy(ss.sosfilt(sos, m)))


def band_power(m: np.ndarray, t0: float, t1: float, freqs: list[float], rel_bw=0.015, nfft=1 << 16) -> float:
    a, b = int(t0 * SR), int(t1 * SR)
    a, b = max(a, 0), min(b, len(m))
    if b - a < 256:
        return 1e-30
    seg = m[a:b] * np.hanning(b - a)
    sp = np.abs(np.fft.rfft(seg, n=max(nfft, 1 << int(math.ceil(math.log2(b - a)))))) ** 2
    fr = np.fft.rfftfreq(max(nfft, 1 << int(math.ceil(math.log2(b - a)))), 1 / SR)
    tot = 0.0
    for f in freqs:
        if f > 16000:
            continue
        sel = (fr > f * (1 - rel_bw)) & (fr < f * (1 + rel_bw))
        tot += sp[sel].sum()
    return tot / (b - a)


def f0_estimate(m: np.ndarray, t0: float, t1: float, key: float, span_cents=60.0, partials=None) -> tuple[float, float]:
    """Harmonic-sum f0 (with fitted inharmonicity B in a small grid) in +-span_cents of the ET pitch.
    Returns (cents_re_ET, B)."""
    a, b = int(t0 * SR), int(t1 * SR)
    seg = m[a:b]
    if len(seg) < 2048:
        return float("nan"), float("nan")
    seg = seg * np.hanning(len(seg))
    nfft = 1 << 19
    sp = np.abs(np.fft.rfft(seg, n=nfft))
    fr_res = SR / nfft
    f_et = midi_hz(key)
    if partials is None:
        partials = list(range(1, 9)) if key >= 48 else list(range(2, 13))
    partials = [p for p in partials if p * f_et < 12000]
    cents = np.arange(-span_cents, span_cents + 0.01, 0.25)
    best = (-1, 0, 0)
    Bs = [0.0] if key >= 84 else [0.0, 1e-4, 2e-4, 4e-4, 8e-4]
    logsp = np.log(sp + 1e-12)
    for B in Bs:
        f0s = f_et * 2 ** (cents / 1200)
        score = np.zeros_like(f0s)
        for p in partials:
            fp = p * f0s * math.sqrt(1 + B * p * p)
            idx = fp / fr_res
            i0 = np.floor(idx).astype(int)
            frac = idx - i0
            ok = i0 + 1 < len(sp)
            v = np.where(ok, (1 - frac) * logsp[np.minimum(i0, len(sp) - 2)] + frac * logsp[np.minimum(i0 + 1, len(sp) - 1)], -30)
            score += v
        j = int(np.argmax(score))
        if score[j] > best[0] or best[0] == -1:
            best = (score[j], cents[j], B)
    return float(best[1]), float(best[2])


def partial_peak_cents(m: np.ndarray, t0: float, t1: float, key: float, p: int = 1, span=80.0) -> float:
    """Frequency of the strongest peak near partial p of the ET pitch (parabolic interpolation),
    in cents re p*f_ET. Robust single-partial estimate for the mid/high register."""
    a, b = int(t0 * SR), int(t1 * SR)
    seg = m[a:b] * np.hanning(b - a)
    nfft = 1 << 20
    sp = np.abs(np.fft.rfft(seg, n=nfft))
    fr = np.fft.rfftfreq(nfft, 1 / SR)
    fc = p * midi_hz(key)
    sel = np.nonzero((fr > fc * 2 ** (-span / 1200)) & (fr < fc * 2 ** (span / 1200)))[0]
    i = sel[np.argmax(sp[sel])]
    y0, y1, y2 = np.log(sp[i - 1:i + 2] + 1e-20)
    d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2) if (y0 - 2 * y1 + y2) != 0 else 0
    f = (i + d) * SR / nfft
    return 1200 * math.log2(f / fc)


def click_scan(x: np.ndarray, protect: list[float] = (), k: float = 10.0, protect_ms=8.0) -> list[dict]:
    """Candidate clicks: samples whose |second difference| exceeds k x the local (10 ms) RMS of the
    second difference, outside +-protect_ms of the given onset times. Returns events (merged within 5 ms)."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    d2 = np.diff(m, 2)
    w = int(0.010 * SR)
    loc = np.sqrt(np.convolve(d2 ** 2, np.ones(w) / w, mode="same")) + 1e-12
    r = np.abs(d2) / loc
    cand = np.nonzero(r > k)[0]
    prot = np.array(sorted(protect))
    out, last = [], -10 ** 9
    peak = np.abs(m).max() + 1e-20
    for i in cand:
        t = (i + 1) / SR
        if len(prot):
            j = np.searchsorted(prot, t)
            near = min(abs(t - prot[j - 1]) if j > 0 else 9, abs(t - prot[j]) if j < len(prot) else 9)
            if near < protect_ms / 1000:
                continue
        if i - last < int(0.005 * SR):
            last = i
            continue
        lvl = 20 * math.log10(abs(d2[i]) / peak + 1e-20)
        out.append({"t": round(t, 4), "ratio": round(float(r[i]), 1), "d2_db_re_peak": round(lvl, 1)})
        last = i
    return out


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, default=lambda o: float(o) if isinstance(o, np.floating) else int(o)))
