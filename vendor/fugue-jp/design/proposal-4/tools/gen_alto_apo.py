import sys, time
sys.path.insert(0, '.')
from p4 import *; from mats import *
from solve import Solver, show
from fractions import Fraction as F
bass = ly("bes,2. bes,8 c8 | bes,2. bes,8 c8 | bes,4. a,8 a,4. f,8 | f,2. d,4 | f,2. f,8 e,8 | f,2. f,8 e,8 | f,4. g,8 g,4. bes,8 | bes,2. a,8 f,8 | bes,1~ | bes,1")
ten = ly("f2 g4 f4 | bes4 aes4 g4 f4 | f4 d'4 c'4. c'8 | c'2. f4 | f2. f8 g8 | f2. f8 g8 | f4. e8 e4. c8 | c2. d8 f8 | d'1 | ees'2 d'2")
A14 = ly("d'4. ees'8 f'4 ees'4 | d'4 f'4 ees'4 f'8 ees'8 | f'4. ees'8 ees'4. f'8 | a'2 g'4 f'4")
PAL = "a bes c' d' ees' e' f' g' a' bes' c''"
KEY = {10, 0, 2, 3, 5, 7, 9}
must = {}
# keep bars 1-4 of the P06 alto fixed via 'must' on its onsets
t = 0
for p, d in A14:
    must[t] = name(p)
    t += int(d * 16)
pats1 = {1: ["6 2 4 4"], 2: ["4 4 4 2 2"], 3: ["6 2 6 2"], 4: ["8 4 4"]}
S = Solver({'soprano': CF_APO, 'tenor': ten, 'bass': bass}, 'alto', palette=PAL,
           patterns=["4 4 4 4", "8 4 4", "4 4 8", "8 8", "6 2 4 4", "4 4 6 2", "4 2 2 4 4", "t4 4 4 4", "t4 4 8", "12 4", "4 4 4 2 2", "16", "t8 8"],
           bar_patterns={**pats1, 9: ["16"], 10: ["8 8"]}, must=must, width=600, keep=12, key_pcs=KEY, lo=55, hi=74,
           inner=40, still_pen=(8, 0.2, 12, 0.5), end_pitch="f'")
t0 = time.time()
sols = S.solve()
print(len(sols), round(time.time() - t0))
for c, ns in sols[:12]:
    print(f'{c:6.1f} ' + show(ns, S.total))
