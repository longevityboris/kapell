#!/usr/bin/env python3
"""Beam search for a countersubject that is invertible at the octave against one or more fixed lines.

A generator only: every result must still be placed in a 4-voice lab and pass tools/check.py.

Model (2-voice pairs CS/F for each fixed line F, both placements: CS below and CS an octave up):
  * consonances valid in BOTH placements: unison/8ve, 3rds, 6ths. Perfect 5ths and 4ths are treated
    as dissonances (they invert into each other), so they may only be passing/weak.
  * a dissonance struck by the CS must be a passing or neighbour note on a weak eighth or a weak beat;
  * a dissonance created by the fixed line moving against a held CS note must be a suspension:
    the CS note was consonant when struck and resolves down by step to a consonance;
  * no parallel perfect intervals (attack to attack, and beat to beat);
  * distance CS <-> F kept within an octave so octave inversion never crosses.
Melodic taste (per style): step bonus, chromatic-step bonus, leap penalties with recovery,
syncopation bonus (CS attacks while the fixed line holds), harmonic-plan chord-tone bonus.
"""
import sys, itertools, math
from fractions import Fraction as F
from p2 import parse, emit, pname

NAMES = {0: 'c', 1: 'des', 2: 'd', 3: 'ees', 4: 'e', 5: 'f', 6: 'ges', 7: 'g', 8: 'aes', 9: 'a', 10: 'bes', 11: 'ces'}
LETTER_OF = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 4, 8: 5, 9: 5, 10: 6, 11: 0}


def labs_of(m):
    pc = m % 12
    octv = m // 12 - 1
    l = LETTER_OF[pc]
    if pc == 11:  # ces belongs to the next octave letter-wise
        octv += 1
    return l + 7 * octv


def sound(notes, t):
    for n in notes:
        if n[2] is not None and n[0] <= t < n[0] + n[1]:
            return n
    return None


CONS = {0, 3, 4, 8, 9}


class Ctx:
    def __init__(self, fixed, t0, t1, lo, hi, style, plan=None, below=True, maxdist=12, cons_extra=()):
        self.fixed, self.t0, self.t1, self.lo, self.hi = fixed, F(t0), F(t1), lo, hi
        self.style, self.plan, self.below, self.maxdist = style, plan or {}, below, maxdist
        self.cons = CONS | set(cons_extra)
        self.fattacks = sorted({n[0] for f in fixed for n in f if n[2] is not None})


def strong(t):
    return t % 2 == 0


