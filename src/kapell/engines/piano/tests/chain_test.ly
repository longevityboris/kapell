\version "2.24.0"
%% Dynamics test for the perform.py -> render_piano.py chain (see make_chain_test.py).
%% Bars 1-4, 6-9, 11-14: the same phrase (theme bars 1-4, B-flat major) three times;
%% the plan plays it pp, mf, ff. Bars 16-23: one repeated bar of eighths over a
%% repeated bass, so that pitch stays constant while the plan's hairpin goes
%% pp -> ff (bars 16-19) and back to pp (bars 20-23).

soprano = \absolute {
  bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes' |
  R1 |
  bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes' |
  R1 |
  bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes' |
  R1 |
  f'8 bes' d'' bes' f' bes' d'' bes' | f'8 bes' d'' bes' f' bes' d'' bes' |
  f'8 bes' d'' bes' f' bes' d'' bes' | f'8 bes' d'' bes' f' bes' d'' bes' |
  f'8 bes' d'' bes' f' bes' d'' bes' | f'8 bes' d'' bes' f' bes' d'' bes' |
  f'8 bes' d'' bes' f' bes' d'' bes' | f'8 bes' d'' bes' f' bes' d'' bes' |
  R1 |
}

bass = \absolute {
  bes,1 | d2 bes, | ees2 c | f,2. bes,4 |
  R1 |
  bes,1 | d2 bes, | ees2 c | f,2. bes,4 |
  R1 |
  bes,1 | d2 bes, | ees2 c | f,2. bes,4 |
  R1 |
  bes,4 f bes, f | bes,4 f bes, f | bes,4 f bes, f | bes,4 f bes, f |
  bes,4 f bes, f | bes,4 f bes, f | bes,4 f bes, f | bes,4 f bes, f |
  R1 |
}
