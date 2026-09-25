#!/usr/bin/env python3
"""Harmonic x-ray of a score: sonority at every attack, with Roman numerals in a given key.

usage: python3 tools/harmony.py FILE.ly [--voices soprano,alto,tenor,bass] [--bars A-B]
                               [--key 1-20=bb,21-30=f] [--measure 1] [--stats]
Prints per bar: position, bass note, pitch-class set, chord name, Roman numeral (music21).
--stats prints richness metrics: share of seventh chords, diminished sevenths, chromatic
sonorities (non-diatonic to the local key), suspensions/dissonant attacks, distinct harmonies.
"""
import sys
from fractions import Fraction as F
from bisect import bisect_right
sys.path.insert(0, __import__('os').path.dirname(__file__))
from lyparse import parse_voice
from music21 import chord, key as m21key, roman, pitch

a = sys.argv[1:]
src = open(a[0]).read()
voices = (a[a.index('--voices') + 1] if '--voices' in a else 'soprano,alto,tenor,bass').split(',')
measure = F(a[a.index('--measure') + 1]) if '--measure' in a else F(1)
bars = tuple(map(int, a[a.index('--bars') + 1].split('-'))) if '--bars' in a else None
keymap = []
if '--key' in a:
    for part in a[a.index('--key') + 1].split(','):
        rng, k = part.split('=')
        lo, hi = map(int, rng.split('-'))
        keymap.append((lo, hi, k))


def key_for(bar):
    for lo, hi, k in keymap:
        if lo <= bar <= hi:
            tonic = k[0].upper() + k[1:].replace('is', '#').replace('es', '-').replace('s', '-') if len(k) > 1 else k.upper()
            if k[0].isupper():
                return m21key.Key(tonic)
            return m21key.Key(tonic.lower() if False else tonic, 'minor')
    return None


data = {}
for v in voices:
    n = parse_voice(src, v, measure)
    if n:
        data[v] = ([x for x in n], [x.start for x in n])


def at(v, t):
    notes, starts = data[v]
    i = bisect_right(starts, t) - 1
    if i < 0:
        return None
    x = notes[i]
    return x if x.start <= t < x.end and x.midi is not None else None


times = sorted({x.start for v in data for x in data[v][0]})
stats = dict(n=0, sev=0, dim7=0, chrom=0, diss=0, names=set())
cur_bar = None
line = []
for t in times:
    b = int(t / measure) + 1
    if bars and not (bars[0] <= b <= bars[1]):
        continue
    snd = [at(v, t) for v in data]
    snd = [x for x in snd if x]
    if not snd:
        continue
    mids = sorted(x.midi for x in snd)
    c = chord.Chord([pitch.Pitch(midi=m) for m in mids])
    k = key_for(b)
    rn = ''
    if k is not None:
        try:
            rn = roman.romanNumeralFromChord(c, k).figure
        except Exception:
            rn = '?'
    beat = float((t - (b - 1) * measure) * 4 + 1)
    name = c.pitchedCommonName
    if b != cur_bar:
        if line:
            print(' | '.join(line))
        line = [f"{b:3d}:"]
        cur_bar = b
    line.append(f"{beat:g} {pitch.Pitch(midi=mids[0]).name}{'':0s} {rn or name}")
    stats['n'] += 1
    stats['names'].add(rn or name)
    if c.isSeventh() or c.isDominantSeventh() or c.isHalfDiminishedSeventh():
        stats['sev'] += 1
    if c.isDiminishedSeventh():
        stats['dim7'] += 1
    if k is not None:
        sc = {p.name for p in k.getScale().getPitches()} | {k.getScale().getPitches()[6].transpose('A1').name if k.mode == 'minor' else ''}
        if any(p.name not in sc for p in c.pitches):
            stats['chrom'] += 1
if line:
    print(' | '.join(line))
if '--stats' in a and stats['n']:
    n = stats['n']
    print(f"\nattacks {n}; seventh-type {stats['sev']/n:.0%}; dim7 {stats['dim7']/n:.0%}; "
          f"chromatic-to-key {stats['chrom']/n:.0%}; distinct labels {len(stats['names'])}")
