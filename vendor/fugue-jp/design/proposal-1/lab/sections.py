"""Section drafts of proposal-1 as LilyPond voice strings (\\absolute, 2/2).

python3 sections.py [NAME ...]  -> writes lab/<NAME>.ly for each section draft and
runs tools/check.py (with the fixed ranges) + the strict stile-antico filter.
Bar numbers in comments are GLOBAL bar numbers of the planned piece.
"""
import sys
from ricer import *

SEC = {}

# --------------------------------------------------------------------------
# E1  Exposition, bars 1-18 (+ joint bar 19:1).  B-flat minor -> G7 (V7 of C).
#   1-4  S  S1 (b-flat')                      solo, p
#   5-8  A  A1 real answer (f')    S  CS1 (answer level, elided from S1's c'')
#   9-10 codetta S+A: G - C/E - F - F/C -> b-flat (circle of fifths)
#  11-14 T  S1 (b-flat)            A  CS1         S  CS2 (bes' replaces its rest)
#  15-18 B  A1 (f)                 T  CS1 (ans)   A  CS2 (ans)   S free, enters 16:3
#  19:1  C minor 6/4 over G (B g = I1 begins; T c' tied = IC1 begins, resolves c'-b;
#        A ees' tied; S rests = IC2's opening rest) -> mirror section
SEC['E1_exposition'] = dict(title='E1 exposition bars 1-19', soprano="""
bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes' |
c''2 des''2 | d''4. ees''8 f''4. g''8 | f''2. ees''4~ | ees''4 d''4 des''4 c''4 |
b'2 c''2~ | c''4 bes'4 a'2 |
bes'4 f''4 ees''4 des''8 c''8 | bes'4 c''4 des''4 ees''4 | des''4 c''4 ees''4. des''8 | c''2 bes'4. aes'8~ |
aes'4 r4 r2 | r2 c''2~ | c''4 bes'4 ees''2~ | ees''2 des''4 f''4 |
r2
""", alto="""
R1*4 |
f'2. f'8 e' | f'2. f'8 e' | f'4. g'8 g'4. bes'8 | bes'2. aes'8 f' |
g'2 e'2 | f'2 c'2 |
f'2 ges'2 | g'4. aes'8 bes'4. c''8 | bes'2. aes'4~ | aes'4 g'4 ges'4 f'4 |
r4 c''4 bes'4 aes'8 g'8 | f'4 g'4 aes'4 bes'4 | aes'4 g'4 bes'4. aes'8 | g'2 f'4. ees'8~ |
ees'2
""", tenor="""
R1*10 |
bes2. bes8 a | bes2. bes8 a | bes4. c'8 c'4. ees'8 | ees'2. des'8 bes |
c'2 des'2 | d'4. ees'8 f'4. g'8 | f'2. ees'4~ | ees'4 d'4 des'4 c'4~ |
c'2
""", bass="""
R1*14 |
f2. f8 e | f2. f8 e | f4. g8 g4. bes8 | bes2. aes8 f |
g2
""")


# --------------------------------------------------------------------------
# M  Mirror counter-exposition, GLOBAL bars 19-27 (fully voiced; bar 27 = start of
#    the stretto chain, only its first notes shown).
#  M1 19-22  B  I1 in c minor (g), elided from the answer's landing: G pedal, b9 sigh
#            T  IC1 (c'), tied from CS1's c': the lament keeps falling c'-b-bes-a-g-f
#            S  IC2 (c''), A free (ees'-d' = 6/4-5/3, then c'-b over the V4/2)
#  M2 23-26  A  I1 in f minor (c''), T IC1 (f'), B IC2 (F,), S free (from aes'')
#  27        A  S1 b-flat (bes') = I1's landing; S CS1 (f''); B des (i6)
SEC['M_mirror'] = dict(title='M mirror counter-exposition, bars 19-27', soprano="""
r4 c''4 d''4 ees''8 f''8 | g''4 f''4 ees''4 d''4 | ees''4 f''4 d''4. ees''8 | f''2 g''4. a''8 |
aes''2 g''2~ | g''2 f''4. e''8 | f''2 e''2 | f''4 g''4 bes''4 aes''4 |
f''2 ges''2
""", alto="""
ees'2 d'2 | ees'2. c'4~ | c'2 b4. d'8 | f'2. ees'4 |
c''2. c''8 des''8 | c''2. c''8 des''8 | c''4. bes'8 bes'4. g'8 | g'2. aes'8 c''8 |
bes'2. bes'8 a'8
""", tenor="""
c'2 b2 | bes4. a8 g4. f8 | g2. aes8 a8~ | a4 bes4 b4 c'4 |
f'2 e'2 | ees'4. d'8 c'4. bes8 | c'2. des'8 d'8~ | d'4 ees'4 e'4 f'4 |
r1
""", bass="""
g2. g8 aes8 | g2. g8 aes8 | g4. f8 f4. d8 | d2. ees8 g8 |
f4 f,4 g,4 aes,8 bes,8 | c4 bes,4 aes,4 g,4 | aes,4 bes,4 g,4. aes,8 | bes,2 c4. d8 |
des2 r2
""")

