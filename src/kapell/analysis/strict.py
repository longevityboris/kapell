"""Strict second opinion on top of check (from final-lab/strict.py).

run(path, voices=None, bars=None, measure=None, src=None) -> {clash, xrel, acc, acc2, items}

check accepts any dissonance whose note moves by step as "PT/NT", even on beats 1 and 3 and even
when both notes are struck together. This flags what a strict ear would question:
  CLASH  two notes a chromatic semitone apart on the same letter sounding together (always wrong)
  XREL   cross relation within a quarter between two voices (for review)
  ACC    dissonance on beat 1 or 3 that is not a prepared suspension/retardation (for review)
  ACC2   as ACC but both notes struck together (stronger)
items: [{kind, pos, line}]
"""
from fractions import Fraction as F

from kapell.analysis import parse_bars, parse_measure, parse_voices, read_source
from kapell.analysis.lyparse import parse_voice


def run(path=None, voices=None, bars=None, measure=None, src=None):
    src = read_source(path, src)
    measure = parse_measure(measure)
    bars = parse_bars(bars)
    data = {}
    for v in parse_voices(voices):
        n = parse_voice(src, v, measure)
        if n:
            data[v] = [x for x in n if x.midi is not None]
    index = {v: {id(x): i for i, x in enumerate(data[v])} for v in data}

    def at(v, t):
        for x in data[v]:
            if x.start <= t < x.end:
                return x
        return None

    def pos(t):
        b = int(t / measure) + 1
        return f"{b}:{float((t - (b - 1) * measure) * 4 + 1):g}"

    def inbars(t):
        return bars is None or bars[0] <= int(t / measure) + 1 <= bars[1]

    times = sorted({x.start for v in data for x in data[v]})
    out = []
    cnt = dict(clash=0, xrel=0, acc=0, acc2=0)

    def add(kind, t, line):
        cnt[kind] += 1
        out.append(dict(kind=kind.upper(), pos=pos(t), line=line))

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
                if a.name[0] == b.name[0] and (a.midi - b.midi) % 12 != 0:
                    add('clash', t, f"CLASH {pos(t)} {vs[i]} {a.name} / {vs[j]} {b.name}")
                iv = abs(a.midi - b.midi) % 12
                lower = a if a.midi < b.midi else b
                dis = iv in (1, 2, 10, 11) or (iv in (5, 6) and lower.midi == low)
                if not (dis and strong):
                    continue
                ok = False
                for v, x in ((vs[i], a), (vs[j], b)):
                    k = index[v][id(x)]
                    notes = data[v]
                    if x.start < t:
                        nx = notes[k + 1] if k + 1 < len(notes) else None
                        nx2 = notes[k + 2] if k + 2 < len(notes) else None
                        if nx is not None and 1 <= abs(nx.midi - x.midi) <= 2:
                            ok = True
                        elif (nx is not None and nx.midi == x.midi and nx.start == x.end and nx2 is not None
                              and 1 <= x.midi - nx2.midi <= 2):
                            ok = True  # held, re-struck, then resolves down by step
                    elif x.start == t:
                        pv = notes[k - 1] if k > 0 else None
                        nx = notes[k + 1] if k + 1 < len(notes) else None
                        if (pv is not None and pv.midi == x.midi and pv.end == t and nx is not None
                                and 1 <= x.midi - nx.midi <= 2):
                            ok = True  # re-struck suspension
                if ok:
                    continue
                key = 'acc2' if a.start == t and b.start == t else 'acc'
                add(key, t, f"{key.upper():5} {pos(t)} {vs[i]} {a.name} / {vs[j]} {b.name}")
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
                    if (y.name[0] == x.name[0] and (y.midi - x.midi) % 12 != 0 and y.start >= x.end - F(1, 4)
                            and (y.start >= x.end or y.start > x.start)):
                        add('xrel', x.start, f"XREL  {pos(x.start)}->{pos(y.start)} {v1} {x.name} then {v2} {y.name}")
    return {**cnt, 'items': out}


def lines(result, verbose=False):
    """The original script's text output (ACC lines only with verbose)."""
    out = [o['line'] for o in result['items'] if verbose or o['kind'] != 'ACC']
    out.append(f"strict: clash {result['clash']}, xrel {result['xrel']}, acc {result['acc']}, acc2 {result['acc2']}")
    return out
