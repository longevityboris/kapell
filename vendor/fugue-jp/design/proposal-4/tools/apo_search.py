#!/usr/bin/env python3
"""Which subject forms can a THIRD voice (tenor or alto) sing inside the apotheosis frame
(CF soprano + mirror/answer bass of P06)? whole-bar offsets, real transpositions, checker-judged."""
import sys
from fractions import Fraction as F
from p4 import *
from mats import *
BASS = ly("bes,2. bes,8 c8 | bes,2. bes,8 c8 | bes,4. a,8 a,4. f,8 | f,2. d,4 | f,2. f,8 e,8 | f,2. f,8 e,8 | f,4. g,8 g,4. bes,8 | bes,2. a,8 f,8 | bes,1~ | bes,1")
S1Me = cat(S1M_CORE, ly("c''2"))
forms = {'S1M': S1Me, 'S2M': S2M, 'MIR': S1_MIRROR('bes-major', S1Me)}
IV = [(0,0,'P1'),(-2,-3,'m3'),(-2,-4,'M3'),(-3,-5,'P4'),(-4,-7,'P5'),(-5,-8,'m6'),(-5,-9,'M6'),(-7,-12,'P8'),
      (-1,-2,'M2'),(-6,-10,'m7'),(-8,-14,'M9'),(-9,-15,'m10'),(-9,-16,'M10'),(-10,-17,'P11'),(-11,-19,'P12')]
voice = sys.argv[1] if len(sys.argv) > 1 else 'tenor'
lo, hi = RANGES[voice]
res = []
for fn, f in forms.items():
    for st, se, nm in IV:
        g = real(f, st, se)
        ms = [midi(p) for p, _ in g if p]
        for k in (-2, -1, 0, 1):
            gg = real(g, 7 * k, 12 * k)
            mm = [m + 12 * k for m in ms]
            if min(mm) < lo or max(mm) > hi:
                continue
            for off in range(0, 7):
                v = rest(F(off)) + gg
                if length(v) > 10:
                    continue
                p = write_lab('_tmp_as.ly', {'soprano': CF_APO, voice: fill(v, F(10)), 'bass': BASS})
                sc = score(check(p))
                bad = sc['par'] + sc['beat'] + sc['err'] + sc['cros'] + sc['dis'] + sc['d4']
                res.append((bad, sc['dir'], fn, nm, k, off, ' '.join(to_ly(gg))[:40]))
res.sort()
for r in res[:30]:
    print(r)
