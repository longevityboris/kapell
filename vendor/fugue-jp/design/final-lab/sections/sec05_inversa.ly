\version "2.24.0"
% bars 35-45
% Section 5: Fuga inversa: three entries, A minor established, deceptive link to F. Starter = the verified skeleton; enrich per BLUEPRINT.md
% and verify with: python3 ../splice_check.py sec05_inversa.ly
soprano = \absolute {
  % 35
  r1 | e''8 f''8 e''8 d''8 c''8 d''8 b'8 g''8 | c''4 d''8 a'8 ~ a'4 b'4 | b'8 a'8 b'8 c''8 d''4 c''4 |
  % 39
  f''2 e''4 d''4 | dis''2. r4 | e''2. e''8 f''8 | e''2. e''8 f''8 |
  % 43
  e''4. d''8 d''4. b'8 | b'2. c''8 e''8 | d''4. f''8 a''4 r4 |
}
alto = \absolute {
  % 35
  r2. a'4 | c'2. d'4 | e'4 f'4 fis'2 | gis'2. a'4 |
  % 39
  f'4. d'8 c'4 b4 | fis'2. e'4 | c''4 a'4 gis'4 r4 | e'8 f'8 e'8 d'8 c'8 d'8 b8 g'8 |
  % 43
  c'4 d'8 a8 ~ a4 b4 | b8 a8 b8 c'8 d'4 c'4 | a'4. f'8 e'4 gis'4 |
}
tenor = \absolute {
  % 35
  r1 | r1 | b2. b8 c'8 | b2. b8 c'8 |
  % 39
  b4. a8 a4. fis8 | fis2. g8 b8 | a4. c'8 e'4 r4 | r1 |
  % 43
  r1 | r1 | a4. a8 c'4 b4 |
}
bass = \absolute {
  % 35
  e2. e8 f8 | e2. e8 f8 | e4. d8 d4. b,8 | b,2. c8 e8 |
  % 39
  d4. f8 a,4 b,4 | b,2. e4 ~ | e2. a,4 | c2. d4 |
  % 43
  e4 f4 fis2 | gis2. a4 | f4. d8 a,4 e,4 |
}
