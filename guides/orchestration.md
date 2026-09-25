# Orchestration

One score, four voices, five renderings. `kapell render --version` takes a folder under `performance/` or a kind. A kind resolves to the one folder of that kind in `kapell.toml` `[versions].render`.

| Kind | What it is | How it is built |
|---|---|---|
| `organ` | Bach: one division per voice | spec with one `organ` group; articulation, then the organ engine |
| `piano` | Beethoven: one grand, four voices | `plan.json` only; piano velocities |
| `quartet` | solo strings | spec with one `quartet` group; bowing and swell, then the mix |
| `orchestra` | Webern: colour follows the motif | spec with an `orchestra` group, then the mix |
| `ensemble` | piano and quartet together | spec with several groups, then the mix |

`kapell engrave --layout` uses the same five names, plus `all`. The finish recipe engraves `all`.

Nothing in the spec composes. Every part note is a note of the assigned voice, moved by a whole octave or not at all (`octave` of −24, −12, 0, +12, +24). A derived pedal holds a pitch that voice already holds.

## Idioms

**Organ.** Each voice has its own division, so the lines differ in colour and in where they speak. The working map is soprano Hauptwerk (`HW`), alto Oberwerk (`OW`), tenor Rückpositiv (`POS`), bass Pedal (`PED`). The engine's default, if the spec says nothing, puts soprano and alto both on `HW`. Do not leave them there: two voices on one division that strike the same key sound one set of pipes. Dynamics are registration changes at section joins. The swell box is off unless the spec sets `swell`. The first piece kept the full reed chorus for the second climax, stepped down in terraces at the hinge, and gave the tune a single principal over flutes before the trumpet. One tempo per section is the Bach reading; the plan may still ritard.

**Piano.** Four tracks, one instrument. Dynamics and voicing are hammer velocity. The reading can drop subito, take time, and pedal through a harmony. Entries come forward by `role_boost`. This is the reference recording for the form table in the listener's guide.

**Quartet.** The piano reading's tempo and dynamics, on `vn1`, `vn2`, `va`, `vc` (and `cb` if the bass needs it). Entries come forward by bow pressure, `role_level`, not by a harder attack. The viola takes the alto where it goes below violin II. Long notes carry a swell; `kapell perform` deepens it, and a bar where every part holds at once can be excluded so the swell does not outshout the climax.

**Orchestra.** Colour changes where the motif changes, which is Webern's orchestration of the Ricercar a 6, not a new colour at every bar line. Subject, answer and inversion entries start on a colour that can sustain a line, in the first piece the strings. A featured inner line, such as the lament, walks across a choir of its own (the reeds, one player after another) instead of sitting inside a tutti. Brass and timpani build a climax head by head. A note held across a phrase stays with the instrument that started it.

**Piano and quartet (`ensemble`).** The model is a quintet that treats the piano as a fifth voice with its own entrances, not as a doubling of the strings from bar 1. In the first piece the strings played alone through the exposition and the first climax, the piano entered with the inversion, the climax and the apotheosis were tutti with the piano in octaves, and the coda thinned. A doubled line is louder because two groups play it. Do not also boost it unless it is the feature.

## Ranges

MIDI numbers. Middle C is 60.

The piece's own limits live in `kapell.toml` `[ranges]` and `check` enforces them. The first piece's composer ranges were soprano 60–84, alto 53–77, tenor 48–72, bass 36–62. The finished draft sat inside soprano 65–84, alto 53–77, tenor 48–68, bass 36–57.

Instrument compasses are the engine's. A note outside an orchestra part's compass fails the integrity check. Quartet and organ notes outside the compass are warnings: the quartet's samples stretch two semitones below the written low note, and the organ folds a key into the compass by octaves. Prefer a part that can play the note. `allow_octave_shift` turns an orchestra miss into a warning. It is not a way to score.

| Part | Low | High | Where a voice overflows |
|---|---|---|---|
| Flute | 60 | 96 | |
| Oboe | 58 | 91 | alto below A3 |
| Clarinet | 50 | 91 | tenor at C3 and below |
| Bassoon | 34 | 75 | the low bass |
| Horn | 34 | 77 | |
| Trumpet | 54 | 84 | |
| Trombone | 40 | 72 | bass below E2 |
| Bass trombone | 31 | 67 | |
| Tuba | 26 | 65 | |
| Timpani | 38 | 57 | only the pitches the drums hold |
| Violin I | 55 | 100 | |
| Violin II | 55 | 96 | alto below G3 (F3 is the stretch, and a warning on `vn2`) |
| Viola | 48 | 88 | holds the alto's F3 |
| Cello | 36 | 81 | holds the bass |
| Double bass | 24 | 67 | |
| Organ manual | 36 | 85 | C2 to C♯6 |
| Organ pedal | 36 | 64 | C2 to E4 |
| Piano | 21 | 108 | the checker's default when `[ranges]` is silent |

