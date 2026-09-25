#!/usr/bin/env python3
"""Section timeline of the skeleton under plan.json, with the same time grid as tools/perform.py.

usage: python3 timeline.py [SCORE.ly] [PLAN.json]      (defaults: SK_final.ly, plan.json)
Prints each section's bars, start time, duration and share of the piece, and the times of the
landmarks listed in LANDMARKS (climaxes, pivots), so the form table in BLUEPRINT.md is measured.
"""
import json
import os
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools'))
from perform import Plan  # noqa: E402
from lyparse import parse_voice  # noqa: E402
from build_sk import offsets  # noqa: E402
from piece import SECTIONS  # noqa: E402

LANDMARKS = [('Climax I fermata (E dim7 -> A dim7)', '29:1'), ('A-minor cadence', '45:3'),
             ('Climax II peak (C7 complete, fff; C6 at 52:3)', '53:1'), ('V fermata', '53:4'), ('tune in B-flat major', '55:1'),
             ('c-d, the answered question', '63:1'), ('final chord', '66:3')]


def timeline(score, plan_path):
    src = open(score).read()
    plan = Plan(json.load(open(plan_path)))
    voices = [parse_voice(src, v, plan.measure) for v in plan.voices]
    end = max(n[-1].end for n in voices if n)
    step = F(1, 16)
    bpmf = plan.bpm_quarter_fn()
    breaths = {plan.pos(b['at']): b['ms'] / 1000 for b in plan.d.get('breaths', [])}
    ferm = {plan.pos(x['at']): x['extra_beats'] for x in plan.d.get('fermatas', [])}
    grid = {F(0): 0.0}
    t, s = F(0), 0.0
    while t < end + F(1, 2):
        bpm = bpmf(t)
        stretch = 1.0
        if t in ferm:
            stretch += ferm[t] / 0.25
        if t + step in breaths:
            stretch += breaths[t + step] / (60.0 / bpm / 4)
        s += 60.0 / bpm / 4 * stretch
        t += step
        grid[t] = s
    return grid, end, plan


def main():
    score = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'SK_final.ly')
    planp = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'plan.json')
    grid, end, plan = timeline(score, planp)
    total = grid[end]
    off = offsets()
    print(f"{'section':32} {'bars':>7} {'start s':>8} {'dur s':>7} {'share':>6}")
    for s in SECTIONS:
        a = off[s['id']]
        b = a + s['bars'] - 1
        t0, t1 = grid[F(a - 1)], grid[min(F(b), end)]
        print(f"{s['id']:32} {a:>3}-{b:<3} {t0:8.1f} {t1 - t0:7.1f} {100 * (t1 - t0) / total:5.1f}%")
    print(f"{'total':32} {'':7} {'':8} {total:7.1f}")
    for name, p in LANDMARKS:
        x = plan.pos(p)
        if x <= end:
            print(f"  {p:>6} {grid[x]:6.1f} s ({100 * grid[x] / total:4.1f}%)  {name}")


if __name__ == '__main__':
    main()
