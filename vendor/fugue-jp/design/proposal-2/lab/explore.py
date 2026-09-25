#!/usr/bin/env python3
"""Stretto / combination explorer for proposal-2 (a search aid, not the proof).

Each form is a LilyPond \\absolute fragment. Two forms are overlaid at a given
transposition and time offset; every attack is scored for 2-voice counterpoint:
strong-beat dissonance that is not a suspension, long dissonances, parallel
perfects, and simultaneous cross-relations (e.g. E natural against E flat).
The real proof is always a 4-voice lab file run through tools/check.py.
"""
import re, sys, itertools
from fractions import Fraction as F

PC = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)
LET = 'cdefgab'
TOK = re.compile(r"([a-g](?:isis|eses|is|es)?[',]*)(\d+)?(\.*)(~)?|([rs])(\d+)?(\.*)|(\|)")


def parse(src):
    """-> list of [start, dur, midi, letter_abs, alter] (quarter = 1)."""
    t, dur, out, tie = F(0), F(1), [], False
    for m in TOK.finditer(src):
        n, d, dots, ti, r, rd, rdots, bar = m.groups()
        if bar:
            continue
        if n or r:
            dd = d if n else rd
            if dd:
                dur = F(4, int(dd))
                x = dur
                for _ in (dots if n else rdots):
                    x /= 2
                    dur += x
        if r:
            t += dur
            tie = False
            continue
        if n:
            letter = n[0]
            acc = n[1:].rstrip("',")
            alt = {'': 0, 'is': 1, 'es': -1, 'isis': 2, 'eses': -2}[acc]
            octv = 3 + n.count("'") - n.count(",")
            midi = 12 * (octv + 1) + PC[letter] + alt
            labs = LET.index(letter) + 7 * octv
            if tie and out and out[-1][2] == midi:
                out[-1][1] += dur
            else:
                out.append([t, dur, midi, labs, alt])
            t += dur
            tie = bool(ti)
    return out


def transpose(form, steps, semis):
    return [[s, d, m + semis, l + steps, None] for s, d, m, l, a in form]


def shift(form, dt):
    return [[s + dt, d, m, l, a] for s, d, m, l, a in form]


def scale(form, k):
    return [[s * k, d * k, m, l, a] for s, d, m, l, a in form]


def at(form, t):
    for n in form:
        if n[0] <= t < n[0] + n[1]:
            return n
    return None


def name(n):
    m, l = n[2], n[3]
    letter = LET[l % 7]
    octv = l // 7
    alt = m - (12 * (octv + 1) + PC[letter])
    return letter.upper() + {0: '', 1: '#', -1: 'b', 2: '##', -2: 'bb'}.get(alt, '?') + str(octv)


def score(up, lo, fourth_ok=False, verbose=False):
    """up/lo: note lists; returns (penalty, notes)."""
    times = sorted({n[0] for n in up} | {n[0] for n in lo})
    pen, log = 0, []
    prev = None
    for t in times:
        a, b = at(up, t), at(lo, t)
        if a is None or b is None:
            prev = None
            continue
        iv = a[2] - b[2]
        ic = iv % 12
        cons = ic in (0, 3, 4, 7, 8, 9) or (fourth_ok and ic == 5)
        if iv < 0:
            pen += 5
            log.append(f"{t}: crossing {name(a)}/{name(b)}")
        # cross relation: same letter class, different pitch class, sounding together
        if a[3] % 7 == b[3] % 7 and ic != 0:
            pen += 8
            log.append(f"{t}: CROSS-REL {name(a)}/{name(b)}")
        if not cons:
            strong = (t % 2 == 0)
            # suspension: the dissonant note was held from before t and moves down by step
            def susp(x, other):
                return x[0] < t and x is not None
            held_a = a[0] < t
            held_b = b[0] < t
            dur_overlap = min(a[0] + a[1], b[0] + b[1]) - t
            kind = 'held' if (held_a or held_b) else 'attack'
            p = 0
            if strong and kind == 'attack':
                p = 4
            elif strong:
                p = 1
            else:
                p = 0.5
            if dur_overlap > 1:
                p += 2 * float(dur_overlap)
            pen += p
            if p >= 1:
                log.append(f"{t}: diss {name(a)}/{name(b)} ({kind}, {'strong' if strong else 'weak'}, len {dur_overlap})")
        if prev is not None:
            pa, pb = prev
            if pa is not a and pb is not b and pa[2] != a[2] and pb[2] != b[2]:
                pic = (pa[2] - pb[2]) % 12
                if pic == ic and ic in (0, 7):
                    pen += 10
                    log.append(f"{t}: PARALLEL {'8' if ic == 0 else '5'} {name(pa)}/{name(pb)} -> {name(a)}/{name(b)}")
        prev = (a, b)
    return pen, log


FORMS = dict(
    S1="bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes' | c''4. a'8 f'4",
    ANS="f''2. f''8 e'' | f''2. f''8 e'' | f''4. g''8 g''4. bes''8 | bes''2. aes''8 f'' | g''4. e''8 c''4",
    INV="f''2. f''8 ges'' | f''2. f''8 ges'' | f''4. ees''8 ees''4. c''8 | c''2. des''8 f'' | ees''4. ges''8 bes''4",
    S2="c''4. a'8 f'4 des''8 bes' | c''2. f''8 bes' | ees''4. des''8 des''4. c''8 | c''1",
)

# diatonic transpositions (steps, semitones), to be applied to the LOWER voice
IVS = {
    'P8': (-7, -12), 'P5': (-4, -7), 'P4': (-3, -5), 'M6': (-5, -9), 'm6': (-5, -8),
    'M3': (-2, -4), 'm3': (-2, -3), 'P12': (-11, -19), 'P11': (-10, -17), 'M10': (-9, -16),
    'm10': (-9, -15), 'M9': (-8, -14), 'M2': (-1, -2), 'm7': (-6, -10), 'P1': (0, 0),
}

if __name__ == '__main__':
    # usage: explore.py UPPER LOWER [--first lower|upper] [--max 8]
    upn, lon = sys.argv[1], sys.argv[2]
    first = 'upper'
    if '--first' in sys.argv:
        first = sys.argv[sys.argv.index('--first') + 1]
    maxd = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 8
    fourth_ok = '--4ok' in sys.argv
    aug = '--aug' in sys.argv
    up0, lo0 = parse(FORMS[upn]), parse(FORMS[lon])
    if aug:
        lo0 = scale(lo0, 2)
    res = []
    for ivn, (st, se) in IVS.items():
        lo1 = transpose(lo0, st, se)
        for half in range(1, 2 * maxd + 1):
            d = F(half, 2)
            if first == 'upper':
                up, lo = up0, shift(lo1, d)
            else:
                up, lo = shift(up0, d), lo1
            p, log = score(up, lo, fourth_ok)
            res.append((p, ivn, d, log))
    res.sort(key=lambda r: r[0])
    for p, ivn, d, log in res[:int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 15]:
        print(f"pen {p:5.1f}  lower={lon} {ivn:4} below, {'lower' if first=='upper' else 'upper'} enters +{d} beats")
        for l in log[:8]:
            print('      ', l)
