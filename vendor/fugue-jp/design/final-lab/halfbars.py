#!/usr/bin/env python3
"""Print the sonority of SK_final.ly on every half bar (beats 1 and 3): bass-up pitches and a chord name.
usage: python3 halfbars.py [A-B]"""
import os, sys
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools'))
from lyparse import parse_voice
from music21 import chord
src = open(os.path.join(HERE, 'SK_final.ly')).read()
V = ['soprano', 'alto', 'tenor', 'bass']
data = {v: parse_voice(src, v) for v in V}
a, b = (map(int, sys.argv[1].split('-')) if len(sys.argv) > 1 else (1, 62))
def snd(v, t):
    for n in data[v]:
        if n.start <= t < n.end and n.midi is not None:
            return n
for bar in range(a, b + 1):
    row = []
    for beat in (1, 3):
        t = F(bar - 1) + F(beat - 1, 4)
        ns = sorted([x for x in (snd(v, t) for v in V) if x], key=lambda n: n.midi)
        names = [n.name for n in ns]
        try:
            c = chord.Chord([n.name[0] + n.name[1:-1].replace('b', '-') + n.name[-1] for n in ns]).pitchedCommonName if ns else '-'
        except Exception:
            c = '?'
        row.append(f"{beat}: {' '.join(names):22s} {c}")
    print(f"{bar:3d} | " + " | ".join(row))
