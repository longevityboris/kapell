#!/usr/bin/env python3
"""show.py UPPER LOWER IVNAME OFFSET [--first lower] [--aug] : print the interval timeline."""
import sys
from fractions import Fraction as F
from explore import *
upn, lon, ivn, off = sys.argv[1], sys.argv[2], sys.argv[3], F(sys.argv[4])
up, lo = parse(FORMS[upn]), parse(FORMS[lon])
if '--aug' in sys.argv: lo = scale(lo, 2)
if '--augup' in sys.argv: up = scale(up, 2)
st, se = IVS[ivn]
lo = transpose(lo, st, se)
if '--first' in sys.argv and sys.argv[sys.argv.index('--first')+1] == 'lower':
    up = shift(up, off)
else:
    lo = shift(lo, off)
times = sorted({n[0] for n in up} | {n[0] for n in lo})
for t in times:
    a, b = at(up, t), at(lo, t)
    if a and b:
        ic = (a[2]-b[2]) % 12
        lab = {0:'8',1:'m2!',2:'M2!',3:'m3',4:'M3',5:'P4',6:'TT!',7:'P5',8:'m6',9:'M6',10:'m7!',11:'M7!'}[ic]
        print(f"{float(t):6.2f} bar{int(t//4)+1}:{float(t%4)+1:<5g} {name(a):5} {name(b):5} {lab}")
    else:
        print(f"{float(t):6.2f} {name(a) if a else '-':5} {name(b) if b else '-':5}")
p, log = score(up, lo, '--4ok' in sys.argv)
print('penalty', p); print('\n'.join(log))
