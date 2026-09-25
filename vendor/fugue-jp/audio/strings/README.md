# String-quartet renderer

Turns the multi-voice MIDI written by `tools/perform.py --target strings` (or any
one-voice-per-track MIDI) into a solo string quartet in a concert hall: violin I,
violin II, viola and cello from the University of Iowa MIS solo-string recordings
(pp, mf and ff played separately by real players), built into SFZ instruments and
played by sfizz, one dry stem per voice, placed on stage, convolved with the
measured Detmold Konzerthaus response. Output is 48 kHz / 24-bit stereo WAV at a
true peak of -1 dBTP plus a 256 kb/s AAC `.m4a`. Nothing is played through the
speakers.

## Setup (once)

```sh
./setup_strings.sh              # install what is missing, build, verify (a second run: under 30 s)
./setup_strings.sh --check      # verify only (no downloads, no builds)
./setup_strings.sh --force      # also re-analyse and rebuild the instruments (about 8 min)
./setup_strings.sh --with-vpo3  # also install Virtual Playing Orchestra 3 (comparison only)
```

Assets live outside git in `$SAMPLE_LIBRARIES` (default `~/Music/SampleLibraries`).

| step | what | verified by |
|---|---|---|
| Iowa MIS | 131 arco stereo AIFFs (2.2 GB) scraped from the four 2012 string pages | file count and a manifest SHA-256 per instrument (Iowa publishes no checksums) |
| sfizz_render | the piano's pinned sfizz (commit `f5c6e29`) with the float-output patch | renders a sine and must write 32-bit float at 48 kHz |
| hall IR | the piano's `make_ir.py` output (Detmold, CC BY 4.0), built if missing | file present |
| analysis | `iowa_analyze.py`: segments every chromatic run into notes, pitch, level, attack | `analysis.json` present |
| instruments | `iowa_build.py`: one string per note, trim, 48 kHz, slow pitch drift and the level of the first second flattened, grain-spliced 10 s sustain, attack pitch drift flattened (`attack_tune.py`), K-weighted level calibration, SFZ; violin II plays a neighbouring key's take (a semitone away, same string) where it would otherwise use violin I's very recording | every sample carries its attack analysis and the current flattening version (`flat_v`); SFZ regenerated when the builder or the tuning corrections are newer |
| tuning and shape | closed loop: `verify_tuning.py` measures every key x layer through sfizz at 0.45-1.05 s and 1.05-1.9 s with YIN and harmonic peaks, `iowa_build.py --retune` folds the errors into `tuning_corrections.json`, up to three passes; `verify_shape.py` checks every normal and slurred region's first second | every key x layer within 5 c in both windows by both estimators (steady), every key x layer x stroke within 30 c 40-200 ms after the note-on (attack); no region sits 3 dB low or dips 5.5 dB and jumps back in its first second; stamped in `verified.sha256` so an unchanged install is not re-measured |
| smoke test | a three-voice render through `render_quartet.py` | 48 kHz stereo WAV + m4a, true peak -1 dBTP |

A second run leaves every SFZ, `tuning_corrections.json` and `meta.json`
byte-identical (checked with `qa/qa_setup.sh`).

## The chain

```sh
python3 ../../tools/perform.py SCORE.ly PLAN.json out/x.mid --target strings
python3 render_quartet.py out/x.mid -o out/x            # out/x.wav, out/x.m4a

./render_demos.sh    # the old fugue (fugue-jp/fugue.ly, demo/fugue_plan.json), the
                     # contrabass-doubling variant, VPO3 comparison, dynamics proof, and the
                     # final renders' test music (design/final-lab SK_final.ly + plan.json)
```

The demo plan: pp opening, the subject and answer entries brought out with
`role_level`, a hairpin to f at the stretto, ff to the end.

| option | default | meaning |
|---|---|---|
| `--wet` | 0 | the hall's energy relative to the dry sound, both summed over the two channels, measured on the music being rendered (the renderer convolves at unit gain, measures, and scales). 0 is the piano renderer's `--wet-db` default and means the same thing: the hall as loud as the dry quartet, C80 +4.6 dB on SK_final, +4.5 on the old fugue. +4 is about the old default's hall (C80 +2.4). The console and the report (`hall_stats`: `hall_re_dry_db`, `ir_scale_db`, `c80_db`) give both figures measured on the render |
| `--bass-double` | off | `on` / `auto`: a contrabass an octave below the cello; `auto` fades it in where the cello is at `--bass-threshold` (ff) or above; CC22 on the cello track overrides |
| `--map` | | `soprano=vn1,alto=vn2,...` or `0=vn1`; exact name first, then whole words |
| `--legato-pre-ms` / `--legato-xfade-ms` | 25 / 5 | a slurred note starts 25 ms early (30 ms fade-in); its predecessor lets go 5 ms after the beat |
| `--normal-pre-ms` | 15 | a new-bow stroke starts this early |
| `--lead-in` | 0.3 | silence before the first note-on (the piano uses 0.3 s too) |
| `--keep-start` | | the output starts at MIDI time 0 instead (measurements) |
| `--stems`, `--report` | | dry stems (same start as the mix) and a JSON report; `offset_s` in the report is the MIDI time of the output's first sample (negative = lead-in) |
| `--lib vpo3` | | the comparison library |
| `QUARTET_SHORT_REL` | 0.09 | environment: release of a short note into the next one (s) |

