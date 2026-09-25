# Orchestra renderer: MIDI input contract

`render_orchestra.py IN.mid -o OUT` turns a multi-track Standard MIDI File into a
romantic symphony orchestra in the Detmold Konzerthaus (the same measured hall as
the piano and the quartet). This file is the interface the orchestration tool
(`tools/orchestrate.py`) writes against. It is stable: new features only add
optional controllers or sidecar keys; nothing below changes meaning.

The short version: write one track per orchestral line, name the track with a
part ID, give every track the CC1/CC11 envelope and velocities that
`perform.py --target strings` writes for a voice, write every pitch at sounding
(concert) pitch. Everything else is optional.

## 1. File and time base

* SMF type 1 (type 0 is accepted: its channels are split into tracks, one per
  channel). Any ticks-per-quarter. The tempo map (set_tempo in any track) is
  honoured; the renderer converts every event to seconds before rendering.
* **Time zero** = MIDI time 0. The output's first sample is MIDI time
  `-lead_in` (default `--lead-in 0.3` s, the same as the piano and quartet
  renderers), so renders from the three engines line up sample for sample when
  they are rendered with the same lead-in. `--keep-start` makes sample 0 =
  MIDI time 0. The JSON report (`OUT.json`, always written) states `offset_s`
  = MIDI time of the first output sample.
* Output: `OUT.wav` (48 kHz, stereo, 24-bit PCM, true peak -1 dBTP unless
  `--peak` / `--no-normalize`), `OUT.m4a` (AAC 256 kb/s), `OUT.json` (report).
  `--stems` adds `OUT.stems/<track name>.wav`: 32-bit float stereo, dry but
  already placed on stage (pan, width, depth delay and air absorption), at the
  same gain, start and length as in the mix before the final normalisation
  gain (the report gives that gain as `norm_gain_db`). In the file name every
  character of the track name other than a letter, digit, `.`, `_` or `-` is
  replaced by `_` (`fl:oct` -> `fl_oct.wav`, `tpt 2` -> `tpt_2.wav`); the
  report's `stems` maps each file name back to its track.

## 2. Tracks and part IDs

One track = one orchestral line (one player, a unison pair, or a string
section). The **track name** selects the instrument:

```
<part>            e.g. "fl", "hn", "vn1"
<part><sep><tag>  e.g. "hn.1", "hn.2", "vc.div", "fl:oct", "tpt 2"   (sep = . : _ - or space)
```

Part IDs (case-insensitive; stable, never renamed):

| ID | instrument | sounding compass (MIDI) | default seat |
|---|---|---|---|
| `fl` | flute | 60-96 (C4-C7) | woodwinds, row 1 left |
| `ob` | oboe | 58-91 (Bb3-G6) | woodwinds, row 1 right |
| `cl` | clarinet (in B-flat, written at concert pitch) | 50-91 (D3-G6) | woodwinds, row 2 left |
| `bn` | bassoon | 34-75 (Bb1-Eb5) | woodwinds, row 2 right |
| `hn` | horn (in F, concert pitch) | 34-77 (Bb1-F5) | left, behind the woodwinds |
| `tpt` | trumpet (concert pitch) | 54-84 (F#3-C6) | back row, right of centre |
| `tbn` | tenor trombone | 40-72 (E2-C5) | back row, right |
| `btbn` | bass trombone | 31-67 (G1-G4) | back row, right |
| `tba` | tuba | 26-65 (D1-F4) | back row, far right |
| `timp` | timpani | 38-57 (D2-A3) | back, centre-left |
| `vn1` | first violins (section) | 55-100 (G3-E7) | front left |
| `vn2` | second violins (section) | 55-96 (G3-C7) | left, behind vn1 |
| `va` | violas (section) | 48-88 (C3-E6) | centre right |
| `vc` | cellos (section) | 36-81 (C2-A5) | front right |
| `cb` | double basses (section; 5-string / C extension) | 24-67 (C1-G4) | right, behind the cellos |

* **Several tracks may share a part**: `hn.1` and `hn.2` are two horn lines
  (e.g. horns 1-2 and 3-4), `vn1` and `vn1.div` a divided first-violin
  section. Each track is rendered as its own player (or desk group) of that
  part; same-part tracks sit side by side at the part's seat (spread by up
  to 1.5 m), never on top of each other. (How: the second, third, ... track of
  a part sits 3 deg aside and 0.5 m further back per track, is detuned by a
  few cents, starts its notes up to 8 ms apart and, for winds and brass,
  starts its player order on the next recording, so `hn.1` and `hn.2` in
  unison are two horns, not one horn 6 dB louder.)
