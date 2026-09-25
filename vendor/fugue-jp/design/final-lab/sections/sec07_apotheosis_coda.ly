\version "2.24.0"
% bars 55-66
% Section 7: Apotheosis: the whole tune over the triple counterpoint in B-flat major; coda. Starter = the verified skeleton; enrich per BLUEPRINT.md
% and verify with: python3 ../splice_check.py sec07_apotheosis_coda.ly
soprano = \absolute {
  % 55
  bes'2. bes'8 a'8 | bes'2. bes'8 a'8 | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes'8 |
  % 59
  c''4. a'8 f'4 d''8 bes'8 | c''2. f''8 bes'8 | ees''4. d''8 d''4. c''8 | c''1 |
  % 63
  d''1~ | d''1 | d''2 c''2 | d''1 |
}
alto = \absolute {
  % 55
  d'1 | f'2. g'4 | g'4 f'2 ees'4 | bes'2 c''4 bes'8 f'8 |
  % 59
  a'4. f'8 c'4 d'8 c'8 | f'2 a'4. g'8 | a'4. bes'8 bes'4. g'8 | e'2. a'4 |
  % 63
  f'2. f'8 g'8 | f'4 ees'4 d'2 | f'2 ees'2 | d'2 f'2 |
}
tenor = \absolute {
  % 55
  f1 | bes8 a8 bes8 c'8 d'8 c'8 ees'8 g8 | d4 c8 f8 ~ f2 | ees8 f8 ees8 d8 c4 d4 |
  % 59
  ees4 c4 a4 bes8 g8 | a2 c'4. bes8 | f4. e8 e4. c8 | c2. ees4 |
  % 63
  d2 f2 | bes2 f2 | bes2. bes8 a8 | bes1 |
}
bass = \absolute {
  % 55
  bes,2. f,4 | d2. c4 | bes,4 a,4 aes,2 | ges,2. f,4 |
  % 59
  f,2. f,8 e,8 | f,2. f,8 e,8 | f,4. g,8 g,4. bes,8 | bes,2. a,8 f,8 |
  % 63
  bes,1 | bes,1 | bes,1 | bes,1 |
}
