#!/usr/bin/env python3
"""Stage 3 of the Iowa quartet build: turn the analysed Iowa MIS arco notes into
playable, expressive SFZ instruments for sfizz.

For every instrument (violin, viola, cello, bass) and every chromatic note it
  1. picks one string per note (the normal fingering: the highest string whose
     open pitch is below the note; open-string pitches prefer the stopped note
     on the next lower string so vibrato stays continuous), the same string for
     pp, mf and ff so the dynamic crossfade stays within one timbre family;
  2. high-passes the note just below its fundamental (the recordings carry
     building rumble below 60 Hz), trims it to the bow onset, resamples to 48 kHz;
  3. extends the sustain to SUSTAIN_S seconds by pitch-synchronous grain
     splicing (cross-correlation matched splice points, 70 ms crossfades, random
     grain order, slow level normalisation) so long notes never loop audibly;
  4. flattens the pitch drift of the recorded attack (attack_tune.py: many notes
     start 20-120 c off and settle over 0.2-0.5 s, which is all a short note
     plays) by time-varying resampling, and records where an unpitched ff
     scratch ends (settle_s) so strokes start at most 30-40 ms before it;
  5. measures the K-weighted (BS.1770) steady level of each note, smooths the
     level across the range, and calibrates the three layers to fixed loudness steps
     (ff = 0 dB, mf = -6.5 dB, pp = -16 dB) so CC1 behaves predictably;
  6. writes <inst>.sfz with:
       CC1   dynamics on the perform.py scale (ppp 36, pp 49, p 62, mp 75, mf 88,
             f 101, ff 114, fff 127): the pp recording up to 65, mf from 72 to
             104, ff from 111, equal-power crossfades only in the two narrow zones
             between (two takes of one note interfere, see XF); a volume curve
             moves loudness about 3.5 dB per dynamic step (CC1_TARGET) and a high
             shelf adds brightness with CC1 inside each layer (EQ_DEPTH)
       CC20  articulation (set by render_quartet.py before each note-on):
             0-63 normal bow stroke (recorded attack, slow swells shortened),
             64-95 legato (slurred: starts in the sustain, 30 ms fade-in),
             96-127 short (crisp onset, small accent decay, for fast notes)
       CC21  release time: 0.03 s + 1.2 s * cc21/127 (exponential, -78 dB at the end)
       vel   attack softness of the normal stroke (vel 127: 15 ms fade-in, vel 32:
             41 ms) and a gentle accent (amp_veltrack 30 %)
       pitch bend +-2 semitones.
     CC11/CC7 are applied by render_quartet.py as post-gain on each voice.

Usage:  python3 iowa_build.py [--only violin,viola] [--jobs 10] [--sustain 10]
Outputs: IowaMIS/quartet/{violin,violin2,viola,cello,bass}.sfz and samples/<inst>/*.wav
(violin2 = the second violin: same recordings, next lower string where recorded)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from fractions import Fraction
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import bilinear, butter, lfilter, resample_poly, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attack_tune  # noqa: E402
from iowa_common import (DYNAMICS, INSTRUMENTS, QUARTET_DIR, RAW_DIR, base_of, load_audio,  # noqa: E402
                         load_iowa, midi_name, midi_to_hz)

SR = 48000
SUSTAIN_S = 10.0
# CC1 scale = the one ricercar/tools/perform.py writes for --target strings:
#   value = 36 + 13 * (level - 1), level ppp=1 pp=2 p=3 mp=4 mf=5 f=6 ff=7 fff=8
#   -> ppp 36, pp 49, p 62, mp 75, mf 88, f 101, ff 114, fff 127
# Each recorded layer plays alone at its anchor and is crossfaded (equal power)
# with its neighbour in between: pp <= 49, pp->mf 49..88, mf->ff 88..114, ff >= 114.
LAYER_CC1 = {"pp": 49, "mf": 88, "ff": 114}
# Two recordings of the same note sounding together interfere (independent vibrato:
# the sum swells and fades by 5-8 dB at 0.2-3 Hz), so the layers overlap only in two
# narrow zones, pp->mf over CC1 65-72 and mf->ff over 104-111.  sfizz reads xfin_hicc /
# xfout_hicc as hi + 0.999 (Defaults.h kFillGap), so a zone's fade runs over (hi - lo) / 127
# and a layer is fully in or out only AT the zone's end value: at CC1 71 the pp take still
# plays at -8.4 dB under the mf take (round-2 QA measured 2-3.5 dB of extra wander there).
# Every named level (p 62, mp 75, f 101, ff 114) is a single recording; CC1_TARGET carries
# the loudness in between.
# render_quartet.py never parks inside a zone: it holds each layer in its home range
# (LAYER_HOME) and crosses a zone in 50 ms at a note-on (0.3 s inside a held note),
# with hysteresis (LAYER_UP / LAYER_DOWN), and restores the loudness of the true CC1
# as a gain.  Other players of the SFZ get the narrow zones.
XF = {"pp": (0, 65, 65, 72), "mf": (65, 72, 104, 111), "ff": (104, 111, 111, 127)}
LAYER_HOME = {"pp": (0, 65), "mf": (72, 104), "ff": (111, 127)}   # one recording each (65, 72, 104, 111 checked)
LAYER_UP = {"pp": 70, "mf": 109}          # switch to the next layer at CC1 >= this
LAYER_DOWN = {"mf": 66, "ff": 106}        # back to the lower layer at CC1 <= this
# loudness of each layer at its anchor (dB re ff) = the CC1 target there, so the
# compensation curve is 0 dB at the anchors and only evens out the crossfades
LAYER_DB = {"pp": -16.0, "mf": -6.5, "ff": 0.0}
REF_DB = -20.0          # K-weighted steady level of the ff layer mid-range (dBFS, before volume=-6)
REGISTER_SLOPE_DB = 2.0  # how much of an instrument's natural register slope is kept (+-dB)
# CC1 -> target loudness (dB, relative to the ff layer); about 3.5 dB per dynamic step
CC1_TARGET = [(0, -30.0), (20, -24.5), (36, -20.0), (49, -16.0), (62, -12.5), (75, -9.5), (88, -6.5),
              (101, -3.2), (114, 0.0), (127, 1.5)]
# articulation timing (s): 'normal' notes keep at most NORMAL_RISE of the recorded
# rise before the note reaches steady-3 dB (Iowa players often swell into pp/mf
# notes for 0.3-0.6 s, far too slow for eighth notes); 'short' notes keep SHORT_RISE
NORMAL_RISE = 0.10
SHORT_RISE = 0.035
# a stroke starts at most this long before the pitch has settled (ff scratch on low strings)
SETTLE_LEAD = {"normal": 0.04, "short": 0.03}
# brightness follows CC1 within each layer too: a high shelf (EQ_FREQ Hz) whose gain is
# EQ_DEPTH[inst] * EQ_CURVE(CC1) dB (0 at mf).  The violins' recorded mf and ff differ
# little above 2 kHz (Violin I: 0.0 dB gain-matched 2-5 kHz), the cello's by 12 dB.
EQ_FREQ = 2200
EQ_DEPTH = {"violin": 5.0, "violin2": 5.0, "viola": 3.0, "cello": 1.5, "bass": 1.5}
EQ_CURVE = [(0, -1.0), (49, -0.5), (88, 0.0), (114, 0.5), (127, 0.7)]


# --------------------------------------------------------------------------- DSP
def a_weighting(fs: int):
    f1, f2, f3, f4, a1000 = 20.598997, 107.65265, 737.86223, 12194.217, 1.9997
    nums = [(2 * np.pi * f4) ** 2 * (10 ** (a1000 / 20)), 0, 0, 0, 0]
    dens = np.polymul([1, 4 * np.pi * f4, (2 * np.pi * f4) ** 2], [1, 4 * np.pi * f1, (2 * np.pi * f1) ** 2])
    dens = np.polymul(np.polymul(dens, [1, 2 * np.pi * f3]), [1, 2 * np.pi * f2])
    return bilinear(nums, dens, fs)


AW_B, AW_A = a_weighting(SR)


def k_level_db(x: np.ndarray) -> float:
    """ITU-R BS.1770 K-weighted level (the loudness proxy used for calibration:
    A-weighting under-reads the cello's low register by ~5 dB against the violin)."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    y = lfilter([1.53512485958697, -2.69169618940638, 1.19839281085285],
                [1.0, -1.69065929318241, 0.73248077421585], m)
    y = lfilter([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621], y)
    return float(10 * np.log10(np.mean(y.astype(np.float64) ** 2) + 1e-20))


