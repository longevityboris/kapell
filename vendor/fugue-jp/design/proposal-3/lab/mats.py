"""Proposal-3 materials (B-flat minor frame unless noted). Single source of truth for the labs."""
from p3 import mel, tr, inv, aug, at, octs, S1

# Subject I: theme bars 1-4, real rhythm, tweak: bar 4 "des''8 bes'" -> "des''8 c''", then bes' (4-3-2-1 close)
S1 = S1
# Real answer (F minor)
ANS = tr(S1, '5')
# CS1 "lament": chromatic 6-b6-5-#4, then Phrygian turn 5-b6-5; first half-bar free (held/cadence note)
CS1 = mel("r2 g2 | ges2 f2 | e2 f2 | ges2 f2")
# CS2 "cascade": syncopated descending scale g'..a (7-6 / 4-2 suspension chain), cadence a-c'-des'
CS2 = mel("r4 g'2 f'2 ees'2 des'2 c'2 bes2 a2 c'4 | des'2")
# Subject II: theme bars 5-8 (minor), open ending on 2^ over V
S2 = mel("c''4. a'8 f'4 des''8 bes' | c''2. f''8 bes' | ees''4. des''8 des''4. c''8 | c''1")
# Inversion of S1: diatonic mirror about des (1<->5, 2<->4, 3<->3, #7<->b6)
S1I = mel("f'2. f'8 ges' | f'2. f'8 ges' | f'4. ees'8 ees'4. c'8 | c'2. des'8 ees' | f'2")
# Major forms for the apotheosis (B-flat major)
S1M = mel("bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. d''8 c'' | bes'2")
S2M = mel("c''4. a'8 f'4 d''8 bes' | c''2. f''8 bes' | ees''4. d''8 d''4. c''8 | c''1")
THEME_M = mel("bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes' | "
              "c''4. a'8 f'4 d''8 bes' | c''2. f''8 bes' | ees''4. d''8 d''4. c''8 | c''1")

# ---- mirror forms (tonal mirror about des in B-flat harmonic minor: bes<->f, c<->ees, a<->ges, g<->aes, e<->ces)
from p3 import tmirror
S1I = tmirror(S1)       # f'2. f'8 ges' | f'2. f'8 ges' | f'4. ees'8 ees'4. c'8 | c'2. des'8 ees' | f'2
CS1I = tmirror(CS1)     # r2 aes | a bes | ces bes | a bes     (rising chromatic 7-#7-1-b2, turn about the tonic)
CS2I = tmirror(CS2)     # r4 aes'2 bes' c'' des'' ees'' f'' ges''2 ees''4 | des''  (rising cascade: retardations)

# ---- augmentation: the answer in doubled values in the bass = the dominant pedal; last beat g -> ges (German sixth)
from p3 import setpitch
_aug = octs(aug(ANS, 2), -3)                      # f, ... (8 bars + final f,)
AUG = setpitch(_aug, len([n for n in _aug if n.step is not None]) - 2, "ges,")   # aes, g, -> aes, ges,
S1I_BES = tr(S1I, '11')                           # mirror on bes'' (rectus/inversus wedge with S1 on bes')
S2F = tr(S2, '5')
S2SUB = tr(S2, '4')
ANSM = tr(S1M, '-4')
CS2M = mel("r4 g'2 f'2 ees'2 d'2 c'2 bes2 a2 c'4 | d'2")   # cascade in B-flat major

# ---- Part II combination: S1 (answer form) + S2 entering two beats later a fourth above + CS2 (answer frame)
ANS_LO = tr(S1, '-4')          # f' f' e' f' ...  (the answer an octave below ANS)
S2_2 = at(S2, 2)               # S2 delayed by two beats
CS2F = tr(CS2, '-4')           # d' c' bes aes g f e g aes
CS1M = CS1                                        # lament unchanged in major (ges = b6 mixture: the minor's shadow)
S2M_2 = at(S2M, 2)
CS2MF = tr(CS2M, '-4')                            # d' c' bes a g f e g | a
