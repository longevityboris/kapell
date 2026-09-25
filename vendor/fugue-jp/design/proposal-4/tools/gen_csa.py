#!/usr/bin/env python3
"""CSa (lament bass under S1): bars 1-2 fixed chromatic tetrachord ees'-d'-des'-c'-ces'-bes,
bars 3-4 searched; ends on the dominant (f) at bar 5 beat 1 under the subject's c''."""
import sys, time
from p4 import ly, cat, to_ly
from mats import S1_CORE
from solve import Solver, show
sub = cat(S1_CORE, ly("c''2 r2"))
PAL = "f g aes a bes ces' c' des' d' ees' e' f' ges' g' aes'"
KEYPCS = {10, 0, 1, 3, 5, 6, 8, 9, 7}
v = sys.argv[1] if len(sys.argv) > 1 else '1'
b2 = {'1': ["8 4 4"], '2': ["12 2 2"]}[v]
S = Solver({'alto': sub}, 'tenor', palette=PAL, patterns=["8 8", "8 4 4", "4 4 8", "12 4", "4 4 4 4", "6 2 4 4", "4 4 6 2", "8 6 2", "12 2 2", "t4 4 8", "t4 4 4 4", "t8 8", "t8 4 4"],
           bar_patterns={1: ["8 8"], 2: b2, 5: ["8 r8"]},
           must={0: "ees'", 8: "d'", 16: "des'", 24: "c'", 28: "ces'", 26: "ces'", 32: "bes"},
           start_pitch="ees'", end_pcs={5}, width=800, keep=30, key_pcs=KEYPCS, lo=48, hi=66)
sols = S.solve()
for c, ns in sols:
    print(f'{c:6.1f}  ' + show(ns, S.total))
