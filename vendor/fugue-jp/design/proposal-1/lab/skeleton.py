"""Thematic skeleton of the whole piece (proposal-1).

Every planned statement of S1, A1, I1, S2, CS1, CS2, CS3, IC1, IC2, A1aug and the
apotheosis theme is placed at its planned GLOBAL bar, in its planned voice, key and
octave; free counterpoint is left as rests.  The exposition (bars 1-18) is taken
complete from sections.py.  The file is checked as a whole: if the skeleton is clean,
every contrapuntal combination the form relies on is proven at its real pitch and
position, including the joints between sections.

python3 skeleton.py  -> writes lab/SK_skeleton.ly, prints the checker summary and
the strict list, and prints the statement table used in DESIGN.md.
"""
from fractions import Fraction as F
from ricer import *
from mats import *
import sections

VOX = ['soprano', 'alto', 'tenor', 'bass']
TOTAL = 84


def B(bar, beat=1):
    """global bar (1-based) and quarter beat -> whole-note time"""
    return F(bar - 1) + F(beat - 1, 4)


def trim(line, end):
    """cut a line at time `end` (relative), dropping/shortening notes"""
    out = []
    for s, d, p in line:
        if s >= end:
            break
        out.append((s, min(d, end - s), p))
    return out


def drop_landing(line):
    return line[:-1]


STMT = []    # (voice, bar, beat, label, line)


def put(voice, bar, label, line, beat=1):
    STMT.append((voice, bar, beat, label, line))


# ---------------------------------------------------------------- lines per key
def tr(line, semis, dia):
    return transpose(line, dia, semis)


CS3 = parse("c'2 f'2 | ges'4 f'4 ees'4 f'4 | bes'2 aes'4 ges'4 | aes'4 bes'4 c''4 des''4 | c''2")   # D-flat level
S2D = transpose(S2M, 2, 3)                      # S2, D-flat major, ees''
BASS_S2D = parse("c2 des2 | ges2 aes4 f4 | ees2 f4 ees4 | aes2 c2 | aes2")
S2Ab = transpose(S2D, -3, -5)                   # answer, A-flat major, bes'
CS3Ab = transpose(CS3, -3, -5)                  # g ... aes'
S2m_c1 = octave(S2, -1)                         # S2 minor, original pitch class, tenor c'
BASS_S2m = parse("a,2 bes,2 | ees2 f4 des4 | c2 des4 c4 | f2 a,2 | f2")   # bass for S2 minor (B-flat)
S2Mu = transpose(S2M, 4, 7)                     # F major, g''

# ---------------------------------------------------------------- statements
# II  mirror counter-exposition (C minor -> F minor), bars 19-26
put('bass', 19, 'I1 c-minor (g), elided from A1 landing', drop_landing(octave(tr(I1, 2, 1), -2)) + [(F(4), F(1, 4), pitch('f'))])
put('tenor', 19, 'IC1 c-level (c\'), tied from CS1', drop_landing(octave(tr(IC1, 2, 1), -2)))
put('soprano', 19, 'IC2 c-level (c\'\')', drop_landing(tr(IC2, 2, 1)))
put('alto', 23, 'I1 f-minor (c\'\')', drop_landing(octave(tr(I1, 7, 4), -1)))
put('tenor', 23, 'IC1 f-level (f\')', drop_landing(octave(tr(IC1, 7, 4), -2)))
put('bass', 23, 'IC2 f-level (F,), its opening rest taken by the I1 landing f', shift(drop_landing(octave(tr(IC2, 7, 4), -3))[1:], F(-1, 4)), beat=2)
# free voices of the mirror section, now written (sections.py M_mirror)
put('alto', 19, 'free alto (M1): 6/4-5/3 then c\'-b over V4/2', parse("d'2 | ees'2. c'4~ | c'2 b4. d'8 | f'2. ees'4"), beat=3)
put('soprano', 23, 'free soprano (M2)', parse("aes''2 g''2~ | g''2 f''4. e''8 | f''2 e''2 | f''4 g''4 bes''4 aes''4"))
put('bass', 27, 'bass des (i6) under the first chain entry', parse("des2"))
put('soprano', 27, 'CS1 over the chain (f\'\'), landing dropped', drop_landing(octave(CS1, 1)))
# III stretto chain in descending fifths, bars 27-36
put('alto', 27, 'S1 b-flat (bes\')', S1, beat=1)
put('tenor', 29, 'S1 e-flat (ees\')', tr(S1, -7, -4))
put('bass', 31, 'S1 a-flat (aes)', tr(S1, -14, -8))
put('soprano', 33, 'S1 D-flat MAJOR (des\'\')', drop_landing(tr(S1M, 3, 2)))
# IV  S2 exposition, bars 37-48
put('soprano', 37, 'S2 D-flat major (ees\'\') = theme completed', S2D)
put('alto', 37, 'CS3 (D-flat)', drop_landing(CS3))
put('bass', 37, 'bass for S2/CS3 (D-flat)', drop_landing(BASS_S2D))
put('alto', 41, 'S2 answer A-flat major (bes\'); landing becomes 4-3 bes\'-a\' (free)', drop_landing(S2Ab))
put('tenor', 41, 'CS3 (A-flat)', drop_landing(CS3Ab))
put('tenor', 45, 'S2 B-flat minor, original (c\')', S2m_c1)
put('bass', 45, 'bass for S2 minor (B-flat)', drop_landing(BASS_S2m))
# V   combination, bars 49-58
put('bass', 49, 'S1 b-flat (bes,) = tonic pedal', octave(S1, -2))
put('alto', 49, 'S2 F major (g\')', octave(S2Mu, -1))
put('soprano', 49, 'CS2 (f\'\')', CS2)
put('soprano', 54, 'S1 e-flat (ees\'\')', tr(S1, 5, 3))
put('alto', 54, 'CS2 e-flat level', tr(CS2, -7, -4))
put('tenor', 54, 'S2 B-flat MAJOR, original pitch (c\')', octave(S2M, -1))
# VI  climax on the dominant pedal, bars 59-67
put('bass', 59, 'A1 augmented (F,) = dominant pedal', octave(A1aug, -3))
put('soprano', 59, 'I1 (f\'\')', I1)
put('tenor', 59, 'S1 (bes)', octave(S1, -1))
put('alto', 59, 'S2 B-flat minor, original pitch (c\'\')', drop_landing(S2))
put('soprano', 63, 'S1 (bes\') per arsin et thesin: enters on beat 3; landing cut to a quarter', trim(S1, F(4) + F(1, 4)), beat=3)
# VII apotheosis, bars 69-77
put('soprano', 69, 'THEME B-flat MAJOR (bes\')', THEMEM)
put('alto', 71, 'S1 major at the lower fifth (ees\')', tr(S1M, -7, -4))


