#!/usr/bin/env python3
"""Every pipe the renderer can play, held 5 s and released: loop wraps and release joins checked.

usage: python3 tests/loop_sweep.py [--stops SUBSTR] [--hold 5.0] -> tests/loop_sweep.json

For every stop and every key of its division's compass (manuals 36-85, pedal 36-64), the pipe event
is rendered alone by pipe_engine.render_event (the renderer's own code path: attack, loops with
their crossfaded wraps, retuning, release chosen for a long key press, phase-aligned join):

* wrap clicks: per channel, the second difference over its running median (10 ms RMS, 21-window
  median), as in qa_organ.py, from 1.0 s to the key-up minus 60 ms, where only loop wraps can
  cause a spike; spikes > 12x are counted;
* level steps: on the stereo power (L^2+R^2)/2, the largest change between successive 20 ms windows
  in that span (a badly matched loop shows as a periodic level jump), and the level range over it;
* release join: per channel, second-difference spikes within +-60 ms of the key-up, against the
  sustain's own second-difference level (> 12x counted); and the stereo power 20-40 ms after the
  key-up relative to the sustain (a gap or a bump at the join would show). The mono sum is not
  used: the samples are spaced-pair recordings, and some pipes are nearly anti-phase between the
  channels, so their mono sum swings with any phase change while each channel is steady.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import scipy.signal as ss

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from organ_paths import SR  # noqa: E402
from pipe_engine import PipeBank, ReleaseCache, SampleCache, render_event  # noqa: E402

COMPASS = {'HW': (36, 85), 'POS': (36, 85), 'OW': (36, 85), 'PED': (36, 64)}


def spikes(m, a, b, ref_med=None):
    d2 = np.diff(m, 2)
    win = int(0.01 * SR)
    rms = np.sqrt(np.convolve(d2 ** 2, np.ones(win) / win, 'same')) + 1e-12
    med = ss.medfilt(rms[::win], 21)
    med = np.repeat(med, win)[:len(rms)] + 1e-9
    if ref_med is not None:
        med = np.maximum(med, ref_med)
    r = np.abs(d2[a:b]) / med[a:b]
    idx = np.nonzero(r > 12)[0]
    n = 0
    last = -10 ** 9
    for i in idx:
        if i - last > int(0.005 * SR):
            n += 1
        last = i
    return n, float(r.max()) if len(r) else 0.0, float(np.median(med[a:b])) if b > a else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stops')
    ap.add_argument('--hold', type=float, default=5.0)
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
    bank = PipeBank()
    samples = SampleCache()
    rels = ReleaseCache(samples)
    jobs = []
    for sk, st in bank.stops.items():
        if a.stops and a.stops not in sk:
            continue
        lo, hi = COMPASS[st['division']]
        for k in range(lo, hi + 1):
            jobs.append((sk, k))

    def one(job):
        sk, k = job
        pc = bank.choose(sk, k)
        if pc is None:
            return sk, k, None
        rng = np.random.default_rng(k)
        y, _ = render_event(bank, pc, a.hold, samples, rels, rng)
        y = y.astype(np.float64)
        pw = (y ** 2).mean(axis=1)                     # stereo power: what a stereo listener hears
        p = int(a.hold * SR)
        s0, s1 = int(1.0 * SR), p - int(0.06 * SR)
        wrap_n, wrap_max, rel_n, rel_max = 0, 0.0, 0, 0.0
        for c in range(2):                             # clicks per channel
            n_, mx_, med_ = spikes(y[:, c], s0, s1)
            rn_, rmx_, _ = spikes(y[:, c], p - int(0.06 * SR), p + int(0.06 * SR), ref_med=med_)
            wrap_n, wrap_max = wrap_n + n_, max(wrap_max, mx_)
            rel_n, rel_max = rel_n + rn_, max(rel_max, rmx_)
        w = int(0.02 * SR)
        seg = pw[s0:s1]
        nw = len(seg) // w
        lv = 10 * np.log10(seg[:nw * w].reshape(nw, w).mean(axis=1) + 1e-24)
        sus = float(np.mean(pw[p - int(0.25 * SR):p - int(0.05 * SR)]))
        after = float(np.mean(pw[p + int(0.02 * SR):p + int(0.04 * SR)]))
        return sk, k, dict(file=pc.file, shift_cents=round(pc.shift_cents, 1), wrap_spikes=wrap_n,
                           wrap_spike_max_ratio=round(wrap_max, 1), level_step_max_db=round(float(np.abs(np.diff(lv)).max()), 2),
                           level_range_db=round(float(lv.max() - lv.min()), 2), release_spikes=rel_n,
                           release_spike_max_ratio=round(rel_max, 1),
                           level_30ms_after_keyup_db=round(10 * math.log10(after / (sus + 1e-24) + 1e-24), 1))
    t0 = time.time()
    out = {}
    with ThreadPoolExecutor(a.jobs) as ex:
        for sk, k, r in ex.map(one, jobs):
            out.setdefault(sk, {})[k] = r
    summ = {}
    allr = [r for d in out.values() for r in d.values() if r]
    for sk, d in out.items():
        rs = [r for r in d.values() if r]
        summ[sk] = dict(keys=len(rs), wrap_spikes=sum(r['wrap_spikes'] for r in rs),
                        level_step_max_db=max(r['level_step_max_db'] for r in rs),
                        level_range_max_db=max(r['level_range_db'] for r in rs),
                        release_spikes=sum(r['release_spikes'] for r in rs),
                        after_keyup_db_range=[min(r['level_30ms_after_keyup_db'] for r in rs),
                                              max(r['level_30ms_after_keyup_db'] for r in rs)])
    tot = dict(pipes=len(allr), wrap_spikes=sum(r['wrap_spikes'] for r in allr),
               pipes_with_wrap_spikes=sum(1 for r in allr if r['wrap_spikes']),
               level_step_max_db=max(r['level_step_max_db'] for r in allr),
               level_step_p99_db=round(float(np.percentile([r['level_step_max_db'] for r in allr], 99)), 2),
               level_range_p99_db=round(float(np.percentile([r['level_range_db'] for r in allr], 99)), 2),
               release_spikes=sum(r['release_spikes'] for r in allr),
               pipes_with_release_spikes=sum(1 for r in allr if r['release_spikes']),
               after_keyup_db_median=float(np.median([r['level_30ms_after_keyup_db'] for r in allr])),
               seconds=round(time.time() - t0, 1))
    res = {'hold_s': a.hold, 'total': tot, 'per_stop': summ, 'per_key': out}
    Path(HERE / 'tests').mkdir(exist_ok=True)
    json.dump(res, open(HERE / 'tests' / 'loop_sweep.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(tot, indent=1))
    for sk, s_ in summ.items():
        print(f'{sk:28s} {s_}')
    worst = sorted(((r['wrap_spikes'] + r['release_spikes'], sk, k, r) for sk, d in out.items() for k, r in d.items() if r),
                   key=lambda t: -t[0])[:12]
    for w in worst:
        if w[0]:
            print('worst', w[1], w[2], w[3])


if __name__ == '__main__':
    main()
