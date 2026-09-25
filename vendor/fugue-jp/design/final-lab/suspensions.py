#!/usr/bin/env python3
"""Count real prepared suspensions: preparation, dissonance, resolution.

usage: python3 suspensions.py FILE.ly [-v]

A suspension is counted at a strong beat t (beat 1 or 3) when
  PREPARATION  a voice holds (or re-strikes at t) a note N that was consonant with every voice
               sounding when N was attacked (4ths above the lowest voice count as dissonant);
  AGENT        another voice attacks at t, and N against the agent forms a suspension interval:
               N above the agent: 7th (7-6), 9th (9-8, compound only) or 4th (4-3, agent = lowest voice);
               N below the agent: 2nd or 9th (2-3, the bass suspension) or 4th (4-5, N = lowest voice);
  RESOLUTION   N's next different note (same-pitch re-strikes are skipped) is a step down (1-2 semitones), comes while the agent's note still
               sounds, and is consonant with it (3rd, 6th, 8ve, 5th or unison class);
  DISSONANCE   N is actually dissonant at t (not a chord tone merely held under a moving voice).
Held chord tones (a bass root under a new seventh above it, a seventh held while the bass moves to
another chord member) are not counted: the agent test fails for them. The same figure on beat 2 or 4
(agent at least a quarter long) is listed separately as a weak-beat suspension and not counted.
"""
import os
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools'))
from lyparse import parse_voice  # noqa: E402

V = ['soprano', 'alto', 'tenor', 'bass']
CONS = {0, 3, 4, 7, 8, 9}


def main():
    src = open(sys.argv[1]).read()
    data = {v: [n for n in parse_voice(src, v) if n.midi is not None] for v in V}

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

    out, weak, count, seen = [], [], 0, set()
    times = sorted({n.start for v in V for n in data[v]})
    for t in times:
        beat = (t % 1) * 4
        if beat != int(beat):
            continue
        strong = int(beat) in (0, 2)
        sounding_now = [snd(w, t) for w in V]
        lowest = min((m.midi for m in sounding_now if m is not None), default=None)
        for v in V:
            n = snd(v, t)
            if n is None:
                continue
            i = data[v].index(n)
            prep = None
            if n.start < t:
                prep = n
            elif i > 0 and data[v][i - 1].midi == n.midi and data[v][i - 1].end == t:
                prep = data[v][i - 1]  # re-struck suspension
            if prep is None:
                continue
            # skip same-pitch re-strikes (pulsing accompaniments re-articulate a suspension)
            j = i + 1
            while j < len(data[v]) and data[v][j].midi == n.midi and data[v][j].start == data[v][j - 1].end:
                j += 1
            nx = data[v][j] if j < len(data[v]) else None
            if nx is None or not (1 <= n.midi - nx.midi <= 2):
                continue
            k = data[v].index(prep)
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
                # the resolution comes while the agent still sounds (otherwise N was a held chord
                # tone that moved with the harmony) and is consonant with it
                ag_now = snd(w, nx.start)
                if ag_now is None or ag_now.midi != ag.midi:
                    continue  # (a repeated agent note counts as still sounding)
                r = abs(nx.midi - ag.midi) % 12
                if r not in CONS:
                    continue
                found = (w, ag, kind)
                break
            if found and (v, nx.start) in seen:
                continue  # one suspension, re-articulated: count it once
            if found:
                seen.add((v, nx.start))
                b = int(t) + 1
                w, ag, kind = found
                line = f"{b}:{float((t - b + 1) * 4 + 1):g} {v} {n.name}->{nx.name} ({kind} against {w} {ag.name})"
                if strong:
                    count += 1
                    out.append(line)
                else:
                    weak.append(line)
    if '-v' in sys.argv:
        print("\n".join(out))
        if weak:
            print("weak-beat (not counted): " + "; ".join(weak))
    print(f"prepared suspensions: {count}")
    print(f"weak-beat suspensions (not counted): {len(weak)}")


if __name__ == '__main__':
    main()
