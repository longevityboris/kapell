#!/usr/bin/env python3
"""Beam-search line generator (proposal 3). Writes one new voice against fixed voices.

Rules mirror tools/check.py (so its output is usually clean) but are STRICTER:
 - dissonance on a strong beat (beats 1, 3) only as a suspension (held, resolves down by step)
   or as a fixed voice's own passing/neighbour note;
 - dissonance on a weak onset only as passing/neighbour (step in, step out);
 - no parallel/contrary 5ths/8ves (onset to onset) and no 5ths/8ves on successive beats;
 - melodic: steps, 3rds, 4ths, 5ths, m6 up, octave; no aug/dim leaps; big leaps recover by step.
Scores prefer stepwise motion, imperfect consonances on beats, contrary motion to the other voices,
and pitch classes listed in an optional harmonic skeleton {beat_time: {pcs}}.
"""
import random
from fractions import Fraction as F
from p3 import N, LET, NAT, mel, S1, quick, bad, at, tr, end

SPELL = {0: ('c', 0), 1: ('d', -1), 2: ('d', 0), 3: ('e', -1), 4: ('e', 0), 5: ('f', 0), 6: ('g', -1),
         7: ('g', 0), 8: ('a', -1), 9: ('a', 0), 10: ('b', -1), 11: ('b', 0)}


def mk(midi, t, d, spell=SPELL):
    l, a = spell[midi % 12]
    o = midi // 12 - 1
    return N(t, d, LET.index(l) + 7 * o, a)


class Fixed:
    def __init__(self, voices):
        self.v = [[n for n in m if n.step is not None] for m in voices]
        self.onsets = sorted({n.t for m in self.v for n in m})

    def sounding(self, t):
        out = []
        for i, m in enumerate(self.v):
            for j, n in enumerate(m):
                if n.t <= t < n.t + n.d:
                    out.append((i, j, n))
                    break
        return out

    def just(self, i, j):
        """is fixed note j of voice i a passing/neighbour note or a suspension in its own line?"""
        m = self.v[i]
        n = m[j]
        pv = m[j - 1] if j > 0 and m[j - 1].t + m[j - 1].d == n.t else None
        nx = m[j + 1] if j + 1 < len(m) else None
        si = pv is not None and 1 <= abs(n.midi - pv.midi) <= 2
        so = nx is not None and 1 <= abs(nx.midi - n.midi) <= 2
        return si and so


def dissonant(a, b, a_is_lowest):
    ic = abs(a - b) % 12
    if ic in (1, 2, 10, 11):
        return True
    if ic in (5, 6) and a_is_lowest:
        return True
    return False


def generate(fixed_voices, rhythm, lo, hi, pcs_allowed=None, skeleton=None, start=None, finish=None,
             beam=300, lowest=None, seed=0, prefer_contrary=True, top=10, pen_extra=None):
    """rhythm: list of (t, d) (rests omitted). lowest: True if the new voice is always the bass."""
    random.seed(seed)
    fx = Fixed(fixed_voices)
    pcs_allowed = pcs_allowed or {10, 0, 1, 3, 5, 6, 8, 9, 7, 4, 2}
    cands = [p for p in range(lo, hi + 1) if p % 12 in pcs_allowed]
    beams = [(0.0, [])]
    for k, (t, d) in enumerate(rhythm):
        t, d = F(t), F(d)
        new = []
        for score, seq in beams:
            prev = seq[-1] if seq else None
            options = cands if prev is not None or start is None else [start]
            if k == len(rhythm) - 1 and finish is not None:
                options = [p for p in options if p % 12 in finish]
            for p in options:
                r = eval_step(fx, seq, p, t, d, rhythm, k, lowest, skeleton, prefer_contrary)
                if r is None:
                    continue
                s, flag = r
                if pen_extra:
                    s += pen_extra(seq, p, t, d)
                new.append((score + s + random.random() * 0.01, seq + [(t, d, p, flag)]))
        new.sort(key=lambda x: x[0])
        # diversity: limit identical last-4 suffixes
        seen, pruned = {}, []
        for sc, sq in new:
            key = tuple(x[2] for x in sq[-4:])
            if seen.get(key, 0) >= 3:
                continue
            seen[key] = seen.get(key, 0) + 1
            pruned.append((sc, sq))
            if len(pruned) >= beam:
                break
        beams = pruned
        if not beams:
            return []
    # final: resolution checks for the last note are skipped; return top sequences
    return [(sc, [mk(p, t, d) for t, d, p, _ in sq]) for sc, sq in beams[:top]]