## MIDI contract (what perform.py writes, what the renderer reads)

One track per voice named soprano / alto / tenor / bass (or pedal), channels 0-3,
programs 40/40/41/42, a text marker `perform.py target=strings` in the tempo
track. Voice names map to Violin I / Violin II / Viola / Cello; instrument names
("Violin II", "Vc.", ...) and GM programs work as well.

* **CC1** = dynamic level on perform.py's scale (ppp 36, pp 49, p 62, mp 75,
  mf 88, f 101, ff 114, fff 127), sampled every 16th; ramps are reconstructed.
  It picks the recorded layer and sets loudness (about 3.5 dB per step) and
  brightness (a high shelf that follows CC1 inside each layer).
* **CC11** = expression gain at half the GM depth (perform.py sends CC11 = CC1,
  so full depth would double-count: pp to ff would be about 32 dB instead of 20).
* **CC7** = channel volume (GM curve). CC10 and CC64 are ignored.
* **velocity** = accent and attack bite (15-41 ms fade-in of a new bow stroke).
* optional **CC20** = articulation per note (0-63 new bow, 64-95 slurred, 96-127
  short), **CC21** = release time per note, **CC22** on the cello = doubling amount.
  Without them the renderer infers articulation from the note timing.
* no CC1 at all (a `--target piano` file): the level comes from the velocities.

perform.py and the renderer agree on names, channels and CC meaning; nothing in
perform.py had to change for this renderer beyond the optional `role_level`.

## How it sounds the way it does

**Dynamics are recordings, not gain.** Each key has a pp, an mf and an ff take.
Two takes of the same note sounding together interfere (independent vibrato: the
sum swells and fades by 5-8 dB at 0.2-3 Hz), so they never sound together for
long. The SFZ crossfades only in two narrow zones (CC1 65-72 and 104-111) and the
renderer never parks in them: it holds each layer in its own range (pp up to 65,
mf 72-104, ff from 111: the first values where sfizz plays one take only; at 71
and 110 the lower take still sounded 8 dB down), switches with hysteresis (up at 70 / 109, down at 66 /
106), does the switch at the nearest note-on (a 50 ms crossfade on the new note)
or, inside a held note, over 0.3 s, and restores the loudness of the true CC1 as
a gain. Timbre changes at the layer switch and, more gently, with a CC1-driven
high shelf inside each layer (+-2.5 dB on the violins, less below).

**Attacks are in tune.** Iowa players often start a note off pitch and settle
over 0.2-0.5 s (the G-string A4 of the second violin starts 120 c flat and is
still 20 c flat at 200 ms). A short note is only that attack, so the builder
tracks the attack's pitch (narrow-range YIN), takes its slow trend and removes
it by time-varying resampling up to the steady part; bow noise and transient
stay. Where an ff stroke on a low string scratches without pitch (cello C2 ff,
about 0.2 s), the short and normal strokes start 30-40 ms before the pitch
settles.

**Articulation.** Short notes (under 260 ms) use the recorded attack with an 8 ms
fade-in and a small accent decay; slurred notes enter in the sustain, 25 ms early
with a 30 ms fade, while the previous note releases just after the beat; new bow
strokes keep at most 100 ms of a recorded swell. A long note before a short one
lifts 25 ms early, a repeated key dips about 14 dB instead of stopping.

**Balance.** Every sample is calibrated on its K-weighted (BS.1770) steady level,
keeping at most +-2 dB of the instrument's natural register slope, so the four
instruments sit within about 2 dB of each other in the fugue's tutti.