def add_k_levels(meta: list[dict]) -> bool:
    """Measure the K-weighted steady level of every built sample (older meta.json
    files only carry the A-weighted one).  Returns True if anything changed."""
    changed = False
    for m in meta:
        if "klevel_db" in m:
            continue
        y, _ = sf.read(str(QUARTET_DIR / m["path"]), dtype="float64", always_2d=True)
        steady = y[m["s0"]: max(m["s0"] + int(0.3 * SR), m["s1"])]
        m["klevel_db"] = k_level_db(steady) - m["norm_gain_db"]
        changed = True
    return changed


def hshelf(fs: int, f0: float, gain_db: float, bw_oct: float = 1.0):
    """RBJ-cookbook high shelf (sfizz's eq_type=hshelf, bandwidth in octaves) -> (b, a)."""
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / fs
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw * np.sinh(np.log(2) / 2 * bw_oct * w0 / sw)
    b = [A * ((A + 1) + (A - 1) * cw + 2 * np.sqrt(A) * alpha), -2 * A * ((A - 1) + (A + 1) * cw),
         A * ((A + 1) + (A - 1) * cw - 2 * np.sqrt(A) * alpha)]
    a = [(A + 1) - (A - 1) * cw + 2 * np.sqrt(A) * alpha, 2 * ((A - 1) - (A + 1) * cw),
         (A + 1) - (A - 1) * cw - 2 * np.sqrt(A) * alpha]
    return np.array(b) / a[0], np.array(a) / a[0]


def add_eq_k(meta: list[dict]) -> bool:
    """Loudness change (K-weighted dB) per dB of the brightness shelf, per sample,
    so the CC1 volume curve can keep loudness on target while the shelf moves."""
    changed = False
    b, a = hshelf(SR, EQ_FREQ, 3.0)
    for m in meta:
        if m.get("eq_k_freq") == EQ_FREQ:
            continue
        y, _ = sf.read(str(QUARTET_DIR / m["path"]), dtype="float64", always_2d=True)
        steady = y[m["s0"]: max(m["s0"] + int(0.5 * SR), m["s1"])]
        m["eq_k"] = round((k_level_db(lfilter(b, a, steady, axis=0)) - k_level_db(steady)) / 3.0, 4)
        m["eq_k_freq"] = EQ_FREQ
        changed = True
    return changed


def a_level_db(x: np.ndarray) -> float:
    y = lfilter(AW_B, AW_A, x.mean(axis=1) if x.ndim == 2 else x)
    return float(10 * np.log10(np.mean(y.astype(np.float64) ** 2) + 1e-20))


