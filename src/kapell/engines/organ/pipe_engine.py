"""Pipe-level sample playback for the Norrfjärden organ (used by render_organ.py).

One *pipe event* = one rank sounding one key from t_on to t_off. Its audio is built the way
GrandOrgue plays a pipe, offline and deterministically:

1. **Pipe choice and tuning.** The target is the key's pitch in the chosen temperament at A4
   (default equal temperament, 440 Hz), times harmonic/8 for the rank (so quints and mixture ranks are
   pure against the tempered unison). Among the rank's recorded pipes, the one whose measured pitch
   (``data/norrfjarden_pipes.json``) is nearest is used and retuned by resampling. The organ stands
   about a semitone above A440 (hoher Chorton), so key k is normally played by the organ's pipe k-1,
   retuned by a few cents out of its 1/4-comma meantone; keys the organ lacks (its short bass octave)
   borrow the neighbouring pipe, retuned by about a semitone (counted in the report).
2. **Sustain.** Attack from the sample start, then one of the sample's loops (chosen per note among
   the loops that wrap cleanly, preferring long ones) repeated with a 4 ms crossfade at every wrap.
   The sustain is built at the source rate and resampled once (soxr, very high quality), so the
   retuning never breaks a loop.
3. **Stereo.** The samples are spaced-pair recordings; some pipes are nearly anti-phase between the
   channels. The right channel of each pipe (sustain and releases alike) is delayed by the lag,
   measured on its steady tone (<= 1.5 ms), that maximises the L/R correlation, so no pipe drops out
   in mono. The shift is applied after the loops are built, so their seams are untouched.
4. **Release.** The release sample is chosen by how long the key was held, as the ODF prescribes
   (``rel00150`` <= 150 ms, ``rel00500`` <= 500 ms, else the recorded release that follows the cue in
   the main file). Release samples begin with steady tone before their cue; the renderer crossfades
   from the sustain into that steady tone at the phase that matches best (search over one period, so
   the key-up moment moves by at most half a period), level-matched, and the recorded release (the pipe
   stopping and the Norrfjärden church's decay) follows.
"""
from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass

import numpy as np
import soxr

from odf import read_sample
from organ_paths import PIPES_JSON, SR

# Temperaments: cents relative to equal temperament per pitch class (C..B), with A = 0.
TEMPERAMENTS = {
    'equal': [0.0] * 12,
    'vallotti': [5.9, 0.0, 2.0, 3.9, -2.0, 7.8, -2.0, 3.9, 2.0, 0.0, 5.9, -3.9],
    'werckmeister3': [11.7, 2.0, 3.9, 5.9, 2.0, 9.8, 0.0, 7.8, 3.9, 0.0, 7.8, 3.9],
}
MAX_SHIFT_CENTS = 160.0     # beyond this a key has no pipe on this rank (folded by the renderer)
LOOP_XFADE_S = 0.004
GOOD_LOOP_ERR = 0.06


def cents(a, b):
    return 1200.0 * math.log2(a / b)


@dataclass
class PipeChoice:
    file: str                 # main sample of the chosen pipe
    attacks: list             # [(file, f8)]
    releases: list            # [(file, max_ms)]
    f8: float                 # measured 8'-equivalent pitch of the main sample
    ratio: float              # retune ratio (target / measured)
    shift_cents: float
    gain: float               # stop x pipe AmplitudeLevel
    fundamental: float        # target fundamental of the pipe (Hz), for crossfade sizes


class PipeBank:
    def __init__(self, temperament='equal', a4=440.0, model=None):
        self.model = model or json.load(open(PIPES_JSON))
        self.files = self.model['files']
        self.stops = self.model['stops']
        if temperament not in TEMPERAMENTS:
            raise SystemExit(f'unknown temperament {temperament}; known: {", ".join(TEMPERAMENTS)}')
        self.temper = TEMPERAMENTS[temperament]
        self.a4 = a4
        self._choice = {}

    def target_f8(self, key):
        return self.a4 * 2.0 ** ((key - 69) / 12.0 + self.temper[key % 12] / 1200.0)

    def choose(self, stop_key, key):
        """-> PipeChoice or None (no pipe within MAX_SHIFT_CENTS)."""
        ck = (stop_key, key)
        if ck in self._choice:
            return self._choice[ck]
        st = self.stops[stop_key]
        target = self.target_f8(key)
        best = None
        seen = set()
        for p in st['pipes'] + st['extra']:
            if p['file'] in seen or p['file'] not in self.files:
                continue
            seen.add(p['file'])
            f8 = self.files[p['file']]['f8']
            c = cents(target, f8)
            if best is None or abs(c) < abs(best[0]):
                best = (c, p, f8)
        if best is None or abs(best[0]) > MAX_SHIFT_CENTS:
            self._choice[ck] = None
            return None
        c, p, f8 = best
        attacks = [(f, self.files[f]['f8']) for f in p['attacks'] if f in self.files]
        pc = PipeChoice(file=p['file'], attacks=attacks, releases=[tuple(r) for r in p['releases']],
                        f8=f8, ratio=target / f8, shift_cents=c, gain=st['amp'] * p['amp'],
                        fundamental=target * p['harmonic'] / 8.0)
        self._choice[ck] = pc
        return pc


