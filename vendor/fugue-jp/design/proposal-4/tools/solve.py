#!/usr/bin/env python3
"""Beam-search counterpoint solver: write ONE free voice against fixed voices.

The hard rules mirror ricercar/tools/check.py exactly (so every returned line is checker-clean
against the fixed voices: no PAR!, no BEAT, no DIS!, no D4?, no crossing), and a stricter musical
cost ranks the survivors (accented dissonance, leaps, repeated notes, chromatic colour, suspensions).

Optional: `invert=[voice,...]`: the free line must ALSO be clean when transposed by octaves to the
other side of that voice (two-voice double counterpoint at the octave: 4ths count as dissonant in
both placements, parallel 4ths are forbidden because they become 5ths).

Time unit = sixteenth note (int). Pitches are p4 tuples (letter, octave, alter).
"""
import itertools
import os
import sys
from fractions import Fraction as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p4 import ly, midi, dn, name, to_ly, length, fill, write_lab, check, summary, score, VOICES, RANGES  # noqa

Q = 16  # units per whole note


def to_units(ev):
    out, t = [], 0
    for p, d in ev:
        u = d * Q
        assert u.denominator == 1, ('duration not on 16th grid', d)
        u = int(u)
        out.append((t, t + u, p))
        t += u
    return out, t


class Fixed:
    """one fixed voice as a list of notes (start, end, midi, dn, pitch) incl. rests (midi None)"""

    def __init__(self, vname, ev):
        self.v = vname
        self.notes = []
        for s, e, p in to_units(ev)[0]:
            self.notes.append((s, e, midi(p) if p else None, dn(p) if p else None, p))
        self.total = self.notes[-1][1] if self.notes else 0
        self.idx = {}
        for i, (s, e, m, d, p) in enumerate(self.notes):
            for t in range(s, e):
                self.idx[t] = i

    def at(self, t):
        i = self.idx.get(t)
        if i is None or self.notes[i][2] is None:
            return None
        return i

    def tags(self, i, t):
        """check.py justification tags for fixed note i at time t (list, empty = none)"""
        N = self.notes
        s, e, m, d, p = N[i]
        pv = N[i - 1] if i > 0 and N[i - 1][2] is not None and N[i - 1][1] == s else None
        nx = N[i + 1] if i + 1 < len(N) and N[i + 1][2] is not None else None
        nx2 = N[i + 2] if i + 2 < len(N) else None
        return cp_tags(m, s, t, pv[2] if pv else None, nx[2] if nx else None,
                       nx2[2] if nx2 is not None else None)


def cp_tags(m, start, t, pvm, nxm, nx2m):
    si = pvm is not None and 1 <= abs(m - pvm) <= 2
    so = nxm is not None and 1 <= abs(nxm - m) <= 2
    held = start < t or (pvm is not None and pvm == m)
    restep = nxm is not None and nxm == m and nx2m is not None and 1 <= m - nx2m <= 2
    if si and so and start == t:
        return 'PT'
    if held and nxm is not None and nxm < m and so:
        return 'SUS'
    if held and nxm is not None and nxm == m + 1 and so:
        return 'RET'
    if start == t and so:
        return 'APP' if not si else 'APT'
    if held and restep:
        return 'SUSre'
    if start == t and nxm is not None and nxm == m and si:
        return 'ANT'
    if start == t and restep:
        return 'ANT7'
    if start == t and si and not so:
        return 'ESC'
    return None


DIS_ALWAYS = {1, 2, 10, 11}


