#!/usr/bin/env python3
"""S1/S2 combination search judged by check.py (+strict2 second opinion). B transposed (real) below A."""
import sys
from fractions import Fraction as F
from p4 import *
from mats import *
from strict2 import evaluate
from stretto_ck import IVS

def ck2(up, lo):
    tot = max(length(up), length(lo)); tot = F(int(tot) + (1 if tot % 1 else 0))
    p = write_lab('_tmp_cb.ly', {'soprano': fill(up, tot), 'tenor': fill(lo, tot)})
    return score(check(p))

def run(label, A, B, offs, show=14, below=True):
    res = []
    for st, se, nm in IVS + [(-12, -20, 'm13'), (-12, -21, 'M13'), (-16, -27, 'M17?')]:
        Bt = real(B, st, se)
        for o in offs:
            if o >= 0:
                a, b = A, rest(F(o, 4)) + Bt
            else:
                a, b = rest(F(-o, 4)) + A, Bt
            sc = ck2(a, b)
            h, s = evaluate(a, b)
            res.append((sc['par'] + sc['beat'] + sc['err'] + sc['cros'], sc['dis'], sc['d4'], sc['dir'], h, s, nm, o))
    res.sort()
    print('==', label)
    for r in res[:show]:
        print(f'  hard {r[0]} dis! {r[1]} d4? {r[2]} dir {r[3]} | strict {r[4]}/{r[5]} | lower {r[6]} offset {r[7]:+d} beats')

S1x = cat(S1_CORE, ly("c''2"))
S2x = S2
if sys.argv[1] == 'minor':
    run('S2 above, S1 below', S2x, S1x, [-8, -4, 0, 4, 8])
    run('S1 above, S2 below', S1x, S2x, [-8, -4, 0, 4, 8])
if sys.argv[1] == 'major':
    S1Mx = cat(S1M_CORE, ly("c''2"))
    run('S2M above, S1M below', S2M, S1Mx, [-8, -4, 0, 4, 8])
    run('S1M above, S2M below', S1Mx, S2M, [-8, -4, 0, 4, 8])
