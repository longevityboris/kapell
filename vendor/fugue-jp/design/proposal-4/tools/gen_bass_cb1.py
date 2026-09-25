#!/usr/bin/env python3
"""Bass under CB1 (S2 in soprano over the answer in alto)."""
import sys, time
from p4 import *
from mats import *
from solve import Solver, show
S1e = cat(S1_CORE, ly("c''2"))
sop = cat(S2, ly("r1"))
alt = cat(A1_CORE, ly("g'2 r2"))
PAL = "c d des ees e f ges g aes a bes b c' des' d' ees' e' f,, g, aes, a, bes, c, des, d, ees, e, f, ges, g, a, b, e,"
PAL = ' '.join(sorted(set(PAL.split())))
KEY = {5, 7, 8, 10, 0, 1, 2, 3, 4}
S = Solver({'soprano': sop, 'alto': alt}, 'bass', palette=PAL, patterns=["8 8", "4 4 8", "8 4 4", "4 4 4 4", "12 4", "t4 4 8", "t8 8", "6 2 4 4", "4 4 6 2", "t4 4 4 4"],
           bar_patterns={5: ["8 r8"]}, end_pcs={0}, width=600, keep=15, key_pcs=KEY, lo=36, hi=57, sigh_bonus=0,
           still_pen=(12, 0.5, 16, 1.0), inner=40)
t0 = time.time()
sols = S.solve()
print(len(sols), time.time() - t0)
for c, ns in sols:
    print(f'{c:6.1f} ' + show(ns, S.total))
