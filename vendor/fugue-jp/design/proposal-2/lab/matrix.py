#!/usr/bin/env python3
"""Penalty matrix of 2-voice strettos by distance (beats). Keys named by transposition from the written form."""
from explore import *
from fractions import Fraction as F
import sys
S1, INV, S2 = parse(FORMS['S1']), parse(FORMS['INV']), parse(FORMS['S2'])
def T(form, st, se): return transpose(form, st, se)
# follower placements relative to leader S1 at bes' (70)
cases = {
 'S1 Bb | S1 Bb  8vb':      (S1, T(S1,-7,-12)),
 'S1 Bb | S1 F   4th below': (S1, T(S1,-3,-5)),
 'S1 Bb | S1 F   5th above': (S1, T(S1,4,7)),
 'S1 Bb | S1 Eb  5th below': (S1, T(S1,-4,-7)),
 'S1 Bb | S1 Eb  4th above': (S1, T(S1,3,5)),
 'S1 Bb | INV(F) 5th above':(S1, T(INV,-7,-12+0) if False else T(INV,0,0)),
 'S1 Bb | INV(F) 4th below':(S1, T(INV,-7,-12)),
 'S1 Bb | INV(F) 11th below':(S1, T(INV,-14,-24)),
 'INV F | S1 Bb 4th below': (T(INV,0,0), S1),
 'INV F | S1 Bb 11th below': (T(INV,0,0), T(S1,-7,-12)),
 'S1 Bb | INV(Bb=Eb minor) 8vb': (S1, T(INV,-10,-19)),
 'S1 Bb | INV(Bb) unison-above': (S1, T(INV,-3,-7)),
}
mode = sys.argv[1] if len(sys.argv) > 1 else 'both'
ds = [F(k,2) for k in range(1,17)]
print('distance(beats):        ' + ' '.join(f"{float(d):>5g}" for d in ds))
for nm,(lead,fol) in cases.items():
    for who in ('lead','follow'):
        row=[]
        for d in ds:
            a, b = (lead, shift(fol,d)) if who=='lead' else (shift(lead,d), fol)
            # a is written higher in pitch?  put higher-sounding as 'up'
            hi = a if a[0][2] >= b[0][2] else b
            lo = b if hi is a else a
            p,_ = score(hi, lo, True)
            row.append(p)
        print(f"{nm:28} {'1st' if who=='lead' else '2nd'}: " + ' '.join(f"{p:5.1f}" for p in row))
