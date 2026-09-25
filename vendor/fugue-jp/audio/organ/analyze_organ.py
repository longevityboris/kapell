#!/usr/bin/env python3
"""Measure every pipe of the Norrfjärden sample set once -> data/norrfjarden_pipes.json.

usage: python3 analyze_organ.py [--jobs 8] [--only STOPNAME]

For every sample file used by a sounding stop (main pipes, attack alternates, subsemitone pipes):

* ``f8``: the pipe's pitch expressed as the 8'-equivalent key frequency (fundamental x 8 / harmonic
  number), measured on the steady region (before the release cue) with a harmonic comb: the comb
  of multiples of f8/2 whose summed spectral magnitude is largest, searched in 0.25-cent steps within
  +-150 cents of the RIFF ``smpl`` pitch (single-rank stops) or of the organ key's nominal pitch
  (compound stops: mixtures, Sesquialtera, Cimbel, Zimbel, whose ``smpl`` pitch is not the key's).
  Every rank of a compound stop is a multiple of f8/2 when tuned pure, so the comb measures the key
  reference the whole compound is tuned to.
* loops (``smpl`` or ODF override) with their wrap error: the RMS difference between the samples
  that follow the loop end and the loop's first samples, relative to the loop's RMS (0 = seamless).
* ``cue`` (release start), ``rms_db`` of the steady tone, ``onset_ms`` (first sample within 40 dB of
  the steady level) and ``speech_ms`` (time to within 6 dB of it).
* ``lr_lag``: the delay (source samples, <= 1.5 ms) of the right channel that maximises the L/R
  correlation of the steady tone, with the mono fold-down before and after it (the samples are
  spaced-pair recordings; the renderer applies the lag so that no pipe is anti-phase in mono).

The renderer (render_organ.py) retunes each pipe from its measured f8 to the target temperament, so
the organ's own 1/4-comma meantone at about a semitone above A=440 (hoher Chorton) plays in equal
temperament at A=440, with mutations and mixtures pure against the tempered unison.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odf import file_key, load_organ, read_sample  # noqa: E402
from organ_paths import PIPES_JSON  # noqa: E402

SINGLE_RANK_MAX_H = 48   # harmonic numbers above this (and the Sesquialtera) are compound stops
COMPOUND = ('Mixtur', 'Sesquialtera', 'Cimball', 'Zimball')
REED_DIRS = ('Pos16/', 'Tr8/', 'D8/', 'Cor4/', 'Kh8/', 'Dul16/', 'Geigen4/', 'D16/', 'Regal8/', 'Sch8/')


def f_of_midi(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def cents(a, b):
    return 1200.0 * math.log2(a / b)


def harmonic_comb(x, sr, f_guess, span_cents=150.0, fmax=9000.0, base_ratio=0.5):
    """-> (f8, score_ratio): the f8 maximising the comb of multiples of f8*base_ratio (magnitude^0.5).

    base_ratio = harmonic/8 (the pipe's own fundamental) for single-rank stops, 1/2 for compound
    stops, whose ranks are all multiples of f8/2 when tuned pure."""
    n = len(x)
    w = np.hanning(n)[:, None]
    nfft = 1 << int(math.ceil(math.log2(n * 4)))
    X = np.fft.rfft(x * w, nfft, axis=0)
    mag = np.sqrt(np.sqrt((np.abs(X) ** 2).sum(axis=1)))
    df = sr / nfft

    def score(f8s):
        base = f8s * base_ratio
        out = np.zeros(len(f8s))
        kmax = int(fmax / base.min())
        for k in range(1, kmax + 1):
            fk = k * base
            ok = fk < fmax
            idx = fk / df
            i0 = np.floor(idx).astype(int)
            fr = idx - i0
            v = mag[i0] * (1 - fr) + mag[np.minimum(i0 + 1, len(mag) - 1)] * fr
            out += np.where(ok, v, 0.0)
        return out
    grid = f_guess * 2.0 ** (np.arange(-span_cents, span_cents + 0.25, 0.25) / 1200.0)
    s = score(grid)
    i = int(np.argmax(s))
    fine = grid[i] * 2.0 ** (np.arange(-0.3, 0.3001, 0.01) / 1200.0)
    sf_ = score(fine)
    f8 = float(fine[int(np.argmax(sf_))])
    return f8, float(s[i] / (np.median(s) + 1e-12))


def loop_error(a, s, e, L=48):
    """wrap error of an inclusive loop [s, e]: samples after e vs samples from s."""
    if e + 1 + L > len(a) or s + L > len(a):
        L = max(4, min(len(a) - e - 1, len(a) - s))
    ref = a[s:s + L]
    nxt = a[e + 1:e + 1 + L]
    if len(nxt) < len(ref):
        return float('nan')
    body = a[s:e + 1]
    r = np.sqrt(np.mean(body ** 2)) + 1e-12
    return float(np.sqrt(np.mean((ref - nxt) ** 2)) / r)


def variant(rel):
    """'D#' / 'Eb' for the split-key pipes, else ''."""
    m = re.search(r'\d{3}-(D#|Eb)', rel)
    return m.group(1) if m else ''


def analyse_file(args):
    rel, harm, compound, odf_loops, med_guess = args
    t0 = time.time()
    s = read_sample(rel)
    a, sr = s.audio, s.sr
    n = len(a)
    loops = odf_loops or s.loops
    cue = s.cue if s.cue else n
    lo = min([l[0] for l in loops]) if loops else int(0.35 * sr)
    lo = max(lo, int(0.25 * sr))
    hi = cue if cue > lo + int(0.3 * sr) else n
    seg = a[lo:min(hi, lo + int(2.5 * sr))]
    key = file_key(rel)
    nominal8 = f_of_midi(key) * 2 ** (105 / 1200)      # organ ~ +105 c above A440 on the same key
    flag = ''
    if compound:
        # the division's single-rank pipes on the same key (and D#/Eb side) give the key's pitch;
        # the compound's ranks are tuned to it, so search +-40 cents around it
        guess = med_guess or nominal8
        f8, sharp = harmonic_comb(seg, sr, guess, span_cents=40.0, base_ratio=0.5)
        if abs(cents(f8, guess)) > 35.0:
            flag = 'compound pitch at the search edge: using the key pitch of the single-rank stops'
            f8 = guess
    else:
        guess = f_of_midi(s.smpl_pitch) * 8.0 / harm if s.smpl_pitch else nominal8
        span = 50.0
        if abs(cents(guess, nominal8)) > 250:          # smpl pitch does not belong to this key
            guess, span = nominal8, 150.0
            flag = 'smpl pitch inconsistent with the file name: searched around the key'
        f8, sharp = harmonic_comb(seg, sr, guess, span_cents=span, base_ratio=harm / 8.0)
    # envelope for onset / speech time / level
    mono2 = (a ** 2).sum(axis=1)
    win = max(1, int(0.005 * sr))
    env = np.sqrt(np.convolve(mono2, np.ones(win) / win, mode='same') + 1e-20)
    steady = float(np.sqrt(np.mean((seg ** 2).sum(axis=1))))
    onset = int(np.argmax(env > steady * 10 ** (-40 / 20)))
    speech = int(np.argmax(env > steady * 10 ** (-6 / 20)))
    lerr = []
    mono = a.mean(axis=1)
    for (ls, le) in loops:
        lerr.append(round(loop_error(mono, ls, le), 5))
    # inter-channel alignment: the spaced microphones put some pipes nearly anti-phase in the mono
    # sum; the lag (<= 1.5 ms) that maximises the L/R correlation of the steady tone is applied to the
    # right channel by the renderer (as the piano lane does per note)
    L, R = seg[:, 0].astype(np.float64), seg[:, 1].astype(np.float64)
    nn = len(L)
    cc = np.fft.irfft(np.fft.rfft(L, 2 * nn) * np.conj(np.fft.rfft(R, 2 * nn)))
    ml = int(0.0015 * sr)
    cc = np.concatenate([cc[-ml:], cc[:ml + 1]])
    lr_lag = int(np.arange(-ml, ml + 1)[int(np.argmax(cc))])
    ps = np.mean((L ** 2 + R ** 2) / 2) + 1e-24
    mono0 = 10 * math.log10(np.mean(((L + R) / 2) ** 2) / ps + 1e-24)
    R2 = np.roll(R, lr_lag)
    mono1 = 10 * math.log10(np.mean(((L + R2) / 2) ** 2) / ps + 1e-24)
    rel_decay = None
    if s.cue and n - s.cue > int(0.5 * sr):
        tail = mono2[s.cue:]
        edc = np.cumsum(tail[::-1])[::-1]
        edc_db = 10 * np.log10(edc / edc[0] + 1e-30)
        i5, i25 = int(np.argmax(edc_db <= -5)), int(np.argmax(edc_db <= -25))
        if i25 > i5 > 0:
            t = np.arange(i5, i25) / sr
            p = np.polyfit(t, edc_db[i5:i25], 1)
            rel_decay = round(float(-60 / p[0]), 3)
    return rel, dict(
        key=key, harmonic=harm, sr=sr, n=n, dur=round(n / sr, 3), loops=[list(l) for l in loops],
        loop_err=lerr, cue=s.cue, smpl_pitch=None if s.smpl_pitch is None else round(s.smpl_pitch, 4),
        f8=round(f8, 5), f8_cents_vs_key_et=round(cents(f8, f_of_midi(key)), 2), comb_peak=round(sharp, 2),
        rms_db=round(20 * math.log10(steady + 1e-12), 2), onset_ms=round(onset / sr * 1000, 1),
        speech_ms=round(speech / sr * 1000, 1), release_T20=rel_decay, flag=flag,
        lr_lag=lr_lag, mono_folddown_db=round(mono0, 2), mono_folddown_aligned_db=round(mono1, 2),
        secs=round(time.time() - t0, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--only')
    ap.add_argument('-o', default=str(PIPES_JSON))
    a = ap.parse_args()
    org = load_organ()
    tasks, stops_out = {}, {}
    for div, stops in org.items():
        for name, st in stops.items():
            if a.only and a.only not in name:
                continue
            compound = st.harmonic > SINGLE_RANK_MAX_H or any(c in name for c in COMPOUND)
            files = []
            for p in st.pipes + st.extra_files:
                for f in p.attacks:
                    files.append(f)
                    tasks.setdefault(f, [f, p.harmonic, compound, p.loops, None, div])
            stops_out[f'{div}/{name}'] = dict(
                division=div, name=name, harmonic=st.harmonic, amp=st.amp, compound=compound,
                pipes=[dict(index=p.index, file=p.file, attacks=p.attacks, releases=p.releases, amp=p.amp,
                            harmonic=p.harmonic, pitch_tuning=p.pitch_tuning) for p in st.pipes],
                extra=[dict(index=p.index, file=p.file, attacks=p.attacks, releases=p.releases, amp=p.amp,
                            harmonic=p.harmonic, pitch_tuning=p.pitch_tuning) for p in st.extra_files],
                files=sorted(set(files)))
    t0 = time.time()
    results = {}
    single = [t for t in tasks.values() if not t[2]]
    compound = [t for t in tasks.values() if t[2]]
    with ProcessPoolExecutor(a.jobs) as ex:
        for rel, r in ex.map(analyse_file, [t[:5] for t in single], chunksize=4):
            results[rel] = r
        # key pitch per (division, key, D#/Eb side) from single-rank flue stops (reeds drift)
        med = {}
        for t in single:
            r = results[t[0]]
            if any(x in t[0] for x in REED_DIRS):
                continue
            med.setdefault((t[5], r['key'], variant(t[0])), []).append(r['f8'])
        for t in compound:
            k = file_key(t[0])
            v = med.get((t[5], k, variant(t[0]))) or med.get((t[5], k, ''))
            t[4] = float(np.median(v)) if v else None
        for rel, r in ex.map(analyse_file, [t[:5] for t in compound], chunksize=4):
            results[rel] = r
    print(f'analysed {len(results)} files in {time.time() - t0:.0f} s')
    out = dict(sample_set='Norrfjärden Church Baroque Replica (Lars Palo, CC BY-SA 4.0), version 20230618',
               method=__doc__.strip().split('\n\n')[1], stops=stops_out, files=results)
    Path(a.o).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.o, 'w'), indent=1, ensure_ascii=False)
    print('wrote', a.o)


if __name__ == '__main__':
    main()
