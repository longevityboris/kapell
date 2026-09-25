\version "2.24.0"
% Compile test for the final skeleton: lilypond -o /tmp/sk compile_test.ly (expects no warnings)
\include "SK_final.ly"
\score {
  \new PianoStaff <<
    \new Staff << \key bes \minor \new Voice { \voiceOne \soprano } \new Voice { \voiceTwo \alto } >>
    \new Staff << \key bes \minor \clef bass \new Voice { \voiceOne \tenor } \new Voice { \voiceTwo \bass } >>
  >>
  \layout { }
}
