#!/usr/bin/env python3
"""Two-voice stretto / mirror search judged by the PROJECT CHECKER (check.py) plus strict2 as a
second opinion. leader L in the upper or lower voice, follower F = form(S1) transposed (real) and
delayed by k quarter beats. Only whole-beat delays; ranks by (hard, DIS!, D4?, DIR, strict-hard)."""
import sys, itertools
from fractions import Fraction as F
from p4 import *
from mats import *
from strict2 import evaluate

IVS = [(0, 0, 'P1'), (-2, -3, 'm3'), (-2, -4, 'M3'), (-3, -5, 'P4'), (-4, -7, 'P5'), (-5, -8, 'm6'),
       (-5, -9, 'M6'), (-7, -12, 'P8'), (-9, -15, 'm10'), (-9, -16, 'M10'), (-10, -17, 'P11'),
       (-11, -19, 'P12'), (-14, -24, 'P15'), (-1, -2, 'M2'), (-1, -1, 'm2'), (-6, -10, 'm7'), (-8, -14, 'M9')]


def ck2(up, lo, vu='soprano', vl='tenor'):
    tot = max(length(up), length(lo)); tot = F(int(tot) + (1 if tot % 1 else 0))
    p = write_lab('_tmp_st.ly', {vu: fill(up, tot), vl: fill(lo, tot)})
    return score(check(p))


def search(label, L, Fo, delays, show=12, above=False):
    res = []
    for st, se, nm in IVS:
        f = real(Fo, -st, -se) if above else real(Fo, st, se)
        for k in delays:
            fs = rest(F(k, 4)) + f
            up, lo = (fs, L) if above else (L, fs)
            if any(p is None for p, _ in up[-1:]):
                pass
            sc = ck2(up, lo)
            h, s = evaluate(up, lo)
            res.append((sc['par'] + sc['beat'] + sc['err'] + sc['cros'], sc['dis'], sc['d4'], sc['dir'], h, s, nm, k))
    res.sort()
    print('==', label)
    for r in res[:show]:
        print(f'  hard {r[0]} dis! {r[1]} d4? {r[2]} dir {r[3]} | strict {r[4]}/{r[5]} | follower {"above" if above else "below"} {r[6]} +{r[7]} beats')
    return res


if __name__ == '__main__':
    what = sys.argv[1]
    S1x = cat(S1_CORE, ly("c''2"))
    if what == 's1':
        search('S1 leader, S1 follower below', S1x, S1x, range(2, 13, 2))
        search('S1 leader, S1 follower above', S1x, S1x, range(2, 13, 2), above=True)
    if what == 'inv':
        ax = ly("bes'4")[0][0]
        INV = mirror(S1x, ax, mode='key', key='bes-harm')
        print('INV (diatonic mirror around bes\'):', ' '.join(to_ly(INV)))
        search('S1 leader, INV follower below', S1x, INV, range(0, 13, 2))
        search('S1 leader, INV follower above', S1x, INV, range(0, 13, 2), above=True)
        search('INV leader, S1 follower below', INV, S1x, range(0, 13, 2))
        search('INV leader, S1 follower above', INV, S1x, range(0, 13, 2), above=True)
    if what == 'm':
        S1Mx = cat(S1M_CORE, ly("c''2"))
        search('S1M leader, S1M follower below', S1Mx, S1Mx, range(2, 13, 2))
        search('S1M leader, S1M follower above', S1Mx, S1Mx, range(2, 13, 2), above=True)
