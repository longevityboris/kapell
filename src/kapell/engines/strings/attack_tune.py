"""Attack pitch of the Iowa string samples: measure it, flatten it, find where it settles.

Many Iowa notes start off pitch and drift onto it over 0.2-0.5 s (a player
settling after a shift, or a slow bow start), e.g. the G-string A4 at pp starts
120 c flat and is still 20 c flat at 200 ms; the high E-string notes at pp sit
20-30 c flat for 0.4 s.  The tuning loop (verify_tuning.py) only sees the steady
part of a 2 s note, but a 16th note consists of nothing but this attack.

correct_attack() tracks the pitch of the attack (narrow-range YIN, 5 ms hop),
takes its slow trend (vibrato removed by a moving average that widens from
50 ms at the tone start to 160 ms, one vibrato period), and removes the trend by
time-varying resampling of the attack, ending at the start of the steady window
where the reference pitch is measured.  The bow noise and the attack transient
stay as recorded; only the pitch drift goes.  Where the tone has no pitch at all
(the scratch of an ff stroke on a low string, up to 0.2 s), nothing can be
corrected: settle_s reports where the pitch becomes stable, and the builder
starts the short and normal strokes at most SETTLE_LEAD before it.
"""
from __future__ import annotations

import numpy as np

HOP_S = 0.005
DEV_TOL_C = 20.0          # a frame is "settled" if within this of the steady pitch
CONF_MAX = 0.25           # YIN cumulative-mean-normalised difference at the chosen lag