def hpf(x, sr, fc, order=4):
    sos = butter(order, fc, btype="highpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x, axis=0)


def rms_track(mono, win):
    k = np.ones(win) / win
    return np.sqrt(np.convolve(mono.astype(np.float64) ** 2, k, mode="same") + 1e-20)


def best_align(mono, ref_end, q_center, W, search):
    """Return q (near q_center) maximising the normalised cross-correlation of
    mono[q-W:q] with mono[ref_end-W:ref_end]."""
    ref = mono[ref_end - W: ref_end]
    lo = max(W, q_center - search)
    hi = min(len(mono), q_center + search)
    if hi <= lo:
        return q_center, -1.0
    seg = mono[lo - W: hi]
    # correlation of ref with every window ending in [lo, hi)
    c = np.correlate(seg, ref, mode="valid")[: hi - lo]
    e = np.sqrt(np.convolve(seg ** 2, np.ones(W), mode="valid")[: hi - lo] * np.dot(ref, ref) + 1e-20)
    ncc = c / e
    i = int(np.argmax(ncc))
    return lo + i, float(ncc[i])


def extend_sustain(x: np.ndarray, sr: int, f0: float, s0: int, s1: int, total: int, seed: int,
                   cut: int | None = None):
    """Grow x to `total` samples by splicing grains from the steady region [s0, s1).

    Output = x[:cut] (attack + natural steady part) followed by grains taken
    from the steady region in random order; every splice point is aligned by
    normalised cross-correlation (waveform + vibrato phase) and crossfaded."""
    rng = np.random.default_rng(seed)
    mono = x.mean(axis=1).astype(np.float64)
    period = sr / f0
    W = int(max(0.035 * sr, 3 * period))
    XFL = int(0.07 * sr)
    s0 = max(s0, W + 1)
    s1 = min(s1, len(x) - XFL - 1)
    if s1 - s0 < int(0.25 * sr):
        s0 = max(W + 1, s1 - int(0.25 * sr))
    cut = min(cut if cut is not None else s1 - XFL, s1 - XFL)
    out = [x[:cut]]
    n = cut
    cur = cut                           # next source sample of the current grain
    fade_in = np.sin(0.5 * np.pi * (np.arange(XFL) + 0.5) / XFL) ** 2
    fade_out = 1.0 - fade_in
    last_q = -10 ** 9
    min_grain = int(0.18 * sr)
    avail = s1 - XFL - s0
    while n < total:
        # pick a new grain start among random candidates, keep the best-aligned
        best = None
        for _ in range(24):
            hi_q = s1 - XFL - min_grain
            if hi_q <= s0:
                q0 = s0
            else:
                q0 = int(rng.integers(s0, hi_q))
            if abs(q0 - cur) < 0.12 * sr or abs(q0 - last_q) < 0.1 * sr:
                if avail > 0.6 * sr:
                    continue
            q, ncc = best_align(mono, cur, q0, W, int(period) + 2)
            if best is None or ncc > best[1]:
                best = (q, ncc)
        q = best[0] if best else s0
        q = int(np.clip(q, s0, s1 - XFL - 1))
        a = x[cur: cur + XFL]
        b = x[q: q + XFL]
        m = min(len(a), len(b))
        out.append(a[:m] * fade_out[:m, None] + b[:m] * fade_in[:m, None])
        n += m
        g_len = int(rng.uniform(0.25, 0.7) * sr)
        start = q + m
        stop = min(start + g_len, s1 - XFL)
        if stop <= start:
            stop = min(start + min_grain, len(x) - XFL - 1)
        out.append(x[start:stop])
        n += stop - start
        cur = stop
        last_q = q
    y = np.concatenate(out, axis=0)[:total]
    # slow level normalisation toward the level of the stable window, from the
    # end of the attack onward (keeps the recorded bow attack untouched)
    steady = np.sqrt(np.mean(mono[s0:s1] ** 2) + 1e-20)
    r = rms_track(y.mean(axis=1), int(0.3 * sr))
    g = np.clip(steady / r, 10 ** (-6 / 20), 10 ** (6 / 20))
    ramp = np.clip((np.arange(len(y)) - (s0 - int(0.05 * sr))) / (0.25 * sr), 0, 1)
    g = 1.0 + (g - 1.0) * ramp
    return (y * g[:, None]).astype(np.float32)


# ------------------------------------------------------- sustain flattening
# Pitch: players drift 5-17 c for a few tenths of a second inside the steady part (violin I Db5 mf
# sits 7-14 c flat from 0.4 to 1.0 s, viola C6 ff 10-17 c flat at 0.55-0.85 s), and the grains of the
# spliced sustain inherit that, so a note is in tune over 2 s but off over the half second a quarter
# note plays.  flatten_pitch() removes the slow trend (Hann PITCH_TREND_S: vibrato at >= 3.5 Hz is
# >= 17 dB down, drifts below ~1.5 Hz are removed) from the recorded note before the sustain is
# spliced, by time-varying resampling (attack_tune's method); attack_tune.correct_attack() still
# handles the faster drift of the attack itself.
PITCH_TREND_S = 0.4
PITCH_FROM_T20_S = 0.15        # the flattening ramps in over 0.1 s from t20 + this
# Level: 69 of 1094 regions sat 3 dB low, then dipped 5.5-17 dB and jumped back within their first
# second (violin I Eb5 mf: -6 dB at 0.5-0.65 s, then +5.7 dB): recording content before the stable
# window, where extend_sustain's slow normalisation does not act.  flatten_level() pulls the level
# (LEVEL_WIN_S RMS) toward the sustain's median level wherever it strays more than LEVEL_DEADZONE_DB,
# from the end of the recorded rise on (max(t20 + 0.1 s, t3)), so the bow attack stays as recorded and
# the recording's own amplitude vibrato (+-1 dB) is untouched.
LEVEL_WIN_S = 0.1
LEVEL_DEADZONE_DB = 1.5
LEVEL_CLIP_DB = (-6.0, 12.0)
FLATTEN_VERSION = 1


def _sinc_read_chunked(x: np.ndarray, pos: np.ndarray, chunk: int = 1 << 15) -> np.ndarray:
    """attack_tune._sinc_read in chunks (bounded memory for 10 s samples)."""
    return np.concatenate([attack_tune._sinc_read(x, pos[i: i + chunk]) for i in range(0, len(pos), chunk)]
                          or [np.zeros((0, x.shape[1]))], axis=0)


def _hann_avg(v: np.ndarray, w: np.ndarray, n: int):
    """Weighted moving average of v (weights w) with a Hann window of n frames -> (avg, weight sum)."""
    k = np.hanning(max(3, n | 1))
    num = np.convolve(v * w, k, mode="same")
    den = np.convolve(w, k, mode="same")
    return num / np.maximum(den, 1e-12), den / k.sum()


def flatten_pitch(x: np.ndarray, sr: int, f_exp: float, start: int, ref: tuple[int, int],
                  win_s: float = PITCH_TREND_S, max_c: float = 60.0):
    """Remove the slow pitch trend of the recorded note x (frames, ch) from sample `start` on, relative to
    the median trend over ref = (a, b).  -> (y, remap, info); remap(i) = where sample i of x is in y."""
    mono = x.mean(axis=1).astype(np.float64)
    hop = int(0.01 * sr)
    info = dict(pitch_flat=False)
    if start >= len(mono) - int(0.5 * sr):
        return x, (lambda i: i), info
    f0, conf, W = attack_tune.yin_track(mono[start:], sr, f_exp, hop)
    if len(f0) < 10:
        return x, (lambda i: i), info
    centres = start + np.arange(len(f0)) * hop + W // 2
    ok = (conf < attack_tune.CONF_MAX) & np.isfinite(f0) & (f0 > 0)
    c = 1200 * np.log2(np.where(ok, f0, f_exp) / f_exp)
    tr, wsum = _hann_avg(c, ok.astype(float), int(win_s * sr / hop))
    valid = wsum > 0.3
    sel = valid & (centres >= ref[0]) & (centres < ref[1])
    if sel.sum() < 5 or valid.sum() < 10:
        return x, (lambda i: i), info
    r = float(np.median(tr[sel]))
    good = np.flatnonzero(valid)
    dev = np.interp(np.arange(len(tr)), good, tr[good] - r)
    corr = np.clip(-dev, -max_c, max_c) * np.clip((centres - start) / (0.1 * sr), 0, 1)
    n = np.arange(start, len(mono))
    c_s = np.interp(n, centres, corr, left=0.0, right=float(corr[-1]))
    rate = 2 ** (c_s / 1200.0)
    phi = start + np.concatenate([[0.0], np.cumsum(rate)[:-1]])
    phi = phi[phi < len(mono) - 17]
    y = np.concatenate([x[:start].astype(np.float64), _sinc_read_chunked(x.astype(np.float64), phi)], axis=0)
    phi_full = np.concatenate([np.arange(start, dtype=float), phi])

    def remap(i, phi_full=phi_full):
        return int(min(len(phi_full) - 1, np.searchsorted(phi_full, i)))
    m = centres >= start + 0.1 * sr
    info.update(pitch_flat=True, pitch_ref_c=round(r, 1),
                pitch_trend_p2_p98_c=round(float(np.percentile(dev[m], 98) - np.percentile(dev[m], 2)), 1)
                if m.sum() > 5 else 0.0)
    return y.astype(np.float32), remap, info


def level_track(mono: np.ndarray, sr: int, win_s: float = LEVEL_WIN_S, hop_s: float = 0.01):
    """RMS level (dB) over win_s windows centred on a hop_s grid -> (centres [samples], dB)."""
    W, H = int(win_s * sr), int(hop_s * sr)
    c = np.concatenate([[0.0], np.cumsum(mono.astype(np.float64) ** 2)])
    idx = np.arange(0, max(1, len(mono) - W), H)
    return idx + W // 2, 10 * np.log10((c[idx + W] - c[idx]) / W + 1e-20)


def flatten_level(y: np.ndarray, sr: int, t_from: int, ref_from: int, passes: int = 2) -> tuple[np.ndarray, dict]:
    """Pull the level of y (frames, ch) from sample t_from on toward the median level after ref_from,
    wherever it strays more than LEVEL_DEADZONE_DB (the excess is removed, clipped to LEVEL_CLIP_DB),
    ramped in over 50 ms.  Two passes (the second catches what the 100 ms window smeared)."""
    y = y.astype(np.float64)
    info = {}
    for p in range(passes):
        cen, lv = level_track(y.mean(axis=1), sr)
        tail = (cen >= ref_from) & (cen < len(y) - int(0.5 * sr))
        if tail.sum() < 10:
            return y.astype(np.float32), info
        target = float(np.median(lv[tail]))
        dev = lv - target
        corr = -np.sign(dev) * np.maximum(np.abs(dev) - LEVEL_DEADZONE_DB, 0.0)
        corr = np.clip(corr, *LEVEL_CLIP_DB)
        corr *= np.clip((cen - t_from) / (0.05 * sr), 0, 1)
        k = np.hanning(7)
        corr = np.convolve(corr, k / k.sum(), mode="same")
        g = np.interp(np.arange(len(y)), cen, corr, left=0.0, right=float(corr[-1]))
        if p == 0:
            early = (cen >= t_from) & (cen < t_from + int(1.2 * sr))
            info = dict(level_flat=True, level_max_boost_db=round(float(corr.max()), 1),
                        level_max_cut_db=round(float(-corr.min()), 1),
                        level_dev_p2_early_db=round(float(np.percentile(dev[early], 2)), 1) if early.any() else 0.0)
        y *= 10 ** (g / 20)[:, None]
    return y.astype(np.float32), info


def stable_window(x: np.ndarray, sr: int, att_s: float, sus_end_s: float):
    """Most stable stretch of the sustained note (flat envelope, early preferred)
    -> (start, end) in samples.  Protects against notes that were recorded with
    a swell or a fading bow."""
    db, hop = rms_db_track(x.mean(axis=1), sr)
    a = int((att_s + 0.04) * sr / hop)
    e = max(a + 5, int(sus_end_s * sr / hop))
    length = float(np.clip(0.45 * (e - a) * hop / sr, 0.35, 1.2))
    w = int(length * sr / hop)
    if e - a <= w:
        return a * hop, e * hop
    best, arg = 1e9, a
    for i in range(a, e - w + 1, 2):
        seg = db[i:i + w]
        slope = abs(np.polyfit(np.arange(w) * hop / sr, seg, 1)[0])
        score = np.std(seg) + 0.5 * slope + 0.4 * (i - a) * hop / sr
        if score < best:
            best, arg = score, i
    return arg * hop, (arg + w) * hop


def rms_db_track(mono, sr, win_s=0.02):
    hop = int(win_s * sr)
    n = len(mono) // hop
    fr = mono[: n * hop].reshape(n, hop).astype(np.float64)
    return 10 * np.log10(np.mean(fr ** 2, axis=1) + 1e-20), hop


def find_loop(mono: np.ndarray, sr: int, f0: float):
    """Loop points inside the (already extended) sustain tail, for notes longer
    than SUSTAIN_S; aligned by cross-correlation."""
    end = len(mono) - int(0.25 * sr)
    W = int(max(0.035 * sr, 3 * sr / f0))
    q, _ = best_align(mono, end, end - int(2.5 * sr), W, int(sr / f0) + 2)
    return q, end


# ------------------------------------------------------------------ selection
def load_analysis():
    data = json.loads((QUARTET_DIR / "analysis.json").read_text())
    table = defaultdict(list)       # (inst, dyn, midi) -> [candidates]
    for r in data:
        for n in r["notes"]:
            if n.get("junk"):
                continue
            table[(r["inst"], r["dyn"], n["midi"])].append(dict(file=r["file"], string=r["string"], hpf=r["hpf"], **n))
    return table


def string_pref(inst: str, midi: int) -> list[str]:
    strings = INSTRUMENTS[inst]["strings"]
    order = sorted(strings, key=lambda s: strings[s])              # low -> high
    below = [s for s in order if strings[s] < midi]
    first = below[-1] if below else order[0]
    rest = sorted(order, key=lambda s: (s != first, abs(strings[s] - strings[first]), -strings[s]))
    return rest


def choose(inst: str, table, shift: int = 0) -> dict:
    """-> {(dyn, midi): candidate}.  shift=1 prefers the next lower string when the
    note was recorded there at all three dynamics (the violin2 variant)."""
    keys = sorted({m for (i, d, m) in table if i == inst})
    picks = {}
    strings = INSTRUMENTS[inst]["strings"]
    order = sorted(strings, key=lambda s: strings[s])

    def ok(c):
        return c["body_s"] >= 0.45 and abs(c["cents"]) < 60

    for midi in keys:
        pref = string_pref(inst, midi)
        if shift:
            i = order.index(pref[0])
            if i - shift >= 0:
                lower = order[i - shift]
                if all(any(c["string"] == lower and ok(c) for c in table.get((inst, d, midi), []))
                       for d in DYNAMICS):
                    pref = [lower] + [s for s in pref if s != lower]

        # string that has all three dynamics (in preference order), else most
        best_s, best_cov = None, -1
        for s in pref:
            cov = sum(any(c["string"] == s and ok(c) for c in table.get((inst, d, midi), [])) for d in DYNAMICS)
            if cov > best_cov:
                best_s, best_cov = s, cov
        for d in DYNAMICS:
            cands = [c for c in table.get((inst, d, midi), []) if ok(c)]
            if not cands:
                continue
            same = [c for c in cands if c["string"] == best_s]
            if same:
                picks[(d, midi)] = max(same, key=lambda c: c["body_s"])
            else:
                picks[(d, midi)] = sorted(cands, key=lambda c: pref.index(c["string"]))[0]
    return picks


# ----------------------------------------------------------------- processing
def process_one(job):
    inst, dyn, midi, c, out_path, sustain_s = job
    src = base_of(inst)
    x, sr = load_iowa(src, RAW_DIR / src / c["file"])
    a = c["a"] + c["onset"]
    b = c["a"] + c["end"]
    seg = x[max(0, a - int(0.002 * sr)): b].astype(np.float64)
    f0 = midi_to_hz(midi + c["cents"] / 100.0)
    seg = hpf(seg, sr, max(c["hpf"], 0.6 * f0), order=4)
    if sr != SR:
        fr = Fraction(SR, sr).limit_denominator(1000)
        seg = resample_poly(seg, fr.numerator, fr.denominator, axis=0)
    fs = SR
    att = c["attack_s"]
    sus_end = min(c["sus_end_s"] - c["onset"] / sr - 0.06, len(seg) / fs - 0.1)
    s0, s1 = stable_window(seg, fs, att, max(sus_end, att + 0.4))
    # flatten the slow pitch trend of the recorded note (the grain source) before splicing
    t20_src = rise_times(seg, fs, s0, s1)["rise20_s"]
    seg, premap, flat_info = flatten_pitch(seg, fs, f0, int((t20_src + PITCH_FROM_T20_S) * fs), (s0, s1))
    s0, s1 = premap(s0), premap(s1)
    cut = s0 + int(min(0.3 * fs, (s1 - s0) / 2))
    total = int(sustain_s * fs)
    y = extend_sustain(seg, fs, f0, s0, s1, total, seed=midi * 7 + DYNAMICS.index(dyn), cut=cut)
    # flatten the pitch drift of the attack (attack_tune.py); y[:end] is the recorded
    # attack, the grain-spliced sustain starts at `cut`
    t20 = rise_times(y, fs, s0, s1)["rise20_s"]
    end = min(cut, max(s0, int((t20 + 0.45) * fs)))
    y, shift, att_info = attack_tune.correct_attack(y, fs, f0, end, t20)
    remap = att_info.pop("remap", None)
    if remap is not None:
        s0, s1, cut = int(remap(s0)), int(remap(s1)), int(remap(cut))
    # flatten the level from the end of the recorded rise on (dips before the stable window)
    rt = rise_times(y, fs, s0, s1)
    y, lev_info = flatten_level(y, fs, int(max(rt["rise20_s"] + 0.1, rt["rise3_s"]) * fs), cut + int(0.1 * fs))
    flat_info.update(lev_info)
    # fade the last 20 ms (the loop region never reaches it)
    fl = int(0.02 * fs)
    y[-fl:] *= np.linspace(1, 0, fl)[:, None]
    # onset fade-in of 2 ms (the pre-roll)
    fi = int(0.002 * fs)
    y[:fi] *= np.linspace(0, 1, fi)[:, None]
    steady = y[s0: max(s0 + int(0.3 * fs), s1)]
    level = a_level_db(steady)
    klevel = k_level_db(steady)
    peak = float(np.max(np.abs(y)))
    gain = 10 ** (-1.0 / 20) / peak                         # peak-normalise to -1 dBFS
    y *= gain
    loop_start, loop_end = find_loop(y.mean(axis=1), fs, f0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), y, fs, subtype="PCM_24")
    m = dict(inst=inst, dyn=dyn, midi=midi, file=c["file"], string=c["string"], cents=c["cents"],
             path=str(out_path.relative_to(QUARTET_DIR)), level_db=level, klevel_db=klevel,
             norm_gain_db=20 * np.log10(gain), attack_s=att, loop_start=int(loop_start), loop_end=int(loop_end),
             s0=s0, s1=s1, frames=len(y), attack=att_info, settle_s=att_info["settle_s"],
             flatten=flat_info, flat_v=FLATTEN_VERSION)
    m.update(rise_times(y, fs, s0, s1))
    return m


