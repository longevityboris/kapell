# Performance

The notes are in the score. The performance is `performance/<version>/plan.json`. `kapell perform --version V` turns that plan, and the version's orchestration spec if it has one, into MIDI. `kapell render --version V` turns the MIDI into audio. Neither command invents a reading.

Write the plan from the theme ledger and the tension curve. A deriver that does this from `xray` is planned. Until it exists, write the plan by hand from those two, and let `xray` reject a featured line with no cue. The first piece's plans were written from the skeleton and then edited, and they cut entries short: a stretto boosted for two bars of a five-bar statement, a lament never marked.

Positions are `bar:beat`. The beat is a quarter note, 1-based, and fractions are allowed (`12:2.5`). `end` means the end of the score.

## Schema

Every key is optional except `voices`.

```json
{
  "voices": ["soprano", "alto", "tenor", "bass"],
  "measure": "1",
  "tempo": [
    {"at": "1:1", "bpm": 78, "unit": "quarter"},
    {"at": "28:1", "until": "29:1", "to_bpm": 66}
  ],
  "breaths":  [{"at": "30:1", "ms": 1400}],
  "fermatas": [{"at": "29:1", "extra_beats": 3}],
  "dynamics": [
    {"at": "1:1", "level": "p"},
    {"at": "26:3", "until": "28:1", "to": "ff"},
    {"at": "30:1", "level": "pp", "voice": "soprano"}
  ],
  "roles": [
    {"voice": "alto", "at": "5:1", "until": "9:1", "role": "answer"}
  ],
  "role_boost": {"subject": 9, "answer": 9, "cf": 8, "cs": 2, "free": -4},
  "role_level": {"subject": 0.7, "answer": 0.7, "cs": 0.2, "free": -0.2},
  "pedal": [{"at": "30:1", "until": "35:1", "every": "half"}],
  "humanize": {"ms": 6, "vel": 2}
}
```

**`voices`.** Top to bottom. These are the LilyPond variable names.

**`measure`.** Bar length in whole notes. `"1"` is 4/4 or 2/2.

**`tempo`.** A step change at `at`, in `bpm` per `unit` (`quarter`, `half`). A linear ritardando or accelerando is `until` plus `to_bpm`. One map for every version. Orchestration may not override it.

**`breaths`.** A caesura before `at`. The sixteenth before that position is stretched by `ms`, and notes that end there release before the added time, so the breath is silence rather than a longer note. Notes held across the position are held through it. The first piece lost the general pause before the arioso until this was true: the fermata chord filled the gap.

**`fermatas`.** `extra_beats` lengthens the moment that starts at `at`.

**`dynamics`.** A global level, a hairpin, or a per-voice override from that point on. `level` is `ppp` `pp` `p` `mp` `mf` `f` `ff` `fff`, or a number 1 through 8. A hairpin is `to`, linear in that scale, from `at` to `until`. Hairpins need an attack inside every half bar: the piano sets its loudness at the note-on, so a hairpin with nothing under it does not sound.

The words map to velocity on the piano target: `ppp` 22, `pp` 32, `p` 44, `mp` 56, `mf` 68, `f` 82, `ff` 98, `fff` 112. A downbeat adds 3, beat 3 adds 1.5, an off-beat subtracts 2 or 3. A note above the local mean, within a bar, is a little louder, capped at 6. A note of a half or longer adds 2.

**`pedal`.** Piano sustain, CC64, re-pedalled every `half` or every `bar` from `at` to `until`. `every: harmony` is accepted and behaves as `half`. Pedal changes that fall while the piano rests are dropped.

**`humanize`.** Random onset and velocity. Defaults are 6 ms and 2 velocity steps.

## Roles and role boosts

`role` is `subject`, `answer`, `cf`, `cs` or `free`. `free` is the default when no role covers the note.

`role_boost` is a velocity offset. On the piano target it is applied in full. On the strings target it is halved, because the line is brought out by the envelope instead. The numbers in the schema above are the working piano set: subject and answer +9, cantus +8, countersubject +2, free −4. The first piece used +7 and a `role_level` of +0.5 for an augmented cantus, so that a long pedal note did not shout like an entry. Set the offsets in the plan. Do not inherit them from a comment.

`role_level` is added to the strings CC1/CC11 envelope (bow pressure and timbre), in the same 1-to-8 dynamic scale. Default, if the key is absent, is no offset. Subject and answer at +0.7, countersubject at +0.2, free at −0.2 is the quartet reading.

Subject, answer and cantus also speak 8 ms early, a melody lead. That is not a substitute for a cue. A role with a zero or negative boost does not count as bringing the line out.

Write the role for the whole statement. The ledger's `at` and `until` are the span. A boost that covers the head and stops is the fault the cue rule was added to catch.

## Dynamics and the curve

The dynamic shape is the dramaturgy's tension curve, written as levels. Consequences, from the first piece:

- Two subito drops (into the arioso, onto the pedal) are events. Six resets, one per section, mean each composer shaped a private arc. The frame's owner decides which drops survive.
- The loudest stretch is the climax the dramaturgy named. On the first piece the organ check required the second climax at least 1.5 dB of short-term loudness above the first, and 1 dB above the apotheosis. Those margins belonged to that piece. A new piece sets its own, and `qa` (planned) enforces them in code.
- The arrival after a climax is a diminuendo, not another subito and not a breath, when the drama is one of continuation.
- On that same organ check the arioso sat under the exposition, and its tune sat at least 3 dB over each accompanying stem. A solo that the global curve would bury gets a per-voice override. The override is not a second dynamic plan.

## Tempo maps

The map is part of the drama. The first piece's piano reading, which the form table uses:

| Bars | Tempo |
|---|---|
| 1–27 | 78 |
| 28 | ritardando to 66; fermata at 29:1, plus 3 beats; pause of 1.4 s |
| 30–34 | 52, the arioso |
| 35–45 | breath, then 64 accelerando to 76 |
| 46–52 | 76 |
| 53 | ritardando to 68; fermata on the dominant, plus 2 beats |
| 54 | 62 slowing to 56 through the hinge |
| 55–62 | 72 |
| 63–66 | ritardando to 56; final fermata, plus 3 beats |

A new piece has its own map. What carries over is the shape of that one: a slower aria, an accelerando out of the collapse, a broadening at the hinge, one tempo shared by every version. Mixed metres are a property of the score. The tools still assume one metre in several places; a change of metre is a design decision, and the bars have to parse.

Organ articulation is applied after the plan. A step into the next note is legato (the key up 8 ms before the next key). A repeated note is detached, about a quarter of its length, so the pipe speaks again. A leap of a third, or of a fourth or more, opens a shorter gap. A note before a rest, and a note that ends on a breath, release early enough that the rest stays empty.

Quartet bowing tapers the bow into each breath, so the players lift together instead of stopping at full bow. The swell on notes of a half or longer is already in the strings target; the quartet helper deepens it, and leaves out the bars where a tutti sustain would become the loudest moment.

## Organ registration

Registration is not a key of `plan.json`. It is the organ group's `registration` sidecar. `kapell perform` writes it from the spec.

```json
{
  "manuals": {"soprano": "HW", "alto": "OW", "tenor": "POS", "bass": "PED"},
  "manual_changes": [{"at": "30:1", "voice": "soprano", "division": "POS"}],
  "changes": [
    {"at": "1:1", "HW": "flute8", "POS": "flute8", "PED": "pedal16+8"},
    {"at": "50:1", "HW": "plenum_reed", "PED": "pedal_plenum_reed"}
  ],
  "enclosed": [],
  "gain_db": 0
}
```

`changes` switches the named divisions at `at`. A division not named keeps its stops. `manual_changes` moves a voice to another division, at a rest, the way a hand moves. `enclosed` names the divisions in a swell box. Leave it empty for the Bach reading: loudness changes by adding stops. `swell: true` on the organ group lets the plan's dynamic envelope drive CC11, and then `enclosed` defaults to `POS`.

Named registrations (`flute8`, `principal8`, `plenum`, `plenum_reed`, and the pedal pairs) are the organ engine's. A change may also be `"off"`, a custom name, or an explicit list of that division's stops. Couplers are not modelled. A stop list names only the division's own stops.

Decide the registration from the curve. Add stops at section joins. Hold the reed chorus until the main climax. Step down in terraces at a hinge. Give a cantus a principal the listener can separate from the flutes under it. The last chord can be the softest registration in the piece.

## Every featured line gets a cue

`xray` fails a version that does not bring its featured lines out. This is a gate, not a preference.

A featured line is:

- a `subject`, `answer` or `cf` role in the piece model;
- or a `[[features]]` entry in `kapell.toml`: `label`, `voice`, `at`, `until`. Use these for a lament, a head imitation, or any inner line the analysis says must be heard. Set `[checks] featured_roles = []` only to turn the piece-model half off.

A cue, in that version:

- a `roles` entry for that voice whose role has a positive `role_boost` in that plan; the overlap with the feature is what counts; or
- an orchestration assignment or pedal point for that voice with `level` above 0, an articulation, or `players: solo`, and the window starts or ends within one quarter-note of the feature.

The cues have to cover at least three quarters of the span (`[checks] feature_cover`, default 0.75). A section-long assignment does not count, because neither end falls on the feature. Cover the statement.

One shortcut in the linter: if a spec in that version takes its marks from `piece.py` or `piece.toml`, every piece-model role is treated as cued for its whole span. A `[[features]]` entry is never covered by that shortcut. Write the cue anyway. The shortcut is not the reading.

Every version is linted, the organ included. A registration change is how that version makes a line audible, and the linter does not read the registration sidecar. The cue it accepts is the plan role or the assignment. `level` does nothing on the organ (orchestration guide), so the assignment cue there is an articulation or `players: solo`, and the plan cue is a positive `role_boost`. A line with no cue is `ROLE` in `xray`, and the render is not finished.
