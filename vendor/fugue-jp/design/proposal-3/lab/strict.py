#!/usr/bin/env python3
"""Strict second opinion on top of tools/check.py (proposal 3).

usage: python3 strict.py FILE.ly [--bars A-B] [-v]

tools/check.py accepts any dissonance whose note moves by step as "PT/NT", even on beats 1 and 3 and
even when both notes are struck together. This script flags what a strict ear would question:
  CLASH  two notes a chromatic semitone apart on the same letter (g/ges, a/aes...) sounding together:
         an augmented unison/octave. Always wrong in this style.
  XREL   cross relation: a letter with one accidental in one voice followed within a quarter by the same
         letter with another accidental in a different voice (e.g. aes then a). Reported for review.
  ACC    dissonance on beat 1 or 3 that is not a prepared suspension/retardation (held from a consonance
         and resolving by step): accented passing tone or appoggiatura. Reported for review.
  ACC2   as ACC but both notes struck together (stronger).
Summary line: 'strict: clash N, xrel N, acc N, acc2 N'.
"""
import sys, os
from fractions import Fraction as F
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'tools'))
from lyparse import parse_voice

args = sys.argv[1:]
path = args[0]
src = open(path).read()
VOICES = ['soprano', 'alto', 'tenor', 'bass']
bars = tuple(map(int, args[args.index('--bars') + 1].split('-'))) if '--bars' in args else None
verbose = '-v' in args
data = {}
for v in VOICES:
    n = parse_voice(src, v)
    if n:
        data[v] = [x for x in n if x.midi is not None]
LET = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}


def at(v, t):
    for x in data[v]:
        if x.start <= t < x.end:
            return x
    return None


def idx(v, x):
    return data[v].index(x)


def pos(t):
    b = int(t) + 1
    return f"{b}:{float((t - (b - 1)) * 4 + 1):g}"


def letter(x):
    return x.name[0]


def inbars(t):
    return bars is None or bars[0] <= int(t) + 1 <= bars[1]


times = sorted({x.start for v in data for x in data[v]})
out = []
cnt = dict(clash=0, xrel=0, acc=0, acc2=0)
for t in times:
    if not inbars(t):
        continue
    snd = {v: at(v, t) for v in data if at(v, t)}
    low = min(x.midi for x in snd.values())
    vs = list(snd)
    strong = (t * 4) % 2 == 0
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            a, b = snd[vs[i]], snd[vs[j]]
            if a.start != t and b.start != t:
                continue
            if letter(a) == letter(b) and (a.midi - b.midi) % 12 != 0:
                cnt['clash'] += 1
                out.append(f"CLASH {pos(t)} {vs[i]} {a.name} / {vs[j]} {b.name}")
            iv = abs(a.midi - b.midi) % 12
            lower = a if a.midi < b.midi else b
            dis = iv in (1, 2, 10, 11) or (iv in (5, 6) and lower.midi == low)
            if not (dis and strong):
                continue
            # prepared suspension / retardation: a note held into t (start < t) from a consonance
            ok = False
            for v, x, other in ((vs[i], a, b), (vs[j], b, a)):
                if x.start < t:
                    k = idx(v, x)
                    nx = data[v][k + 1] if k + 1 < len(data[v]) else None
                    nx2 = data[v][k + 2] if k + 2 < len(data[v]) else None
                    if nx is not None and 1 <= abs(nx.midi - x.midi) <= 2:
                        ok = True
                    elif (nx is not None and nx.midi == x.midi and nx.start == x.end and nx2 is not None
                          and 1 <= x.midi - nx2.midi <= 2):
                        ok = True  # held, re-struck, then resolves down by step
                elif x.start == t:
                    # re-struck suspension: same pitch as previous note, then resolves by step
                    k = idx(v, x)
                    pv = data[v][k - 1] if k > 0 else None
                    nx = data[v][k + 1] if k + 1 < len(data[v]) else None
                    if pv is not None and pv.midi == x.midi and pv.end == t and nx is not None and 1 <= x.midi - nx.midi <= 2:
                        ok = True
            if ok:
                continue
            both = a.start == t and b.start == t
            key = 'acc2' if both else 'acc'
            cnt[key] += 1
            out.append(f"{key.upper():5} {pos(t)} {vs[i]} {a.name} / {vs[j]} {b.name}")
# cross relations
for v1 in data:
    for x in data[v1]:
        if not inbars(x.start):
            continue
        for v2 in data:
            if v2 == v1:
                continue
            for y in data[v2]:
                if y.start < x.start or y.start > x.start + F(1, 4) or y is x:
                    continue
                if letter(y) == letter(x) and (y.midi - x.midi) % 12 not in (0,) and y.start >= x.end - F(1, 4):
                    if y.start >= x.start and (y.start > x.start or True):
                        # same letter, different accidental, successive (y starts at/after x ends - 1/16)
                        if y.start >= x.end or y.start > x.start:
                            cnt['xrel'] += 1
                            out.append(f"XREL  {pos(x.start)}->{pos(y.start)} {v1} {x.name} then {v2} {y.name}")
for o in out:
    if verbose or not o.startswith('ACC '):
        print(o)
print(f"strict: clash {cnt['clash']}, xrel {cnt['xrel']}, acc {cnt['acc']}, acc2 {cnt['acc2']}")
