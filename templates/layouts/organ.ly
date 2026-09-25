\version "2.24.0"
%% kapell layout template: organ (two manuals and pedal). Filled by `kapell engrave --layout organ`:
%% @TITLE@ and @SUBTITLE@ come from kapell.toml [piece]. The music comes from the project's score
%% files (music-global.ly: \global \marks \dynamicsLine; music-voices.ly: \soprano \alto \tenor \bass),
%% found through lilypond's include path.
\include "music-global.ly"
\include "music-voices.ly"

\header {
  title = "@TITLE@"
  subtitle = "@SUBTITLE@ (organ)"
  tagline = ##f
}
\paper { #(set-paper-size "a4") ragged-last-bottom = ##t }

\score {
  <<
    \new PianoStaff \with { instrumentName = "Manuals" } <<
      \new Staff = "upper" << \global \marks
        \new Voice = "soprano" { \voiceOne \soprano }
        \new Voice = "alto" { \voiceTwo \alto } >>
      \new Dynamics \dynamicsLine
      \new Staff = "lower" << \global \clef bass
        \new Voice = "tenor" { \tenor } >>
    >>
    \new Staff = "pedal" \with { instrumentName = "Pedal" } << \global \clef bass
      \new Voice = "bass" { \bass } >>
  >>
  \layout {
    \context { \Score
      barNumberVisibility = #all-bar-numbers-visible
      \override BarNumber.break-visibility = #end-of-line-invisible
      \override BarNumber.font-size = #-2 }
  }
}