**Hall.** The Detmold response (source left of centre; right-side players get
the mirrored response) is normalised to unit energy over both channels. That is
0 dB re dry only for white noise: the quartet's energy sits at 125 Hz-2 kHz,
where the hall rings longest, and there the same IR is about 8 dB louder (+8.3
dB on SK_final, +8.1 on the fugue). So the renderer convolves every player at
unit gain, measures the hall's energy against the dry sum on the piece it is
rendering, and scales it to `--wet`; C80 (dry plus the first 80 ms of the hall
against the rest) is measured on the same signals. The measured file is 1.44 s long and faded at
-50 dB; at load it is continued to 3.5 s with octave-band noise decaying at the
rates fitted to the measured response (63 Hz 2.1 s, 125 Hz 1.9 s, 250 Hz-2 kHz
1.5-1.6 s, 4-8 kHz 1.2-1.3 s), so the final chord dies away like the room.

## Library choice (measured)

Both candidates were rendered from the same dynamics test and the same fugue MIDI
(`verify_dynamics.py` -> `out/verify/dynamics_{iowa,vpo3}.json`, `qa_render.py` ->
`out/demo/qa_{iowa,vpo3}.json`; `render_demos.sh` regenerates both):

| | Iowa MIS (chosen) | VPO3 solo strings |
|---|---|---|
| timbre change pp -> ff (centroid ratio, median over keys) | 1.14 (violin) from the recordings alone; 1.45 with the CC1 brightness shelf | 1.00: one layer, dynamics are gain only |
| short notes in the fugue (level rise at the onset) | +5..+7 dB | -1.8 dB (notes do not articulate) |
| steady pitch | within 5 c after the closed loop (every key x layer, max 3.7 c) | 15-18 c spread from vibrato, several keys 15-18 c off |
| licence | free for any use | free for music, redistribution with credit |

VPO3 stays available as `--lib vpo3` for comparison.

## Measured evidence

All numbers from `qa/` (the adversarial QA suite: `qa_chain`, `qa_dynamics`,
`qa_layers`, `qa_attack_pitch`, `qa_edge`, `qa_mix`, `qa_clicks`, `qa_variants`,
`qa_setup.sh`; results in `qa/results/*.json`).

State measured: the instruments as `setup_strings.sh --force` builds them from
scratch (7.5 min), `render_quartet.py` at commit time; demo input the old fugue
(648 notes) through perform.py with `qa/fugue_qa.plan.json`.

**Chain** (perform.py -> render_quartet): 648/648 notes rendered, none dropped,
stuck or transposed; renderer timing = mido within 0.05 ms.

| onset (ms after the MIDI note-on) | median | p90 | within 20 ms |
|---|---|---|---|
| slurred note, new pitch overtakes the old (n=350) | +10 | +20 | 96 % (was +65, 2.6 %) |
| short stroke, pitch change (n=189) | 0 | +10 | 97 % |
| new bow after a rest, -20 dB / -6 dB (n=20) | -7 / +18 | 0 / +37 | 100 % / 70 % (-6 dB was +44) |
| repeated key: dip between the strokes (n=88) | 14 dB | 17 dB | (was 42 dB, silence) |

Pitch of long notes, median |c| / p95: vn1 1.2/3.8, vn2 1.2/4.9, va 0.7/2.5, vc
1.1/3.3; no note more than 50 c off (the three quarter-tone-flat alto A4s are gone).
Attack pitch (median 40-200 ms after the note-on, every key x layer x stroke
including the two stretched keys below each compass: 1416 notes through sfizz,
spectral estimator): median 1.1-1.6 c per instrument; over 15 c only violin D#7
pp (+26 c) and the second violin's ff C#6 (+22..26 c, a wide ff vibrato) and F5
(+16 c, normal stroke). Setup's YIN gate (1356 notes, the compass only) finds
none over 15 c.

**Dynamics** (perform.py hairpins, dry stems, K-weighted, pp -> mf -> ff):
vn1 -44.3/-32.0/-22.6 dB, vn2 -41.9/-29.5/-21.1, va -43.4/-30.5/-21.9, vc
-42.5/-29.7/-20.4, i.e. pp -> ff +20.8..+22.0 dB. Timbre follows: centroid pp -> ff
vn1 927 -> 1805 Hz, vn2 478 -> 884, va 389 -> 531, vc 193 -> 254; gain-matched
2-5 kHz band +6.0 / +8.2 / +12.9 / +13.2 dB. Direct CC1 49/88/114 with CC11
fixed: mf -> ff band +1.7 (vn1), +3.0, +2.5, +5.9 dB; loudness within 0.9 dB of
the CC1 target at every step (`verify_dynamics.py`). The eight-bar held-chord
hairpin is smooth: largest 0.5 s step 2.4 dB, 0-2 non-monotonic 0.5 s steps per
half (was an 8 dB jump in 0.3 s on violin II). Held notes at a fixed CC1 wander
0.8-2.2 dB (median) at every named level (was 5-6 dB at p and f). Marking the
viola as subject lifts it 3.2 dB; across the fugue's 13 entries role_level lifts
each by 0.3-4.7 dB.

