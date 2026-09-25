\version "2.24.0"
%% QA dynamics test (qa/qa_dynamics.py). Written independently of tests/chain_test.ly.
%% Bars 1-2, 4-5, 7-8: the same three-voice phrase (16ths in the soprano, a tenor line,
%% a bass) -- the plans play it pp, mf, ff. Bars 10-17: one repeated chord in quarters
%% (constant pitch) under a pp -> ff -> pp hairpin. Bars 19-20 and 22-23: the phrase
%% again at mf, first with the tenor voiced as "subject", then without roles.

soprano = \absolute {
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
  ees''4 ees'' ees'' ees'' | ees''4 ees'' ees'' ees'' | ees''4 ees'' ees'' ees'' | ees''4 ees'' ees'' ees'' |
  ees''4 ees'' ees'' ees'' | ees''4 ees'' ees'' ees'' | ees''4 ees'' ees'' ees'' | ees''4 ees'' ees'' ees'' |
  R1 |
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
  c''16 d'' ees'' f'' g''8 f''16 ees'' d''8 g'' b'4 | c''16 b' c'' d'' ees''8 d''16 c'' b'4 c''4 |
  R1 |
}

tenor = \absolute {
  g4 aes8 g f4 d | ees4 f g2 |
  R1 |
  g4 aes8 g f4 d | ees4 f g2 |
  R1 |
  g4 aes8 g f4 d | ees4 f g2 |
  R1 |
  g4 g g g | g4 g g g | g4 g g g | g4 g g g |
  g4 g g g | g4 g g g | g4 g g g | g4 g g g |
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
  c4 c c c | c4 c c c | c4 c c c | c4 c c c |
  c4 c c c | c4 c c c | c4 c c c | c4 c c c |
  R1 |
  c4 c, g, g | c4 aes, g, c |
  R1 |
  c4 c, g, g | c4 aes, g, c |
  R1 |
}