* A track may contain overlapping notes (chords, divisi): every note sounds.
  Wind and brass parts should be monophonic per player; a chord on a wind
  track is rendered but logged (`warnings` in the report).
* Every track's messages apply to that track, whatever their MIDI channel.
  Channels have no meaning when the track name is a part ID (channel 9 is not
  a drum channel here).
* Tracks without notes (the tempo track) are ignored.

**Fallback identification** when a track name is not a part ID (first rule that
applies): instrument names as whole words ("Flute", "Oboe", "Clarinet",
"Bassoon", "Horn", "Trumpet", "Bass Trombone", "Trombone", "Tuba", "Timpani",
"Violin I", "Violin II", "Viola", "Cello"/"Violoncello", "Contrabass"/"Double
Bass"); then the track's first GM program change (73 fl, 68 ob, 71 cl, 70 bn,
60 hn, 56 tpt, 57 tbn, 58 tba, 47 timp, 40 vn1 then vn2, 41 va, 42 vc, 43 cb);
then the SATB voice names `perform.py` writes (soprano -> vn1, alto -> vn2,
tenor -> va, bass/pedal -> vc), so a plain `perform.py --target strings` file
renders as a string orchestra. An unidentifiable track is an error. The SATB
fallback does not look at the notes: an alto that goes below G3 (the ricercar's
alto reaches F3) has those notes moved up an octave on Violins II (section 3);
`tools/orchestrate.py` with a spec that gives those bars to the violas is the
supported route.

## 3. Pitch

* All pitches are **sounding (concert) pitch**, also for clarinet, horn,
  trumpet and double bass (a bass doubling the cellos an octave lower carries
  the notes 12 semitones lower).
* A note outside its part's compass is moved by whole octaves into the
  compass and listed in the report (`octave_shifted`); `--strict-range` turns
  that into an error. The orchestration tool should never rely on this.
* Tuning: A4 = 440 Hz, equal temperament, every sample set measured and
  corrected (the report and README give the residuals). Pitch bend is ignored.

## 4. Controllers and velocity (per track)