**Dynamics proof** (`make_test_midi.py`: the same phrase at CC1 49/88/114, CC11
and velocity fixed, dry stems, RMS dB / centroid):

| | pp | mf | ff |
|---|---|---|---|
| Violin I | -36.0 dB, 781 Hz | -28.5 dB, 1407 Hz | -21.6 dB, 1761 Hz |
| Violin II | -37.2 dB, 871 Hz | -28.4 dB, 1187 Hz | -22.4 dB, 1400 Hz |
| Viola | -37.3 dB, 714 Hz | -28.3 dB, 723 Hz | -22.0 dB, 825 Hz |
| Cello | -36.3 dB, 296 Hz | -27.1 dB, 330 Hz | -19.9 dB, 404 Hz |

(re-rendered after the round-2 rebuild; `verify_dynamics.py` on the rebuilt
instruments: loudness within 0.8 dB of the CC1 target at every step, largest
key-level inversion 1.6 dB, cello Eb3 at CC1 62 -> 68)

and on one held note, CC1 40 -> 124 -> 40: level correlation with CC1 0.99-1.00,
centroid correlation 0.58-0.89, share of energy above 2 kHz 2 % -> 55 % (violin I).

**Mix**: 48 kHz / 2 ch / PCM_24; m4a AAC 256 kb/s; true peak -1.00 dBTP (m4a
decoded -1.04), no clipped samples; -14.7 LUFS, loudness range 21 LU; tutti
balance re the loudest voice (median / p10) vn1 -1.6/-5.6, vn2 -1.7/-4.8, va
-1.6/-5.3, vc -1.1/-3.8; L/R correlation 0.62; no clicks in any job or the mix
(detectors validated on planted events). These mix figures are from round 1, at
the old hall level (4.4 dB over the dry sound, C80 +2.5 dB, not the +8.4 the
renderer printed then); see Round 2 below for the current hall. The tail reaches -60 dB
re the last note 1.65 s after the key lift.

**Other**: `--target piano` MIDI renders all 648 notes (dynamics from velocities,
22.5 dB range); `--bass-double on/auto`: 112/112 cello notes doubled an octave
down, auto silent until the ff section; CC20/CC21 input, "Violin II" before
"Violin I", six voices, a hanging note and a malformed `--map` are handled (see
`qa/results/edge.json`). Setup: `--check` and two install runs 19-29 s, every
built file byte-identical.

## Round 2: the final renders' test music

