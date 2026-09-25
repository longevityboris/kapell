"""Alto for P09 bars 47-54 (lab bars 1-8) against the ACTUAL P09 voices (S2 then the answer on f'')."""
import sys, time
sys.path.insert(0, '.')
from p4 import *; from mats import *
from solve import Solver, show
from fractions import Fraction as F
bass = real(aug(A1_CORE, 2), -14, -24)
sop = cat(S2[:-1], ly("c''2. r4"), real(A1_CORE, 7, 12))
ten = cat(CSA_ANS[:-1], ly("c2 c'2 | bes2. des'4 | des'2 ees'2 | des'2 c'2"))
tot = F(8)
fixed = {'soprano': fill(sop, tot), 'tenor': fill(ten, tot), 'bass': fill(bass, tot)}
PAL = "f g aes a bes c' des' d' ees' e' f' g' aes' a' bes' c'' des''"
KEY = {10, 0, 1, 3, 5, 7, 8, 9, 4}
S = Solver(fixed, 'alto', palette=PAL, patterns=["4 4 4 4", "8 4 4", "4 4 8", "8 8", "t4 4 4 4", "t4 4 8", "t8 4 4", "6 2 4 4", "4 4 6 2", "t8 8", "12 4", "4 2 2 4 4"],
           width=int(sys.argv[1]) if len(sys.argv) > 1 else 500, keep=10, key_pcs=KEY, lo=57, hi=76, inner=30,
           still_pen=(8, 0.3, 12, 0.8), weights=dict(chrom=2.5))
t0 = time.time()
sols = S.solve()
print(len(sols), round(time.time() - t0))
for c, ns in sols[:10]:
    print(f'{c:6.1f} ' + show(ns, S.total))