# --------------------------------------------------------------------------
# X1  Climax exit, GLOBAL bars 65-69 (fully voiced).  Soprano = end of S1 per arsin
#     (entered 63:3); bass = end of A1 augmented, its landing g cut to a half note.
#  65  i (tonic pedal bes,)          66:1 vii°7 over the pedal (a-c-ees-ges), fff
#  66:3 v6/5 (Fm7/A-flat)  66:4 v7   67:1 IV6 (E-flat/G, Dorian)   67:3 French sixth
#      (ges-bes-c-e; the subject's landing c'' is its third)   68:1 V with 4-3 (bes'-a')
#  68:3 V7 (fermata), general pause    69:1 I, B-flat MAJOR: soprano c''-bes' (2-1) =
#      first note of the transfigured theme; the minor third becomes d' in the tenor.
SEC['X1_climax_exit'] = dict(title='X1 climax exit, bars 65-69', soprano="""
bes'4 bes'8 a'8 bes'4. c''8 | c''4. ees''8 ees''2~ | ees''4 des''8 bes'8 c''2~ | c''1 | bes'1
""", alto="""
f'2 f'2 | a'2 aes'2 | bes'2 bes'2 | bes'4 a'4 a'2 | f'1
""", tenor="""
des'2 des'2 | ges'2 f'4 ees'4 | ees'2 e'2 | f'2 ees'2 | d'1
""", bass="""
bes,1 | bes,2 aes,4 f,4 | g,2 ges,2 | f,2 f,2 | bes,1
""")

# --------------------------------------------------------------------------
# X2  End of the apotheosis and coda, GLOBAL bars 75-84 (fully voiced).
#  75  iv (e-flat MINOR inside the major theme) · I    76 V · V7    77 V7
#  78  bVI (G-flat): DECEPTIVE; the theme's c'' falls to bes' over G-flat
#  79  V      80 I · iv6/4 over the tonic pedal, alto f'-ges'-f' (the inverted sigh)
#  81  I · IV6/4 (ges' becomes g': minor turns major)
#  82  S1 head in the soprano, bes'2. bes'8 a'8: I · IV · V7 with 4-3
#  83  I · iv6/4 (last lament sigh)    84  I, ppp, fermata
#  (The alto's S1M-at-the-fifth lands on ges' at 75:1 instead of f': a modal inflection.)
SEC['X2_coda'] = dict(title='X2 apotheosis end and coda, bars 75-84', soprano="""
ees''4. d''8 d''4. c''8 | c''1 | c''1 | bes'1 | c''1 | d''2 ees''2 | d''2 ees''2 | bes'2. bes'8 a'8 | bes'1 | bes'1
""", alto="""
ges'2 f'2 | f'2 ees'2 | ees'1 | des'1 | f'1 | f'2 ges'2 | f'2 g'2 | f'2 g'4 f'4 | f'2 ges'2 | f'1
""", tenor="""
bes2 bes2 | a2 a2 | a1 | bes1 | a1 | bes1 | bes1 | d'2 ees'4 ees'4 | d'2 ees'2 | d'1
""", bass="""
ees2 bes,2 | f,1 | f,1 | ges,1 | f,1 | bes,1 | bes,1 | bes,2 ees4 f4 | bes,1 | bes,1
""")


def build(name):
    d = SEC[name]
    p = lab(name + '.ly', {v: d[v] for v in ('soprano', 'alto', 'tenor', 'bass') if v in d}, d['title'])
    out = check(p)
    cnt, strong, tot = summary(out)
    st = strict(out)
    print(f"{name}: {tot}  strict={len(st)}")
    for l in out.splitlines():
        if l[:4] in ('PAR!', 'BEAT', 'DIS!', 'D4? ', 'ERR ', 'DIR ', 'CROS', 'MEL '):
            print('   ' + l)
    for l in st:
        print('   strict: ' + l)
    return out


if __name__ == '__main__':
    for n in (sys.argv[1:] or SEC):
        build(n)
