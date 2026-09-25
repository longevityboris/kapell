#!/usr/bin/env python3
"""Sonority grid of a four-voice \\absolute file: one line per eighth (or per attack with --attacks).

usage: python3 grid.py FILE.ly [--bars A-B] [--attacks] [--sixteenths]

Columns: position, S A T B (pitch; '.' = held from before, '-' = rest), then the sounding pitch
classes low to high and a chord name (music21). Flags: 'UNI' two voices on the same MIDI pitch,
'HOL' a four-voice sonority with at most two pitch classes, 'X' a voice crossing.
Used to derive every harmony label in BLUEPRINT.md from the notes rather than from intentions.
"""
import os
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools'))
from lyparse import parse_voice  # noqa: E402

V = ['soprano', 'alto', 'tenor', 'bass']


def load(path):
    src = open(path).read()
    return {v: (parse_voice(src, v) or []) for v in V}


def sounding(ns, t):
    for n in ns:
        if n.start <= t < n.end:
            return n
    return None


def pos(t):
    b = int(t) + 1
    return f"{b}:{float((t - (b - 1)) * 4 + 1):g}"


def chord_name(names):
    try:
        from music21 import chord
        c = chord.Chord([nm[0] + nm[1:-1].replace('b', '-') + nm[-1] for nm in names])
        return c.pitchedCommonName
    except Exception:
        return '?'


def rows(data, a=None, b=None, step=F(1, 8), attacks=False):
    end = max((n.end for v in V for n in data[v]), default=F(0))
    t0 = F(a - 1) if a else F(0)
    t1 = F(b) if b else end
    times = []
    if attacks:
        times = sorted({n.start for v in V for n in data[v] if t0 <= n.start < t1 and n.midi is not None})
    else:
        t = t0
        while t < t1:
            times.append(t)
            t += step
    out = []
    for t in times:
        cells, snd = [], []
        for v in V:
            n = sounding(data[v], t)
            if n is None or n.midi is None:
                cells.append('-')
            else:
                cells.append(n.name if n.start == t else '.' + n.name)
                snd.append((v, n))
        flags = []
        mids = [n.midi for _, n in snd]
        for i in range(len(snd)):
            for j in range(i + 1, len(snd)):
                if snd[i][1].midi == snd[j][1].midi:
                    flags.append('UNI')
                if V.index(snd[i][0]) < V.index(snd[j][0]) and snd[i][1].midi < snd[j][1].midi:
                    flags.append('X')
        pcs = sorted({m % 12 for m in mids})
        if len(snd) == 4 and len(pcs) <= 2:
            flags.append('HOL')
        names = [n.name for _, n in sorted(snd, key=lambda x: x[1].midi)]
        out.append((t, cells, names, chord_name(names) if names else '', sorted(set(flags))))
    return out


def main():
    args = sys.argv[1:]
    path = args[0]
    a = b = None
    if '--bars' in args:
        a, b = map(int, args[args.index('--bars') + 1].split('-'))
    step = F(1, 16) if '--sixteenths' in args else F(1, 8)
    data = load(path)
    for t, cells, names, ch, flags in rows(data, a, b, step, '--attacks' in args):
        if (t * 4) % 4 == 0:
            pass
        print(f"{pos(t):>7}  " + ' '.join(f"{c:>5}" for c in cells) + f"   {ch}" + (f"   [{' '.join(flags)}]" if flags else ''))


if __name__ == '__main__':
    main()