def eval_note(ctx, line, dur, m):
    """incremental penalty for appending note (start=end of line, dur, midi m)."""
    t = line[-1][0] + line[-1][1] if line else ctx.t0
    pen = 0.0
    prev = line[-1] if line else None
    # ---- melodic
    if prev is not None:
        iv = m - prev[2]
        a = abs(iv)
        if a == 0:
            pen += 3
        elif a <= 2:
            pen -= 1.0
            if a == 1:
                pen -= ctx.style.get('chroma', 0)
        elif a <= 4:
            pen += 0.5
        elif a in (5, 7):
            pen += 2
        elif a in (8, 9):
            pen += 4
        elif a == 12:
            pen += 3
        else:
            return None  # tritone, sevenths, > octave
        if a == 3 and prev and len(line) >= 1:
            pass
        # leap recovery
        if len(line) >= 2:
            piv = prev[2] - line[-2][2]
            if abs(piv) >= 5 and (iv * piv > 0 or abs(iv) > 2):
                pen += 3
        if iv < 0:
            pen -= ctx.style.get('descend', 0)
    # ---- rhythm
    if dur < F(1, 2) and not ctx.style.get('sixteenths'):
        return None
    if t % F(1, 2) != 0:
        return None
    fa = [x for x in ctx.fattacks if x == t]
    if not fa:
        pen -= ctx.style.get('syncope', 0.5)
    # long notes on weak eighths are awkward
    if t % 1 != 0 and dur > 1:
        pen += 2
    pen += ctx.style.get('dur_pen', {}).get(dur, 0)
    # ---- harmonic plan (chord tones on beats)
    if ctx.plan:
        key = int(t // 2) * 2
        chord = ctx.plan.get(key)
        if chord is not None and t % 1 == 0:
            pen += 0 if m % 12 in chord else ctx.style.get('plan_w', 1.5)
    # ---- counterpoint against each fixed line over [t, t+dur)
    end = t + dur
    for f in ctx.fixed:
        pts = sorted({t} | {n[0] for n in f if t < n[0] < end})
        for p in pts:
            fn = sound(f, p)
            if fn is None:
                continue
            d = fn[2] - m if ctx.below else m - fn[2]
            if d < 0 or d > ctx.maxdist:
                return None
            ic = (fn[2] - m) % 12
            diss = ic not in ctx.cons
            if not diss:
                continue
            if p == t:  # CS strikes a dissonance (fixed may or may not strike simultaneously)
                both = fn[0] == t
                if strong(p) and not ctx.style.get('allow_strong_app'):
                    return None
                # must be approached by step (checked now) and left by step (checked later)
                if prev is None or abs(m - prev[2]) > 2:
                    return None
                if dur > 1:
                    return None
                pen += 1.5 if both else 0.7
            else:  # fixed line moves against held CS note -> suspension or fixed-line passing note
                short_fixed = fn[1] <= F(1, 2) and p % 1 != 0
                if short_fixed:
                    pen += 0.8
                    continue
                # CS note must have been consonant at its own attack (preparation) - checked at attack;
                # resolution down by step checked when the next note arrives (flag it)
                pen += 0.3
                ctx_flag = ('sus', t, m)
    return pen


def resolution_ok(ctx, line, m_next):
    """if the last note became dissonant after its attack, the next note must resolve down by step
    to a consonance; if it was a struck dissonance, it must be left by step."""
    last = line[-1]
    t, d, m = last[0], last[1], last[2]
    end = t + d
    for f in ctx.fixed:
        # dissonance at attack
        fn = sound(f, t)
        if fn is not None and (fn[2] - m) % 12 not in ctx.cons:
            if abs(m_next - m) > 2 or m_next == m:
                return False
        # dissonance arising later (fixed moved against held note)
        for n in f:
            if n[2] is None or not (t < n[0] < end):
                continue
            if (n[2] - m) % 12 not in ctx.cons and not (n[1] <= F(1, 2) and n[0] % 1 != 0):
                if not (1 <= m - m_next <= 2):
                    return False
                fe = sound(f, end)
                if fe is not None and (fe[2] - m_next) % 12 not in ctx.cons:
                    return False
    return True


def parallels(ctx, line):
    """parallel perfects between the last two CS notes and each fixed line (attack-to-attack)."""
    if len(line) < 2:
        return 0
    a, b = line[-2], line[-1]
    pen = 0
    for f in ctx.fixed:
        pts = sorted({a[0], b[0]} | {n[0] for n in f if a[0] < n[0] < b[0] + b[1]})
        prevp = None
        for p in pts:
            c = sound([a, b], p)
            fn = sound(f, p)
            if c is None or fn is None:
                prevp = None
                continue
            if prevp is not None:
                c0, f0 = prevp
                if c0[2] != c[2] and f0[2] != fn[2]:
                    i0, i1 = (f0[2] - c0[2]) % 12, (fn[2] - c[2]) % 12
                    if i0 == i1 and i0 in (0, 7, 5):
                        pen += 20 if i0 in (0, 7) else 6
            prevp = (c, fn)
    return pen


def search(ctx, durs, width=3000, top=10, first=None):
    beams = [(0.0, [])]
    if first is not None:
        beams = [(0.0, [list(x) for x in first])]
    done = []
    pitches = range(ctx.lo, ctx.hi + 1)
    while beams:
        nb = []
        for sc, line in beams:
            t = line[-1][0] + line[-1][1] if line else ctx.t0
            if t == ctx.t1:
                done.append((sc, line))
                continue
            for d in durs:
                d = F(d)
                if t + d > ctx.t1:
                    continue
                for m in pitches:
                    if line and not resolution_ok(ctx, line, m):
                        continue
                    p = eval_note(ctx, line, d, m)
                    if p is None:
                        continue
                    nl = line + [[t, d, m, labs_of(m)]]
                    pp = parallels(ctx, nl)
                    nb.append((sc + p + pp, nl))
        nb.sort(key=lambda x: x[0])
        beams = nb[:width]
    done.sort(key=lambda x: x[0])
    return done[:top]


if __name__ == '__main__':
    from p2 import S1
    s1 = parse(S1)
    style = dict(chroma=0.8, descend=0.3, syncope=0.6)
    ctx = Ctx([s1], 3, 19, 53, 69, style, below=True)
    res = search(ctx, [F(1, 2), 1, F(3, 2), 2, 3], width=4000, top=15)
    for sc, line in res:
        print(f"{sc:6.1f}  ", emit([[n[0], n[1], n[2], n[3]] for n in line]))
