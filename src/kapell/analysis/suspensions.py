"""Count real prepared suspensions: preparation, dissonance, resolution (from final-lab/suspensions.py).

count(path, voices=None, bars=None, measure=None, src=None) -> {strong, weak, items}

A suspension is counted at a strong beat t (beat 1 or 3 in 4/4, beat 1 otherwise) when
  PREPARATION  a voice holds (or re-strikes at t) a note N that was consonant with every voice
               sounding when N was attacked (4ths above the lowest voice count as dissonant);
  AGENT        another voice attacks at t, and N against the agent forms a suspension interval:
               N above the agent: 7th (7-6), 9th (9-8, compound only) or 4th (4-3, agent = lowest voice);
               N below the agent: 2nd or 9th (2-3) or 4th (4-5, N = lowest voice);
  RESOLUTION   N's next different note is a step down, comes while the agent still sounds, and is
               consonant with it.
The same figure on a weak beat (agent at least a quarter long) is listed as weak and not counted.
items: [{pos, voice, from, to, kind, against, agent, strong, line}]
"""
from fractions import Fraction as F

from kapell.analysis import parse_bars, parse_measure, parse_voices, read_source
from kapell.analysis.lyparse import parse_voice

CONS = {0, 3, 4, 7, 8, 9}


def count(path=None, voices=None, bars=None, measure=None, src=None):
    src = read_source(path, src)
    V = parse_voices(voices)
    measure = parse_measure(measure)
    bars = parse_bars(bars)
    data = {v: [n for n in (parse_voice(src, v, measure) or []) if n.midi is not None] for v in V}
    index = {v: {id(n): i for i, n in enumerate(data[v])} for v in V}

    def snd(v, t):
        for n in data[v]:
            if n.start <= t < n.end:
                return n
        return None

    def consonant_at(n, t):
        s = [snd(w, t) for w in V]
        s = [m for m in s if m is not None and m is not n]
        if not s:
            return True
        low = min([m.midi for m in s] + [n.midi])
        for m in s:
            iv = abs(n.midi - m.midi) % 12
            if iv not in CONS and not (iv == 5 and min(n.midi, m.midi) != low):
                return False
            if iv == 5 and min(n.midi, m.midi) == low:
                return False
        return True

    items, seen = [], set()
    times = sorted({n.start for v in V for n in data[v]})
    for t in times:
        bar = int(t / measure) + 1
        if bars and not bars[0] <= bar <= bars[1]:
            continue
        beat = (t - (bar - 1) * measure) * 4
        if beat != int(beat):
            continue
        strong = int(beat) in ((0, 2) if measure == 1 else (0,))
        sounding_now = [snd(w, t) for w in V]
        lowest = min((m.midi for m in sounding_now if m is not None), default=None)
        for v in V:
            n = snd(v, t)
            if n is None:
                continue
            i = index[v][id(n)]
            prep = None
            if n.start < t:
                prep = n
            elif i > 0 and data[v][i - 1].midi == n.midi and data[v][i - 1].end == t:
                prep = data[v][i - 1]  # re-struck suspension
            if prep is None:
                continue
            j = i + 1  # skip same-pitch re-strikes
            while j < len(data[v]) and data[v][j].midi == n.midi and data[v][j].start == data[v][j - 1].end:
                j += 1
            nx = data[v][j] if j < len(data[v]) else None
            if nx is None or not (1 <= n.midi - nx.midi <= 2):
                continue
            k = index[v][id(prep)]
            while k > 0 and data[v][k - 1].midi == n.midi and data[v][k - 1].end == data[v][k].start:
                k -= 1
            prep = data[v][k]
            if not consonant_at(prep, prep.start):
                continue
            found = None
            for w in V:
                if w == v:
                    continue
                ag = snd(w, t)
                if ag is None or ag.start != t:
                    continue
                if not strong and ag.dur < F(1, 4):
                    continue
                d = n.midi - ag.midi
                ic = abs(d) % 12
                if d > 0:
                    kind = {10: '7-6', 11: '7-6', 5: '4-3', 1: '9-8', 2: '9-8'}.get(ic)
                    if kind == '9-8' and d < 12:
                        kind = None
                else:
                    kind = {1: '2-3', 2: '2-3', 5: '4-5'}.get(ic)
                if kind == '4-3' and ag.midi != lowest:
                    kind = None
                if kind == '4-5' and n.midi != lowest:
                    kind = None
                if not kind:
                    continue
                ag_now = snd(w, nx.start)
                if ag_now is None or ag_now.midi != ag.midi:
                    continue
                if abs(nx.midi - ag.midi) % 12 not in CONS:
                    continue
                found = (w, ag, kind)
                break
            if not found or (v, nx.start) in seen:
                continue
            seen.add((v, nx.start))
            w, ag, kind = found
            pos = f"{bar}:{float(beat + 1):g}"
            items.append(dict(pos=pos, voice=v, **{'from': n.name}, to=nx.name, kind=kind, against=w,
                              agent=ag.name, strong=bool(strong),
                              line=f"{pos} {v} {n.name}->{nx.name} ({kind} against {w} {ag.name})"))
    strong_items = [x for x in items if x['strong']]
    return {'strong': len(strong_items), 'weak': len(items) - len(strong_items), 'items': items}


def lines(result, verbose=False):
    """The original script's text output."""
    out = []
    if verbose:
        out += [x['line'] for x in result['items'] if x['strong']]
        weak = [x['line'] for x in result['items'] if not x['strong']]
        if weak:
            out.append("weak-beat (not counted): " + "; ".join(weak))
    out.append(f"prepared suspensions: {result['strong']}")
    out.append(f"weak-beat suspensions (not counted): {result['weak']}")
    return out