The organ sounds a semitone above A440. That is a property of the samples. Write key numbers, not transposed pitches.

## Doubling

The score stays as many real voices as it has. Doubling is colour.

1. One part plays one window at a time. Overlapping windows on a part are an error. Split them.
2. A voice may be played by several parts at once, or by none. None is a rest, and the notes go in `allow_uncovered`, or the integrity check fails.
3. A voice may move from part to part at any beat. A note held across the hand-off stays with the part that began it. If that part's next window starts before the note ends, the held note is cut at the new attack.
4. Octave doubling belongs on an outer voice at a climax (`soprano_8va`, `bass_8vb`), not on every entry, and not on an inner voice in the octave where another voice already speaks. Unison doubling of an inner voice in a busy bar collapses two lines into one.
5. A single-line part cannot take two notes that start together. A chord needs `divisi: true` or a second part.
6. On the organ, do not put two voices on one division if they will share a key. The pipes play once.
7. Give a low note to an instrument whose compass holds it: viola or clarinet for a low alto, bassoon, cello or bass trombone for a low bass. An octave-shifted orchestra note sounds an octave off, and a check that looks for the written pitch will not catch it, because the moved fundamental sits on the second harmonic.
8. A pedal point is the pitch the voice sustains in that window (the longest held pitch, or a MIDI number the voice actually sounds), bridged across neighbour notes no longer than `bridge` beats (default 1). Runs shorter than `min_beats` (default 2) are dropped. It does not add a harmony.
9. All groups share one tempo, one set of fermatas and one set of breaths. The spec may replace dynamics, `role_boost`, `role_level` and pedal per group. It may not replace the time base.
10. Bring a featured line out with `level`, an articulation, or `players: solo` on that entry's window. A section-long assignment of the voice does not count as a cue (performance guide).

`level` is in dynamic steps (1 is from *p* to *mp*). On the piano it changes the hammer velocity. On strings and winds it shifts the CC1/CC11 envelope by 13 per step. On the organ it does nothing: use registration.

## How a spec assigns a voice

`performance/<version>/*.json` with an `assignments` array. `kapell perform` and `kapell render` read it. The full contract of the mixer (hall, calibration, alignment) is in the engine; the fields a scoring needs are these.

```json
{
  "groups": {
    "quartet": {"renderer": "quartet", "parts": ["vn1", "vn2", "va", "vc"]},
    "piano":   {"renderer": "piano", "parts": ["soprano", "alto", "tenor", "bass"]}
  },
  "assignments": [
    {"voice": "soprano", "part": "vn1", "at": "1:1", "until": "35:1"},
    {"voice": "alto", "part": "va", "at": "9:4", "until": "13:1"}
  ],
  "pedal_points": [
    {"voice": "bass", "part": "vc", "at": "46:1", "until": "54:1", "octave": -12}
  ],
  "allow_uncovered": []
}
```

`at` defaults to `1:1`, `until` to `end`. A position may be `bar:beat`, `end`, or a mark: `arioso`, `arioso+8`, `arioso+8:4`. Marks come from the section list (`marks.from` points at the piece model). Each section's first bar is a mark under its id. If the sections do not add up to the score, orchestration stops.

| Key | Meaning |
|---|---|
| `voice` | a voice of the plan: `soprano`, `alto`, `tenor`, `bass` |
| `part` | who plays it; part names are unique across groups |
| `at`, `until` | the window, by the note's written start |
| `octave` | −24, −12, 0, +12, +24 |
| `level` | dynamic steps added to the plan |
| `accent` | a velocity offset |
| `articulation` | `auto`, `legato`, `detache`, `short`, and `roll` for timpani |
| `players` | orchestra winds and brass: `solo`, `a2`, `a4` |

`renderer` is `piano`, `quartet`, `orchestra` or `organ`. Quartet part names are `vn1`, `vn2`, `va`, `vc`, `cb`. Orchestra part names are the ids in the range table (`fl`, `hn.1`, `vc.div`, `timp`). Organ divisions are `HW`, `POS`, `OW`, `PED`, by part name unless `division` or the registration sidecar says otherwise (performance guide).

Group `options` carry what is not a line: the piano's `pedal` list, the orchestra's seating sidecar, the organ's `registration`. Piano pedal `"every": "harmony"` is not implemented and falls back to every half bar. Write `half` or `bar`.

The integrity check refuses a part note that is not its voice's note at the declared octave, a score note that no part plays, a pedal that is not a pitch the voice holds, a second line on a single-line part, a tempo that differs between groups, and an orchestra note outside its compass.