# -------------------------------------------------------------------------------------------------
# sample cache (per render; decoded WavPack at the source rate)

class SampleCache:
    def __init__(self):
        self._d = {}
        self._lock = threading.Lock()
        self._flocks = {}

    def get(self, rel):
        with self._lock:
            if rel in self._d:
                return self._d[rel]
            fl = self._flocks.setdefault(rel, threading.Lock())
        with fl:
            with self._lock:
                if rel in self._d:
                    return self._d[rel]
            s = read_sample(rel)
            with self._lock:
                self._d[rel] = s
            return s

    def drop(self, rels):
        with self._lock:
            for r in rels:
                self._d.pop(r, None)


def shift_right(x, lag):
    """delay the right channel by `lag` samples (advance if negative), zero-filled."""
    if not lag:
        return x
    y = x.copy()
    if lag > 0:
        y[lag:, 1] = x[:-lag, 1]
        y[:lag, 1] = 0.0
    else:
        y[:lag, 1] = x[-lag:, 1]
        y[lag:, 1] = 0.0
    return y


def resample(x, sr_in, ratio):
    """play x (at sr_in) faster by `ratio` and return it at SR."""
    return soxr.resample(x, sr_in * ratio, SR, quality='VHQ').astype(np.float32)


def choose_loop(info, rng):
    loops = info['loops']
    errs = info['loop_err']
    if not loops:
        return None
    good = [i for i, e in enumerate(errs) if e == e and e < GOOD_LOOP_ERR]
    if good:
        w = np.array([loops[i][1] - loops[i][0] for i in good], dtype=float)
        return loops[good[int(rng.choice(len(good), p=w / w.sum()))]]
    i = int(np.nanargmin([e if e == e else 9 for e in errs]))
    return loops[i]


