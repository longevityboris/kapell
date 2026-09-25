# Orchestration and ensemble mix

Two tools turn the four-voice score into ensemble recordings:

```sh
# score + performance plan + orchestration spec -> one MIDI per renderer group (+ manifest, integrity check)
python3 tools/orchestrate.py SCORE.ly PLAN.json ORCH.json OUTDIR
# render every group, align, place in one hall, master -> WAV + m4a
python3 tools/mix.py OUTDIR/manifest.json
```

The demo (piano quintet on the skeleton):

```sh
python3 tools/orchestrate.py design/final-lab/SK_final.ly design/final-lab/plan.json \
        orchestration/quintet_skeleton.json orchestration/out/skeleton_quintet
python3 tools/mix.py orchestration/out/skeleton_quintet/manifest.json
#   -> orchestration/out/skeleton_quintet.wav, .m4a, .mix.json (report)
```

`python3 tools/orchestrate.py ... OUTDIR --check` re-runs only the integrity check on existing output.
`orchestration/tests/test_orchestrate.py` runs the checker's mutation tests and the contract checks.

## 1. What orchestrate.py does

* It imports `perform.py` and runs it once per renderer target on the same plan: `--target piano`
  velocities for the piano (and the organ), `--target strings` CC1/CC11 envelopes and accent
  velocities for bowed and wind parts. perform.py's timing (tempo map, breaths, fermatas, humanised
  onsets, melody lead) does not depend on the target, and orchestrate.py checks this: every group
  file gets the same tempo track and ticks per quarter (960), and a note doubled in two groups
  starts on the same tick in both.
* Each performed note is matched to its score note (lyparse). The spec's windows route notes to
  parts by their **notated start**: a note belongs to the window `[at, until)` that contains its
  start. A note held across a hand-off stays with the part that started it; if that part's next
  window starts before the note ends, the held note is shortened to the new note (reported).
* Nothing is composed: every part note is a score note of the assigned voice, moved by whole
  octaves only (`octave` -24, -12, 0, +12, +24). Derived pedal points (below) hold a pitch that the
  source voice itself holds.
* Each group's MIDI follows its renderer's own contract (section 4) and keeps perform.py's
  `perform.py target=...` marker in the tempo track (the piano and quartet renderers pick their
  velocity scale and CC meaning from it), plus an `orchestrate.py group=...` text event.

## 2. The spec (ORCH.json)

```json
{
 "title": "...",
 "groups": {
  "quartet": {"renderer": "quartet", "parts": ["vn1", "vn2", "va", "vc"]},
  "piano":   {"renderer": "piano",
              "parts": ["soprano", "alto", "tenor", "bass", "soprano_8va", "bass_8vb", "pedal_8vb"],
              "options": {"pedal": [{"at": "46:1", "until": "50:4", "every": "half"}]}}
 },
 "assignments": [
  {"voice": "soprano", "part": "vn1", "at": "1:1", "until": "35:1"},
  {"voice": "alto", "part": "va", "at": "9:4", "until": "13:1"},
  {"voice": "soprano", "part": "soprano_8va", "at": "48:1", "until": "59:1", "octave": 12, "level": -1}
 ],
 "pedal_points": [
  {"voice": "bass", "part": "pedal_8vb", "at": "42:1", "until": "46:1", "octave": -12, "bridge": 1}
 ],
 "allow_uncovered": [],
 "allow_octave_shift": [],
 "mix": {"lead_in": 0.5, "reference_group": "quartet",
         "groups": {"quartet": {"wet_db": -4}, "piano": {"wet_db": -3, "stage": {"*": {"az": 0, "depth": 1.2}}}}}
}
```

Positions are perform.py's `"bar:beat"` (quarter-note beats, 1-based, fractions allowed), `"end"`,
or a **mark**: `"MARK"`, `"MARK+N"`, `"MARK-N"`, `"MARK+N:beat"` (N bars after the mark, then the beat
in that bar). `at` defaults to `"1:1"`, `until` to `"end"`. Marks come from the spec:

```json
"marks": {"from": "../design/final-lab/piece.py", "tutti": "50:1"}
```

