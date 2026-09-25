#!/usr/bin/env python3
"""CSb (descant) over answer (alto, f') + CSa lament (tenor): must also be clean as a 2-voice duet
with the answer (answer = bass in the exposition bars 5-8)."""
import sys, time
from p4 import ly, cat, to_ly
from mats import A1_CORE, CSA_ANS
from solve import Solver, show
ans = cat(A1_CORE, ly("g'2 r2"))
csa = cat(CSA_ANS, ly("r2"))
PAL = "bes' c'' des'' d'' ees'' e'' f'' ges'' g'' aes'' a'' bes''"
KEYPCS = {5, 7, 8, 10, 0, 1, 2, 3, 4}
W = int(sys.argv[1]) if len(sys.argv) > 1 else 600
P = ["4 4 4 4", "4 2 2 4 4", "4 4 2 2 4", "4 4 4 2 2", "2 2 4 4 4", "6 2 4 4", "4 4 6 2", "4 6 2 4",
     "8 4 4", "4 4 8", "t4 4 4 4", "t4 2 2 4 4", "t4 4 2 2 4", "t4 4 4 2 2", "t8 4 4", "t4 4 8", "4 2 2 2 2 4", "2 2 2 2 4 4"]
t0 = time.time()
S = Solver({'alto': ans, 'tenor': csa}, 'soprano', palette=PAL, patterns=P, bass_like=['alto'],
           start_pitch="c''", end_pcs={4, 7, 10}, width=W, keep=40, key_pcs=KEYPCS, lo=70, hi=82,
           bar_patterns={5: ["8 r8"]}, sigh_bonus=1.5, min_span=8, inner=30)
sols = S.solve()
print(f'{len(sols)} in {time.time()-t0:.0f}s', file=sys.stderr)
for c, ns in sols:
    print(f'{c:6.1f}  ' + show(ns, S.total))
