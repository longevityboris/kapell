from fractions import Fraction as F
from search import *
from mats import *
import sys
cands = {'S1Maug': S1Maug, 'I1Maug': I1Maug, 'S2Maug': S2Maug}
res = []
for nm, base in cands.items():
    for tr in [(0,0),(4,7),(-3,-5),(3,5),(-4,-7)] + [('d',k) for k in range(-6,7) if k]:
        for oc in (-3, -2, -1):
            if tr[0] == 'd':
                b = dtrans(base, tr[1], scale=HMAJ)
            else:
                b = transpose(base, *tr)
            b = octave(b, oc)
            for off in [F(k, 4) for k in range(-8, 13)]:
                bb = shift(b, off)
                # keep only overlapping part within theme span
                pen, notes = evaluate(THEMEM, bb)
                res.append((pen, nm, tr, oc, off, notes[:5]))
res.sort(key=lambda r: r[0])
for r in res[:40]:
    print(f"{r[0]:5.1f} {r[1]:7} tr={r[2]} oct={r[3]} off={str(r[4]):5} {r[5]}")
