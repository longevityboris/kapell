# Orchestra renderer (symphonic version)

`render_orchestra.py` turns a multi-track MIDI file (the interface is `CONTRACT.md`) into a romantic
symphony orchestra in the measured Detmold Konzerthaus: 48 kHz / 24-bit WAV at -1 dBTP, AAC m4a, and a
JSON report. Free samples: VSCO-2-CE (CC0), University of Iowa MIS winds and brass, Virtual Playing
Orchestra 3 (string sections' second recording, four-horn section). `setup_orchestra.sh` installs,
builds and verifies everything once (assets live outside git in `~/Music/SampleLibraries`).

## Chain

```sh
# score + plan + orchestration spec -> one MIDI per renderer group (integrity-checked)
python3 tools/orchestrate.py SCORE.ly PLAN.json SPEC.json OUTDIR
python3 audio/orchestra/render_orchestra.py OUTDIR/orchestra.mid -o OUT      # reads OUTDIR/orchestra.orchestra.json
# or, inside an ensemble: python3 tools/mix.py OUTDIR/manifest.json
```

A plain `perform.py --target strings` file also renders (soprano/alto/tenor/bass -> Violins I,
Violins II, violas, cellos), but it is a fallback, not the supported route: the ricercar's alto goes
down to F3, below Violins II's G3, and those notes (three on the skeleton: 26.9 s, 33.9 s, 36.2 s)
are played an octave up and listed in the report's `octave_shifted`. `orchestrate.py` with a spec
that gives those bars to the violas (as `specs/skeleton_symphonic.json` does, 9:4-13:1) keeps every
note at pitch.

The demo skeleton goes through the real chain: `python3 make_demo.py --render` writes
`out/demo_instruments`, `out/demo_tutti`, `out/demo_crescendo` and `out/skeleton_orchestra` (perform.py
+ orchestrate.py with `specs/skeleton_symphonic.json`: 16 part tracks, strings on the four voices,
basses 8vb, the arioso's lament on a solo clarinet, woodwind doublings, a horn (F3) and a timpani roll
(F2) under the bass's dominant pedal F in bars 46-49, a2 horns, trumpet, trombones and tuba only in the
two climaxes and the apotheosis peak).
It is a renderer test, not the final scoring. Rendering the 232 s skeleton takes about 30 s.

## Measurements

`python3 probe_orchestra.py` (per part, alone, dry: held notes low/middle/high of the compass at mf, a
pp-ff-pp hairpin inside one held note, six short notes, a slur; timpani strokes and a crescendo roll)
writes `evidence/probe.json`; `python3 qa_orchestra.py` (skeleton stems, instrument demo, crescendo
demo, final file) writes `evidence/qa.json`. Numbers below are from the current commit.

**Pitch (A4 = 440 Hz).** Probe: 112 of 112 held and slurred notes measured, median 1.0 cents, worst
7.8 cents. Skeleton stems: 1287 of 1311 notes measured, median 0.8 c, p95 4.2 c (hn.2 reads about
3-4 c flat by design: a second track of a part is detuned a few cents, see Seating). The one note over
25 c is a real defect, not a measuring error: a 0.40 s slurred tuba Eb1 in Climax I (85.94 s) sounds
about 50 c flat (YIN -50 c; harmonics 2-5 -49 c). At ff the Iowa tuba has no Eb1, so its D1 plays it,
and that recording is about 50 c flatter in its first half second than in its body (raw D1: -71 c at
0.1-0.5 s, -20 c at 1.0-3.8 s); the tuning corrects the body, so the held Eb1 that follows measures
+0.3 c. It sits under the ff tutti. Timpani are tuned by the builder's kettledrum partial-template fit
(YIN reads a roll +33 c; not a valid measure for a drum); the pedal roll's partials sit at 86-88 Hz
(F2 = 87.3 Hz).

**Dynamics change the timbre.** Per part at pp / mf / ff (demo_instruments, K-weighted level dB and
spectral centroid Hz; richness = harmonics 3+ re 1-2):

| part | pp | mf | ff | richness pp->ff dB | centroid pp / mf / ff |
|---|---|---|---|---|---|
| fl | -43.4 | -34.6 | -27.6 | +6.4 | 2124 / 2461 / 2716 |
| ob | -43.6 | -35.3 | -28.5 | +4.5 | 2314 / 1893 / 2684 |
| cl | -50.0 | -37.3 | -29.0 | +11.5 | 4451 / 2725 / 3495 |
| bn | -46.1 | -36.8 | -30.0 | +3.0 | 1017 / 1103 / 1620 |
| hn | -46.7 | -33.6 | -23.8 | +5.9 | 746 / 692 / 792 |
| tpt | -45.4 | -32.1 | -22.2 | +11.3 | 1202 / 2218 / 2589 |
| tbn | -45.9 | -33.3 | -23.2 | +6.8 | 1439 / 1560 / 3275 |
| btbn | -46.3 | -33.2 | -22.7 | +4.6 | 1242 / 1216 / 2965 |
| tba | -48.0 | -36.0 | -25.9 | +13.9 | 1210 / 751 / 1081 |
| timp | -50.8 | -37.1 | -25.7 | | 1785 / 375 / 375 |
| vn1 | -44.6 | -31.9 | -21.8 | +2.0 | 3699 / 4135 / 4516 |
| vn2 | -43.9 | -31.3 | -21.5 | +9.1 | 2653 / 3312 / 3651 |
| va | -44.6 | -32.0 | -23.4 | -0.7 | 1820 / 2290 / 2645 |
| vc | -42.1 | -30.6 | -21.5 | +0.5 | 1532 / 1983 / 2296 |
| cb | -47.2 | -36.2 | -27.7 | +3.9 | 971 / 1265 / 1491 |

Inside a held note (probe hairpin), level follows CC1 with r = 0.96-1.00 for every part; the timbre
follows it (centroid or richness r > 0.5) for all but the double basses, whose recorded layers barely
differ in colour at A2 (both measures fall slightly as they swell: accepted). The crescendo demo's
centroid does not rise because low brass and timpani join as it grows; its level rises 31 dB with
r = 0.996.

**Entries.** `qa_orchestra.py` times every entry after 0.3 s or more of silence on the stems: the
moment the band of the note's harmonics 1-3 reaches 12 dB below its peak, minus the note-on and the
seat's distance delay. Skeleton: 50 entries, median -4 ms, p10/p90 -18/+10 ms, earliest -24 ms;
the 18 string entries median -2 ms (vn1 -2, vn2 -1, va -4, vc +14, cb +15; earliest -6 ms). Where two
parts enter on the same beat the worst gap is 36 ms (flute/Violins I; ob/vn1 2-24, cl/va 8-24 ms).
The final file's first sample above 1e-5 comes 12 ms before MIDI 0. The older column in `qa.json`
(`onset_med_ms`, the broadband level reaching 6 dB below the first 0.3 s peak) times the bow's swell
into the sustain, not the start of the note (Violins I, cellos and basses +50-58 ms on it); it is kept
for comparison only.
A test of every part alone at mf (six short notes, six 0.8 s notes, each after silence, same rule):
short notes -14..+7 ms median per part, held notes -25..+27 ms (horns and trombones speak early, violas
and Violins II late at mf, as a bow does).

**Short and long notes.** Short notes (CC20 short, 0.2 s) fall 20 dB within 0.25-0.40 s in every part
except the low strings, whose spiccato recordings ring to the next note 0.45 s later (the room of the
recording). Held notes at a constant CC1 hold within 3-5 dB (winds, brass, basses); the upper strings
move 6-11 dB in 100 ms frames inside a held note, as each recording does alone (vibrato and bow; a
sweep of every key, stack against each recording, `sweep_strings.py`). No clicks in any stem or in the
mix; no dropped or stuck notes.

**Seating and hall.** American seating by default (German with the sidecar): violins I 30 deg left at
1 m, cellos 27 deg right, basses 37 deg right at 5 m, woodwinds 6.5-8 m, brass 9-10.5 m, timpani 12 m;
depth delays the direct sound and lowers it `20 log10(10 / (10 + depth))`, the hall is not
attenuated, so the back rows sound further away and wetter. Several tracks of one part (`hn.1` and
`hn.2`, `vc` and `vc.div`) are separate players: each further track sits 3 deg aside and 0.5 m further
back (at most 1.5 m), is detuned a few cents, starts its notes up to 8 ms apart and, for winds and
brass, starts its player order on the next recording (hn.2's player 1 is the Iowa horn); two horn
tracks on one F3 now sum to +2.1 dB over one, not +6 dB of one copy. a4 horns are three recordings
(VSCO, Iowa, and the VPO3 four-horn section at -2 dB for horns 3-4).

**Hall.** The renderer's own default, `--wet -5`, is impulse-referenced (`hall.py`: C80 +9.3 dB). On
this music the orchestra's hall measures -1.3 dB re its dry sound in `tools/mix.py` (wet_db -5), about
5 dB drier than the quartet and piano in the quintet demo (+4 dB each), because the orchestra's energy
sits where the hall rings less. In an ensemble, set the hall as measured on the music:
`groups.orchestra.hall_re_dry_db` in the manifest (the skeleton spec uses +3 dB; the final symphonic
spec sets its own). Final skeleton file (standalone render, wet -5): -19.2 LUFS integrated, loudness
range 26.9 LU, true peak -1.0 dBTP (m4a -0.96 dBFS), L/R correlation 0.48, lead-in 0.3 s (`offset_s`
-0.3).

**Tutti.** The string voices in the skeleton sit within a few dB of the loudest (median re loudest:
vn1 -1.5, vn2 -4.4, va -2.9, vc 0.0 dB), so the inner voices stay audible under the brass.

## Fixes in this round (why; adversarial QA of the symphonic chain)

* Bowed-string entries sounded 32-90 ms before their beat (violas -84 ms median, Violins I -47), a
  48-92 ms flam against the wind doubling them, and the piece's first sound came 96 ms before MIDI 0.
  The renderer moved every normal note earlier by the recording's `latency_ms`, which
  `tune_orchestra.py` measures as note-on to 6 dB below the peak of the first 0.6 s: for the string
  section recordings (54-96 ms) that is the bow's swell into the sustain, not the start of the note.
  Bowed strings now keep only the 15 ms bow pre-roll (as the quartet renderer); their short notes keep
  the staccato layers' measured latency (those recordings do start late: -14..+4 ms with it).
  Trombones get half their latency (they were 38-46 ms early, now 16-18). Winds and horns keep theirs:
  without it the clarinet and horns enter 31-56 ms late. Result above (Entries).
* The horn and timpani pedal sat in bars 42-45 (`inversa+7 .. pedal_climax`), where the bass has no
  pedal: one lone 2.5 s C3 roll. They now hold the bass's F pedal in bars 46-49 (`pedal_climax .. +4`):
  one 11.85 s F2 roll and a horn F3, at -12.5 dB (timpani) and -10.7 dB (horn) re the orchestra's dry
  sum there. The clarinet doubles the tenor from its subject entry (bar 37), not the entry's second bar.
* Same-part tracks were one player: `hn.1` and `hn.2` in unison rendered bit-identical (+6 dB, one
  louder horn), against CONTRACT section 2 (see Seating). In a4 horns player 4 was a second copy of
  player 1's VSCO recording (+7 c, +30 ms), which combed 17-26 dB per harmonic; the section recording
  now stands for horns 3-4 as intended.
* Timpani strokes rang about 3 s whatever the note length (the hit samples were `one_shot`, so sfizz
  ignored the note-off), so quick strokes on different drums smeared. The note-off now starts the
  CC21 release (CONTRACT section 4): a 0.3 s F2 stroke is 54 dB down 0.2 s after its note-off.
* Stems of tracks named with ':' or '/' (`fl:oct` -> `fl_oct.wav`) were left out of `mix.py`'s
  alignment measurement; the name rule is now in CONTRACT section 1, the report maps stem files to
  tracks (`stems`), and `mix.py` maps them back.

## Earlier fixes (why)

* Notes inside the contract compass were silent where no recording reached (Violins I D7-E7, cello A5,
  basses E4-G4, tuba E4-F4): the extreme samples' regions now reach the part's compass
  (`orch_build.key_bounds`), and the renderer still routes such notes to the set with the closest
  sample.
* The two double-bass recordings summed on one held note beat slowly against each other (a held A2
  faded 12 dB in 4 s): the basses play VSCO, with VPO3 only where VSCO has no sample.
* A note only some recordings of a string stack reach keeps the stack's total level (Violins II's top
  octave was 4 dB low).
* The Iowa tuba's pp layer carried hiss that the layer calibration lifted (-13 dB re the note above
  5 kHz): the tuba is low-passed at 3.5 kHz (its ff has nothing above 5 kHz at -43 dB).