def yin_track(x: np.ndarray, sr: int, f_exp: float, hop: int, win_s: float = 0.03, span_c: float = 450.0):
    """Narrow-range YIN around f_exp -> (f0 per frame [Hz], confidence (lower = better), window)."""
    x = np.asarray(x, dtype=np.float64)
    tmin = max(2, int(sr / (f_exp * 2 ** (span_c / 1200))) - 1)
    tmax = int(sr / (f_exp * 2 ** (-span_c / 1200))) + 2
    W = int(max(win_s, 4.0 / f_exp) * sr)
    n_fr = max(0, (len(x) - W - tmax - 1) // hop)
    f0 = np.full(n_fr, np.nan)
    conf = np.full(n_fr, 9.0)
    if n_fr == 0:
        return f0, conf, W
    L = 1 << int(np.ceil(np.log2(2 * (W + tmax + 1))))
    lags = np.arange(tmax + 1)
    for i in range(n_fr):
        fr = x[i * hop: i * hop + W + tmax + 1]
        if not fr[:W].any():
            continue
        F = np.fft.rfft(fr, L)
        a = np.fft.irfft(F * np.conj(np.fft.rfft(fr[:W], L)), L)[: tmax + 1]
        cs = np.concatenate([[0.0], np.cumsum(fr ** 2)])
        d = cs[W] + (cs[lags + W] - cs[lags]) - 2 * a
        d[0] = 0.0
        cm = np.ones_like(d)
        cm[1:] = d[1:] * lags[1:] / np.maximum(np.cumsum(d[1:]), 1e-20)
        t = tmin + int(np.argmin(cm[tmin:tmax]))
        y0, y1, y2 = cm[t - 1], cm[t], cm[t + 1]
        den = y0 - 2 * y1 + y2
        tt = t + (0.5 * (y0 - y2) / den if abs(den) > 1e-12 else 0.0)
        f0[i] = sr / tt
        conf[i] = cm[t]
    return f0, conf, W


def _track_cents(mono, sr, f_exp, a, b, hop):
    """Cents re f_exp for frames centred in [a, b) (sample indices) -> (centre samples, cents, ok mask)."""
    a0 = max(0, a)
    f0, conf, W = yin_track(mono[a0: b + int(0.08 * sr)], sr, f_exp, hop)
    centres = a0 + np.arange(len(f0)) * hop + W // 2
    keep = centres < b
    cents = 1200 * np.log2(np.where(np.isfinite(f0) & (f0 > 0), f0, f_exp) / f_exp)
    ok = (conf < CONF_MAX) & np.isfinite(f0)
    return centres[keep], cents[keep], ok[keep]


def _medfilt(v, k=5):
    h = k // 2
    p = np.concatenate([np.full(h, v[0]), v, np.full(h, v[-1])])
    return np.array([np.median(p[i: i + k]) for i in range(len(v))])


def analyse(y: np.ndarray, sr: int, f_exp: float, end: int, t20: float) -> dict:
    """Pitch of the attack [t20 - 20 ms, end) relative to the steady pitch: the
    median over the 1.2 s after `end`, i.e. what a long note settles on and what
    the closed tuning loop (verify_tuning.py, 0.45-1.9 s of a 2 s note) tunes."""
    mono = y.mean(axis=1) if y.ndim == 2 else y
    hop = int(HOP_S * sr)
    _, c_st, ok_st = _track_cents(mono, sr, f_exp, end, min(len(mono) - int(0.1 * sr), end + int(1.2 * sr)), hop * 4)
    ref = float(np.median(c_st[ok_st])) if ok_st.any() else 0.0
    start = max(0, int((t20 - 0.02) * sr))
    t, c, ok = _track_cents(mono, sr, f_exp, start, end, hop)
    dev = c - ref
    raw = dev.copy()
    if ok.sum() >= 5:
        dev_ok = _medfilt(dev[ok])
        dev = np.interp(np.arange(len(dev)), np.flatnonzero(ok), dev_ok)
    return dict(t=t, dev=dev, raw=raw, ok=ok, ref=ref)


def trend(t: np.ndarray, dev: np.ndarray, ok: np.ndarray, sr: int, t_v: float) -> np.ndarray:
    """Slow pitch trend: moving average over voiced frames, window 50 ms at the
    tone start widening to 160 ms (one vibrato period) 200 ms later."""
    ts = t / sr
    out = np.zeros(len(dev))
    for i, x in enumerate(ts):
        w = float(np.clip(0.05 + 0.55 * (x - t_v), 0.05, 0.16))
        m = (np.abs(ts - x) <= w / 2) & ok
        out[i] = dev[m].mean() if m.any() else np.nan
    if np.isnan(out).all():
        return np.zeros(len(dev))
    good = np.flatnonzero(~np.isnan(out))
    return np.interp(np.arange(len(out)), good, out[good])


def settle_time(t, tr, ok, sr, t20, raw=None, tol=DEV_TOL_C, window=0.3, min_run=3) -> float:
    """Time (s) from which the pitch is defined and on pitch: the end of the last run
    of at least min_run frames within [t20, t20 + window] that are off pitch --
    voiced frames whose trend is more than tol cents off, or unreliable frames
    (YIN confidence poor) whose own estimate is more than tol off (scratch, noise).
    Isolated frames are ignored."""
    if len(t) == 0:
        return float(t20)
    ts = t / sr
    raw = tr if raw is None else raw
    bad = ((ok & (np.abs(tr) > tol)) | (~ok & (np.abs(raw) > tol))) & (ts >= t20 - 0.01) & (ts <= t20 + window)
    settle = float(t20)
    i = 0
    while i < len(bad):
        if bad[i]:
            j = i
            while j + 1 < len(bad) and bad[j + 1]:
                j += 1
            if j - i + 1 >= min_run:
                settle = float(ts[min(j + 1, len(ts) - 1)])
            i = j + 1
        else:
            i += 1
    return settle


def _sinc_read(x: np.ndarray, pos: np.ndarray, taps: int = 32) -> np.ndarray:
    """x (frames, ch) read at fractional positions with a Kaiser-windowed sinc."""
    base = np.floor(pos).astype(np.int64)
    frac = pos - base
    k = np.arange(-taps // 2 + 1, taps // 2 + 1)
    idx = base[:, None] + k[None, :]
    arg = frac[:, None] - k[None, :]
    w = np.sinc(arg) * np.kaiser(taps, 8.0)[None, :]
    w /= w.sum(axis=1, keepdims=True)
    idx = np.clip(idx, 0, len(x) - 1)
    return np.einsum("nk,nkc->nc", w, x[idx])


def correct_attack(y: np.ndarray, sr: int, f_exp: float, end: int, t20: float,
                   min_dev_c: float = 5.0, max_corr_c: float = 150.0):
    """Flatten the pitch drift of the attack, y[:end] (end = where the builder's
    grain-spliced sustain begins, or earlier).  Returns (y2, shift, info):
    content at index m >= end of y is at m - shift in y2 (whole samples, for
    moving s0 / s1); info has the trend before/after and settle_s."""
    a = analyse(y, sr, f_exp, end, t20)
    t, dev, ok = a["t"], a["dev"], a["ok"]
    info = dict(ref_c=round(a["ref"], 1), corrected=False)
    if len(t) < 8 or ok.sum() < 8:
        info.update(settle_s=round(settle_time(t, np.zeros(len(t)), ok, sr, t20, a["raw"]), 3), max_trend_c=None)
        return y, 0, info
    # first stable voiced run (6 frames = 30 ms)
    run = np.convolve(ok.astype(float), np.ones(6), mode="valid")
    iv = int(np.flatnonzero(run >= 6)[0]) if (run >= 6).any() else int(np.flatnonzero(ok)[0])
    t_v = t[iv] / sr
    tr = trend(t, dev, ok, sr, t_v)
    tr[:iv] = tr[iv]
    seg = tr[iv:]
    info["max_trend_c"] = round(float(np.max(np.abs(seg))), 1)
    info["trend_40_200_c"] = round(float(np.median(tr[(t / sr >= t20 + 0.04) & (t / sr <= t20 + 0.2)]))
                                   if ((t / sr >= t20 + 0.04) & (t / sr <= t20 + 0.2)).any() else 0.0, 1)
    if info["max_trend_c"] < min_dev_c:
        info["settle_s"] = round(settle_time(t, tr, ok, sr, t20, a["raw"]), 3)
        return y, 0, info
    corr = np.clip(-tr, -max_corr_c, max_corr_c)
    # taper the correction to zero over the last 100 ms
    tap0 = max(t[iv], end - int(0.1 * sr))
    g = np.clip((end - t) / max(1, end - tap0), 0, 1)
    corr = corr * g
    n = np.arange(end)
    c_s = np.interp(n, t, corr, left=corr[0], right=0.0)
    rate = 2 ** (c_s / 1200.0)
    phi = np.concatenate([[0.0], np.cumsum(rate)])[:end]
    delta = float(phi[-1] + rate[-1] - end)            # read position runs ahead by delta after `end`
    x = y if y.ndim == 2 else y[:, None]
    head = _sinc_read(x.astype(np.float64), np.concatenate([phi, end + delta + np.arange(64)]))
    # the rest: shift by delta (integer part + FFT fractional delay)
    N = len(x)
    di = int(np.floor(delta))
    df = delta - di
    rest = np.zeros_like(x, dtype=np.float64)
    src = x[max(0, di):, :].astype(np.float64) if di >= 0 else np.concatenate([np.zeros((-di, x.shape[1])), x])
    src = src[:N]
    if len(src) < N:
        src = np.concatenate([src, np.zeros((N - len(src), x.shape[1]))])
    if abs(df) > 1e-9:
        F = np.fft.rfft(src, axis=0)
        k = np.fft.rfftfreq(N)
        src = np.fft.irfft(F * np.exp(2j * np.pi * k * df)[:, None], n=N, axis=0)
        src[N - 64:] = 0.0                             # circular wrap of the FFT shift
    rest[:] = src
    y2 = rest.copy()
    y2[:end] = head[:end]
    xf = 32
    w = np.linspace(0, 1, xf)[:, None]
    y2[end: end + xf] = head[end: end + xf] * (1 - w) + rest[end: end + xf] * w
    # the sample's last 20 ms fade (the wrap region is silent anyway)
    fl = int(0.02 * sr)
    y2[-fl - 64: -64] *= np.linspace(1, 0, fl)[:, None]
    y2 = y2.astype(np.float32)
    if y.ndim == 1:
        y2 = y2[:, 0]
    shift = int(round(delta))
    b = analyse(y2, sr, f_exp, end, t20)
    tr2 = trend(b["t"], b["dev"], b["ok"], sr, t_v)
    m = b["t"] / sr >= t_v
    w = (b["t"] / sr >= t20 + 0.04) & (b["t"] / sr <= t20 + 0.2)
    info.update(corrected=True, delta_samples=round(delta, 2),
                max_trend_after_c=round(float(np.max(np.abs(tr2[m]))) if m.any() else 0.0, 1),
                trend_40_200_after_c=round(float(np.median(tr2[w])) if w.any() else 0.0, 1),
                settle_s=round(settle_time(b["t"], tr2, b["ok"], sr, t20, b["raw"]), 3))
    phi_full = np.concatenate([phi, [end + delta]])

    def remap(m_idx, phi_full=phi_full, end=end, delta=delta):
        """index in y -> index in y2"""
        if m_idx >= end + delta:
            return m_idx - delta
        return float(np.searchsorted(phi_full, m_idx))
    info["remap"] = remap
    return y2, shift, info


def measure_settle(y: np.ndarray, sr: int, f_exp: float, end: int, t20: float) -> float:
    """settle_s of an already corrected sample (no resampling)."""
    a = analyse(y, sr, f_exp, end, t20)
    t, ok = a["t"], a["ok"]
    if len(t) < 8 or ok.sum() < 8:
        return round(settle_time(t, np.zeros(len(t)), ok, sr, t20, a["raw"]), 3)
    run = np.convolve(ok.astype(float), np.ones(6), mode="valid")
    iv = int(np.flatnonzero(run >= 6)[0]) if (run >= 6).any() else int(np.flatnonzero(ok)[0])
    tr = trend(t, a["dev"], ok, sr, t[iv] / sr)
    tr[:iv] = tr[iv]
    return round(settle_time(t, tr, ok, sr, t20, a["raw"]), 3)
