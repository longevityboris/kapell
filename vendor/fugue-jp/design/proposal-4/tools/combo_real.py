#!/usr/bin/env python3
"""S1/S2 combinations under exact (real) transposition; B below A. Ranks by strict evaluator."""
from search_combo import *
from strict2 import evaluate, notes_of
from combo_rank import overlap

IVS = [(0, 0, 'P1'), (-1, -1, 'm2'), (-1, -2, 'M2'), (-2, -3, 'm3'), (-2, -4, 'M3'), (-3, -5, 'P4'), (-4, -7, 'P5'),
       (-5, -8, 'm6'), (-5, -9, 'M6'), (-6, -10, 'm7'), (-7, -12, 'P8'), (-8, -14, 'M9'), (-9, -15, 'm10'),
       (-9, -16, 'M10'), (-10, -17, 'P11'), (-11, -19, 'P12'), (-12, -20, 'm13'), (-12, -21, 'M13'),
       (-14, -24, 'P15'), (-8, -13, 'm9'), (-3, -6, 'A4'), (-4, -6, 'd5')]


def rank(label, A, B, offsets, min_ov=12, show=12):
    res = []
    for st, se, nm in IVS:
        Bt = real(B, st, se)
        for o in offsets:
            lo = shift(Bt, o)
            if not any(p for p, _ in lo):
                continue
            ov = overlap(A, lo)
            if ov < min_ov:
                continue
            h, sf = evaluate(A, lo)
            res.append((h, sf, -ov, nm, o))
    res.sort()
    print('==', label)
    for r in res[:show]:
        print(f'  hard {r[0]} soft {r[1]} overlap {-r[2]:g}  B {r[3]} below, offset {r[4]:+d} beats')
    return res


if __name__ == '__main__':
    import sys
    rank('S1 over S2 (minor)', S1, S2, range(-14, 15))
    rank('S2 over S1 (minor)', S2, S1, range(-14, 15))
    rank('S1 over S2 (major)', S1M, S2M, range(-14, 15))
    rank('S2 over S1 (major)', S2M, S1M, range(-14, 15))
