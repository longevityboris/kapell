"""Regenerate the core proof labs of proposal-1 and record checker summaries.

python3 build_core.py  -> writes lab/P*.ly and prints one summary line per lab
(also written to lab/proofs_core.txt).  Materials come from mats.py.
"""
import io, contextlib, itertools
from fractions import Fraction as F
from ricer import *
from mats import *
from perm import place, pick_voices

RESULTS = []


def record(name, voices, title, bars=None):
    lab(name, voices, title)
    out = check(name, bars)
    cnt, strong, tot = summary(out)
    st = strict(out)
    line = (f"{name:34s} PAR!={cnt['PAR!']} BEAT={cnt['BEAT']} DIS!={cnt['DIS!']} D4?={cnt['D4?']} "
            f"DIR={cnt['DIR']} CROS={cnt['CROS']} MEL={cnt['MEL']} ERR={cnt['ERR']} strict={len(st)}")
    RESULTS.append(line)
    print(line)
    for l in out.splitlines():
        if l[:4] in ('PAR!', 'BEAT', 'DIS!', 'D4? ', 'ERR ', 'DIR ', 'CROS', 'MEL '):
            print('      ' + l)
    for l in st:
        print('      strict: ' + l)
    return out


def perm_labs(prefix, lines, title):
    for order in itertools.permutations(lines):
        b = place(order, lines)
        cost, octs, ls = b
        vs = pick_voices(ls)
        record(f"{prefix}_{'-'.join(order)}.ly", dict(zip(vs, ls)), f"{title}: {' / '.join(order)}")


if __name__ == '__main__':
    # P01-P02: S1 / CS1 double counterpoint at the octave (both positions)
    record('P01_S1_over_CS1.ly', dict(alto=S1, tenor=octave(CS1, -1)), 'P01 S1 over CS1 (8ve)')
    record('P02_CS1_over_S1.ly', dict(alto=CS1, tenor=octave(S1, -1)), 'P02 CS1 over S1 (8ve)')
    # P03: answer + CS1 (exposition bars 5-9 texture)
    record('P03_CS1_over_A1.ly', dict(soprano=transpose(CS1, 4, 7), alto=octave(A1, -1)), 'P03 CS1 over answer')
    # P04: CS1 at the 12th below the subject (bass), and above the answer
    record('P04_S1_over_CS1at12.ly', dict(alto=S1, bass=transpose(CS1, -11, -19)), 'P04 CS1 inverted at the 12th (bass)')
    record('P05_A1_over_CS1at12.ly', dict(soprano=A1, alto=CS1), 'P05 answer over CS1 (12th)')
    # P06: triple counterpoint S1 / CS1 / CS2, all six permutations
    perm_labs('P06', {'S1': S1, 'CS1': CS1, 'CS2': CS2}, 'P06 triple counterpoint')
    # P07: the same trio in mirror inversion
    perm_labs('P07', {'I1': I1, 'IC1': IC1, 'IC2': IC2}, 'P07 mirrored trio')
    # P08: rectus against inversus at offset 0 (both vertical orders)
    record('P08_S1_over_I1.ly', dict(alto=S1, tenor=octave(I1, -1)), 'P08 S1 over I1 (offset 0)')
    record('P08_I1_over_S1.ly', dict(soprano=I1, alto=S1), 'P08 I1 over S1 (offset 0)')
    record('P08_CS1_over_I1.ly', dict(alto=CS1, tenor=octave(I1, -1)), 'P08 CS1 over I1')
    record('P08_I1_over_CS1.ly', dict(soprano=I1, alto=CS1), 'P08 I1 over CS1')
    record('P08_CS1_over_IC1.ly', dict(alto=CS1, bass=octave(IC1, -2)), 'P08 CS1 over IC1')
    record('P08_IC1_over_CS1.ly', dict(alto=octave(IC1, -1), tenor=octave(CS1, -1)), 'P08 IC1 over CS1')
    # P09: stretto at the lower fifth; the four-voice chain exactly as used in bars 27-37
    record('P09_stretto5_3q.ly', dict(alto=S1, tenor=shift(transpose(S1, -4, -7), F(3, 4))), 'P09 S1 stretto, lower 5th, 3 quarters')
    record('P09_stretto5_2bars.ly', dict(alto=S1, tenor=shift(transpose(S1, -4, -7), F(2))), 'P09 S1 stretto, lower 5th, 2 bars')
    record('P09_chain_of_fifths.ly', dict(alto=S1, tenor=shift(transpose(S1, -4, -7), F(2)),
                                          bass=shift(transpose(S1, -8, -14), F(4)),
                                          soprano=shift(transpose(S1M, 2, 3), F(6))),
           'P09 chain bes-ees-aes-Des, 2 bars apart (bars 27-37)')
    record('P09_chain_3q.ly', dict(soprano=S1, alto=shift(transpose(S1, -4, -7), F(3, 4)),
                                   tenor=shift(transpose(S1, -8, -14), F(6, 4)), bass=shift(transpose(S1, -12, -21), F(9, 4))),
           'P09 chain of four at 3 quarters (stretto maestrale, reserve)')
    # P10: combination S1 + S2 (S2 in F major a fifth above); trio with CS2 as used in bars 49-53
    S2Mu = transpose(S2M, 4, 7)
    record('P10_S1_over_S2Mu.ly', dict(alto=S1, bass=octave(S2Mu, -2)), 'P10 S1 over S2 (F major)')
    record('P10_S2Mu_over_S1.ly', dict(alto=octave(S2Mu, -1), tenor=octave(S1, -1)), 'P10 S2 (F major) over S1')
    record('P10_CS2_S2Mu_S1.ly', dict(soprano=CS2, alto=octave(S2Mu, -1), bass=octave(S1, -2)), 'P10 combination trio (bars 49-53)')
    # P11: S2 in D-flat with CS3 and its bass; double-octave inversion (range aside)
    S2D = transpose(S2M, 2, 3)
    CS3 = parse("c'2 f'2 | ges'4 f'4 ees'4 f'4 | bes'2 aes'4 ges'4 | aes'4 bes'4 c''4 des''4 | c''2")
    BS = parse("c2 des2 | ges2 aes4 f4 | ees2 f4 ees4 | aes2 c2 | aes2")
    record('P11_S2_CS3_bass.ly', dict(soprano=S2D, alto=CS3, bass=BS), 'P11 S2 (D-flat) + CS3 + bass')
    record('P11b_CS3_over_S2_15th.ly', dict(soprano=octave(CS3, 1), tenor=octave(S2D, -1)), 'P11b CS3 two octaves up')
    # P12: the climax: quadruple combination over the augmented answer (bars 59-63)
    record('P12_climax_quadruple.ly', dict(soprano=I1, alto=S2, tenor=octave(S1, -1), bass=octave(A1aug, -3)),
           'P12 I1 / S2 / S1 over A1 augmented')
    # P13: apotheosis: whole theme with S1 (major) at the lower fifth, 2 bars later
    record('P13_apotheosis_stretto.ly', dict(soprano=THEMEM, alto=shift(transpose(S1M, -4, -7), F(2))),
           'P13 theme (B-flat major) + S1 at the lower fifth')
    open('proofs_core.txt', 'w').write('\n'.join(RESULTS) + '\n')
