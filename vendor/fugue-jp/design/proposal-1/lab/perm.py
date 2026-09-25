"""Test invertible (double/triple) counterpoint: place given lines in every
permutation of top/middle/bottom (octave shifts chosen automatically), write a
lab file per permutation and run tools/check.py on it.

usage (python):  perms({'S1': S1, 'CS1': CS1, 'CS2': CS2}, 'tag')
"""
import itertools, sys
from fractions import Fraction as F
from ricer import *

VOX = ['soprano', 'alto', 'tenor', 'bass']


def avg(line):
    ps = [p[1] for s, d, p in line if p]
    return sum(ps) / len(ps)


def lo_hi(line):
    ps = [p[1] for s, d, p in line if p]
    return min(ps), max(ps)


def crossings(ls):
    """count time points where an upper line is below a lower one"""
    from search import at
    times = sorted({s for l in ls for s, d, p in l})
    c = 0
    for t in times:
        ps = []
        for l in ls:
            e = at(l, t)
            ps.append(e[2][1] if e and e[2] else None)
        for i in range(len(ps) - 1):
            if ps[i] is not None and ps[i + 1] is not None and ps[i] < ps[i + 1]:
                c += 1
    return c


def place(order, lines, top_center=70, gap=None):
    """order: names top->bottom.  Choose octave for each line: no/min crossings,
    everything inside 36..84, top line near top_center, adjacent lines close."""
    best = None
    choices = range(-3, 3)
    for octs in itertools.product(choices, repeat=len(order)):
        ls = [octave(lines[n], o) for n, o in zip(order, octs)]
        avgs = [avg(l) for l in ls]
        if any(not (0 <= avgs[i] - avgs[i + 1] <= 17) for i in range(len(ls) - 1)):
            continue
        if lo_hi(ls[0])[1] > 84 or lo_hi(ls[-1])[0] < 36:
            continue
        cost = 6 * crossings(ls) + abs(avgs[0] - top_center) + sum(abs(avgs[i] - avgs[i + 1] - 8) for i in range(len(ls) - 1))
        if best is None or cost < best[0]:
            best = (cost, octs, ls)
    return best


def pick_voices(ls):
    """choose len(ls) of the four voices (in order) minimising out-of-range notes"""
    best = None
    for combo in itertools.combinations(VOX, len(ls)):
        bad = 0
        for v, l in zip(combo, ls):
            lo, hi = RANGES[v]
            bad += sum(1 for s, d, p in l if p and not lo <= p[1] <= hi)
        if best is None or bad < best[0]:
            best = (bad, list(combo))
    return best[1]


def voices_for(n):
    return {1: ['alto'], 2: ['alto', 'tenor'], 3: ['soprano', 'alto', 'tenor'], 4: VOX}[n]


def run_perm(order, lines, tag, top_center=70, show_all=False, voices=None):
    b = place(order, lines, top_center)
    if b is None:
        print(f"{tag}: no placement for {order}")
        return None
    cost, octs, ls = b
    vs = voices or pick_voices(ls)
    name = f"{tag}_{'-'.join(order)}.ly"
    lab(name, dict(zip(vs, ls)), f"{tag}: {' / '.join(order)} (top->bottom)")
    out = check(name)
    cnt, strong, tot = summary(out)
    print(f"{name:40s} octs={octs} PAR={cnt['PAR!']} BEAT={cnt['BEAT']} DIS!={cnt['DIS!']} D4?={cnt['D4?']} "
          f"DIR={cnt['DIR']} CROS={cnt['CROS']} MEL={cnt['MEL']} ERR={cnt['ERR']} strict={len(strict(out))}")
    if show_all:
        print(out)
    else:
        for l in out.splitlines():
            if l[:4] in ('PAR!', 'BEAT', 'DIS!', 'D4? ', 'ERR ', 'CROS', 'MEL ', 'DIR '):
                print('    ' + l)
        for l in strict(out):
            print('    strict: ' + l)
    return name


def perms(lines, tag, top_center=70, only=None):
    names = list(lines)
    for order in itertools.permutations(names):
        if only and order not in only:
            continue
        run_perm(order, lines, tag, top_center)
