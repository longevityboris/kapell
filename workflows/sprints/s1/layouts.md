You are working in /Users/biobook/Music/llm-music/kapell-wt/s1-layouts, a git worktree (branch s1-layouts) of kapell, a Python CLI composition kit. Do NOT commit; leave your changes for review.

Goal: `kapell engrave --layout organ|orchestra|ensemble|all`. Today only piano and quartet layouts exist (the fixture's score/piano.ly and quartet.ly). You own ONLY src/kapell/piece/engrave.py, src/kapell/commands/engrave.py, templates/layouts/**, tests/unit/test_engrave.py.

Fixture: The Neighbour at /Users/biobook/Music/llm-music/fugue-jp/ricercar (read only): score/music-voices.ly (voices soprano, alto, tenor, bass as \absolute variables), score/music-global.ly (\global, \marks, \dynamicsLine), score/piano.ly and quartet.ly as style references, and the version specs under performance/bach_organ/, performance/symphonic/ and performance/quintet/ (registration and orchestration specs, showing which instrument plays which voice when).
Layouts:
- organ: three staves (manual I: soprano + alto, manual II: tenor, pedal: bass), registration changes from performance/bach_organ/ printed as text marks at their bars if practical.
- ensemble (piano + string quartet): piano staff pair plus four string staves; parts rest where the quintet spec rests them if you can derive it simply, otherwise print all voices and note that.
- orchestra: a condensed conductor's score (strings, woodwinds, brass groups) derived from performance/symphonic/ spec where simple; a short-score fallback is acceptable if clearly labelled.
Titles: "The Neighbour", subtitle "Ricercar a 4 on the Theme from Jurassic Park, for <forces>". Engrave into a temporary output dir with lilypond 2.26 (installed); zero errors; open nothing.
Finish with a short report: layouts done, page counts, warnings, what is approximate.
