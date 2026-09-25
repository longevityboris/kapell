#!/usr/bin/env python3
"""P11 exposition model, bars 1-18: fixed thematic voices + free voices (solver or hand)."""
import sys, time
sys.path.insert(0, '.')
from p4 import *; from mats import *
from solve import Solver, show, notes_to_events
from fractions import Fraction as F

def fixed_voices():
    S = cat(S1_CORE, CSB_ANS[:-1], ly("e''2 ees''2"))                 # 1-4 S1, 5-8 CSb, 9 codetta
    A = cat(rest(4), A1_CORE, ly("g'2 a'2"), CSB[:-1], ly("a'2 r2"))   # 5-8 answer, 9 codetta, 10-13 CSb (subject ctx)
    B = cat(rest(9), ly("bes,2. bes,8 a,8 | bes,2. bes,8 a,8 | bes,4. c8 c4. ees8 | ees2. des8 bes,8~ |"
                            " bes,2 a,2 | aes,2 g,4. ges,8 | f,2 e,2 | ees,2 d,4. des,8 | c,2 r2"))
    T = cat(rest(13), real(A1_CORE, -7, -12), ly("g2 r2"))
    return S, A, T, B

def CSA_ANS_B():
    # lament in answer context, bass octave, without its final c (added separately)
    return real(CSA_ANS[:-1], -7, -12)

if __name__ == '__main__':
    S, A, T, B = fixed_voices()
    for nm, v in zip('SATB', (S, A, T, B)):
        print(nm, length(v), ' '.join(to_ly(v))[:200])


def solve_sop_10_13(width=500):
    S, A, T, B = fixed_voices()
    # window bars 10-14 (times relative): take A and B slices
    def sl(ev, b0, b1):
        out, t = [], F(0)
        for p, d in ev:
            s, e = t, t + d
            t = e
            lo, hi = F(b0 - 1), F(b1)
            if e <= lo or s >= hi:
                continue
            s2, e2 = max(s, lo), min(e, hi)
            out.append((p, e2 - s2))
        return out
    Aw = cat(sl(A, 10, 13), ly("r1"))
    Bw = cat(sl(B, 10, 13), ly("bes,1"))
    PAL = "des'' ees'' f'' ges'' g'' aes'' a'' bes'' c'' bes' a' d''"
    KEY = {10, 0, 1, 3, 5, 6, 8, 9}
    Sv = Solver({'alto': Aw, 'bass': Bw}, 'soprano', palette=PAL,
                patterns=["8 8", "t8 8", "8 4 4", "t4 4 8", "12 4", "t8 4 4", "t12 4", "4 4 8", "6 2 8", "t4 4 4 4"],
                bar_patterns={5: ["16"]}, end_pcs={2, 5, 10, 1}, width=width, keep=12, key_pcs=KEY, lo=70, hi=81,
                inner=30, still_pen=(8, 0.0, 12, 0.3), sigh_bonus=0.0, min_span=5)
    return Sv, Sv.solve()


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'sop':
    t0 = time.time()
    Sv, sols = solve_sop_10_13()
    print(len(sols), round(time.time() - t0))
    for c, ns in sols:
        print(f'{c:6.1f} ' + show(ns, Sv.total))


SOP_10_13 = "f''1 | f''2. ees''4 | f''2 ees''2~ | ees''2 des''4 c''4 |"
SOP_14_18 = "bes'4 des''8 ees''8 f''8 ees''8 des''8 c''8 | aes''4 g''8 f''8 ees''8 des''8 c''8 bes'8 | a'4 bes'4 c''4 des''4~ | des''4 ees''4 f''2 | e''2 r2"


def full(alto_14_18="r1 r1 r1 r1 r2 r2", sop_10_13=SOP_10_13):
    S = cat(S1_CORE, CSB_ANS[:-1], ly("e''2 ees''2"), ly(sop_10_13), ly(SOP_14_18))
    A = cat(rest(4), A1_CORE, ly("g'2 a'2"), CSB[:-1], ly(alto_14_18))
    T = cat(rest(13), real(A1_CORE, -7, -12), ly("g2 r2"))
    B = cat(rest(9), ly("bes,2. bes,8 a,8 | bes,2. bes,8 a,8 | bes,4. c8 c4. ees8 | ees2. des8 bes,8~ |"
                        " bes,2 a,2 | aes,2 g,4. ges,8 | f,2 e,2 | ees,2 d,4. des,8 | c,2 r2"))
    return dict(soprano=S, alto=A, tenor=T, bass=B)


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'check':
    v = full()
    p = write_lab('_tmp_expo.ly', v)
    out = check(p)
    print('\n'.join(l for l in out.splitlines() if not l.startswith('DIS ') or 'strong' in l))