QA round 2 (`qa/round2/`, defects in `qa/round2/qa_r2_defects.json`) rendered
SK_final.ly with plan.json (the design lab's 66-bar test piece) and found two
major and five minor defects. State measured now: the instruments as
`setup_strings.sh` builds them (tuning and shape gates passed, stamp matches),
SK_final at 703 notes (the score has grown since QA's 631), default options.
Results in `qa/round2/results/*_sk_fix.json`, `samples_shape.json`,
`ladder.json`, `edge.json`.

| defect | fix | before -> after |
|---|---|---|
| 69 of 1094 sustain regions sat low, dipped 5.5-17 dB and jumped back in their first second: every long violin I Eb5 wobbled 6.65-7.5 dB (major) | `iowa_build.py` flattens the level of the first second after the attack (and the sample's slow pitch drift) before the sustain is spliced; `verify_shape.py` gates it in setup | flagged regions 69 -> 0; violin I's six long Eb5s 2.75-3.06 dB p2-p98; violin II's D4s 5.8-6.3 -> 2.1-2.3 dB; violin I p90 over its long notes 6.6 -> 3.1 dB. The worst held notes left (3.4-5.3 dB) all have a layer switch inside them |
| `--wet -4` was reverb re dry for white noise only: on the music the hall was 4.4 dB over the dry sound at C80 +2.5 dB while the renderer printed +8.4 (major) | `--wet` is measured and set on the music (see Hall); default 0 dB, the piano's | hall re dry 0.0 dB, C80 +4.6 dB (renderer); +0.1 dB / +4.7 dB measured independently on the file (`an_mix.py`). The new pitch dominates the previous note's partials 0.25 s in for 82 / 86 / 81 % of changes (notes < 0.5 s / 0.5-1 s / >= 1 s) against 74 / 85 / 78 % at the old level on the same music (dry sum 94 / 95 / 92 %); viola 76 % |
| the mf and ff home floors (CC1 71 / 110) still mixed two takes | home ranges mf 72-104, ff 111-127 | at 72 / 111 held notes wander within 0.12 dB of the 88 / 114 anchors (was 2-3.5 dB extra at 71 / 110); the renderer sends 71 / 110 for 0.2-0.33 s per instrument, inside ramps (violin I sat at 71 for 22.5 s) |
| 22 key x layer 5-10 c off (violin I Db5 flat on every note) | tuning gate 15 c -> 5 c in two windows by two estimators, closed loop | ladder max 3.7 c, p95 2.2 c, none over 5 c; SK_final pitch p95 soprano 6.2 -> 3.0 c, alto 4.3 -> 2.6, notes over 5 c 18 -> 0 |
| violins I and II played the same recording on 20 keys: a unison was one violin 6 dB louder | violin II takes the neighbouring key's take there (51 key x layer regions), pitched a semitone | C4 waveform correlation 1.00 -> -0.41, G3 -> 0.65; the swapped keys sit within +-2.5 dB of their neighbours (mostly 1 dB) |
| sfizz slips one sample on its 256-sample block grid 10-20 ms into some notes | not fixed | 0 detections in the mix; -18 to -30 dB re the instrument in the dry stems |
| a key re-struck before its own note-off is cut at the first note-off | not fixed | perform.py never writes this; other MIDI sources would hear it |

SK_final file: 703/703 notes accounted, none dropped, stuck or hanging; 48 kHz /
24-bit, -1.00 dBTP (m4a decoded -0.93), -18.4 LUFS, LRA 18.2 LU; balance re the
loudest (median) vn1 -1.0, vn2 -2.7, va -1.6, vc -0.8 dB; L/R correlation 0.49;
no clicks in the mix; the tail reaches -60 dB re the final chord 1.6 s after the
last lift. The old fugue demo at the new default: hall 0.0 dB re dry (IR -8.1
dB), C80 +4.5 dB, balance within 1.9 dB, no clicks, short-note rise 5.0-6.4 dB.

Known residuals: in a unison on a swapped key the two takes sit partly in
anti-phase (C4: the sum 1.7-3.4 dB under the energy sum), steady rather than
beating; a layer switch inside a held note is now the largest source of held-note
wobble (up to 5.3 dB over a 7 s crescendo on violin I D5); a few E-string violin notes (91/97/99) swell and fade 5-9 dB at
about 3 Hz within one recording (their own amplitude vibrato); 29 % of the
samples step more than 2 dB and 18 % more than 3 dB within 50 ms somewhere in the
sustain (partly the recordings' own amplitude vibrato, partly grain splices; a
22 s violin A4 at mp: 3.0 dB); a layer switch inside a held note wiggles 1-2 dB over
0.3 s; slurs dip 1-3.5 dB at the change; in fast runs the articulation left in
the mix (4.3 dB) is set by the other voices, not the hall (4.6 dB fully dry).

## Files

| file | role |
|---|---|
| `render_quartet.py` | the renderer (docstring = full MIDI conventions) |
| `hall.py` | stage placement, hall IR (unit energy, tail continuation), C80 |
| `iowa_common.py`, `iowa_analyze.py`, `iowa_build.py`, `attack_tune.py` | the Iowa instrument build |
| `verify_tuning.py`, `verify_shape.py`, `verify_dynamics.py`, `measure_dynamics.py`, `make_test_midi.py`, `qa_render.py` | verification and the dynamics proof |
| `vpo3.py` | VPO3 comparison engine |
| `setup_strings.sh`, `render_demos.sh` | reproducible setup and demo renders |
| `demo/fugue_plan.json` | the demo performance plan |
| `qa/` | adversarial QA scripts and results |

## Sources and licences

* University of Iowa Electronic Music Studios, Musical Instrument Samples (2012
  strings): <https://theremin.music.uiowa.edu/MIS.html>; "freely available ... may
  be downloaded and used for any projects, without restrictions". Pages:
  MISviolin2012.html, MISviola2012.html, MIScello2012.html, MISdoublebass2012.html.
* Detmold SRIR database, Konzerthaus Detmold (Amengual Gari, Sahin, Eddy, Kob, AES
  149th Convention, 2020), CC BY 4.0: <https://zenodo.org/records/4116247>.
* sfizz, BSD-2-Clause: <https://github.com/sfztools/sfizz>.
* Virtual Playing Orchestra 3 (Paul Battersby), free for any music including
  commercial, redistribution only with credit:
  <https://virtualplaying.com/virtual-playing-orchestra/>.