def rise_times(y: np.ndarray, fs: int, s0: int, s1: int) -> dict:
    """When the recorded tone reaches steady-20 / -6 / -3 dB (10 ms sliding RMS,
    5 ms steps).  t20 is where the tone really starts: before it there is up to
    0.2 s (viola, cello) of near-silence, sometimes with a bow-contact tick."""
    mono = y.mean(axis=1).astype(np.float64)[: int(2.5 * fs)]
    hop, w = int(0.005 * fs), int(0.01 * fs)
    db = 10 * np.log10(np.convolve(mono ** 2, np.ones(w) / w, mode="same")[::hop] + 1e-20)
    st = 10 * np.log10(np.mean(y.mean(axis=1)[s0:s1].astype(np.float64) ** 2) + 1e-20)

    def first(th):
        i = np.flatnonzero(db > st + th)
        return float(max(0, i[0] * hop - w // 2) / fs) if len(i) else s0 / fs
    return dict(rise20_s=first(-20.0), rise6_s=first(-6.0), rise3_s=first(-3.0))


SETTLE_VERSION = 2


def _settle_one(m):
    y, fs = sf.read(str(QUARTET_DIR / m["path"]), dtype="float64", always_2d=True)
    f0 = midi_to_hz(m["midi"] + m["cents"] / 100.0)
    end = min(m["s0"] + int(0.3 * fs), max(m["s0"], int((m["rise20_s"] + 0.45) * fs)))
    return attack_tune.measure_settle(y, fs, f0, end, m["rise20_s"])


def add_settle_times(meta: list[dict], jobs: int = 8) -> bool:
    """(Re)measure settle_s on the built (attack-corrected) samples when the rule changed."""
    todo = [m for m in meta if m.get("settle_v") != SETTLE_VERSION]
    if not todo:
        return False
    with ProcessPoolExecutor(jobs) as ex:
        for m, st in zip(todo, ex.map(_settle_one, todo)):
            m["settle_s"] = st
            m["settle_v"] = SETTLE_VERSION
    return True


def add_rise_times(meta: list[dict]) -> bool:
    changed = False
    for m in meta:
        if "rise20_s" in m:
            continue
        y, fs = sf.read(str(QUARTET_DIR / m["path"]), dtype="float64", always_2d=True)
        m.update(rise_times(y, fs, m["s0"], m["s1"]))
        changed = True
    return changed


def articulation_offsets(m: dict, fs: int = SR) -> dict:
    """Sample start per articulation (frames).  Every stroke starts no earlier than
    5 ms before the tone does (t20), so all instruments speak on the note-on;
    normal strokes keep at most NORMAL_RISE of a slow swell, short strokes
    SHORT_RISE; where the pitch only settles later (the scratch of an ff stroke on a
    low string, attack_tune.settle_s), a stroke starts at most SETTLE_LEAD before it;
    slurred notes enter in the sustain, after the pitch has settled."""
    t20, t3 = m["rise20_s"], m["rise3_s"]
    settle = m.get("settle_s", t20)
    start = max(0.0, t20 - 0.005)
    normal = max(start, t3 - NORMAL_RISE)
    short = max(start, t3 - SHORT_RISE) if t3 - t20 > 0.1 else max(start, start + 0.3 * (t3 - start))
    normal = max(normal, min(settle - SETTLE_LEAD["normal"], t20 + 0.2))
    short = max(short, min(settle - SETTLE_LEAD["short"], t20 + 0.2))
    legato = float(np.clip(max(t3 + 0.05, 0.12, settle + 0.02), 0.12, max(0.12, m["s1"] / fs - 0.2)))
    return dict(normal_offset=int(normal * fs), short_offset=int(short * fs), legato_offset=int(legato * fs))


# ------------------------------------------------------------------- SFZ
def smooth_levels(meta: list[dict]) -> dict:
    """Per-note calibration offsets (dB) so that each layer follows a smooth
    register curve and sits at LAYER_DB relative to the ff curve."""
    by_dyn = defaultdict(dict)
    for m in meta:
        # level of the note as it will sound = measured level + normalisation gain
        by_dyn[m["dyn"]][m["midi"]] = m["klevel_db"]
    out = {}
    curves = {}
    for d, lv in by_dyn.items():
        ks = np.array(sorted(lv))
        vs = np.array([lv[k] for k in ks])
        # robust smooth: rolling median (+-3 semitones) then quadratic fit
        med = np.array([np.median(vs[np.abs(ks - k) <= 3]) for k in ks])
        coef = np.polyfit(ks, med, 2 if len(ks) > 6 else 1)
        curves[d] = coef
    ref = curves.get("ff") if "ff" in curves else next(iter(curves.values()))
    keys = sorted({m["midi"] for m in meta})
    k_mid = keys[len(keys) // 2]
    dev = defaultdict(list)                  # each note's deviation from its layer's smooth curve
    for m in meta:
        dev[m["midi"]].append(m["klevel_db"] - float(np.polyval(curves[m["dyn"]], m["midi"])))
    for m in meta:
        k = m["midi"]
        # keep a little of the instrument's natural register slope (+-REGISTER_SLOPE_DB),
        # and pin the ff curve at the middle of the range to REF_DB for every instrument
        slope = float(np.clip(np.polyval(ref, k) - np.polyval(ref, k_mid), -REGISTER_SLOPE_DB, REGISTER_SLOPE_DB))
        target = REF_DB + slope + LAYER_DB[m["dyn"]]
        # all layers of a key keep the same 30 % of that key's natural unevenness,
        # so the pp/mf/ff crossfade of one key never bulges or dips
        keep = 0.3 * float(np.clip(np.mean(dev[k]), -3, 3))
        out[(m["dyn"], k)] = float(target + keep - m["klevel_db"])
    return out


def cc1_curve(eq_k: dict | None = None, eq_depth: float = 0.0) -> list[float]:
    """Volume (dB) to add at each CC1 value so loudness follows CC1_TARGET given
    equal-power crossfades between layers calibrated to LAYER_DB, and net of the
    brightness shelf's own loudness change (eq_k[layer] dB per dB of shelf)."""
    tx = [p[0] for p in CC1_TARGET]
    ty = [p[1] for p in CC1_TARGET]
    ex = [p[0] for p in EQ_CURVE]
    ey = [p[1] for p in EQ_CURVE]
    comp = []
    for v in range(128):
        p = 0.0
        k = 0.0
        for d, (i0, i1, o0, o1) in XF.items():
            # same maths as sfizz crossfadeIn/crossfadeOut (power curve -> linear power); the
            # fade length is (hi + 0.999 - lo - 1) / 127, i.e. (hi - lo) steps (kFillGap on hi)
            pin = 1.0 if (d == "pp" or v >= i1) else (0.0 if v < i0 else min(1.0, (v - i0) / (i1 - i0)))
            if d == "ff" or v <= o0:
                pout = 1.0
            else:
                pos = (v - o0) / (o1 - o0)
                pout = 0.0 if pos > 1 else 1.0 - pos
            w = pin * pout * 10 ** (LAYER_DB[d] / 10)
            p += w
            k += w * (eq_k or {}).get(d, 0.0)
        eq_db = (k / p) * eq_depth * float(np.interp(v, ex, ey)) if p > 0 else 0.0
        comp.append(float(np.interp(v, tx, ty) - 10 * np.log10(p) - eq_db))
    return comp


CORR_PATH = QUARTET_DIR / "tuning_corrections.json"


def load_corrections() -> dict:
    return json.loads(CORR_PATH.read_text()) if CORR_PATH.exists() else {}


RETUNE_MIN_C = 1.0      # errors below this are measurement noise and left alone (no churn between passes)


def retune(verify_json: Path, only: set, min_c: float = RETUNE_MIN_C):
    """Closed-loop tuning: fold the pitch errors measured by verify_tuning.py (through sfizz, per
    layer and key: the mean of YIN and harmonic-peak estimates over 0.45-1.05 s and 1.05-1.9 s)
    into tuning_corrections.json.  Keys are the SFZ region keys (every key of a chromatic set)."""
    rep = json.loads(Path(verify_json).read_text())
    rep = rep.get("steady", rep)
    corr = load_corrections()
    meta = json.loads((QUARTET_DIR / "samples" / "meta.json").read_text())
    n = 0
    for inst, layers in rep.items():
        if only and inst not in only:
            continue
        centres = {(m["dyn"], m["midi"]) for m in meta.get(inst, [])}
        for dyn, rows in layers.items():
            for r in rows:
                if (dyn, r["key"]) in centres and r["cents"] is not None and min_c <= abs(r["cents"]) < 60:
                    key = f"{inst}/{dyn}/{r['key']}"
                    corr[key] = round(corr.get(key, 0.0) - r["cents"], 1)
                    n += 1
    CORR_PATH.write_text(json.dumps(corr, indent=0, sort_keys=True))
    print(f"retune: updated {n} corrections -> {CORR_PATH}")


def shared_takes(meta: list[dict], base_meta: list[dict] | None) -> dict:
    """Violin II keys whose pick is the very take violin I plays at that key -> the meta entry of the
    neighbouring key's take (same string, same layer) that plays there instead, pitched by a semitone:
    violin II's own neighbour if it is on the same string, else violin I's (which violin I only plays
    at that neighbouring pitch).  Round-2 QA: on G3-D4, 82, 87 and 93-100 both desks played one
    recording, so a unison was one violin 6 dB louder (waveform correlation 1.00) instead of two
    players; a neighbour's take has its own vibrato and bow."""
    if not base_meta:
        return {}
    base = {(m["dyn"], m["midi"]): m for m in base_meta}
    by = {(m["dyn"], m["midi"]): m for m in meta}
    out = {}
    for (d, k), m in sorted(by.items()):
        b = base.get((d, k))
        if b is None or (b["file"], b["string"]) != (m["file"], m["string"]):
            continue
        for src in (by, base):
            for n in (k + 1, k - 1):                 # prefer the take above, pitched down (a darker colour)
                mn = src.get((d, n))
                if mn is not None and mn["string"] == m["string"]:
                    out[(d, k)] = mn
                    break
            if (d, k) in out:
                break
    return out


def write_sfz(inst: str, meta: list[dict], base_meta: list[dict] | None = None):
    corr = load_corrections()
    cal = smooth_levels(meta)
    eq_k = {d: float(np.median([m["eq_k"] for m in meta if m["dyn"] == d and "eq_k" in m] or [0.0]))
            for d in DYNAMICS}
    comp = cc1_curve(eq_k, EQ_DEPTH.get(inst, 2.0))
    depth = 30.0
    by = defaultdict(dict)
    for m in meta:
        by[m["dyn"]][m["midi"]] = m
    swap = shared_takes(meta, base_meta)
    cal_base = smooth_levels(base_meta) if swap else {}
    lo_all = INSTRUMENTS[inst]["lo"]
    hi_all = INSTRUMENTS[inst]["hi"]
    lines = [
        f"// {inst.capitalize()} (solo) - University of Iowa MIS 2012 arco samples, pp/mf/ff"
        + (f" (variant of {base_of(inst)}: next lower string where recorded)" if base_of(inst) != inst else ""),
        "// generated by ricercar/audio/strings/iowa_build.py - do not edit by hand",
        "// CC1 = dynamics (timbre crossfade + loudness), CC20 = articulation, CC21 = release,",
        "// velocity = attack softness / accent.  CC7/CC11 are applied by render_quartet.py.",
        "<control>",
        "hint_ram_based=1",      # load every sample into RAM: sfizz_render's disk streaming drops notes
        "set_cc1=88",
        "set_cc20=0",
        "set_cc21=30",
        "<curve>curve_index=17 " + " ".join(f"v{v:03d}={comp[v] / depth:.4f}" for v in range(128)),
        "<curve>curve_index=18 " + " ".join(
            f"v{v:03d}={np.interp(v, [p[0] for p in EQ_CURVE], [p[1] for p in EQ_CURVE]):.4f}" for v in range(128)),
        "<global>",
        "loop_mode=loop_continuous loop_crossfade=0.12",
        "xf_cccurve=power",
        f"volume_oncc1={depth:g} volume_curvecc1=17",
        # brightness follows CC1 inside each layer as well (0 dB at mf)
        f"eq1_type=hshelf eq1_freq={EQ_FREQ} eq1_bw=1 eq1_gain=0 "
        f"eq1_gain_oncc1={EQ_DEPTH.get(inst, 2.0):g} eq1_gain_curvecc1=18",
        "amp_veltrack=30",
        # normal stroke: velocity 127 = 15 ms, velocity 32 (pp) = 41 ms linear fade-in
        "ampeg_attack=0.05 ampeg_vel2attack=-0.035",
        "ampeg_release=0.03 ampeg_release_oncc21=1.2",
        "bend_up=200 bend_down=-200",
        "pitch_random=3",
        "volume=-6",
    ]
    arts = [  # (locc20, hicc20, offset key, envelope override)
        # normal bow stroke: recorded attack, slow swells shortened to NORMAL_RISE;
        # velocity 127 = the recorded bite, low velocity = a softer start (up to 50 ms)
        (0, 63, "normal_offset", None),
        # slurred: enters in the sustain, fades in under the previous note's release
        # (render_quartet.py starts it 20 ms early so the 30 ms fade is centred on the beat)
        (64, 95, "legato_offset", "ampeg_attack=0.03 ampeg_vel2attack=0"),
        # short (detache / spiccato-like): crisp start and a small accent decay
        (96, 127, "short_offset", "ampeg_attack=0.008 ampeg_vel2attack=0 ampeg_hold=0.03 "
                                   "ampeg_decay=0.12 ampeg_sustain=60"),
    ]
    for d in DYNAMICS:
        notes = by.get(d, {})
        if not notes:
            continue
        i0, i1, o0, o1 = XF[d]
        xf = []
        if d != "pp":
            xf.append(f"xfin_locc1={i0} xfin_hicc1={i1}")
        if d != "ff":
            xf.append(f"xfout_locc1={o0} xfout_hicc1={o1}")
        ks = sorted(notes)
        # key ranges: each sample covers up to half-way to its neighbours; extend
        # the ends by up to 3 semitones (pitch-shifted) to reach the full range
        bounds = []
        for j, k in enumerate(ks):
            lo = lo_all - 2 if j == 0 else (ks[j - 1] + k) // 2 + 1
            hi = hi_all if j == len(ks) - 1 else (k + ks[j + 1]) // 2
            lo = max(lo, k - 3) if j == 0 else lo
            hi = min(hi, k + 3) if j == len(ks) - 1 else hi
            bounds.append((lo, hi))
        for (lc, hc, offk, att) in arts:
            lines.append(f"<group> // {d} art cc20 {lc}-{hc}")
            lines.append(" ".join(xf + [f"locc20={lc} hicc20={hc}"] + ([att] if att else [])))
            for k, (lo, hi) in zip(ks, bounds):
                m = swap.get((d, k), notes[k])           # the take that plays key k (a neighbour's, see shared_takes)
                n = m["midi"]
                vol = (cal if m["inst"] == inst else cal_base)[(d, n)] - m["norm_gain_db"]
                # the closed tuning loop measures and corrects each region at its own key k
                tune = -m["cents"] + corr.get(f"{inst}/{d}/{k}", 0.0)
                reg = (f"<region> sample={m['path']} lokey={lo} hikey={hi} pitch_keycenter={n} "
                       f"tune={tune:.1f} volume={vol:.2f} loop_start={m['loop_start']} loop_end={m['loop_end']}")
                if offk:
                    reg += f" offset={articulation_offsets(m)[offk]}"
                reg += f"  // {midi_name(k)} {m['string']} {m['file']}"
                if n != k:
                    reg += (f" (the {midi_name(n)} take" + ("" if m["inst"] == inst else f" of {m['inst']}")
                            + f": {base_of(inst)} plays this key's own take)")
                lines.append(reg)
    out = QUARTET_DIR / f"{inst}.sfz"
    out.write_text("\n".join(lines) + "\n")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--sustain", type=float, default=SUSTAIN_S)
    ap.add_argument("--sfz-only", action="store_true", help="rewrite SFZ from samples/meta.json")
    ap.add_argument("--retune", type=Path, metavar="VERIFY_JSON",
                    help="fold the errors measured by verify_tuning.py --json into the tune corrections, "
                         "then rewrite the SFZ files (implies --sfz-only)")
    a = ap.parse_args()
    only = set(a.only.split(",")) - {""}
    if a.retune:
        retune(a.retune, only)
        a.sfz_only = True
    table = load_analysis()
    meta_path = QUARTET_DIR / "samples" / "meta.json"
    all_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    for inst in INSTRUMENTS:
        if only and inst not in only:
            continue
        src = base_of(inst)
        if not any(k[0] == src for k in table):
            print(f"{inst}: no analysed notes, skipped")
            continue
        if not a.sfz_only or inst not in all_meta:
            picks = choose(src, table, INSTRUMENTS[inst].get("string_shift", 0))
            jobs = []
            for (d, midi), c in sorted(picks.items(), key=lambda t: (t[0][1], t[0][0])):
                out = QUARTET_DIR / "samples" / inst / f"{inst}_{d}_{midi:03d}_{midi_name(midi)}.wav"
                jobs.append((inst, d, midi, c, out, a.sustain))
            with ProcessPoolExecutor(a.jobs) as ex:
                meta = list(ex.map(process_one, jobs))
            all_meta[inst] = meta
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(all_meta, indent=1))
        meta = all_meta[inst]
        if add_k_levels(meta) | add_rise_times(meta) | add_settle_times(meta, a.jobs) | add_eq_k(meta):
            meta_path.write_text(json.dumps(all_meta, indent=1))
        base_meta = all_meta.get(base_of(inst)) if base_of(inst) != inst else None
        path = write_sfz(inst, meta, base_meta)
        cov = {d: len([m for m in meta if m["dyn"] == d]) for d in DYNAMICS}
        sw = shared_takes(meta, base_meta)
        print(f"{inst}: {len(meta)} samples {cov} -> {path}"
              + (f"; {len(sw)} key x layer play a neighbour's take (violin I has this key's)" if sw else ""))


if __name__ == "__main__":
    main()
