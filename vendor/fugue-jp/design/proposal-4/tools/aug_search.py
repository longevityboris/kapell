#!/usr/bin/env python3
"""CF (complete theme, Bb major, soprano) against S1M in 2x augmentation (bass), offsets in half bars."""
import sys
from p4 import *
from mats import *
from fractions import Fraction as F
res = []
for tr_name, st, se in [('bes,', -14, -24), ('f,', -18, -31), ('f', -11, -19), ('ees,', -17,-29), ('d', -15, -26)]:
    bass = real(aug(S1M_CORE + ly("c''1"), 2), st, se)
    for off2 in range(-8, 9):   # offset in half bars; positive = bass starts later
        off = F(off2, 2)
        if off >= 0:
            b = rest(off) + bass; s = THEME_M
        else:
            b = bass; s = rest(-off) + THEME_M
        tot = max(length(b), length(s))
        tot = F(int(tot) + (1 if tot % 1 else 0))
        p = write_lab('_tmp_aug.ly', {'soprano': fill(s, tot), 'bass': fill(b, tot)})
        out = check(p)
        sc = score(out)
        res.append((sc['par'] + sc['beat'] + sc['err'], sc['dis'], sc['d4'], sc['dir'], tr_name, float(off)))
res.sort()
for r in res[:25]:
    print(r)