`from` (relative to the spec) reads section lengths: a Python file with `SECTIONS = [{"id", "bars"},
...]` (the skeleton's `piece.py`), a JSON list of the same, or a JSON `{name: "bar:beat"}`. Each
section's first bar becomes a mark under its id and without its `secNN_` prefix (`sec05_inversa`
and `inversa`). If the sections do not add up to the score's length, orchestrate.py stops: the
score and the section list disagree. Other keys are explicit marks. The demo spec uses marks only,
so its scoring follows the form when the composer inserts bars (the skeleton grew from 62 to 66
bars while the demo was being made, and the spec did not change). Positions in group options (piano
pedal spans, organ registration changes) and in `allow_uncovered` may use marks too; they are
rewritten as `bar:beat` for perform.py and the organ. `orchestration.json` lists every mark with its
bar and time.

### groups

| key | meaning |
|---|---|
| `renderer` | `piano`, `quartet`, `orchestra` or `organ` (default: the group's name) |
| `parts` | list of part names, or `{part: {options}}`. Part names are unique across groups; an assignment may also say `"group.part"` |
| `options` | per-renderer options (below) |
| `plan_overrides` | plan keys replaced for this group's perform.py run (`dynamics`, `role_boost`, `role_level`, `pedal`, ...). Timing keys (`tempo`, `fermatas`, `breaths`, `measure`, `voices`, `humanize`) are refused: all groups share one time base |

Part options and group options by renderer:

| renderer | part name / part options | group options |
|---|---|---|
| `piano` | the track (voice) name the piano renders as a stem; `track`, `program` | `pedal`: `"plan"` (default: the plan's pedal), `"none"`, or a list of perform.py pedal spans `{"at", "until", "every": "bar" \| "half"}`. Pedal changes where the piano rests are dropped (no pedal noise while it is silent) |
| `quartet` | an instrument id `vn1 vn2 va vc cb`, or `{"instrument": id}`; tracks are named "Violin I", "Violin II", "Viola", "Cello", "Contrabass" | |
| `orchestra` | the track name: a part id with an optional tag (`fl`, `hn.1`, `vc.div`, `fl:oct`); `{"part": id}` for other names; `divisi: true` allows chords; `gain_db`, `players` (`solo`, `a2`, `a4`), `pan`, `depth_m`, `width` go into the sidecar | `sidecar`: the base of `<group>.orchestra.json` (`hall`, `seating`, `tracks`) |
| `organ` | the track name (lower-cased); `division` `HW`, `POS`, `OW` or `PED` (manuals MIDI 36-85, pedal 36-64) (default by name: soprano, alto: HW, tenor: POS, bass: PED) | `registration`: the sidecar of `audio/organ/CONTRACT.md` section 3 (`changes`, `manual_changes`, `custom`, `enclosed`, `gain_db`); `manuals` and `measure` are filled in. `swell: true`: the plan's dynamic envelope drives the swell box (CC11; `enclosed` defaults to `["POS"]`) |

### assignments (lines)

| key | default | meaning |
|---|---|---|
| `voice` | | `soprano`, `alto`, `tenor`, `bass` (the plan's voices) |
| `part` | | who plays it |
| `at`, `until` | `1:1`, `end` | the window, by notated start |
| `octave` | 0 | -24, -12, 0, +12, +24 semitones: an octave doubling or a transposed hand-off |
| `level` | 0 | dynamic steps added to the plan's level (1 = p to mp). Piano: a different hammer velocity through perform.py's level curve (so timbre follows); bowed and wind parts: CC1/CC11 + 13 per step (layer and brightness follow); organ: none (use registration) |
| `accent` | 0 | velocity offset in perform.py units (piano: level; bowed: attack bite) |
| `articulation` | `auto` | `legato`/`slur`, `detache`/`normal`/`tenuto`, `short`/`staccato`/`spiccato`, and `roll`/`stroke` (timpani). Quartet and orchestra: CC20 per note (once a part has a hint, every note of it gets a CC20 value, with the renderers' own inference for `auto` notes, because the renderers stop inferring when a track carries CC20). Piano: `short` halves the sounding length, `legato` overlaps the next note by 40 ticks |
| `players` | | orchestra winds and brass: `solo`, `a2`, `a4` (CC16 at each note) |

Rules: one part plays one window at a time (overlapping windows on a part are an error; split
them). A voice may be played by any number of parts at once (doubling), by none (a rest: it must
then be listed in `allow_uncovered`, see below), and may move from part to part at any beat
(hand-offs, Klangfarben). Single-line parts (quartet, orchestra without `divisi`) may not receive
two notes starting together.

### pedal_points (derived sustained parts)

`{"voice", "part", "at", "until", "octave", "level", "articulation", "mode", "bridge", "min_beats", "pitch", "rate"}`

The part holds the pitch the voice sustains in the window (`pitch`: `"auto"` = the pitch held
longest, or a MIDI number the voice sounds there), from the first note of that pitch to the end
of the last one, merged over repeated notes and bridged over other notes no longer than `bridge`
beats (default 1: neighbour notes). Runs shorter than `min_beats` (default 2) are dropped. `mode`:
`sustain` (one held note; on `timp` a roll by the orchestra renderer's rule, or say
`"articulation": "roll"`), or `repeat` (re-struck `rate` times per second). The demo holds the
bass's dominant pedal F an octave down in the piano (42-45) under the cello's line with its
G-flat neighbours.

### allow_uncovered

`[{"voice": "tenor", "at": "44:1", "until": "46:1"}]`: score notes deliberately played by no part.
Without it, a score note that no part plays fails the integrity check.

### allow_octave_shift

`["vn2", "orchestra.ob"]` (or `true`): orchestra parts whose notes outside their compass the
renderer may move by octaves. Without it such a note fails the integrity check (section 3). Give
those bars to a part whose compass holds them (or split the window) rather than allow the shift:
a moved note sounds an octave off.

Ranges of the final score draft (`score/music-voices.ly`, MIDI): soprano 65-84, alto 53-77, tenor
48-68, bass 36-57. Notes that fall outside common orchestra compasses (`orch_common.PARTS`: vn1/vn2
55-, ob 58-, fl 60-, cl 50-, tbn 40-, timp 38-57):

* alto below vn2 (55): 9:4 F3, 12:1 F#3, 12:4 F3. Also below the oboe (58): 11:2 A3, 11:3 Ab3,
  13:1 and 13:3 A3, 30:1-30:2 A3 (arioso), 43:2.5 and 44:1.5 A3. Viola (48-) or clarinet (50-)
  hold all of them;
* tenor below the clarinet (50): C3 at 17:3, 57:2, 58:3, 61:4.5, 62:1. Bassoon (34-) or viola;
* bass below the tenor trombone (40): 18 notes (lowest C2 at 13:4, 16:4, 17:3, 51:4-53:1); below
  the timpani (38) at C2/C#2. Bass trombone (31-), tuba, cello, bassoon.

## 3. Integrity check

Written to `OUTDIR/integrity.json`; the exit code is 1 if it fails. It re-reads the score with
lyparse and the written MIDI files with mido (independently of the routing code) and checks:

* every note of every part is a note of its assigned voice, at the same notated onset (within
  the humanising tolerance, 60 ticks or a third of the shortest note) and at pitch + the declared
  octave; nothing is missing and nothing is extra; no note lasts past its notated end;
* every score note is played by some part (unless allowed);
* pedal-point notes sound a pitch the voice holds, start on one of its notes, end with its last
  note of that pitch, and bridge only stretches no longer than `bridge`;
* no hanging note-ons, no re-struck held keys, single-line parts stay single lines (perform.py's
  own legato overlap of a few ms is allowed);
* all group files have the same tempo map and ticks per quarter;
* notes outside an **orchestra** part's compass (from the renderer's own table, `orch_common.PARTS`)
  are errors: `render_orchestra.py` would play them an octave off (its report's
  `tracks[].octave_shifted`), and a note-presence check keyed to the score pitch cannot catch that,
  because the moved note's fundamental sits on the expected note's second harmonic. The message
  names the notes and the remedy. Parts listed in `allow_octave_shift` and the other renderers'
  compasses (quartet, including its SFZ's two-semitone stretch down; organ manuals 36-85, pedal
  36-64) give warnings; mix.py reports every move any renderer made (below).

`orchestration/tests/test_orchestrate.py` plants errors in clean output (a semitone, an undeclared
octave, a dropped note, an added note, a hanging note, a tempo change, an uncovered window, a
pedal held past its pedal, bad specs) and checks that each one is caught, and checks the contract
details (markers, track names, pedal only where the piano plays, CC20 on every note once hinted,
the viola's CC1 following the alto and then the tenor across a hand-off, a level of -1 lowering
piano velocities by one dynamic step, shared onset ticks in doublings, a 17-part orchestra group
(more than 16 MIDI channels: channels are reused), the alto on vn2 throughout failing on its 3
notes below the compass, and `allow_octave_shift` turning them into warnings): 30/30 pass
(`tests/results/orchestrate_tests.json`).

## 4. Renderer contracts used

| group | perform.py target | tracks | controllers written | sidecar |
|---|---|---|---|---|
| piano (`audio/piano/README.md`) | piano | one per part (stems by track name) | velocity; CC64 on the first track | |
| quartet (`audio/strings/README.md`) | strings | Violin I, Violin II, Viola, Cello, Contrabass | CC1 = CC11 envelope of the voice being played (+13 x level); velocity = accent; CC20 when hinted | |
| orchestra (`audio/orchestra/CONTRACT.md`) | strings | part ids (`fl`, `hn.1`, `vn1`, `timp`, ...), concert pitch | CC1/CC11 as above; CC16 players; CC20 (timpani: roll/stroke) | `<group>.orchestra.json` |
| organ (`audio/organ/CONTRACT.md`) | piano (strings with `swell`) | lower-cased part names | CC11 swell only with `swell` | `<group>.registration.json` |

While a bowed or wind part rests, its envelope follows its next window, so the right dynamic
layer is already in place at its entry.

## 5. The manifest and mix.py

orchestrate.py writes `OUTDIR/manifest.json` from the spec's `mix` section:

```json
{"title": "...", "out": "../skeleton_quintet", "lead_in": 0.5, "peak_dbtp": -1.0, "hall": "detmold",
 "reference_group": "quartet",
 "groups": {"quartet": {"renderer": "quartet", "midi": "quartet.mid", "parts": {...},
                        "gain_db": 0, "wet_db": -4, "stage": {"vn1": {"az": 30, "depth": 0}}},
            "piano": {"renderer": "piano", "midi": "piano.mid", "parts": {...}, "gain_db": 0, "wet_db": -3,
                      "stage": {"*": {"az": 0, "depth": 1.2, "width": 0.7}}, "render_args": ["--jobs", "2"]}}}
```

| key | meaning |
|---|---|
| `out` | output path without extension, relative to the manifest (`.wav`, `.m4a`, `.mix.json`) |
| `lead_in` | seconds of silence before MIDI time 0 in the mix (and passed to every renderer) |
| `reference_group` | the group whose calibration level the others are levelled to |
| `groups.<g>.gain_db` | balance trim after calibration |
| `groups.<g>.hall_re_dry_db` | hall energy re this group's dry sound, **measured on this music** (the reverb is computed at unit gain, measured, and scaled). Portable between instruments: at the same impulse-referenced level the piano's hall is about 2.5 dB stronger than the quartet's, because its energy sits where the hall rings longest. The quartet renderer's own default (`--wet -4`) is +4.2 dB on this piece; the demo gives both groups +4 dB |
| `groups.<g>.wet_db` | used when `hall_re_dry_db` is absent: hall energy re the dry sound for an impulse (`hall.py` convention, default -4) |
| `groups.<g>.stage` | per stem seat: keys part, track, instrument or `"*"`; `az` (degrees, + = left), `depth` (m behind the front; adds 1/343 s per m and -1 dB/m), `width` (share of the stem's own stereo width). Quartet defaults: its renderer's seats; piano: centre, 1.2 m back. Orchestra stems come seated by their renderer |
| `groups.<g>.render_args` | extra arguments for that renderer |
| `groups.<g>.latency_ms` | shift the group earlier by this many ms, or `"auto"`: by its own time base from the timing probe, so its attacks land on the MIDI clock. Default `"auto"` for the organ (its renderer already anticipates half of each pipe's speech; the rest, about 11 ms, is its time base), 0 for the others |

**Rendering.** One group at a time, dry stems and no reverb, into `OUTDIR/render/<group>/`; a
render is reused while its MIDI, sidecar, arguments and **engine** are unchanged (`--rerender`
forces it). The engine fingerprint (`engine_hash`, in `stamp.json` and in the calibration key)
covers the renderer script, every local module it imports (found transitively in its directory
and `audio/strings`: the orchestra's `orch_common` and the quartet's `render_quartet`, `iowa_build`,
`hall`; the organ's `pipe_engine`, `odf`), and its instrument definitions as text: the SFZ files
and tuning, latency and layer JSON of the built instruments (content and mtime), the piano's
velocity calibration, the organ's ODF, pipe model and `registrations.json`. Samples are not hashed
(a rebuild rewrites its SFZ). After changing anything else a renderer reads, run with
`--rerender --recalibrate`.

**Octave moves.** Every note a renderer moved by octaves into a compass is copied into the report
(`groups.<g>.octave_shifted`: the orchestra's `[MIDI s, key in, key played]` per track, the
organ's folded notes per division, the quartet's count per job from its log) and printed as a
warning; `warnings` in the report lists them.

**Time base.** Every stem is placed so that its sample 0 is MIDI time `-lead_in`: the piano and
the organ start their output at MIDI time `-lead_in`; the quartet and the orchestra report
`offset_s` (MIDI time of their first sample). No stretch or resampling: offsets are whole samples.

**Levels.** The quartet normalises its stems with its mix; mix.py undoes that from the report's
pre-normalisation stem levels (the four instruments give the same gain within 0.01 dB). The organ's
stems carry its render's normalisation gain (organ CONTRACT section 6); mix.py undoes it with the
report's `normalisation_gain_db` (before calibration version 3 it did not, and an organ in an
ensemble sat 5.6 dB low on the whole piece, by the difference between the piece's and the
chorale's normalisation). The piano's and the orchestra's stems are pre-normalisation by contract. The renderers are then
levelled against each other with a **calibration chorale**: `orchestration/calibration/chorale.ly`
(eight bars of four-part B-flat major at mf, `chorale.plan.json`) goes through orchestrate.py and
each renderer, seated as in the mix; the K-weighted loudness of each (`calibration.json`, cached
under a key of the calibration version, the engine fingerprint, the chorale, orchestrate.py and
hall.py) sets a gain so that an mf chorale is equally
loud on every renderer. `gain_db` is applied on top. So the scoring changes the balance the way
it would on stage (a doubled line is louder, a solo softer), and nothing depends on how loud a
group happens to be where it plays.

**Alignment check.** Every stem is on the MIDI time base by construction (whole-sample offsets
from the renderers' own reports). What is verified by cross-correlation, with an onset envelope
(1 ms frames, log-energy rises in four bands) against impulse trains at MIDI note-on times:

1. **Time base, per renderer (the gate).** A timing probe, cached with the calibration: the
   calibration chorale with every note `short` (no bow pre-roll, no slur crossfade, a plain attack
   on the note-on), orchestrated, rendered and loaded through exactly the path a mix uses. Each
   stem's envelope is cross-correlated with its note-ons (orchestra: plus its seat's depth delay,
   because its stems arrive seated), the curves of the renderer's stems are summed, the peak
   within +-30 ms is the renderer's lag (per-note p10-p90 about 1-4 ms wide for piano, quartet
   and orchestra). The groups' lags must agree within `--max-lag-ms` (5 ms). This is the only
   gate. If it fails, the mix is still written, `alignment_ok` is false and the exit code is 3.
   The search window: the orchestra starts each sample early by its measured onset latency
   (about 80 ms for the VPO3 violins), so on a note after silence a quiet pre-attack rises out
   of digital silence 80 ms before the note-on, and the log-energy envelope scores that rise
   above the tone's. The global peak (-76.7 ms) is kept in `calibration.json` as
   `time_base_global_peak_ms`; within +-30 ms the orchestra measures +3.3 ms (per-note median
   +2.5 ms); on the orchestra + piano chorale that gives +2.9 ms re the piano, and the doubled
   onsets there measure -1.8 ms. A peak on the window's edge fails
   the gate (time base not measured).
2. **Doublings in this piece (information).** Where two groups play the same onsets, their two
   envelopes, masked to +-60 ms around the shared onsets, are cross-correlated directly
   (`direct_xcorr_lag_ms`, with its peak prominence), and again on the onsets that both renderers
   attack (`direct_xcorr_lag_ms_attacks`: piano and organ every note; strings and winds new-bow,
   tongued and short notes). This used to be a gate and is not any more. On bowed music the
   curve is flat over several ms (0.421-0.423 from -5 to +1 ms on the current score draft):
   slurred notes enter by crossfade, and bow attacks are slow. So its peak moved with the
   subset of notes: -4.6 ms over all 206 shared onsets, -4.9 to +0.9 ms over 80 % bootstrap
   subsets, +4.1 ms on the 34 attacked ones. Meanwhile the stems sat sample-accurately
   where intended (cross-correlated against the final WAV: vn1 -0.02 ms, piano +3.5 ms = its 1.2 m
   seat).
3. **Attacks in the music (information).** The same cross-correlation per stem against the notes
   whose attack the renderer places on the note-on (piano: all; quartet and orchestra: new-bow,
   tongued and short notes, from their reports, orchestra plus seat delay; organ: notes after
   100 ms of silence), per group and per quarter of the piece, plus every note and notes after
   silence. These depend on articulation by design: a bowed stroke after a rest starts its bow
   noise 15 ms early and is caught there (-12 ms), a repeated note re-articulates out of a dip, a
   cello slur peaks up to 17 ms late. They are reported, not gated.

`--max-lag-ms` sets the tolerance. `latency_ms` (per group, ms or `"auto"`) shifts a group earlier;
by default only the organ is shifted, by its measured pipe speech; the gate compares the time
bases after that shift. Numbers: `groups.<g>.alignment`
(`time_base_lag_ms`, `entry_xcorr_lag_ms` ...), `inter_group`, `alignment_worst_ms`.

Measured time bases (`orchestration/calibration/calibration.json`, calibration version 4, 56 probe
notes each; per-note p10..p90 in brackets): piano +0.4 ms (-1..+1), quartet +2.3 ms (0..+3.5),
orchestra +3.3 ms (-27..+15: the VPO3 pre-attacks above; per-note median +2.5), organ +10.7 ms
(-11.5..+52.5: the renderer now anticipates half of each pipe's speech, median 13 ms, and the rest
is slower in the bass; compensated by default, so the organ lands on the MIDI clock).

**Hall.** `audio/strings/hall.py` (shared with the quartet renderer): `place_dry` seats each stem
(constant-power pan, width, depth delay and attenuation) and `Hall("detmold")` is the measured
Detmold Konzerthaus response (the piano's `make_ir.py` output, tail continued to 3.5 s, unit
energy; sources on the right use the mirrored response). Each group's stems are summed per side
and convolved once at the group's wet level.

**Master and report.** 18 Hz high-pass, tail trimmed at -80 dB with a 0.3 s fade, true peak
(4x oversampled) to `peak_dbtp`, 48 kHz 24-bit WAV with the credits in its INFO chunk, AAC
256 kb/s m4a via `afconvert` (decoded and measured; encoded again lower if it overshoots by more
than 0.1 dB). `OUT.mix.json`: per group offsets, gains, calibration, lags, level while playing,
seats, C80; the balance where all groups play; integrated loudness, loudness range, true peak of
WAV and m4a, stereo correlation, mono fold-down, hall re dry, a click scan and a 5 s loudness
curve. The click scan looks for 1 ms bursts above 12 kHz, 15 dB over their surroundings, away
from onsets. It keeps only isolated bursts, with no other burst 3-60 ms away: a low brass note's
lip pulses cross the threshold on every period (bass trombone C2 every 15.3 ms, tuba F1 every
22.9 ms). Before this rule the symphonic mix reported hundreds of such false clicks
(`periodic_candidates_dropped` counts them). Single-sample clicks planted at -50 dBFS in quiet
passages are still found.

**Stems.** `--keep-stems` writes each stem as it enters the hall to `OUT.stems/<group>_<stem>.wav`
(32-bit float, the mix's start and length, seated, with all gains, the latency compensation and
the master's normalisation gain, but without the hall and the 18 Hz high-pass). Their sum is each
group's dry sound in the master: on the organ + quartet chorale the stems give the report's
`level_when_playing_lufs` to 0.01 dB. About 92 MB per stereo stem for four minutes: delete them after
the listening QA.

## 6. Evidence

**Quintet demo** (`orchestration/quintet_skeleton.json` on the 66-bar skeleton
`design/final-lab/SK_final.ly` as of commit e3fbbe3, score sha256 `1e4927257b65a84c`, plan
`7804a26d6d18e0d7`; 232.1 s of music, 234.1 s of audio; report
`orchestration/out/skeleton_quintet.mix.json`, QA `orchestration/tests/results/qa_skeleton_quintet.json`,
integrity `orchestration/out/skeleton_quintet/integrity.json`; re-rendered after the QA round's
fixes, 1.6 min for render and mix). The spec is written in section marks and did not change while
the skeleton was revised (62 to 66 bars, Parts II-V rewritten):

* integrity: every part note is its voice's note at the declared octave, every score note is
  played (soprano 187, alto 207, tenor 176, bass 133); no note outside a compass;
* on the rendered stems (`tests/qa_mix.py`, independent of mix.py's measurements): 919 of 919 part
  notes sound at their pitch, none dropped, no sound in rests or after the last note; strings
  within 3 cents at p95 (medians -0.0..+0.3), piano on its own stretch curve (bass 8vb about -15
  cents, as its README documents for the bottom octave); median onset per part -2..+1 ms from the
  MIDI (the piano's 8vb bass +7 ms);
* alignment: time bases quartet - piano +1.87 ms (probe, the gate); for information, the 190
  doubled onsets -0.34 ms (-0.71 ms over the 47 that both groups attack), attacks in the music
  +0.69 ms;
* levels: the quartet's stems are brought back to its raw scale (-13.7 dB; the four instruments
  agree within 0.01 dB); calibration puts the piano +0.35 dB, the spec trims it -1 dB (it sits
  behind the quartet and carries the octave doublings); where both play (68 s) the quartet sits at
  -29.5 LUFS and the piano at -28.4; hall +4.0 dB re dry for each group on this music;
* master: 48 kHz / 24-bit, -21.85 LUFS integrated, loudness range 20.4 LU, true peak -1.0 dBTP
  (m4a -0.99; ffmpeg ebur128 agrees: -21.8 LUFS, -1.0 dBTP for both), m4a sample-aligned with the
  WAV, no clicks away from onsets, L/R correlation 0.54, mono fold-down -1.1 dB.

**Orchestra adapter** (`tests/spec_chorale_orch_piano.json`: string sections, flute 8va, horn,
piano; 29 s; calibration version 4): time bases orchestra - piano +2.86 ms (the orchestra's probe
searched within +-30 ms, section 5); for information, 32 doubled onsets -1.81 ms; -1.0 dBTP (m4a
-1.08), no clicks.

**Organ adapter** (`tests/spec_chorale_organ_quartet.json`: four voices on HW/POS/PED with a
registration change and the swell, violin and cello doubling from bar 5; 30 s): rendered with its
registration sidecar; its stems taken back to its raw scale (+4.39 dB, the render's own
normalisation undone), calibration -9.74 LUFS raw (was -15.2 before the organ's normalisation was
undone), so the quartet's calibration gain is +23.6 dB (was +17.8); the organ shifted by its
10.7 ms time base, time bases then organ - quartet -2.27 ms; -1.0 dBTP (m4a -1.05), no clicks.

**Whole piece, other ensembles** (the adversarial QA round, in /tmp sandboxes, on SK_final and on
the score draft): organ + quartet and a 17-part orchestra ran through orchestrate.py and mix.py
with integrity OK. All 1037 orchestra, 703 organ and 589 quartet notes were present on the stems,
with no sound in rests or after the last note, no clipped samples and no cut tails. The
registration and dynamics steps showed in level and spectral centroid. Placement in the final WAV,
cross-correlated stem by stem against the mix, was sample-accurate: vn1 -0.02 ms (intended 0),
piano +3.5 ms (its 1.2 m seat), organ -10.69 ms (its compensation). That round found the defects
fixed since: the doubled-onset gate, octave-moved orchestra notes passing integrity, the organ's
level, false clicks from low brass, the render cache, and `--keep-stems`.

## 7. Limits

* Quartet and organ compass moves are warnings, not errors (the quartet's compass includes its
  SFZ's two-semitone stretch down, which covers the alto's F3 on vn2). mix.py reports every move.
* The onset envelope measures log-energy rises, so a quiet pre-attack after silence can outscore
  the tone (the orchestra's VPO3 violins). The time-base search is bounded to +-30 ms for this
  reason. A renderer whose time base is really off by more than 30 ms fails the gate, but its
  error is not measured.
* The engine fingerprint does not hash the samples themselves or the sfizz binary.
* The calibration equates the renderers at mf on a four-part chorale. It does not know that a
  concert grand at mf may be louder than a string quartet at mf; `gain_db` is the balance control.
* A piano quintet in one hall: the groups share one measured response (source position S1, one
  seat); seats differ by pan, width, depth delay and level only.
* The orchestra reports `offset_s` rounded to 0.1 ms: its stems can sit up to 2 samples off.
* perform.py's pedal `"every": "harmony"` (used in plan.json) is not implemented there and falls
  back to every half bar.
