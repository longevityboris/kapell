#!/usr/bin/env python3
"""CS2 'motor' (running eighths) below S2, octave-invertible (so it can also go above)."""
import sys, time
from p4 import *
from mats import *
from solve import Solver, show
sop = cat(S2, ly("r1"))
PAL = "c' des' d' ees' e' f' ges' g' aes' a' bes' b' c'' des'' d'' ees''"
KEY = {10, 0, 1, 3, 5, 6, 8, 9, 7}
E = "2 2 2 2 2 2 2 2"
P = [E, "4 2 2 2 2 2 2", "2 2 2 2 4 2 2", "2 2 4 2 2 2 2", "t2 2 2 2 2 2 2 2", "t4 2 2 2 2 2 2", "4 2 2 4 2 2"]
inv = sys.argv[1] == 'inv' if len(sys.argv) > 1 else False
S = Solver({'soprano': sop}, 'alto', palette=PAL, patterns=P, bass_like=['soprano'] if False else [],
           invert=['soprano'] if inv else [], bar_patterns={5: ["16"]} if False else {5: ["r16"]},
           width=500, keep=20, key_pcs=KEY, lo=58, hi=74, still_pen=(4, 0.6, 8, 2.0), min_span=9, inner=30,
           weights=dict(rep=3.0, leap3=0.3, leap4=0.8))
t0 = time.time()
sols = S.solve()
print(len(sols), round(time.time() - t0))
for c, ns in sols:
    print(f'{c:6.1f} ' + show(ns, S.total))
