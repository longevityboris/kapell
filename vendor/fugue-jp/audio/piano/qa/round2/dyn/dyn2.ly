\version "2.24.0"
%% Round-2 QA dynamics test (independent of tests/chain_test.ly). C major, three voices.
%% Bars 1-2, 4-5, 7-8: the same phrase; the plan plays it pp, mf, ff.
%% Bars 10-17: repeated eighths (soprano), quarters (alto, bass) at constant pitch under a
%% hairpin pp -> ff (bars 10-13) -> pp (bars 14-17).
%% Bars 19-20 and 22-23: the phrase at mf, first with all voices free, then with the alto voiced
%% as a subject entry.
soprano = \absolute {
  e''4 d''8 c'' g''4 e'' | f''8 e'' d'' c'' d''2 | R1 |
  e''4 d''8 c'' g''4 e'' | f''8 e'' d'' c'' d''2 | R1 |
  e''4 d''8 c'' g''4 e'' | f''8 e'' d'' c'' d''2 | R1 |
  g'8 g' g' g' g' g' g' g' | g'8 g' g' g' g' g' g' g' | g'8 g' g' g' g' g' g' g' | g'8 g' g' g' g' g' g' g' |
  g'8 g' g' g' g' g' g' g' | g'8 g' g' g' g' g' g' g' | g'8 g' g' g' g' g' g' g' | g'8 g' g' g' g' g' g' g' |
  R1 |
  e''4 d''8 c'' g''4 e'' | f''8 e'' d'' c'' d''2 | R1 |
  e''4 d''8 c'' g''4 e'' | f''8 e'' d'' c'' d''2 | R1 |
}
alto = \absolute {
  c''4 b'8 a' b'4 c'' | a'8 g' f' e' g'2 | R1 |
  c''4 b'8 a' b'4 c'' | a'8 g' f' e' g'2 | R1 |
  c''4 b'8 a' b'4 c'' | a'8 g' f' e' g'2 | R1 |
  e'4 e' e' e' | e'4 e' e' e' | e'4 e' e' e' | e'4 e' e' e' |
  e'4 e' e' e' | e'4 e' e' e' | e'4 e' e' e' | e'4 e' e' e' |
  R1 |
  c''4 b'8 a' b'4 c'' | a'8 g' f' e' g'2 | R1 |
  c''4 b'8 a' b'4 c'' | a'8 g' f' e' g'2 | R1 |
}
bass = \absolute {
  c4 g, e c | f,4 g, g,2 | R1 |
  c4 g, e c | f,4 g, g,2 | R1 |
  c4 g, e c | f,4 g, g,2 | R1 |
  c4 c c c | c4 c c c | c4 c c c | c4 c c c |
  c4 c c c | c4 c c c | c4 c c c | c4 c c c |
  R1 |
  c4 g, e c | f,4 g, g,2 | R1 |
  c4 g, e c | f,4 g, g,2 | R1 |
}
