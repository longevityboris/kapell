"""Write one lab file per vertical order for a set of lines and check each with check.py + strict.py.
usage: python3 lab_perm.py PREFIX NAME1,NAME2,NAME3 (names from mats.py) [bars]"""
import sys, itertools
from p3 import *
import mats

prefix, names = sys.argv[1], sys.argv[2].split(',')
bars = int(sys.argv[3]) if len(sys.argv) > 3 else 5
lines = {n: getattr(mats, n) for n in names}
for order in itertools.permutations(names):
    b = place([lines[n] for n in order])
    if b is None:
        print(' > '.join(order), 'no placement'); continue
    spread, ks, ms = b
    best = None
    for i in range(0, 4 - len(order) + 1):
        vs = VOICES[i:i + len(order)]
        for sh in range(-3, 3):
            parts = {v: [octs(m, sh)] for v, m in zip(vs, ms)}
            s, _ = quick(parts, bars)
            if s['err'] == 0:
                k = (bad(s), s['d4'], s['dir'])
                if best is None or k < best[0]:
                    best = (k, vs, sh, parts)
    if best is None:
        print(' > '.join(order), 'no range fit'); continue
    k, vs, sh, parts = best
    fn = f"{prefix}_{'-'.join(order)}.ly"
    write_lab(fn, f"Proposal 3, {prefix}: vertical order (top->bottom) {' > '.join(order)}; voices {', '.join(vs)}", parts, bars)
    s, l1 = check(fn)
    d, l2 = strict(fn)
    print(f"{fn:40s} {l1[-1].split(';')[1].strip()} | {l2[-1]}")