| message | meaning |
|---|---|
| **CC1** | **dynamic level**, perform.py's scale: ppp 36, pp 49, p 62, mp 75, mf 88, f 101, ff 114, fff 127 (= 36 + 13 x (level - 1)). It sets the timbre (crossfades the recorded dynamic layers where the library has them, and a brightness filter that follows CC1 inside every layer) and the loudness. Linear ramps between CC events are reconstructed (perform.py samples every 16th). A hairpin inside a held note changes the sound during the note. |
| **CC11** | expression: gain only, `0.5 x 20 log10(v/127)` dB (half the GM depth, as in the quartet renderer: perform.py sends CC11 = CC1, full depth would double-count). Default 127. |
| **CC7** | channel volume, GM curve `40 log10(v/127)` dB. Default 127. Use for balance trims inside the orchestration. |
| **velocity** | accent / attack strength of the note (1-127). With CC1 present it does not set the level: 64 = neutral attack, 127 = strongest accent (about +3 dB and a harder, faster attack), low = softer, slower start. Timpani: stroke strength on top of the CC1 level. |
| no CC1 on a track | the level is taken from the note velocities on perform.py's velocity scale (ppp 22, pp 32, p 44, mp 56, mf 68, f 82, ff 98, fff 112), as a `--target piano` file writes them. |
| **CC16** | **players** (winds and brass), value in force at the note-on: 0-42 solo (one player), 43-84 **a2** (two players in unison: two different recordings, seated side by side), 85-127 **a4** (horns only: four players; other parts treat it as a2). Default solo. Strings ignore CC16 (always the full section). |
| **CC20** | **articulation** of the note (value in force at the note-on): 0-63 normal (new bow / tongued), 64-95 legato (slurred from the previous note: no new attack, the pitch changes on the beat), 96-127 short (staccato / spiccato). Absent: inferred per note: a note that starts within 60 ms of the previous note's end, at another pitch, and is not short, is legato; a note shorter than `--short-ms` (default 260 ms) is short; anything else normal. |
| CC20 on `timp` | 0-63 single stroke (rings until the note-off, then damped over the CC21 release, default 0.35 s: write the note as long as the drum should ring), 64-127 **roll** for the note's whole duration (the roll's loudness follows CC1, so a CC1 ramp is a crescendo roll). Absent: a note of 0.9 s or longer is a roll, shorter notes are strokes. |
| **CC21** | release time of the note (value in force at the note-on): `0.03 + 1.2 x v/127` s. Absent: chosen from the context (short into a slur, longer before a rest, the hall carries the rest). |
| CC10, CC64, pitch bend, aftertouch, sysex | ignored (seating is fixed per part, see the sidecar to move a part). |
| program change | identification only (section 2); it never switches sounds. |

The controller set is the quartet renderer's (`audio/strings/README.md`) plus
CC16 and the timpani meaning of CC20, so a track written for the quartet
renders unchanged on a string section.

## 5. Sidecar (optional)

`OUT`-independent overrides in JSON, read from `--sidecar PATH` or, if that is
not given, from `IN.orchestra.json` next to the MIDI file (`x.mid` ->
`x.orchestra.json`). Every key is optional.

```json
{
  "tracks": {
    "hn.1":  {"gain_db": -1.5, "players": "a2"},
    "vn1":   {"pan": -0.55, "depth_m": 2.0, "width": 0.5},
    "fl:oct": {"part": "fl"}
  },
  "hall": {"wet_db": -2.0},
  "seating": "german"
}
```

* `tracks.<name>.gain_db`: level trim in dB (after the part's calibration).
* `tracks.<name>.players`: `"solo" | "a2" | "a4"`: default for notes without
  CC16 (CC16 wins where present).
* `tracks.<name>.pan` (-1 left .. +1 right), `depth_m` (metres behind the
  front of the stage), `width` (0 = point source, 1 = the sample's own
  stereo width): move a part.
* `tracks.<name>.part`: the part ID for a track whose name is not one.
* `hall.wet_db`: reverb energy re the dry sound (default: the renderer's,
  printed in the report); same meaning as `--wet`.
* `seating`: `"american"` (default: vn1 and vn2 left, va centre right, vc
  front right, cb behind the cellos) or `"german"` (antiphonal violins: vn2
  front right, vc and cb left of centre, va right of centre).

## 6. Levels and balance

Levels are **natural**: at the same CC1 every part plays the loudness a real
player or section produces at that marking in the hall (a trumpet at f is
louder than a flute at f; a string section is louder than a solo wind), so
the orchestration's dynamics mean what they say and doubling a line makes it
louder, as it does on stage. The calibration table (K-weighted level of every
part at pp, mf, ff) is measured by `setup_orchestra.sh` and printed in
`README.md`; use CC7 or the sidecar `gain_db` to rebalance.

## 7. Command line (summary; the full list is in the script's docstring)

```
python3 render_orchestra.py IN.mid -o OUT [--stems] [--no-reverb] [--lead-in S]
        [--keep-start] [--sidecar JSON] [--wet DB] [--peak DB] [--no-normalize]
        [--short-ms MS] [--strict-range] [--only PART,PART] [--jobs N]
```
