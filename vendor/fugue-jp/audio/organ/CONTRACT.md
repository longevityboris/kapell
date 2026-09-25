# Pipe organ renderer: input contract

`render_organ.py IN.mid [--registration REG.json | PRESET] -o OUT [--stems DIR] [--no-reverb] [--lead-in SEC]`

This contract is fixed; additions are backward compatible. The instrument behind it (the
Norrfjärden Church organ and the added church acoustic) is described in `README.md`. A caller
writes a MIDI file with one voice per track and, optionally, a registration sidecar JSON.
Registration can also travel inside the MIDI as text events (section 4).

## 1. Time base

* Standard MIDI file, type 0 or 1, any `ticks_per_beat`. The tempo map is the `set_tempo` meta
  events (any track, usually track 0). Rubato can be written as a tempo map or as note timing.
* Time zero is tick 0. The output begins with `--lead-in` seconds of silence (default 0.5 s)
  and ends when the reverberation has decayed (80 dB below the loudest moment, at most 8 s after
  the last pipe stops).
* **Bar:beat positions** in the sidecar are converted with the file's own tick grid:
  quarter-note position `q = (bar - 1) * measure * 4 + (beat - 1)`, tick `= q * ticks_per_beat`.
  `beat` is a 1-based quarter-note beat and can be fractional (`"12:2.5"`); `measure` is the bar
  length in whole notes (default `"1"` = 4/4, as in perform.py plans). perform.py writes every
  note at the tick of its score position (tempo is carried by the tempo map), so bar:beat is
  exact for its files. Alternatives to `"at"`: `"at_tick"` (integer tick) or `"at_sec"`
  (seconds from time zero, after the tempo map).

## 2. Voices, divisions, keys

* **One voice per track or per channel.** Every (track, channel) pair holding notes is a voice,
  named by the track's `track_name` (trimmed, lower-cased). Several channels in one track get
  `.chN` appended. A repeated name becomes `name.2`, `name.3` (warning). No name: `track3`.
  perform.py's `soprano`, `alto`, `tenor`, `bass` are the usual names.
* **A MIDI note number is a KEY, not a sounding pitch.** As on a real organ, the stop's footage
  decides the octave: an 8' stop sounds as written, 16' an octave lower, 4' an octave higher,
  mutations and mixtures at their harmonics. Write the bass line at its notated pitch and give
  the pedal `pedal16+8` for the usual 16' foundation (the 8' keeps the written pitch).
* **Divisions** (keyboards of the Norrfjärden organ):
  - `HW` Hauptwerck (manual II, main principal chorus, the loudest),
  - `POS` Rückpositief (manual I, lighter, in the gallery rail, recorded from its own position),
  - `OW` Oberwerck (manual III, Quintadena, flutes, mutations, Schalmei; optional third manual),
  - `PED` Pedahl.