class Solver:
    def __init__(self, fixed, free, total=None, palette='', lo=None, hi=None, patterns=None,
                 bar_patterns=None, invert=(), start_pitch=None, end_pcs=None, measure=4,
                 width=4000, keep=12, w=None, first_rest_ok=True, forbid_first_attack=False,
                 max_leap=9, weights=None, verbose=False, end_pitch=None, key_pcs=None,
                 must=None, max_same=1, invert_from=0, invert_until=10**9, inner=40, bass_like=(), still_pen=(8, 1.0, 12, 2.0), sigh_bonus=0.0, min_span=0):
        self.fixed = [Fixed(v, ev) for v, ev in fixed.items()]
        self.free = free
        self.total = total or max(f.total for f in self.fixed)
        self.order = VOICES.index(free)
        self.above = [f for f in self.fixed if VOICES.index(f.v) < self.order]
        self.below = [f for f in self.fixed if VOICES.index(f.v) > self.order]
        self.pal = [ly(x + '4')[0][0] for x in palette.split()]
        rlo, rhi = RANGES[free]
        self.lo, self.hi = lo or rlo, hi or rhi
        self.pal = [p for p in self.pal if self.lo <= midi(p) <= self.hi]
        self.key_pcs = key_pcs
        self.measure = measure  # quarters per bar
        self.patterns = [self.parse_pat(x) for x in (patterns or ['4 4 4 4'])]
        self.bar_patterns = {k: [self.parse_pat(x) for x in v] for k, v in (bar_patterns or {}).items()}
        self.invert = [f for f in self.fixed if f.v in invert]
        self.start_pitch = ly(start_pitch + '4')[0][0] if start_pitch else None
        self.end_pitch = ly(end_pitch + '4')[0][0] if end_pitch else None
        self.end_pcs = end_pcs
        self.width, self.keep = width, keep
        self.max_leap = max_leap
        self.W = dict(pt_strong=2.0, app=3.0, esc=4.0, ant=2.5, ret=1.5, sus_bonus=-2.5,
                      rep=2.5, leap3=0.6, leap4=1.2, leap5=2.0, leap6=3.0, leap8=4.0,
                      unrecovered=2.0, chrom=0.8, chrom_step=-0.3, perfect_strong=0.7,
                      unison=3.0, sim_attack=0.25, par_imperf=0.8, dir=6.0, span=0.3,
                      same_dir=0.8, still=0.0)
        if weights:
            self.W.update(weights)
        self.verbose = verbose
        self.must = must or {}
        # precompute slot starts of fixed voices
        self.fixed_onsets = sorted({n[0] for f in self.fixed for n in f.notes})
        self.max_same = max_same
        self.inv_lo, self.inv_hi = invert_from, invert_until
        self.inner = inner
        self.bass_like = set(bass_like)
        self.still_pen = still_pen
        self.sigh_bonus = sigh_bonus
        self.min_span = min_span

    # --- patterns: tokens in 16ths; 't' prefix = tie continuation of previous note; 'r' = rest
    def parse_pat(self, s):
        out = []
        for tok in s.split():
            kind = 'n'
            if tok[0] == 't':
                kind, tok = 't', tok[1:]
            elif tok[0] == 'r':
                kind, tok = 'r', tok[1:]
            out.append((kind, int(tok)))
        assert sum(d for _, d in out) == self.measure * 4, s
        return out

    # --- vertical evaluation of free note (s, e, m, pitch) given prev / next free notes
    def lowest_at(self, t, fm):
        ms = [f.notes[f.at(t)][2] for f in self.fixed if f.at(t) is not None]
        if fm is not None:
            ms.append(fm)
        return min(ms) if ms else None

    def eval_note(self, k, notes):
        """hard-check + cost for free note k (needs notes[k-1], notes[k+1] if they exist).
        returns (ok, cost)"""
        s, e, m, p = notes[k]
        if m is None:
            return True, 0.0
        pv = notes[k - 1] if k > 0 and notes[k - 1][2] is not None and notes[k - 1][1] == s else None
        nx = notes[k + 1] if k + 1 < len(notes) and notes[k + 1][2] is not None else None
        nx2 = notes[k + 2] if k + 2 < len(notes) else None
        pvm = pv[2] if pv else None
        nxm = nx[2] if nx else None
        nx2m = nx2[2] if nx2 is not None else None
        cost = 0.0
        d_ = e - s
        if d_ >= self.still_pen[2]:
            cost += self.still_pen[3]
        elif d_ >= self.still_pen[0]:
            cost += self.still_pen[1]
        # time points inside the note where something attacks
        pts = [s] + [t for t in self.fixed_onsets if s < t < e]
        for t in pts:
            strong = (t % 8) == 0
            for f in self.fixed:
                i = f.at(t)
                if i is None:
                    continue
                fs, fe, fm, fd, fp = f.notes[i]
                if fs != t and s != t:
                    continue
                iv = abs(m - fm) % 12
                low = min(m, fm)
                lw = self.lowest_at(t, m)
                dis = iv in DIS_ALWAYS or (iv in (5, 6) and (low == lw or (f.v in self.bass_like and fm < m)))
                inv_dis = False
                if f in self.invert and self.inv_lo <= t < self.inv_hi:
                    ivi = (12 - iv) % 12
                    inv_dis = ivi in DIS_ALWAYS or ivi in (5, 6) or iv in (5, 6)
                if not (dis or inv_dis):
                    if strong and s == t and iv in (0, 7):
                        cost += self.W['perfect_strong']
                    if iv == 0 and m == fm:
                        cost += self.W['unison']
                    continue
                mt = cp_tags(m, s, t, pvm, nxm, nx2m)
                ft = f.tags(i, t)
                if dis and not (mt or ft):
                    return False, 0
                if inv_dis and not mt and not ft:
                    return False, 0
                # musical cost of the justification actually used (prefer the fixed voice's own)
                tag = mt if not ft else (ft if not mt else (mt if mt in ('PT', 'SUS') else ft))
                if tag == 'PT':
                    cost += self.W['pt_strong'] if strong else 0.0
                elif tag in ('SUS', 'SUSre'):
                    if s < t or (pvm == m):
                        cost += self.W['sus_bonus'] if strong else 0.3
                    else:
                        cost += 1.0
                elif tag in ('APP', 'APT'):
                    cost += self.W['app'] if tag == 'APP' else self.W['app'] * 0.7
                    if tag == mt and strong and s == t and nxm is not None and 1 <= m - nxm <= 2:
                        cost -= self.sigh_bonus
                elif tag == 'ESC':
                    cost += self.W['esc']
                elif tag in ('ANT', 'ANT7'):
                    cost += self.W['ant']
                elif tag == 'RET':
                    cost += self.W['ret']
            # simultaneous attacks (rhythmic independence)
            if s == t and t % 16 != 0:
                for f in self.fixed:
                    i = f.at(t)
                    if i is not None and f.notes[i][0] == t:
                        cost += self.W['sim_attack']
        return True, cost

    def pair_parallels(self, notes, k):
        """parallels between free note k (just completed with its predecessor k-1) and fixed voices;
        uses check.py's pairwise timeline and beat-to-beat rule, evaluated for times up to notes[k] end"""
        s, e, m, p = notes[k]
        for f in self.fixed:
            # union onsets of this pair within [start of k-1 .. e)
            s0 = notes[k - 1][0] if k > 0 else s
            tl = sorted({n[0] for n in notes if n[0] >= s0 and n[0] < e} |
                        {n[0] for n in f.notes if s0 <= n[0] < e})
            prevs = [t for t in tl if t >= s0]
            for t1, t2 in zip(prevs, prevs[1:]):
                if t2 < s:
                    continue
                a1, a2 = self.free_at(notes, t1), self.free_at(notes, t2)
                b1i, b2i = f.at(t1), f.at(t2)
                if a1 is None or a2 is None or b1i is None or b2i is None:
                    continue
                b1, b2 = f.notes[b1i][2], f.notes[b2i][2]
                if a1 == a2 or b1 == b2:
                    continue
                i1, i2 = abs(a1 - b1) % 12, abs(a2 - b2) % 12
                if i1 == i2 and i1 in (0, 7):
                    return False
                if f in self.invert and i1 == i2 and i1 == 5 and t2 >= self.inv_lo and t2 < self.inv_hi:
                    return False
            # beat to beat (check.py BEAT)
            for t2 in range(((s + 3) // 4) * 4, e, 4):
                t1 = t2 - 4
                if t1 < 0:
                    continue
                a1, a2 = self.free_at(notes, t1), self.free_at(notes, t2)
                b1i, b2i = f.at(t1), f.at(t2)
                if a1 is None or a2 is None or b1i is None or b2i is None:
                    continue
                b1, b2 = f.notes[b1i][2], f.notes[b2i][2]
                if a1 == a2 or b1 == b2:
                    continue
                fa = self.free_start_at(notes, t2)
                if fa != t2 and f.notes[b2i][0] != t2:
                    continue
                i1, i2 = abs(a1 - b1) % 12, abs(a2 - b2) % 12
                if i1 == i2 and i1 in (0, 7):
                    return False
                if f in self.invert and i1 == i2 and i1 == 5 and t2 >= self.inv_lo and t2 < self.inv_hi:
                    return False
        return True

    @staticmethod
    def free_at(notes, t):
        for s, e, m, p in reversed(notes):
            if s <= t < e:
                return m
            if e <= t:
                return None
        return None

    @staticmethod
    def free_start_at(notes, t):
        for s, e, m, p in reversed(notes):
            if s <= t < e:
                return s
        return None

    def crossing_ok(self, s, e, m):
        for t in range(s, e):
            for f in self.above:
                i = f.at(t)
                if i is not None and f.notes[i][2] < m:
                    return False
            for f in self.below:
                i = f.at(t)
                if i is not None and f.notes[i][2] > m:
                    return False
        return True

    def melodic(self, a, b):
        """cost of melodic step a->b (tuples) or None if forbidden"""
        if a is None or b is None:
            return 0.0
        sm, st = midi(b) - midi(a), dn(b) - dn(a)
        s, stp = abs(sm), abs(st)
        if (stp == 1 and s == 3) or (stp == 3 and s == 6) or (stp == 4 and s == 6) or \
           (stp == 3 and s == 4) or stp == 6 or s > 12 or (stp == 4 and s == 8) or (stp == 2 and s == 2) \
                or (stp == 0 and s > 1) or (stp == 1 and s == 0) or (stp == 2 and s == 5):
            return None
        if s > self.max_leap and s != 12:
            return None
        if s == 0:
            return self.W['rep']
        if s <= 2:
            return 0.0
        return {3: self.W['leap3'], 4: self.W['leap3'], 5: self.W['leap4'], 7: self.W['leap5'],
                8: self.W['leap6'] + (0 if sm > 0 else 1.5), 9: self.W['leap6'] + 1, 12: self.W['leap8']}.get(s, 9)

    def pc_cost(self, p, prev):
        if self.key_pcs is None:
            return 0.0
        m = midi(p)
        if m % 12 in self.key_pcs:
            return 0.0
        if prev is not None and abs(midi(prev) - m) == 1:
            return self.W['chrom'] + self.W['chrom_step']
        return self.W['chrom'] * 2

    def solve(self):
        bars = self.total // (self.measure * 4)
        # state: (cost, notes list [(s,e,m,p)], pending eval index)
        beam = [(0.0, [], 0)]
        for b in range(bars):
            pats = self.bar_patterns.get(b + 1, self.patterns)
            new = []
            for cost, notes, _ in beam:
                for pat in pats:
                    new.extend(self.expand_bar(cost, notes, pat, b))
            new.sort(key=lambda x: x[0])
            # dedupe identical note sequences
            seen, beam = set(), []
            for c, ns, x in new:
                key = tuple((n[0], n[2]) for n in ns)
                if key in seen:
                    continue
                seen.add(key)
                beam.append((c, ns, x))
                if len(beam) >= self.width:
                    break
            if self.verbose:
                print(f'bar {b + 1}: {len(new)} expansions, best {beam[0][0] if beam else None}', file=sys.stderr)
            if not beam:
                return []
        # finalize last note evaluation
        final = []
        for cost, notes, _ in beam:
            ok, c = self.eval_note(len(notes) - 1, notes)
            if not ok:
                continue
            last = [n for n in notes if n[2] is not None][-1]
            if self.end_pcs is not None and last[2] % 12 not in self.end_pcs:
                continue
            if self.end_pitch is not None and last[3] != self.end_pitch:
                continue
            final.append((cost + c + self.global_cost(notes), notes))
        final.sort(key=lambda x: x[0])
        return final[:self.keep]

    def global_cost(self, notes):
        ms = [n[2] for n in notes if n[2] is not None]
        if not ms:
            return 0
        span = max(ms) - min(ms)
        c = self.W['span'] * max(0, span - 12) + 1.5 * max(0, self.min_span - span)
        # single climax bonus
        if ms.count(max(ms)) == 1:
            c -= 1.0
        return c

    def expand_bar(self, cost, notes, pat, b):
        """expand one bar with pattern pat; yields (cost, notes, 0)"""
        t0 = b * self.measure * 4
        results = [(cost, list(notes))]
        t = t0
        for kind, d in pat:
            nxt = []
            for c, ns in results:
                if kind == 'r':
                    ns2 = ns + [(t, t + d, None, None)]
                    # evaluate previous note (its 'next' is a rest)
                    if len(ns) >= 1:
                        ok, cc = self.eval_note(len(ns) - 1, ns2)
                        if not ok:
                            continue
                        c2 = c + cc
                    else:
                        c2 = c
                    nxt.append((c2, ns2))
                    continue
                if kind == 't':
                    if not ns or ns[-1][2] is None or ns[-1][1] != t:
                        continue
                    ps, pe, pm, pp = ns[-1]
                    if not self.crossing_ok(pe, t + d, pm):
                        continue
                    ns2 = ns[:-1] + [(ps, t + d, pm, pp)]
                    nxt.append((c, ns2))
                    continue
                # new pitch
                prev = ns[-1][3] if ns and ns[-1][2] is not None and ns[-1][1] == t else None
                cands = self.pal
                if not ns and self.start_pitch is not None:
                    cands = [self.start_pitch]
                if t in self.must:
                    cands = [ly(self.must[t] + '4')[0][0]]
                for p in cands:
                    m = midi(p)
                    mc = self.melodic(prev, p) if prev is not None else 0.0
                    if mc is None:
                        continue
                    if not self.crossing_ok(t, t + d, m):
                        continue
                    ns2 = ns + [(t, t + d, m, p)]
                    c2 = c + mc + self.pc_cost(p, prev)
                    # leap recovery / direction
                    if len(ns) >= 2 and ns[-2][2] is not None and prev is not None:
                        a0, a1 = ns[-2][2], ns[-1][2]
                        l1, l2 = a1 - a0, m - a1
                        if abs(l1) >= 5 and not (l2 * l1 < 0 and abs(l2) <= 2):
                            c2 += self.W['unrecovered']
                        if abs(l1) >= 3 and abs(l2) >= 3 and l1 * l2 > 0:
                            c2 += self.W['same_dir'] * 2
                            if abs(l1 + l2) > 12:
                                continue
                    # repeated pitch count
                    if prev is not None and midi(prev) == m and len(ns) >= 2 and ns[-2][2] == m:
                        continue
                    # evaluate previous note now that its successor is known
                    if len(ns) >= 1 and ns[-1][2] is not None:
                        ok, cc = self.eval_note(len(ns) - 1, ns2)
                        if not ok:
                            continue
                        if not self.pair_parallels(ns2, len(ns2) - 1):
                            continue
                        c2 += cc
                    elif len(ns) >= 2 and ns[-1][2] is None:
                        pass
                    nxt.append((c2, ns2))
            # prune within-bar to keep it tractable
            nxt.sort(key=lambda x: x[0])
            results = nxt[:self.inner]
            t += d
        # pending: a note whose successor unknown remains; also check the last note's parallels
        out = []
        for c, ns in results:
            if ns and ns[-1][2] is not None and not self.pair_parallels(ns, len(ns) - 1):
                continue
            # evaluate the second-to-last note (its successor is the last note) already done;
            out.append((c, ns, 0))
        return out


def notes_to_events(notes, total):
    ev, t = [], 0
    for s, e, m, p in notes:
        if s > t:
            ev.append((None, F(s - t, Q)))
        ev.append((p, F(e - s, Q)))
        t = e
    if t < total:
        ev.append((None, F(total - t, Q)))
    return ev


def show(sol, total, measure=F(1)):
    return ' '.join(to_ly(notes_to_events(sol, total), measure))


def run_and_check(fixed, free_name, sol_events, fname, title='', comment='', bars=None, grid=False):
    vs = dict(fixed)
    vs[free_name] = sol_events
    path = write_lab(fname, vs, title=title, comment=comment)
    out = check(path, bars=bars, grid=grid)
    return path, out
