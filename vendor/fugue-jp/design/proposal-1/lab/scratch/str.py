import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
from fractions import Fraction as F
def test(name, voices, total=None):
    p = lab(name, voices, name, total)
    out = check(p)
    cnt, s, tot = summary(out)
    st = strict(out)
    print(f"{name:30s} PAR={cnt['PAR!']} BEAT={cnt['BEAT']} DIS!={cnt['DIS!']} D4?={cnt['D4?']} DIR={cnt['DIR']} CROS={cnt['CROS']} ERR={cnt['ERR']} strict={len(st)}")
    for l in out.splitlines():
        if l[:4] in ('PAR!','BEAT','DIS!','D4? ','DIR ','CROS','ERR '): print('   ', l)
    for l in st: print('    strict:', l)
# leader S1 at bes' (alto), follower S1 a 5th below (ees') at various offsets
for q in (3, 7, 8, 9, 10, 12):
    test(f"st5_{q}.ly", dict(alto=S1, tenor=shift(transpose(S1, -4, -7), F(q, 4))))
print('--- chains of four entries descending by fifths')
for q in (3, 7, 8, 9, 10):
    d = F(q, 4)
    test(f"chain5_{q}.ly", dict(soprano=S1, alto=shift(transpose(S1, -4, -7), d),
                                 tenor=shift(transpose(S1, -8, -14), 2 * d), bass=shift(transpose(S1, -12, -21), 3 * d)))
print('--- chains of three (S, A, T)')
for q in (3, 7, 8, 9, 10):
    d = F(q, 4)
    test(f"chain3_{q}.ly", dict(soprano=S1, alto=shift(transpose(S1, -4, -7), d),
                                 tenor=shift(transpose(S1, -8, -14), 2 * d)))
