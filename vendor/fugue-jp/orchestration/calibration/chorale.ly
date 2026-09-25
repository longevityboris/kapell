\version "2.24.0"
% Calibration chorale for tools/mix.py: eight bars of plain four-part B-flat major at one dynamic
% (mf in chorale.plan.json). mix.py renders it on every renderer of an ensemble and levels the
% renderers so that this chorale has the same K-weighted loudness on each (see ORCHESTRATION.md).
% Do not edit: the cached calibration (calibration.json) is keyed by this file's hash.
soprano = \absolute {
  d''2 c''2 | bes'2 c''2 | d''2 ees''2 | d''1 |
  f''2 ees''2 | d''2 c''2 | bes'2 a'2 | bes'1 |
}
alto = \absolute {
  f'2 f'2 | f'2 f'2 | f'2 g'2 | f'1 |
  f'2 g'2 | f'2 ees'2 | d'2 ees'2 | d'1 |
}
tenor = \absolute {
  bes2 a2 | bes2 a2 | bes2 bes2 | bes1 |
  bes2 bes2 | bes2 a2 | f2 f2 | f1 |
}
bass = \absolute {
  bes,2 f,2 | d,2 f,2 | bes,2 ees,2 | bes,1 |
  d,2 ees,2 | f,2 f,2 | d,2 f,2 | bes,1 |
}
