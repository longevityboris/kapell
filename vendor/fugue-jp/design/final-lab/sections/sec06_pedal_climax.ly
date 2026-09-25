\version "2.24.0"
% bars 46-54
% Section 6: Dominant pedal: both subjects over the augmented inversion, Climax II in three speeds, dominant hinge. Starter = the verified skeleton; enrich per BLUEPRINT.md
% and verify with: python3 ../splice_check.py sec06_pedal_climax.ly
soprano = \absolute {
  % 46
  r1 | r1 | r1 | r1 |
  % 50
  r2 f''4. f''16 ees''16 | ges''4. ges''16 f''16 a''4. a''16 aes''16 | g''2 c'''4. c'''16 bes''16 | bes''2. a''4 |
  % 54
  f''4 ees''4 c''4 a'4 |
}
alto = \absolute {
  % 46
  r1 | r1 | c''4. a'8 f'4 des''8 bes'8 | c''2. f''8 bes'8 |
  % 50
  ees''4. des''8 des''4. c''8 | c''1 | e''4. e''16 dis''16 e''2 | e''4. e''16 d''16 e''4 f''4 |
  % 54
  c''2 a'4 c'4 |
}
tenor = \absolute {
  % 46
  bes2 a2 | aes2 g4 c'4 | bes2. bes8 a8 | bes2. bes8 a8 |
  % 50
  bes4. c'8 c'4. ees'8 | ees'2. des'8 bes8 | c'4. a8 bes2 | g2 g4 c'4 |
  % 54
  a2 c'4 ees4 |
}
bass = \absolute {
  % 46
  f,1 | f,2 f,4 ges,4 | f,1 | f,2 f,4 ges,4 |
  % 50
  f,2. ees,4 | ees,2. c,4 | c,1 | c,2 des,4 f,4 |
  % 54
  ees,2. ges,4 |
}
