#!/usr/bin/env python3
"""Strict two-voice dissonance evaluator used to RANK search candidates (the project checker's
justification heuristics are permissive: e.g. a downbeat 4th against the bass tagged ANT7).

Rules (upper voice U over lower voice L; 4th against L counts as dissonance):
  consonant intervals mod 12: 0,3,4,7,8,9
  a dissonance at time t is OK only if:
    PASS  - exactly one voice attacks at t, the attacking note is approached AND left by step,
            and t is off the main beats (not beat 1 or 3)               -> ok
    APASS - same but on beat 1 or 3 (accented passing tone)            -> soft penalty 1
    SUSP  - the dissonant note was sounding before t (tied/held or re-struck at the same pitch),
            was consonant when it began, and resolves DOWN by step to a consonance -> ok
    APP   - attacking note on a beat, resolves down by step to a consonance -> soft penalty 2
  everything else is a hard fault. Parallel 5ths/8ves between consecutive onsets and
  voice crossing are hard faults. Hidden 8ves/5ths (similar motion, upper voice leaps) soft 1.
"""
from fractions import Fraction as F
from p4 import midi

CONS = {0, 3, 4, 7, 8, 9}


def notes_of(ev):
    out, t = [], F(0)
    for p, d in ev:
        if p is not None:
            out.append((t, t + d, midi(p)))
        t += d
    return out


def at(ns, t):
    for i, (s, e, m) in enumerate(ns):
        if s <= t < e:
            return i
    return None


def evaluate(upper, lower, detail=False):
    U, L = notes_of(upper), notes_of(lower)
    times = sorted({s for s, _, _ in U} | {s for s, _, _ in L})
    hard, soft, log = 0, 0, []
    prev = None
    for t in times:
        iu, il = at(U, t), at(L, t)
        if iu is None or il is None:
            prev = None
            continue
        u, l = U[iu], L[il]
        if u[2] < l[2]:
            hard += 1
            log.append((t, 'CROSS'))
        iv = (u[2] - l[2]) % 12
        # parallels
        if prev is not None:
            pu, pl = prev
            if pu[2] != u[2] and pl[2] != l[2]:
                piv = (pu[2] - pl[2]) % 12
                if piv == iv and iv in (0, 7):
                    hard += 1
                    log.append((t, 'PAR'))
                elif iv in (0, 7) and (u[2] - pu[2]) * (l[2] - pl[2]) > 0 and abs(u[2] - pu[2]) > 2:
                    soft += 1
                    log.append((t, 'HIDDEN'))
        prev = (u, l)
        if iv in CONS:
            continue
        ua, la = u[0] == t, l[0] == t
        beat_pos = (t * 4) % 4          # 0..4 quarter position in bar
        main = (t * 4) % 2 == 0         # beat 1 or 3
        ok = None

        def step(a, b):
            return 1 <= abs(a - b) <= 2

        def nb(ns, i):
            pv = ns[i - 1] if i > 0 and ns[i - 1][1] == ns[i][0] else None
            nx = ns[i + 1] if i + 1 < len(ns) else None
            return pv, nx

        def cons_with(ns_other, note_m, time):
            j = at(ns_other, time)
            if j is None:
                return True
            return (abs(note_m - ns_other[j][2]) % 12) in CONS

        for (ns, i, attacked, other) in ((U, iu, ua, L), (L, il, la, U)):
            pv, nx = nb(ns, i)
            n = ns[i]
            if attacked and not (ua and la):
                if pv and nx and step(pv[2], n[2]) and step(n[2], nx[2]):
                    ok = ok or ('PASS' if not main else 'APASS')
            # suspension: note sounding before t (held) or re-struck at same pitch
            held = n[0] < t or (pv is not None and pv[2] == n[2])
            if held and nx is not None and 1 <= n[2] - nx[2] <= 2:
                begin = n[0] if n[0] < t else pv[0]
                if cons_with(other, n[2], begin) and cons_with(other, nx[2], nx[0]):
                    ok = ok or 'SUSP'
            if attacked and main and nx is not None and 1 <= n[2] - nx[2] <= 2 and cons_with(other, nx[2], nx[0]):
                ok = ok or 'APP'
            if attacked and (ua and la) and pv and nx and step(pv[2], n[2]) and step(n[2], nx[2]) and not main:
                ok = ok or 'PASS2'
        if ok in ('PASS', 'SUSP'):
            pass
        elif ok in ('APASS', 'PASS2'):
            soft += 1
        elif ok == 'APP':
            soft += 2
        else:
            hard += 1
        log.append((t, f'{ok or "FAULT"} iv={iv}'))
    return (hard, soft, log) if detail else (hard, soft)