* **Voice-to-division assignment**, in order of precedence: the sidecar's `manual_changes`
  and `manuals` (section 3), `organ:` text events (section 4), else the default by name:
  `soprano`, `alto` -> `HW`; `tenor` -> `POS`; `bass` -> `PED`; any other name -> `HW`.
  A voice can move to another division during the piece (at a rest, like an organist's hand):
  each note plays on the division its voice is on when the note starts.
* **Compass.** Manuals MIDI 36-85, pedal MIDI 36-64. The organ stands a semitone above A440,
  so its C-c3 manuals and C-d1 pedal sound C#-C#; keys 36, 38 and 40 borrow a neighbouring
  pipe retuned by about a semitone (the organ's short bass octave has no C# or D#), counted in
  the report. A key outside its division's compass is folded by octaves into it, with a warning
  and a count in the report (`--no-fold`: error).
* **Key sharing.** Two voices on the same division holding the same key play ONE set of pipes
  (as on the instrument): the key sounds from the first press to the last release. No doubling,
  no comb filtering. In stems the sound goes to the voice that pressed first. Counted in the
  report.
* **Repeated notes.** A note-off and a note-on of the same key on the same division re-attack the
  pipe (a new speech transient). A zero-length note is played as a 30 ms touch (warning); a
  note-on with no note-off is closed after 2 s (warning).

## 3. Registration sidecar (`--registration REG.json`)

```json
{
  "measure": "1",
  "manuals": {"soprano": "HW", "alto": "HW", "tenor": "POS", "bass": "PED"},
  "manual_changes": [{"at": "30:1", "voice": "soprano", "division": "POS"}],
  "changes": [
    {"at": "1:1",  "HW": "flute8",       "POS": "flute8",  "PED": "pedal16+8"},
    {"at": "20:1", "HW": "principal8+4"},
    {"at": "26:3", "HW": "plenum",       "PED": "pedal_plenum_reed"}
  ],
  "custom": {"solo_reed": {"stops": ["Krumb Horn 8'", "Flött 8'"]}},
  "enclosed": ["POS"],
  "gain_db": {"bass": 0.0}
}
```

* `changes`: at each position, each listed division switches to the named registration.
  Divisions not listed keep theirs. Before the first change every division uses its default
  (`HW`, `POS`: `principal8`; `OW`: `flute8`; `PED`: `pedal16+8`).
* **Held keys follow the stops, as on a real organ**: a stop drawn while a key is held starts
  speaking at the change (with its attack), a stop retired while a key is held releases at the
  change (with its release). Put changes at breaths or section joins for clean joins. A note that
  starts less than 30 ms before a change (perform.py's humanising) starts with the new setting;
  a key released less than 80 ms after a change keeps the old one. The same 30 ms rule applies
  to `manual_changes`.
* **Named registrations** (stop lists in `registrations.json`; `render_organ.py
  --list-registrations` prints them, `--list-stops` the stop names):

  | name | `HW` | `POS` | `OW` | meaning |
  |---|---|---|---|---|
  | `flute8` | yes | yes | yes | stopped flute 8' (Gedackt / Flött / Quintadena) |
  | `flute8+4` | yes | yes | yes | flute 8' + flute 4' |
  | `principal8` | yes | yes | yes* | principal 8' (POS: Flött 8' + Principal 4'; *OW: flutes 8'+4') |
  | `principal8+4` | yes | yes | yes* | principal 8' + octave 4' |
  | `principal8+4+2` | yes | yes | yes* | principal 8' + 4' + 2' |
  | `plenum` | yes | yes | yes | principal chorus with mixture (HW 8' 4' 3' 2' Mixtur VI; POS 8' 4' 2' Cimbel III) |
  | `plenum16` | yes | | | `plenum` + Quintadena 16' |
  | `plenum_reed` | yes | yes | yes | `plenum` + chorus reed (HW Trommeten 8', POS Krummhorn 8', OW Schalmei 8') |
  | `plenum16_reed` | yes | | | `plenum16` + Trommeten 8' |
  | `reed8` | yes | yes | yes | reed 8' + flute 8' |
  | `sesquialtera` | | yes | yes | solo: flutes 8' 4' + Sesquialtera (OW: + Nasat 3') |

  | name | `PED` | meaning |
  |---|---|---|
  | `pedal8` | yes | Gedackter Bass 8' alone (the line at written pitch, light) |
  | `pedal16` | yes | Under Bass 16' alone (sounds an octave below the notes; rarely wanted) |
  | `pedal16+8` | yes | Under Bass 16' + Gedackter Bass 8' |
  | `pedal16+8+4` | yes | + Octava Bass 4' |
  | `pedal_plenum` | yes | 16' 8' 4' flues (the pedal has no mixture) |
  | `pedal_plenum_reed` | yes | `pedal_plenum` + Posaunen Bass 16' + Trommeten Bass 8' |
  | `pedal_reed` | yes | Posaunen Bass 16' + Gedackter Bass 8' |
  | `pedal_cantus` | yes | Gedackter Bass 8' + Corneten Bass 4' (a pedal cantus firmus) |

  Also accepted: `"off"` (division silent), a `custom` name from the sidecar, or an explicit
  list of stop names of that division, e.g. `["Gedackt flött 8'", "Octava 4'"]` (matching
  ignores case, accents and punctuation). An unknown name is an error, not a silent substitute.
  Couplers are not modelled: a stop list may only name the division's own stops.
* `manuals`: initial voice -> division map (overrides the defaults by name). `manual_changes`:
  moves a voice from a position on.
* `enclosed`: divisions that sit in a swell box (section 5). Default: none (the real organ has
  no swell box).
* `gain_db`: static per-voice mix gain in dB (default 0). For balance only; the organ's
  dynamics are its registration.
* Instead of a file, `--registration PRESET` applies one preset from `registrations.json` to the
  whole file: `quiet` (flutes 8', pedal 16'+8'), `principals`, `plenum` (manual plenums, pedal
  with reeds). Voices then use the default divisions.

## 4. Registration inside the MIDI (optional)

`text` or `marker` meta events on any track whose text starts with `organ:` are read as commands
at their tick, after the sidecar's events at the same tick:

```
organ: HW=plenum PED=pedal_plenum_reed      registration change
organ: tenor->POS                           voice to division
```

## 5. Controllers and other messages

* **Velocity: ignored** (an organ key does not know how fast it was pressed). Velocity 0 is a
  note-off. perform.py's dynamic velocities therefore have no effect; its dynamics must be
  translated into registration changes (the demo plan shows how).
* **CC11 = swell box**, only for voices on a division listed in `enclosed`: 127 open, 0 closed.
  The box lowers level (to -18 dB at 0) and highs more than lows (a one-pole low-pass sweeping
  from 20 kHz open to 1.5 kHz closed), smoothed over 60 ms, so a crescendo changes timbre as well
  as level. On divisions that are not enclosed CC11 is ignored.
* Ignored: program change (perform.py writes one per channel), CC1, CC7, CC64, CC10, pitch bend,
  aftertouch, sysex.

## 6. Output

* `OUT.wav`: 48 kHz, 24-bit, stereo, true peak normalised to -1 dBTP (`--peak-db`), church
  reverberation added by convolution (`--wet-db`, default -4 dB: the added church's energy
  relative to the dry organ, measured on the render; `--no-reverb`: none added). `OUT.m4a`: AAC
  256 kb/s (afconvert), licence credits as tags. One normalisation gain for the whole file, so
  registration contrasts are kept.
* `--stems DIR`: one dry 48 kHz 24-bit stereo WAV per voice (`DIR/<voice>.wav`), same time base,
  lead-in and length as the mix, scaled by the mix's normalisation gain: the sum of the stems is
  exactly the dry (pre-reverb) part of `OUT.wav`. "Dry" means without the added church; the
  samples themselves carry the Norrfjärden church's own sound.
* `--json PATH`: report (voices and their divisions, registration timeline in seconds, pipe
  events, borrowed/shared/folded keys, release-join statistics, per-voice levels and
  stereo correlation / mono fold-down (`voices.<v>.stereo`, `stereo_mix`, `stereo_dry_sum`),
  added-hall level and C80, decay of the final chord, loudness, true peak, the normalisation gain
  applied to mix and stems (`normalisation_gain_db`), warnings).
* Nothing is played through the speakers.
