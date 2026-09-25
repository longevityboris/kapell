"""Brute-force search of two-voice combinations (stretto, mirror stretto,
subject combination).  Fast pre-filter only; winners are re-verified with
tools/check.py in named lab files.

Usage: python3 search.py [stretto|mirror|s1s2|aug]
"""
import sys
from fractions import Fraction as F
from ricer import *
from mats import *

DISS = {1, 2, 6, 10, 11}


def at(line, t):
    for s, d, p in line:
        if s <= t < s + d:
            return (s, d, p)
    return None


def neighbours(line, ev):
    i = line.index(ev)
    pv = line[i - 1] if i > 0 else None
    nx = line[i + 1] if i + 1 < len(line) else None
    if pv and (pv[2] is None or pv[0] + pv[1] != ev[0]):
        pv = None
    if nx and nx[2] is None:
        nx = None
    return pv, nx


def step(a, b):
    return a is not None and b is not None and a[2] is not None and b[2] is not None and 1 <= abs(a[2][1] - b[2][1]) <= 2


def evaluate(U, L, detail=False):
    """U nominally upper, L lower.  Returns (penalty, notes)."""
    U = [e for e in U]
    L = [e for e in L]
    times = sorted({s for s, d, p in U + L})
    pen, notes, prev = 0, [], None
    for t in times:
        u, l = at(U, t), at(L, t)
        if not u or not l or u[2] is None or l[2] is None:
            prev = None
            continue
        hi, lo = u[2][1], l[2][1]
        if hi < lo:
            pen += 2
            notes.append(f"{t}: crossing")
        iv = abs(hi - lo) % 12
        strong = (t % F(1, 2) == 0)
        diss = iv in DISS or (iv == 5 and hi >= lo)
        if diss:
            ok = False
            for a, b in ((u, l), (l, u)):
                line = U if a is u else L
                pv, nx = neighbours(line, a)
                if a[0] == t:  # attacked
                    if step(pv, a) and step(a, nx) and not strong:
                        ok = True  # passing / neighbour
                    if nx is not None and nx[2] == a[2] and not strong and step(pv, a):
                        ok = True  # anticipation
                    if step(a, nx) and not strong and nx[2][1] < a[2][1]:
                        ok = True  # weak appoggiatura resolving down (lenient)
                else:  # held: suspension if it resolves down by step
                    if nx is not None and step(a, nx) and nx[2][1] < a[2][1]:
                        ok = True
                    if nx is not None and nx[2] == a[2]:
                        i = line.index(nx)
                        nx2 = line[i + 1] if i + 1 < len(line) else None
                        if nx2 is not None and nx2[2] is not None and 1 <= a[2][1] - nx2[2][1] <= 2:
                            ok = True
            if not ok:
                pen += 4 if strong else 1
                notes.append(f"{float(t):.3f}: {'STRONG ' if strong else ''}diss {iv}")
            elif strong:
                pen += 0.5
        if prev is not None:
            pu, pl, piv = prev
            if pu[2] != u[2] and pl[2] != l[2] and piv == iv and iv in (0, 7):
                pen += 10
                notes.append(f"{float(t):.3f}: parallel {iv}")
        prev = (u, l, iv)
    return pen, notes


def trans_list(diatonic=True):
    out = []
    for dia in range(-15, 16):
        # diatonic transposition inside B-flat harmonic minor
        out.append(('d', dia))
    return out


def follower(line, kind, amount, dt):
    if kind == 'd':
        f = dtrans(line, amount, scale=HMIN)
    else:
        f = transpose(line, *amount)
    return shift(f, dt)


REAL = {'P1': (0, 0), 'P8u': (7, 12), 'P8d': (-7, -12), 'P5u': (4, 7), 'P4d': (-3, -5), 'P12u': (11, 19),
        'P11d': (-10, -17), 'P4u': (3, 5), 'P5d': (-4, -7), 'P15d': (-14, -24), 'P11u': (10, 17), 'P12d': (-11, -19)}


def run(leader, fol, label, offsets, both=True, top=25, maxpen=6):
    res = []
    for name, amt in list(REAL.items()) + [(f'd{d:+d}', d) for d in range(-15, 16) if d % 7 not in (0,)]:
        kind = 'r' if name in REAL else 'd'
        for dt in offsets:
            f = follower(fol, kind, amt, dt)
            # decide which is upper by average pitch in overlap
            lead_avg = sum(p[1] for s, d, p in leader if p) / len(leader)
            fol_avg = sum(p[1] for s, d, p in f if p) / len(f)
            U, L = (f, leader) if fol_avg >= lead_avg else (leader, f)
            pen, notes = evaluate(U, L)
            res.append((pen, name, dt, 'fol-above' if U is f else 'fol-below', notes))
    res.sort(key=lambda r: r[0])
    print(f"=== {label}")
    for r in res[:top]:
        if r[0] <= maxpen:
            print(f"pen {r[0]:5.1f}  {r[1]:6} dt={str(r[2]):5} {r[3]:9}  {'; '.join(r[4][:6])}")


if __name__ == '__main__':
    what = sys.argv[1] if len(sys.argv) > 1 else 'stretto'
    offs = [F(k, 4) for k in range(1, 16)]
    if what == 'stretto':
        run(S1, S1, 'S1 x S1 stretto', offs)
    elif what == 'mirror':
        run(S1, I1, 'S1 leader, I1 follower', [F(0)] + offs)
        run(I1, S1, 'I1 leader, S1 follower', offs)
    elif what == 's1s2':
        run(S1, S2, 'S1 leader, S2 follower', [F(0)] + offs + [F(k, 4) for k in range(16, 20)])
        run(S2, S1, 'S2 leader, S1 follower', offs)
    elif what == 'inv':
        run(I1, I1, 'I1 x I1 stretto', offs)
