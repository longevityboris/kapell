#!/usr/bin/env python3
"""Stretto / mirror / augmentation search for Subject I (two voices, strict evaluator).
Leader L = S1 (or a variant); follower F = transformed S1 entering `o` quarter-beats later,
transposed by a real interval (above or below). Ranked by (hard, soft)."""
import sys
from search_combo import S1, S1M, S2, S2M, shift
from p4 import *
from strict2 import evaluate
from combo_rank import overlap

IV = [(0, 0, 'P1'), (-2, -3, 'm3'), (-2, -4, 'M3'), (-3, -5, 'P4'), (-4, -7, 'P5'), (-5, -8, 'm6'), (-5, -9, 'M6'),
      (-7, -12, 'P8'), (-9, -15, 'm10'), (-9, -16, 'M10'), (-10, -17, 'P11'), (-11, -19, 'P12'), (-1, -2, 'M2'),
      (-6, -10, 'm7'), (-8, -14, 'M9'), (-12, -20, 'm13'), (-12, -21, 'M13'), (-14, -24, 'P15')]


def run(label, lead, fol, offsets, below=True, key=None, show=10, min_ov=6, diat=False):
    res = []
    for st, se, nm in IV:
        if diat:
            if se != IV[[x[0] for x in IV].index(st)][1]:
                continue
            f = inkey(fol, st if below else -st, key)
            nm = f'{"-" if below else "+"}{abs(st)} steps (diatonic)'
        else:
            f = real(fol, st, se) if below else real(fol, -st, -se)
        for o in offsets:
            fs = shift(f, o)
            ov = overlap(lead, fs)
            if ov < min_ov:
                continue
            up, lo = (lead, fs) if below else (fs, lead)
            h, s = evaluate(up, lo)
            res.append((h, s, -ov, nm, o))
    res.sort()
    print('==', label)
    for r in res[:show]:
        print(f'  hard {r[0]} soft {r[1]} overlap {-r[2]:g}  follower {"below" if below else "above"} {r[3]}, +{r[4]} beats')
    return res


if __name__ == '__main__':
    what = sys.argv[1]
    offs = range(1, 13)
    if what == 'minor':
        run('S1 minor: follower below (real)', S1, S1, offs, True)
        run('S1 minor: follower above (real)', S1, S1, offs, False)
        run('S1 minor: follower below (diatonic, harm.)', S1, S1, offs, True, 'bes-harm', diat=True)
        run('S1 minor: follower above (diatonic, harm.)', S1, S1, offs, False, 'bes-harm', diat=True)
    if what == 'major':
        run('S1 major: follower below (real)', S1M, S1M, offs, True)
        run('S1 major: follower above (real)', S1M, S1M, offs, False)
        run('S1 major: follower below (diatonic)', S1M, S1M, offs, True, 'bes-major', diat=True)
        run('S1 major: follower above (diatonic)', S1M, S1M, offs, False, 'bes-major', diat=True)


def mirror_search():
    from p4 import mirror
    ax = ly("bes'4")[0][0]
    INV = mirror(S1, ax)                       # real inversion around bes': bes' ces'' bes' ...
    print('S1 inversion (real, axis bes\'):', ' '.join(to_ly(INV)))
    run('S1 lead, INV follower below', S1, INV, range(0, 13), True, show=8)
    run('S1 lead, INV follower above', S1, INV, range(0, 13), False, show=8)
    run('INV lead, S1 follower below', INV, S1, range(0, 13), True, show=8)
    run('INV lead, S1 follower above', INV, S1, range(0, 13), False, show=8)
    run('INV lead, INV follower below', INV, INV, range(1, 13), True, show=8)
    run('INV lead, INV follower above', INV, INV, range(1, 13), False, show=8)


def dim_search():
    D = aug(S1, F(1, 2))
    run('S1 lead (normal), diminution follower below', S1, D, range(0, 15), True, show=8, min_ov=4)
    run('S1 lead (normal), diminution follower above', S1, D, range(0, 15), False, show=8, min_ov=4)
    run('diminution lead, S1 normal follower below', D, S1, range(0, 8), True, show=8, min_ov=4)
    run('diminution lead, S1 normal follower above', D, S1, range(0, 8), False, show=8, min_ov=4)


if __name__ == '__main__' and sys.argv[1] == 'mirror':
    mirror_search()
if __name__ == '__main__' and sys.argv[1] == 'dim':
    dim_search()