* Low notes were tuned on their first second with YIN, which is biased below 80 Hz and misses a
  recording that settles later (held tuba Eb1 -22 c, F#1 +10 c): `tune_orchestra.py` now measures
  sustains 1.0-3.8 s into a 4 s note, from harmonics 2-5 below 80 Hz, and the tuba, bass trombone and
  basses were retuned (median 0.4 c, p95 1.8 c). `evidence/tuning_summary.json` is refreshed from
  `built/tuning_verify.json`: horns, bassoons and cellos were only re-verified with the new low-note
  measure, not retuned (their worst values, vc/vsco 11 c and hn/vsco 5 c, are 0.2 s short-note regions
  below 80 Hz, where the harmonic measure has little to work with).

## Limits

* Upper strings fluctuate inside held notes as their recordings do; the vn1 stack is not worse than
  either recording alone, but it is not a steady modern library sustain.
* Entry timing (above): the strings enter -6..+22 ms around the beat, winds -18..+24 ms, horns and
  low brass up to 24 ms early; where a wind doubles a string entry the two may be up to about 36 ms
  apart. The old -6 dB-re-peak check could not see the 32-90 ms early string entries this round fixed,
  because the compensation targeted that very criterion; the entry check above is the one to watch.
* The 0.40 s tuba Eb1 at ff (Pitch, above) is about 50 c flat for its short length.
* Timbre inside a double-bass hairpin barely changes (see above).
* Wind chords on one track render but are logged; the orchestration tool keeps winds monophonic.
* Timpani on a pedal: use `pedal_points` mode `sustain` with `articulation: roll`. Mode `repeat`
  (repeated strokes) fails `orchestrate.py`'s integrity check ('pedal note ... is not a pitch bass
  holds': the first stroke inherits a humanised onset a few ms before the notated start).
* Timpani strokes are damped at the note-off (default release 0.35 s): a stroke written short stops
  short; write the note as long as the drum should ring.
* `tools/mix.py` on the symphonic skeleton (`out/skeleton_symphonic.mix.json`, hall +3.0 dB re dry
  on the music = wet -0.65 dB impulse-referenced, C80 +5.9 dB): attacks against MIDI -3.4 ms (356
  entries), per-note entry lag p10/p90 -15/+29 ms (was -22/+42 before this round's latency fix), all
  notes +0.9 ms; -19.3 LUFS, LRA 25.8 LU, -1.0 dBTP (m4a -1.01), first sample 12 ms before MIDI 0 (was
  96). Its click scan flags 10 points (86.4 s and 176.6-181.2 s): at each the bass trombone's stem
  carries 57-65 dB more energy above 8 kHz than its local median, the Iowa ff recording's rasp (the raw
  file is as bursty as the stem), not splices: the stems' own click scan finds none.
* The tuning corrections and the regenerated SFZ files live in `~/Music/SampleLibraries/Orchestra/built/`
  (outside git); `setup_orchestra.sh --force` rebuilds them from the committed `orch_build.py` and
  `tune_orchestra.py`.
