#!/usr/bin/env python3
"""Upper subject entries (1x) against the ANSWER IN AUGMENTATION in the bass (dominant pedal on F).
Whole-bar offsets only (the tune keeps its metre)."""
import sys
from fractions import Fraction as F
from p4 import *
from mats import *
bass = real(aug(cat(A1_CORE, ly("g'1")), 2), -14, -24)   # f, pedal ... ends g,
S1e = cat(S1_CORE, ly("c''2"))
forms = {'S1': S1e, 'ANS': cat(A1_CORE, ly("g'2")), 'S2': S2, 'INV': mirror(S1e, ly("bes'4")[0][0], mode='key', key='bes-harm')}
IV = [(0,0,'P1'),(-2,-3,'m3'),(-2,-4,'M3'),(-3,-5,'P4'),(-4,-7,'P5'),(-5,-8,'m6'),(-5,-9,'M6'),(-7,-12,'P8'),
      (2,3,'+m3'),(2,4,'+M3'),(3,5,'+P4'),(4,7,'+P5'),(-1,-2,'M2'),(1,2,'+M2'),(-1,-1,'m2'),(1,1,'+m2'),(-6,-10,'m7'),(-6,-11,'M7')]
res = []
for fn, f in forms.items():
    for st, se, nm in IV:
        up = real(f, st, se)
        ms = [midi(p) for p, _ in up if p]
        for voice in ['soprano', 'alto', 'tenor']:
            lo, hi = RANGES[voice]
            k = 0
            while max(ms) + 12 * k > hi: k -= 1
            while min(ms) + 12 * k < lo: k += 1
            if max(ms) + 12 * k > hi: continue
            upv = real(up, 7 * k, 12 * k)
            for off in range(0, 6):
                u = rest(F(off)) + upv
                tot = F(int(max(length(u), length(bass))) + 1)
                p = write_lab('_tmp_ap.ly', {voice: fill(u, tot), 'bass': fill(bass, tot)})
                sc = score(check(p))
                res.append((sc['par'] + sc['beat'] + sc['err'] + sc['cros'], sc['dis'], sc['d4'], sc['dir'], fn, nm, voice, off, ' '.join(to_ly(upv)[:1])))
            break
res.sort()
for r in res:
    print(r)