# fully written passages (sections.py) that replace the skeleton in their windows:
# (section name, first global bar, number of bars used)
WRITTEN = [('M_mirror', 19, 8), ('X1_climax_exit', 65, 4), ('X2_coda', 75, 10)]


def build(stmts=STMT, total=TOTAL, name='SK_skeleton.ly', expo=True, written=True):
    lines = {v: [] for v in VOX}
    if expo:
        e = sections.SEC['E1_exposition']
        for v in VOX:
            # the alto's tied ees' (third of the cadential 6/4 at 19:1) is kept
            lines[v] = trim(parse(e[v]), F(37, 2) if v == 'alto' else F(18))
    for v, bar, beat, label, line in sorted(stmts, key=lambda x: B(x[1], x[2])):
        start = B(bar, beat)
        ev = shift(line, start)
        # overlap check
        if lines[v] and max(s + d for s, d, p in lines[v] if p is not None or True) > start:
            last = max(s + d for s, d, p in lines[v])
            if last > start:
                raise SystemExit(f"overlap in {v} at bar {bar}: previous material ends at {last}")
        lines[v] += ev
    if written:
        for sec, bar0, nbars in WRITTEN:
            lo, hi = B(bar0), B(bar0 + nbars)
            d = sections.SEC[sec]
            for v in VOX:
                keep = []
                for st, du, p in lines[v]:
                    if st + du <= lo or st >= hi:
                        keep.append((st, du, p))
                    elif st < lo:                       # cut a note that runs into the window
                        keep.append((st, lo - st, p))
                    elif st + du > hi:                  # keep the part after the window
                        keep.append((hi, st + du - hi, p))
                w = [(a + lo, b, p) for a, b, p in trim(parse(d[v]), F(nbars))]
                lines[v] = keep + w
    for v in VOX:
        lines[v] = sorted(lines[v], key=lambda e: e[0])
    lab(name, lines, 'Thematic skeleton with the written passages (free voices = rests)', F(total))
    return name


if __name__ == '__main__':
    import sys
    p = build()
    out = check(p)
    cnt, s, tot = summary(out)
    print(tot)
    for l in out.splitlines():
        if l[:4] in ('PAR!', 'BEAT', 'DIS!', 'D4? ', 'ERR ', 'DIR ', 'CROS', 'MEL '):
            print('  ' + l)
    for l in strict(out):
        print('  strict: ' + l)
    if '--table' in sys.argv:
        for v, bar, beat, label, line in sorted(STMT, key=lambda x: (x[1], VOX.index(x[0]))):
            print(f"| {bar} | {v} | {label} | {pname(next(p for s,d,p in line if p))} |")
