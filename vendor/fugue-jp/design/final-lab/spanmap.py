#!/usr/bin/env python3
"""Per section and voice: which spans are LOCKED (subject/answer/cf), CS (countersubject, with its landing
window), KEEP (plan.json "keep") and FREE, derived from plan.json so the blueprint's FREE claims can never
contradict a lock that splice_check enforces.

usage: python3 spanmap.py            prints a markdown block per section
"""
import json
import os
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_sk import offsets  # noqa: E402
from piece import SECTIONS  # noqa: E402

V = ['soprano', 'alto', 'tenor', 'bass']
Q = F(1, 8)


def pp(x):
    b, beat = x.split(':')
    return F(int(b) - 1) + (F(beat) - 1) / 4


def pos(t):
    b = int(t) + 1
    return f"{b}:{float((t - (b - 1)) * 4 + 1):g}"


def main():
    plan = json.load(open(os.path.join(HERE, 'plan.json')))
    off = offsets()
    for s in SECTIONS:
        a = off[s['id']]
        b = a + s['bars'] - 1
        print(f"\n{s['id']} (bars {a}-{b})")
        for v in V:
            t, t1 = F(a - 1), F(b)
            labels = []
            while t < t1:
                lab = 'FREE'
                for r in plan['roles']:
                    if r['voice'] != v:
                        continue
                    r0, r1 = pp(r['at']), pp(r['until'])
                    if r0 <= t < r1:
                        if r['role'] in ('subject', 'answer', 'cf'):
                            lab = f"LOCKED {r['role']}"
                        elif r['role'] == 'cs':
                            lab = 'CS landing (free)' if r.get('landing_from') and t >= pp(r['landing_from']) else 'CS'
                        break
                if lab == 'FREE':
                    for k in plan.get('keep', []):
                        if k['voice'] == v and pp(k['at']) <= t < pp(k['until']):
                            lab = 'KEEP'
                            break
                labels.append((t, lab))
                t += Q
            runs, cur = [], None
            for t, lab in labels:
                if cur is None or cur[1] != lab:
                    cur = [t, lab, t + Q]
                    runs.append(cur)
                else:
                    cur[2] = t + Q
            txt = '; '.join(f"{pos(r[0])}-{pos(r[2])} {r[1]}" for r in runs)
            print(f"  {v[0].upper()}: {txt}")


if __name__ == '__main__':
    main()
