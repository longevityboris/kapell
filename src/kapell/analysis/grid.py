"""Sonority grid: one row per eighth (or per attack) with pitches, chord name and flags (from final-lab/grid.py).

grid(path, voices=None, bars=None, step='1/8', attacks=False, src=None)
    -> [{pos, cells, names, chord, flags}]
rows(data, a=None, b=None, step=F(1, 8), attacks=False, voices=None)   the original row builder
cells: per voice pitch name, '.' prefix = held from before, '-' = rest.
flags: 'UNI' two voices on one MIDI pitch, 'HOL' four voices with at most two pitch classes,
'X' a voice crossing.
"""
from fractions import Fraction as F

from kapell.analysis import parse_bars, parse_voices, read_source
from kapell.analysis.lyparse import parse_voice


def load(path=None, voices=None, src=None):
    src = read_source(path, src)
    return {v: (parse_voice(src, v) or []) for v in parse_voices(voices)}


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


def rows(data, a=None, b=None, step=F(1, 8), attacks=False, voices=None):
    V = list(voices or data)
    end = max((n.end for v in V for n in data[v]), default=F(0))
    t0 = F(a - 1) if a else F(0)
    t1 = F(b) if b else end
    if attacks:
        times = sorted({n.start for v in V for n in data[v] if t0 <= n.start < t1 and n.midi is not None})
    else:
        times, t = [], t0
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
        for i in range(len(snd)):
            for j in range(i + 1, len(snd)):
                if snd[i][1].midi == snd[j][1].midi:
                    flags.append('UNI')
                if V.index(snd[i][0]) < V.index(snd[j][0]) and snd[i][1].midi < snd[j][1].midi:
                    flags.append('X')
        pcs = sorted({n.midi % 12 for _, n in snd})
        if len(snd) == 4 and len(pcs) <= 2:
            flags.append('HOL')
        names = [n.name for _, n in sorted(snd, key=lambda x: x[1].midi)]
        out.append((t, cells, names, chord_name(names) if names else '', sorted(set(flags))))
    return out


def grid(path=None, voices=None, bars=None, step='1/8', attacks=False, src=None):
    data = load(path, voices, src)
    ab = parse_bars(bars) or (None, None)
    return [dict(pos=pos(t), cells=cells, names=names, chord=ch, flags=flags)
            for t, cells, names, ch, flags in rows(data, ab[0], ab[1], F(step), attacks, list(data))]


def lines(result):
    """The original script's text output."""
    return [f"{r['pos']:>7}  " + ' '.join(f"{c:>5}" for c in r['cells']) + f"   {r['chord']}"
            + (f"   [{' '.join(r['flags'])}]" if r['flags'] else '') for r in result]
