"""Materials of proposal-1 (tonic level, B-flat minor, 2/2, one bar = 1 whole note).

All lines are event lists from ricer.parse (start, dur, (diatonic, midi)).
The LilyPond text of every material is kept here so DESIGN.md can quote it.
"""
from ricer import *

LY = {}


def mat(name, ly):
    LY[name] = ly
    return parse(ly)


# ---------------------------------------------------------------- Subject I
# Theme bars 1-4 at REAL rhythm (alla breve: the dotted halves are the pulse),
# minor mode (only 3^ lowered), plus the landing c'' = theme bar 5 downbeat.
# The landing is a strong arrival (2^ over V, half cadence) and is ELIDED into
# the countersubject: the voice never stops on the pickup.
S1 = mat('S1', "bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes' | c''2")

# Real answer at the upper fifth (F minor, e natural as leading tone).  The
# subject starts on 1^ and never stresses 5^ early, so no tonal mutation is
# needed; its landing g (2^ of F) is harmonised as G major = V of C, which is
# exactly where the tonal plan goes next (C minor).
A1 = transpose(S1, 4, 7)

# ---------------------------------------------------------------- CS1: lament
# Chromatic arch: 5^ held, rise f-ges-g-aes-bes-c (passus duriusculus up),
# then 7-6 / 2-3 / 4-3 suspensions against the subject's rise and the
# chromatic fall aes-g-ges-f-e (the royal theme's descending tetrachord).
# Invertible at the octave AND at the twelfth (P03).
CS1 = mat('CS1', "f'2 ges'2 | g'4. aes'8 bes'4. c''8 | bes'2. aes'4~ | aes'4 g'4 ges'4 f'4 | e'2")

# ---------------------------------------------------------------- CS2: motor
# Quarter-note line with the theme's dotted cell; bar 1 falls a tetrachord
# (f ees des c), bar 2 rises it back (bes c des ees): an internal mirror.
# Triple counterpoint S1/CS1/CS2 is clean in all six permutations (P04).
CS2 = mat('CS2', "r4 f''4 ees''4 des''8 c''8 | bes'4 c''4 des''4 ees''4 | des''4 c''4 ees''4. des''8 | c''2 bes'4. aes'8 | g'2")

# ---------------------------------------------------------------- inversions
# Diatonic mirror, harmonic minor, axis 1^<->5^ (Art of Fugue convention):
# the leading-tone sigh bes-a-bes becomes the lament sigh f-ges-f.
I1 = mirror(S1)
LY['I1'] = render(I1)
# CS1 mirrored; one chromatic passing note (ges'' in bar 3) added so the
# mirrored 2-3 suspension resolves as a semitone retardation: the line becomes
# a seven-semitone chromatic ascent f-ges-g-aes-a-bes-ces.
IC1 = mat('IC1', "bes''2 a''2 | aes''4. g''8 f''4. ees''8 | f''2. ges''8 g''8~ | g''4 aes''4 a''4 bes''4 | ces'''2")
IC2 = mirror(CS2)
LY['IC2'] = render(IC2)

# ---------------------------------------------------------------- Subject II
# Theme bars 5-8, minor, full length: 4.5 bars like S1, so the two halves of
# the theme can sound together and land together.
S2 = mat('S2', "c''4. a'8 f'4 des''8 bes' | c''2. f''8 bes' | ees''4. des''8 des''4. c''8 | c''1 | c''2")
S2s = mat('S2s', "c''4. a'8 f'4 des''8 bes' | c''2. f''8 bes' | ees''4. des''8 des''4. c''8 | c''2")

# augmented forms
S1aug = augment(S1)
A1aug = augment(A1)
# full theme (S1 + S2, elided on the shared c''): 8.5 bars in B-flat minor
THEME = S1[:-1] + shift(S2, 4)


# B-flat MAJOR versions (des -> d) for the apotheosis
def major(line):
    return [(s, d, (p[0], p[1] + 1) if p and p[1] % 12 == 1 else p) for s, d, p in line]


S1M, S2M, THEMEM = major(S1), major(S2), major(THEME)
S1Maug = augment(S1M)
HMAJ = [0, 2, 4, 5, 7, 9, 11]
I1M = mirror(S1M, scale=HMAJ)          # major-mode mirror (f g f ...)
I1Maug = augment(I1M)
S2Maug = augment(S2M)