def build_sustain(sample, loop, n_src):
    """attack + repeated loop (4 ms crossfade at each wrap) at the source rate, n_src samples."""
    a = sample.audio
    if loop is None or n_src <= loop[1] + 1:
        if n_src <= len(a):
            return a[:n_src]
        return np.concatenate([a, np.zeros((n_src - len(a), 2), np.float32)])
    s, e = loop
    L = int(LOOP_XFADE_S * sample.sr)
    L = max(0, min(L, s, (e - s) // 4))
    body = a[s:e + 1].copy()
    head = a[:e + 1].copy()
    if L > 0:
        w = np.linspace(0.0, 1.0, L, dtype=np.float32)[:, None]
        xf = a[e + 1 - L:e + 1] * (1 - w) + a[s - L:s] * w
        body[-L:] = xf
        head[-L:] = xf
    reps = int(math.ceil(max(0, n_src - len(head)) / len(body)))
    out = np.concatenate([head] + [body] * reps) if reps else head
    return out[:n_src]


def pick_release(releases, hold_ms):
    lim = sorted([r for r in releases if r[1] is not None], key=lambda r: r[1])
    for r in lim:
        if hold_ms <= r[1]:
            return r
    unl = [r for r in releases if r[1] is None]
    if unl:
        return unl[0]
    return lim[-1] if lim else None


class ReleaseCache:
    """resampled release material per (file, ratio): (audio at SR from cue - pre, cue index in it)."""
    def __init__(self, samples: SampleCache):
        self.samples = samples
        self._d = {}
        self._lock = threading.Lock()

    def drop(self, rels):
        with self._lock:
            for k in [k for k in self._d if k[0] in rels]:
                del self._d[k]

    def get(self, rel, ratio, lag=0):
        k = (rel, round(ratio, 7), lag)
        with self._lock:
            if k in self._d:
                return self._d[k]
        s = self.samples.get(rel)
        cue = s.cue if s.cue is not None else int(len(s.audio) * 0.6)
        pre = min(cue, int(0.12 * s.sr))
        seg = shift_right(s.audio[cue - pre:], lag)
        y = resample(seg, s.sr, ratio)
        c = int(round(pre * SR / (s.sr * ratio)))
        # trim the recorded tail where it has decayed below -90 dB of its steady part
        ref = float(np.sqrt(np.mean(y[:max(1, c)] ** 2))) + 1e-9
        env = np.abs(y).max(axis=1)
        above = np.nonzero(env > ref * 10 ** (-90 / 20))[0]
        end = int(above[-1]) + 1 if len(above) else len(y)
        y = y[:max(end, c + 1)]
        fade = min(len(y) - c, int(0.05 * SR))
        if fade > 8:
            y[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
        with self._lock:
            self._d[k] = (y, c)
        return y, c


def render_event(bank: PipeBank, pc: PipeChoice, hold_s: float, samples: SampleCache,
                 rels: ReleaseCache, rng, stats=None):
    """-> stereo float32 audio of one pipe event (key down at index 0, key up at hold_s)."""
    fname, _f8a = pc.attacks[int(rng.integers(len(pc.attacks)))] if len(pc.attacks) > 1 else pc.attacks[0]
    info = bank.files[fname]
    s = samples.get(fname)
    ratio = pc.ratio * (pc.f8 / _f8a) if _f8a else pc.ratio      # alternates are retuned on their own
    p = max(1, int(round(hold_s * SR)))                            # key-up index at SR
    period = SR / max(pc.fundamental, 20.0)
    X = int(min(max(2 * period, 0.006 * SR), 0.030 * SR))          # crossfade length
    W = int(min(max(period, 0.001 * SR), 0.032 * SR))              # phase search span
    D = X + int(0.001 * SR)                                        # crossfade ends 1 ms before the cue
    rel = pick_release(pc.releases, hold_s * 1000.0)
    need = p + W + int(0.02 * SR)
    n_src = int(math.ceil(need * s.sr * ratio / SR)) + 64
    loop = choose_loop(info, rng)
    lag = int(bank.files[pc.file].get('lr_lag', 0))          # the pipe's L/R alignment (main sample)
    sus = resample(shift_right(build_sustain(s, loop, n_src), lag), s.sr, ratio)
    fade_in = min(48, len(sus))
    sus[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)[:, None]
    if rel is None:                                                 # no release recorded: 60 ms fade
        f = int(0.06 * SR)
        out = sus[:p + f].copy()
        out[p:] *= np.linspace(1, 0, len(out) - p, dtype=np.float32)[:, None]
        return out * pc.gain, 0
    R, c = rels.get(rel[0], ratio, lag)
    if p < D + W // 2 + 1:                                          # very short note: shrink the joint
        D = max(8, int(p * 0.6))
        X = max(4, D - int(0.001 * SR))
        W = min(W, max(2, p - D))
    D = min(D, c)
    X = min(X, D)
    o = c - D                                                       # release read position
    ref = R[o:o + X].mean(axis=1)
    lo = max(0, p - D - W // 2)
    hi = max(lo, min(p - D + W // 2, len(sus) - X))
    seg = sus[lo:hi + X].mean(axis=1)
    if hi > lo and len(ref) == X and len(seg) >= X:
        cc = np.correlate(seg, ref, mode='valid')                   # one value per candidate start
        e = np.sqrt(np.convolve(seg ** 2, np.ones(X), mode='valid')) * (np.sqrt(np.sum(ref ** 2)) + 1e-12)
        ncc = cc / (e + 1e-12)
        q = lo + int(np.argmax(ncc))
        corr = float(ncc.max())
    else:
        q = max(0, min(p - D, len(sus) - X))
        corr = 0.0
    a_s = float(np.sqrt(np.mean(sus[q:q + X] ** 2))) + 1e-9
    a_r = float(np.sqrt(np.mean(R[o:o + X] ** 2))) + 1e-9
    g = 1.0 if rel[0] == fname else float(np.clip(a_s / a_r, 10 ** (-6 / 20), 10 ** (6 / 20)))
    t = np.linspace(0.0, 1.0, X, dtype=np.float32)
    if corr > 0.6:
        w_in, w_out = t, 1.0 - t
    else:                                                           # uncorrelated: equal power
        w_in, w_out = np.sin(t * np.pi / 2), np.cos(t * np.pi / 2)
    tail = R[o:] * g
    out = np.empty((q + len(tail), 2), np.float32)
    out[:q] = sus[:q]
    out[q:q + X] = sus[q:q + X] * w_out[:, None] + tail[:X] * w_in[:, None]
    out[q + X:] = tail[X:]
    if stats is not None:
        stats.append((corr, (q + D - p) / SR * 1000.0, 20 * math.log10(g)))
    return out * pc.gain, q + D - p
