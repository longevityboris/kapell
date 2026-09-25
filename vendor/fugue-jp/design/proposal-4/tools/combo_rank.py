#!/usr/bin/env python3
"""Rank two-voice combinations with substantial overlap (strict evaluator), minor and major."""
import sys
from search_combo import *
from strict2 import evaluate, notes_of


def overlap(a, b):
    na, nb = notes_of(a), notes_of(b)
    if not na or not nb:
        return 0
    return max(0, min(na[-1][1], nb[-1][1]) - max(na[0][0], nb[0][0])) * 4


def rank(label, A, B, key, steps, offsets, min_ov=10, show=10, key_to=None):
    res = []
    for s in steps:
        for o in offsets:
            lo = shift(inkey(B, s, key, key_to), o)
            if not any(p for p, _ in lo):
                continue
            ov = overlap(A, lo)
            if ov < min_ov:
                continue
            h, sf = evaluate(A, lo)
            res.append((h, sf, -ov, s, o))
    res.sort()
    print('==', label)
    for r in res[:show]:
        print(f'  hard {r[0]} soft {r[1]} overlap {-r[2]:g} beats  steps {r[3]:+d} offset {r[4]:+d}')
    return res


if __name__ == '__main__':
    rank('S1 over S2 (minor)', S1, S2, 'bes-harm', range(-14, 0), range(-14, 15))
    rank('S2 over S1 (minor)', S2, S1, 'bes-harm', range(-14, 0), range(-14, 15))
    rank('S1 over S2 (major)', S1M, S2M, 'bes-major', range(-14, 0), range(-14, 15))
    rank('S2 over S1 (major)', S2M, S1M, 'bes-major', range(-14, 0), range(-14, 15))