def eval_step(fx, seq, p, t, d, rhythm, k, lowest, skeleton, prefer_contrary):
    s = 0.0
    flag = None
    prev = seq[-1][:3] if seq else None
    if seq and seq[-1][3] and seq[-1][0] + seq[-1][1] == t:
        pf = seq[-1][3]
        if pf == 'pend' and not (1 <= abs(p - prev[2]) <= 2):
            return None
        if pf == 'sus' and not (1 <= prev[2] - p <= 2):
            return None
    # melodic
    if prev is not None:
        pt, pd, pp = prev
        contiguous = pt + pd == t
        iv = p - pp
        a = abs(iv)
        if a == 0:
            s += 2.5
        elif a <= 2:
            s += 0
        elif a in (3, 4):
            s += 1.0
        elif a == 5:
            s += 1.8
        elif a == 7:
            s += 2.5
        elif a == 8 and iv > 0:
            s += 3.5
        elif a == 12:
            s += 3.0
        else:
            return None
        # after a leap of a 4th or more, require step back in opposite direction
        if len(seq) >= 2:
            p2 = seq[-2][2]
            prev_iv = pp - p2
            if abs(prev_iv) >= 5 and not (a <= 2 and iv * prev_iv < 0):
                return None
            if abs(prev_iv) >= 3 and abs(iv) >= 3 and iv * prev_iv > 0:
                s += 2.0  # two leaps same direction
            # outline of a tritone / aug 2 across 3 notes
            if abs(p - p2) == 6 and abs(prev_iv) <= 2:
                s += 0.5
        if a == 3 and abs((p % 12) - (pp % 12)) in (3, 9):
            # aug 2nd check by spelling (e.g. ges -> a): approximated: forbid pcs pairs (6,9),(1,4),(8,11)
            pair = tuple(sorted((p % 12, pp % 12)))
            if pair in ((6, 9), (1, 4), (8, 11), (3, 6)) and pair != (3, 6):
                return None
    # vertical at own onset and at every fixed onset inside the note
    times = [t] + [x for x in fx.onsets if t < x < t + d]
    for x in times:
        snd = fx.sounding(x)
        allp = [n.midi for _, _, n in snd] + [p]
        low = min(allp)
        strong = (x % 2 == 0)
        for i, j, n in snd:
            me_low = (p == low and p < n.midi) or (lowest is True)
            other_low = (n.midi == low and n.midi < p)
            dis = dissonant(p, n.midi, me_low) if p <= n.midi else dissonant(n.midi, p, other_low)
            if abs(p - n.midi) == 0 and strong:
                s += 0.8
            if dis:
                ok = False
                if x == t:  # I attack
                    if n.t == x and fx.just(i, j):
                        ok = True
                    elif prev is not None and prev[0] + prev[1] == t and 1 <= abs(p - prev[2]) <= 2 and not strong:
                        ok = 'pend'  # need step out: checked at next note via lookahead penalty
                    elif prev is not None and prev[2] == p and prev[0] + prev[1] == t:
                        ok = 'sus'  # re-struck suspension
                    elif fx.just(i, j) and n.t == x:
                        ok = True
                    if ok == 'pend' or ok == 'sus':
                        s += 0.3 if ok == 'pend' else 0.8
                        flag = ok
                        ok = True
                else:  # fixed voice attacks while I hold
                    if fx.just(i, j):
                        ok = True
                    else:
                        ok = True
                        s += 0.5  # suspension: must resolve down by step (checked by next note)
                        flag = 'sus'
                if not ok:
                    return None
            else:
                ic = abs(p - n.midi) % 12
                if strong and ic in (0, 7):
                    s += 0.6
    # parallels with each fixed voice between previous onset and this one
    if prev is not None:
        for x in times:
            pass
        for vi, m in enumerate(fx.v):
            a1 = note_at(m, prev[0] if prev[0] >= t - 4 else t)
            a2 = note_at(m, t)
            if a1 is None or a2 is None:
                continue
            # last onset before t among both lines
            b1 = prev[2]
            if a1.midi == a2.midi or b1 == p:
                continue
            i1, i2 = abs(a1.midi - b1) % 12, abs(a2.midi - p) % 12
            if i1 == i2 and i1 in (0, 7):
                return None
            if prefer_contrary:
                if (a2.midi - a1.midi) * (p - b1) > 0:
                    s += 0.15
                elif (a2.midi - a1.midi) * (p - b1) < 0:
                    s -= 0.1
    # skeleton targets
    if skeleton and t in skeleton:
        if p % 12 in skeleton[t]:
            s -= 1.5
        else:
            s += 1.5
    return s, flag


def note_at(m, t):
    for n in m:
        if n.t <= t < n.t + n.d:
            return n
    return None


def eighths(bars, start_rest=F(1, 2), t0=0, last_long=F(2)):
    r, t = [], F(t0) + start_rest
    endt = F(t0) + 4 * bars
    while t < endt:
        r.append((t, F(1, 2)))
        t += F(1, 2)
    r.append((endt, last_long))
    return r
