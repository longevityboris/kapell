import sys
from p4 import *
from mats import *
from fractions import Fraction as F
tr = {'bes,': (-14, -24), 'f,': (-18, -31), 'f': (-11, -19), 'ees,': (-17, -29), 'd': (-15, -26)}
name_, off = sys.argv[1], F(sys.argv[2])
st, se = tr[name_]
bass = real(aug(S1M_CORE + ly("c''1"), 2), st, se)
if off >= 0:
    b = rest(off) + bass; s = THEME_M
else:
    b = bass; s = rest(-off) + THEME_M
tot = max(length(b), length(s)); tot = F(int(tot) + (1 if tot % 1 else 0))
p = write_lab('_tmp_aug.ly', {'soprano': fill(s, tot), 'bass': fill(b, tot)})
print(check(p))
print('\n'.join(to_ly(fill(b, tot))))
