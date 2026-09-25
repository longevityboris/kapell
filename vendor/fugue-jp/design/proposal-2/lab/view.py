#!/usr/bin/env python3
"""view.py LEADER FOLLOWER IV D [--aug-f 2] : print interval timeline at every attack + quality stats."""
import sys, os
from fractions import Fraction as F
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan import form, IVS
from p2 import real, shift, aug, pname
a = sys.argv[1:]
L, Fo, iv, d = a[0], a[1], a[2], F(a[3])
lead = form(L); fol = form(Fo)
if '--aug-f' in a: fol = aug(fol, int(a[a.index('--aug-f') + 1]))
if '--aug-l' in a: lead = aug(lead, int(a[a.index('--aug-l') + 1]))
st, se = IVS[iv]; fol = real(fol, st, se)
if d >= 0: fol = shift(fol, d)
else: lead = shift(lead, -d)
def at(ns, t):
    for n in ns:
        if n[2] is not None and n[0] <= t < n[0] + n[1]: return n
times = sorted({n[0] for n in lead + fol if n[2] is not None})
LAB = {0:'8',1:'m2!',2:'M2!',3:'m3',4:'M3',5:'P4',6:'TT!',7:'P5',8:'m6',9:'M6',10:'m7!',11:'M7!'}
q = dict(imp=0, perf=0, diss=0, fourth=0)
for t in times:
    x, y = at(lead, t), at(fol, t)
    if not (x and y):
        continue
    hi, lo = (x, y) if x[2] >= y[2] else (y, x)
    ic = (hi[2] - lo[2]) % 12
    strong = t % 1 == 0
    tag = LAB[ic]
    if strong:
        if ic in (3, 4, 8, 9): q['imp'] += 1
        elif ic in (0, 7): q['perf'] += 1
        elif ic == 5: q['fourth'] += 1
        else: q['diss'] += 1
    bar = int(t // 4) + 1; beat = float(t % 4) + 1
    print(f"{bar:3d}:{beat:<4g} L {pname(x[2], x[3]):7} F {pname(y[2], y[3]):7} {tag:4} {'*' if (x[0]==t and y[0]==t) else ''}")
print(q)
