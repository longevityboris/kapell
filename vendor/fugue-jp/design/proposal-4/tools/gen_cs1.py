#!/usr/bin/env python3
"""Search CS1 over the real answer (F minor), invertible at the octave (from beat 2 on)."""
import sys, time
from fractions import Fraction as F
from p4 import ly, cat, rest, to_ly
from mats import A1_CORE
from solve import Solver, show

ans = cat(A1_CORE, ly("g'2 r2"))
PAL = "bes' b' c'' des'' d'' ees'' e'' f'' ges'' g'' aes'' a'' bes''"
KEYPCS = {5, 7, 8, 10, 0, 1, 2, 3, 4}  # F minor (harm+mel)
pats = sys.argv[1] if len(sys.argv) > 1 else 'A'
P = {
 'A': ["4 4 4 4", "8 4 4", "4 4 8", "t4 4 4 4", "t8 4 4", "t4 4 8", "6 2 4 4", "4 4 6 2",
       "t4 2 2 4 4", "4 2 2 4 4", "t4 4 2 2 4", "4 4 4 2 2", "t4 4 4 2 2", "8 8", "t8 8", "t4 12"],
}[pats]
t0 = time.time()
S = Solver({'alto': ans}, 'soprano', palette=PAL, patterns=P, invert=['alto'], invert_from=4,
           start_pitch="c''", end_pcs={0, 4, 7, 10}, width=int(sys.argv[2]) if len(sys.argv) > 2 else 1500,
           keep=25, key_pcs=KEYPCS, lo=69, hi=81,
           bar_patterns={5: ["8 r8"]})
sols = S.solve()
print(f'{len(sols)} solutions in {time.time()-t0:.1f}s')
for c, ns in sols:
    print(f'{c:6.1f}  ' + show(ns, S.total))
