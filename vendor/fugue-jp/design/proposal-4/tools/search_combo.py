#!/usr/bin/env python3
"""Search two-voice combinations of melody A (fixed) and melody B (diatonically transposed, time-shifted).

usage: python3 search_combo.py KIND   (KIND in: s1s2, s1s1, s1inv, aug, s2s2)
Every candidate is written to a temporary lab file and run through the project checker
(ricercar/tools/check.py) with the four voice ranges; results are ranked by
(PAR!+BEAT, DIS!, D4?, DIR). Only the upper voice is 'soprano' and the lower is 'alto' or
'tenor'/'bass' so the checker's range test is meaningful for the chosen register.
"""
import os
import sys
import tempfile
from fractions import Fraction as F
from p4 import *

S1 = ly("bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes' | c''2")
S2 = ly("c''4. a'8 f'4 des''8 bes' | c''2. f''8 bes' | ees''4. des''8 des''4. c''8 | c''2")
S1M = ly("bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes' | c''2")
S2M = ly("c''4. a'8 f'4 d''8 bes' | c''2. f''8 bes' | ees''4. d''8 d''4. c''8 | c''2")

TMP = tempfile.mkdtemp()


def run(upper, lower, lower_voice='alto', upper_voice='soprano'):
    tot = max(length(upper), length(lower))
    tot = F(int(tot) + (1 if tot % 1 else 0))
    vs = {upper_voice: fill(upper, tot), lower_voice: fill(lower, tot)}
    lines = []
    for v in VOICES:
        ev = fill(vs.get(v, []), tot)
        lines.append(f'{v} = \\absolute {{\n  ' + ' '.join(to_ly(ev)) + '\n}')
    path = os.path.join(TMP, 'c.ly')
    open(path, 'w').write('\n'.join(lines) + '\n')
    out = check(path)
    return score(out), out


def shift(ev, beats):
    """delay by beats (quarters); negative = trim the start"""
    if beats >= 0:
        return rest(F(beats, 4)) + ev if beats else list(ev)
    cut = F(-beats, 4)
    out, t = [], F(0)
    for p, d in ev:
        if t + d <= cut:
            t += d
            continue
        if t < cut:
            out.append((p, t + d - cut))
        else:
            out.append((p, d))
        t += d
    return out


def fit_register(ev, lo, hi):
    ms = [midi(p) for p, _ in ev if p]
    k = 0
    while max(ms) + 12 * k > hi:
        k -= 1
    while min(ms) + 12 * k < lo:
        k += 1
    return real(ev, 7 * k, 12 * k) if k else ev


def search(A, B, key, steps, offsets, label, lower_is_B=True, voices=('soprano', 'alto'), maxshow=12,
           verify=True, key_to=None):
    from strict2 import evaluate
    res = []
    for s in steps:
        Bt = inkey(B, s, key, key_to)
        for o in offsets:
            Bs = shift(Bt, o)
            up, lo = (A, Bs) if lower_is_B else (Bs, A)
            lo_m = [midi(p) for p, _ in lo if p]
            up_m = [midi(p) for p, _ in up if p]
            r1, r2 = RANGES[voices[0]], RANGES[voices[1]]
            if min(up_m) < r1[0] or max(up_m) > r1[1] or min(lo_m) < r2[0] or max(lo_m) > r2[1]:
                continue
            # overlap length in beats
            ov = min(length(up), length(lo)) - F(max(o, 0), 4) if lower_is_B else None
            hard, soft = evaluate(up, lo)
            res.append((hard, soft, s, o))
    res.sort()
    print(f'== {label}')
    for hard, soft, s, o in res[:maxshow]:
        line = f'  steps {s:+3d} offset {o:+3d} beats : strict hard {hard} soft {soft}'
        if verify and hard == 0:
            Bs = shift(inkey(B, s, key, key_to), o)
            up, lo = (A, Bs) if lower_is_B else (Bs, A)
            sc, out = run(up, lo, lower_voice=voices[1], upper_voice=voices[0])
            line += '  | checker: ' + summary(out).split(';')[1]
        print(line)
    return res


if __name__ == '__main__':
    kind = sys.argv[1] if len(sys.argv) > 1 else 's1s2'
    if kind == 's1s2':
        # S1 in soprano (bes'), S2 below (diatonic transpositions an octave+ lower), offsets in quarters
        search(S1, S2, 'bes-harm', range(-11, -1), range(0, 17), 'S1 above, S2 below (minor)')
        search(S2, S1, 'bes-harm', range(-11, -1), range(-8, 17), 'S2 above, S1 below (minor)')
    if kind == 's1s2M':
        search(S1M, S2M, 'bes-major', range(-11, -1), range(0, 17), 'S1 above, S2 below (major)')
        search(S2M, S1M, 'bes-major', range(-11, -1), range(-8, 17), 'S2 above, S1 below (major)')
