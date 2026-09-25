#!/usr/bin/env python3
"""Section list, section starter files and boundary conditions, all derived from SK_final.ly.

usage: python3 sections.py            writes sections/secN_*.ly and prints the boundary tables (markdown)
       python3 sections.py --spans    also prints keyboard spans per section (upper S+A, lower T+B)

Boundary conditions are read from the verified skeleton, so sections composed in parallel join
without parallels or leaps as long as every voice keeps its first attack and its last note.
"""
import os
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools'))
import fl  # noqa: E402
from lyparse import parse_voice  # noqa: E402

from piece import SECTIONS as _PIECE  # noqa: E402
from build_sk import offsets as _offsets  # noqa: E402

_OFF = _offsets()
# (number, first bar, last bar, slug, title), derived from piece.py so the starters always match SK_final.ly
SECTIONS = [(i + 1, _OFF[s['id']], _OFF[s['id']] + s['bars'] - 1, s['id'].split('_', 1)[1], s['title'])
            for i, s in enumerate(_PIECE)]
NAMES = {'soprano': 'S', 'alto': 'A', 'tenor': 'T', 'bass': 'B'}


def lily_name(n):
    return n.name  # e.g. Bb4


def pos(t):
    b = int(t) + 1
    return f"{b}:{float((t - (b - 1)) * 4 + 1):g}"


def load():
    src = open(os.path.join(HERE, 'SK_final.ly')).read()
    return {v: parse_voice(src, v) for v in fl.VOICES}


def sounding(notes, t):
    for n in notes:
        if n.start <= t < n.end:
            return n
    return None


def chord_name(pitches):
    try:
        from music21 import chord
        c = chord.Chord([p for p in pitches])
        return c.pitchedCommonName
    except Exception:
        return '?'


def m21(n):
    nm = n.name
    return nm[0] + nm[1:-1].replace('b', '-') + nm[-1]


def boundary(data, a, b):
    t0, t1 = F(a - 1), F(b)
    rows = []
    first_ch, last_ch = [], []
    for v in fl.VOICES:
        ns = data[v]
        n0 = sounding(ns, t0)
        if n0 is None or n0.midi is None:
            nxt = next((n for n in ns if n.start >= t0 and n.midi is not None and n.start < t1), None)
            f = f"rest (first note {nxt.name} at {pos(nxt.start)})" if nxt else "rest throughout"
        else:
            tied = n0.start < t0
            f = f"{n0.name}" + (" (tied in from the previous section)" if tied else "")
            first_ch.append(n0)
        inside = [n for n in ns if n.start < t1 and n.end > t0]
        last = inside[-1] if inside else None
        if last is None or last.midi is None:
            prev = [n for n in inside if n.midi is not None]
            l = "rest" + (f" (last note {prev[-1].name} at {pos(prev[-1].start)})" if prev else '')
        else:
            tie_out = last.end > t1
            held = (not tie_out) and last.end == t1 and last.dur >= F(1, 2)
            l = f"{last.name} at {pos(last.start)}" + (" (tied into the next section)" if tie_out else
                                                       " (held to the section end)" if held else '')
        rows.append((NAMES[v], f, l))
    # sonority at the first downbeat and at the last attack inside the section
    atk = sorted({n.start for v in fl.VOICES for n in data[v] if t0 <= n.start < t1 and n.midi is not None})
    tl = atk[-1] if atk else t0
    last_ch = [sounding(data[v], tl) for v in fl.VOICES]
    last_ch = [n for n in last_ch if n is not None and n.midi is not None]
    fc = sorted(first_ch, key=lambda n: n.midi)
    lc = sorted(last_ch, key=lambda n: n.midi)
    return rows, (fc, pos(t0)), (lc, pos(tl))


def spans(data, a, b):
    """max upper-staff (S-A) and lower-staff (T-B) span in semitones, sampled every 8th."""
    out = {'upper': (0, None), 'lower': (0, None)}
    t = F(a - 1)
    wide_lower = set()
    while t < F(b):
        s = {v: sounding(data[v], t) for v in fl.VOICES}
        for key, (hi, lo) in (('upper', ('soprano', 'alto')), ('lower', ('tenor', 'bass'))):
            x, y = s[hi], s[lo]
            if x is not None and y is not None and x.midi is not None and y.midi is not None:
                w = x.midi - y.midi
                if w > out[key][0]:
                    out[key] = (w, pos(t))
                if key == 'lower' and w > 14:
                    wide_lower.add(int(t) + 1)
        t += F(1, 8)
    return out, sorted(wide_lower)


def main():
    data = load()
    sk = fl.read(os.path.join(HERE, 'SK_final.ly'))
    os.makedirs(os.path.join(HERE, 'sections'), exist_ok=True)
    show_spans = '--spans' in sys.argv
    for num, a, b, slug, title in SECTIONS:
        path = os.path.join(HERE, 'sections', f"sec{num:02d}_{slug}.ly")
        win = fl.window(sk, a, b)
        fl.write(path, win, f"bars {a}-{b}\nSection {num}: {title}. Starter = the verified skeleton; enrich per BLUEPRINT.md\n"
                            f"and verify with: python3 ../splice_check.py sec{num:02d}_{slug}.ly", first_bar=a)
        rows, (fc, fp), (lc, lp) = boundary(data, a, b)
        print(f"\n#### Section {num} boundary (bars {a}-{b})\n")
        print("| voice | first attack at %d:1 | last note |" % a)
        print("|---|---|---|")
        for r in rows:
            print(f"| {r[0]} | {r[1]} | {r[2]} |")
        print(f"\nFirst sonority ({fp}): {' '.join(n.name for n in fc)} = {chord_name([m21(n) for n in fc])}.  "
              f"Last sonority ({lp}): {' '.join(n.name for n in lc)} = {chord_name([m21(n) for n in lc])}.")
        if show_spans:
            sp, wide = spans(data, a, b)
            print(f"Spans: upper staff max {sp['upper'][0]} semitones at {sp['upper'][1]}; lower staff max "
                  f"{sp['lower'][0]} at {sp['lower'][1]}; bars with lower staff wider than a 9th+: {wide}")


if __name__ == '__main__':
    main()
