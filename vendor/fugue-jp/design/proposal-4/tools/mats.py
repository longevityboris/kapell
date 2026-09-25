#!/usr/bin/env python3
"""Proposal-4 canonical materials (single source of truth for all labs)."""
from p4 import ly, real, inkey, aug, mirror, cat, rest, length
from fractions import Fraction as F

# Subject I core: theme bars 1-4 at real rhythm, elided into the downbeat c'' (bar 5 beat 1).
S1_CORE = ly("bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes'")
# cadential tail (closed form): theme bar 5's own rhythm c''4. a'8 turned home to the tonic
TAIL_CLOSE = ly("c''4. a'8 bes'2")
# Subject II: theme bars 5-8 (minor)
S2 = ly("c''4. a'8 f'4 des''8 bes' | c''2. f''8 bes' | ees''4. des''8 des''4. c''8 | c''1")
# answer (real, F minor) of S1 core, alto register
A1_CORE = real(S1_CORE, -3, -5)          # f' ... (down a 4th from bes')

# ---- countersubjects (Bb-minor / subject context) ----
# CSa "Lamento": complete chromatic descent ees' -> f (a 2-bar chromatic cell and its transposition a
# fifth lower: iv->i, then i->V). Always BELOW the subject (bass-type countersubject).
CSA = ly("ees'2 d'2 | des'2 c'4. ces'8 | bes2 a2 | aes2 g4. ges8 | f2")
CSA_ANS = real(CSA, -3, -5)   # answer context (bes -> c), same octave band (tenor)
# CSb "Sospiri" (descant, ABOVE the subject), written in ANSWER context (over f'):
# eighth-note arch over the answer's pedal, a leap of a sixth and a long falling scale into the
# German-sixth resolution, then a rising line in contrary motion to the lament, Phrygian close.
# first quarter = elision note (c'' = end of the preceding subject); CSb proper starts beat 2.
CSB_ANS = ly("c''4 des''8 ees''8 f''8 ees''8 des''8 c''8 | aes''4 g''8 f''8 ees''8 des''8 c''8 bes'8 |"
             " a'4 bes'4 c''4 des''4~ | des''4 ees''4 f''2 | e''2")
CSB = real(CSB_ANS, -4, -7)   # subject context (a fifth lower)

# ---- B-flat MAJOR forms (apotheosis) ----
S1M_CORE = ly("bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes'")
S2M = ly("c''4. a'8 f'4 d''8 bes' | c''2. f''8 bes' | ees''4. d''8 d''4. c''8 | c''1")
THEME_M = cat(S1M_CORE, S2M)   # the complete tune (8 bars; the final c'' is a whole note here)

# mirror (diatonic inversion) of S1 around its first note
def S1_MIRROR(key='bes-harm', core=None):
    core = core or cat(S1_CORE, ly("c''2"))
    return mirror(core, ly("bes'4")[0][0], mode='key', key=key)

# apotheosis cantus firmus: the complete tune in B-flat major; its open ending c'' rises to d''
CF_APO = cat(S1M_CORE, ly("c''4. a'8 f'4 d''8 bes' | c''2. f''8 bes' | ees''4. d''8 d''4. c''8 | c''1 | d''1~ | d''1"))
