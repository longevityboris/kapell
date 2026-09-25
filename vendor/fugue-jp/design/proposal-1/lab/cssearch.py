"""Beam search for a countersubject against a given line, invertible at the
octave (both arrangements are scored with search.evaluate).  Pre-filter only;
winners are verified with tools/check.py in named labs.

usage (python): best = cs_search(cantus, template, pitches, above=True, lo=.., hi=..)
  template: LilyPond rhythm with 'x' as pitch placeholder, e.g. "r4 x4 x4 x4 | x2 x2 | ..."
            a tie is written 'x2~ x4' (same pitch forced)
"""
import re, random
from fractions import Fraction as F
from ricer import *
from search import evaluate, at


def template_events(tpl):
    """-> list of (start, dur, kind) kind in {'n','r','tie'}"""
    toks = re.findall(r"([xr])(\d+)(\.?)(~?)", tpl)
    t, out, tie = F(0), [], False
    for k, d, dot, ti in toks:
        dur = F(1, int(d)) * (F(3, 2) if dot else 1)
        out.append((t, dur, 'r' if k == 'r' else ('tie' if tie else 'n')))
        t += dur
        tie = bool(ti)
    return out


def melodic_cost(ps):
    """ps: list of midi (None for rest). Penalise leaps, repeated notes, bad intervals."""
    c = 0.0
    prev = None
    lastleap = 0
    for p in ps:
        if p is None:
            prev = None
            continue
        if prev is not None:
            iv = p - prev
            a = abs(iv)
            if a == 0:
                c += 1.5
            elif a <= 2:
                c += 0
            elif a <= 4:
                c += 0.6
            elif a in (5, 7):
                c += 1.2
            elif a in (8, 9, 12):
                c += 2.5
            else:
                c += 8          # tritone, sevenths, > octave
            if a >= 5 and lastleap and (iv > 0) == (lastleap > 0):
                c += 3          # two leaps same direction
            if lastleap and abs(lastleap) >= 5 and not (a <= 2 and (iv > 0) != (lastleap > 0)):
                c += 1.5        # leap not recovered by step in opposite direction
            lastleap = iv if a >= 3 else 0
        prev = p
    return c


def cs_search(cantus, tpl, pitches, above=True, width=400, keep=10, seed=1, octave_gap=24, extra=None):
    ev = template_events(tpl)
    beams = [([], 0.0)]
    for i, (s, d, kind) in enumerate(ev):
        nb = []
        for seq, cost in beams:
            if kind == 'r':
                cands = [None]
            elif kind == 'tie':
                cands = [seq[-1][2]]
            else:
                cands = pitches
            for p in cands:
                new = seq + [(s, d, p)]
                line = [(a, b, None if q is None else pitch_of(q)) for a, b, q in new]
                # score partial: both arrangements up to current time
                end = s + d
                cpart = [(a, b, q) for a, b, q in cantus if a < end]
                if above:
                    U1, L1 = line, cpart
                    U2, L2 = cpart, octave(line, -octave_gap // 12)
                else:
                    U1, L1 = cpart, line
                    U2, L2 = octave(line, octave_gap // 12), cpart
                p1, _ = evaluate(U1, L1)
                p2, _ = evaluate(U2, L2)
                mc = melodic_cost([None if q is None else pitch_of(q)[1] for a, b, q in new])
                tot = p1 * 3 + p2 * 3 + mc
                if extra:
                    tot += extra(new)
                nb.append((new, tot))
        nb.sort(key=lambda x: x[1])
        beams = nb[:width]
    return beams[:keep]


NAMES = {}


def pitch_of(name):
    if name not in NAMES:
        NAMES[name] = pitch(name)
    return NAMES[name]


def to_ly(seq, total=None):
    line = [(a, b, None if q is None else pitch_of(q)) for a, b, q in seq]
    return render(line, total)
