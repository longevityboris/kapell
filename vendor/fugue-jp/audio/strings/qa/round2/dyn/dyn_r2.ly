\version "2.24.0"
%% Round-2 strings QA dynamics score (an_dyn.py).  Each voice keeps to one register
%% the round-1 score did not use: violin I on the E string, violin II on the G/D
%% strings, viola and cello on their lowest strings (mud / low-end checks).
%% Bars 1-2, 4-5, 7-8: the same phrase; the plan plays it pp, mf, ff.
%% Bars 10-17: one note per voice held eight bars (tied) under pp -> ff -> pp.
%% Bars 19-20 and 22-23: the phrase at mf, first with violin II (alto) marked
%% "subject", then without roles (voicing: only the alto stem may change).

soprano = \absolute {
  e''4 fis''8 g'' a''4 b'' | c'''8 b'' a'' g'' fis''2 |
  R1 |
  e''4 fis''8 g'' a''4 b'' | c'''8 b'' a'' g'' fis''2 |
  R1 |
  e''4 fis''8 g'' a''4 b'' | c'''8 b'' a'' g'' fis''2 |
  R1 |
  a''1~ | a''1~ | a''1~ | a''1~ | a''1~ | a''1~ | a''1~ | a''1 |
  R1 |
  e''4 fis''8 g'' a''4 b'' | c'''8 b'' a'' g'' fis''2 |
  R1 |
  e''4 fis''8 g'' a''4 b'' | c'''8 b'' a'' g'' fis''2 |
  R1 |
}

alto = \absolute {
  g4 a8 b c'4 d' | e'8 d' c' b a2 |
  R1 |
  g4 a8 b c'4 d' | e'8 d' c' b a2 |
  R1 |
  g4 a8 b c'4 d' | e'8 d' c' b a2 |
  R1 |
  d'1~ | d'1~ | d'1~ | d'1~ | d'1~ | d'1~ | d'1~ | d'1 |
  R1 |
  g4 a8 b c'4 d' | e'8 d' c' b a2 |
  R1 |
  g4 a8 b c'4 d' | e'8 d' c' b a2 |
  R1 |
}

tenor = \absolute {
  c4 d8 e f4 g | a8 g f e d2 |
  R1 |
  c4 d8 e f4 g | a8 g f e d2 |
  R1 |
  c4 d8 e f4 g | a8 g f e d2 |
  R1 |
  c1~ | c1~ | c1~ | c1~ | c1~ | c1~ | c1~ | c1 |
  R1 |
  c4 d8 e f4 g | a8 g f e d2 |
  R1 |
  c4 d8 e f4 g | a8 g f e d2 |
  R1 |
}

bass = \absolute {
  c,4 d,8 e, f,4 g, | a,8 g, f, e, d,2 |
  R1 |
  c,4 d,8 e, f,4 g, | a,8 g, f, e, d,2 |
  R1 |
  c,4 d,8 e, f,4 g, | a,8 g, f, e, d,2 |
  R1 |
  c,1~ | c,1~ | c,1~ | c,1~ | c,1~ | c,1~ | c,1~ | c,1 |
  R1 |
  c,4 d,8 e, f,4 g, | a,8 g, f, e, d,2 |
  R1 |
  c,4 d,8 e, f,4 g, | a,8 g, f, e, d,2 |
  R1 |
}
