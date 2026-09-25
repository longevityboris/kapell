\version "2.24.0"
%% Strings QA dynamics score (qa/qa_dynamics.py), four voices = the quartet.
%% Bars 1-2, 4-5, 7-8: the same phrase (16ths, eighths, quarters, a half note in
%% each voice) -- the plan plays it pp, mf, ff.  Bars 10-17: one chord held for
%% eight bars (tied) under a pp -> ff -> pp hairpin (a sustained crescendo and
%% diminuendo, no re-attacks).  Bars 19-20 and 22-23: the phrase at mf, first with
%% the viola (tenor) marked "subject", then without roles.

soprano = \absolute {
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
  ees''1~ | ees''1~ | ees''1~ | ees''1~ | ees''1~ | ees''1~ | ees''1~ | ees''1 |
  R1 |
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
}

alto = \absolute {
  ees'4 f'8 ees' d'4 f'4 | g'4 f'8 ees' d'2 |
  R1 |
  ees'4 f'8 ees' d'4 f'4 | g'4 f'8 ees' d'2 |
  R1 |
  ees'4 f'8 ees' d'4 f'4 | g'4 f'8 ees' d'2 |
  R1 |
  g'1~ | g'1~ | g'1~ | g'1~ | g'1~ | g'1~ | g'1~ | g'1 |
  R1 |
  ees'4 f'8 ees' d'4 f'4 | g'4 f'8 ees' d'2 |
  R1 |
  ees'4 f'8 ees' d'4 f'4 | g'4 f'8 ees' d'2 |
  R1 |
}

tenor = \absolute {
  g4 aes8 g f4 d | ees4 f g2 |
  R1 |
  g4 aes8 g f4 d | ees4 f g2 |
  R1 |
  g4 aes8 g f4 d | ees4 f g2 |
  R1 |
  c'1~ | c'1~ | c'1~ | c'1~ | c'1~ | c'1~ | c'1~ | c'1 |
  R1 |
  g4 aes8 g f4 d | ees4 f g2 |
  R1 |
  g4 aes8 g f4 d | ees4 f g2 |
  R1 |
}

bass = \absolute {
  c4 c, g, g | c4 aes, g, c |
  R1 |
  c4 c, g, g | c4 aes, g, c |
  R1 |
  c4 c, g, g | c4 aes, g, c |
  R1 |
  c1~ | c1~ | c1~ | c1~ | c1~ | c1~ | c1~ | c1 |
  R1 |
  c4 c, g, g | c4 aes, g, c |
  R1 |
  c4 c, g, g | c4 aes, g, c |
  R1 |
}
