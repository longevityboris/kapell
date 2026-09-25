# Counterpoint

`kapell check` and `kapell xray` measure whether the counterpoint is lawful and whether the piece did what it claimed. Character, drama and beauty are the critics' job, after they have read the numbers. Positions are `bar:beat`, 1-based quarter beats.

`check` exits 5 when a violation remains. `xray` exits 5 when any of its gates fails. The digest is the totals and the failing lines. `--full` prints the rest.

## What `check` gates

`kapell check [FILE|--section N] [--bars A-B]`. Violations are `ERR`, `PAR!`, `BEAT` and `DIS!`.

**Parallels (`PAR!`).** Between two attacks where both voices move, a perfect unison, octave or fifth that is answered by the same perfect interval. Same direction and contrary motion both fail. A held voice is not a parallel.

**Beat-parallels (`BEAT`).** The same perfect interval on two successive quarter-beats, both voices moving, at least one of them attacking the second beat, with another attack in between. Adjacent attacks are already `PAR!`.

**Dissonance (`DIS!`).** At an attack, a second, seventh or ninth between two sounding notes, when neither note is justified. A perfect fourth or a tritone is treated as a dissonance only when its lower note is the bass of the sonority.

A dissonance is justified, and printed as `DIS` rather than `DIS!`, when a voice explains it:

| Tag | What the voice does |
|---|---|
| `PT/NT` | attacked by step and left by step |
| `SUS` | held, then down by step |
| `SUS(re)` | held or re-struck, then down by step |
| `RET` | held, then up a semitone |
| `APP` / `APT` | attacked and left by step, or approached by leap and left by step |
| `ANT` / `ANT7` | anticipation, including one that resolves down after a re-strike |
| `ESC?` | left by leap after a stepwise approach |

Stepwise motion is enough for `PT/NT`, including on a strong beat and including when both notes are struck together. That is a gate for grammar, not a reward for dissonance. The safe piece that avoids suspensions passes `check`. The suspension quota exists because of that.

**Errors (`ERR`).** A note outside the voice's MIDI range (`[ranges]` in `kapell.toml`; otherwise 21–108), a voice that does not parse, unequal voice lengths, a failed bar check, a tie onto a different pitch.

## What `check` only reports

These are in the review list. They do not fail the gate. `--full` prints them. A new one still needs a one-line reason in the section file.

| Tag | Meaning |
|---|---|
| `CROS` | a voice sounds below the voice written under it |
| `DIR` | the top voice leaps, in similar motion with the bass, onto a perfect unison, octave or fifth |
| `MEL` | an augmented 2nd, an augmented 4th leap, a diminished 5th leap, a diminished 4th, a 7th, a leap beyond the octave, an augmented 5th |
| `D4?` | a fourth or a tritone over the bass with no justification tag |

`check` classifies intervals by semitones. A spelled augmented fifth, such as D over G-flat, has the semitones of a minor sixth and is not reported. An inner tritone that is not over the bass is not reported either.

## What `xray` adds

`kapell xray [FILE] [--bars A-B] [--full]` runs `check`, then the gates below. `--bars` limits check, strict and resolution. Coverage and featured roles stay whole-piece. Without a `kapell.toml` project, coverage, roles and quotas are skipped.

### Clashes

`CLASH` is a gate: two notes a chromatic semitone apart, on the same letter, sounding together (`C` against `C#`). Always wrong.

Reported and not gated:

| Tag | Meaning |
|---|---|
| `XREL` | the same letter, different accidentals, in two voices within a quarter-note |
| `ACC` | a dissonance on a strong quarter (beats 1 and 3 of a 4/4 bar; every other quarter in the strict checker) that is not a prepared suspension or a retardation |
| `ACC2` | the same, and both notes are struck together |

A new `ACC2` has to be a suspension, a pedal or a chord seventh. That is a composer rule. `xray` will not fail the piece for it.

### Unresolved sevenths and tendency tones

`resolution` reads spelled seventh chords (the letters stack in thirds; a passing sonority does not).

**`DIS7`.** The seventh resolves down by step (1 or 2 semitones) when its voice leaves it, within the beat window in `kapell.toml` `[checks] resolution_beats` (default 4). Also resolved: an ornament that reaches the step below within two beats; another voice taking that step in the same register; another voice taking the same seventh and stepping down; the seventh and the bass rising together (the V4/3–I6 licence); a German sixth spelled as a dominant seventh and resolving outward. A minor seventh with its third in the bass is read as an added sixth and skipped. A bass note held a bar or more is a pedal and skipped. Only a seventh on a quarter-beat, or at least a quarter long, is checked.

This is the bar-54 fault. The seventh, E-flat, was in the bass of a V4/2 and rose to G-flat. Nothing in the old checker saw it.

**`LT`.** The third of a dominant seventh, when it is the top sounding voice, rises a semitone if the next root lies a fifth below, unless another voice takes the tonic in the same register.

### Suspension quotas

`xray` counts real prepared suspensions. A strong beat is beat 1 or 3 in 4/4, and beat 1 in other metres. The figure needs a consonant preparation (a fourth above the bass counts as dissonant), an agent that attacks against it, a suspension interval, and a step down to a consonance while the agent is still sounding.

| Position of the prepared note | Interval |
|---|---|
| above the agent | 7th (7-6), compound 9th (9-8), 4th (4-3, and the agent is the bass) |
| below the agent | 2nd or 9th (2-3), 4th (4-5, and the prepared note is the bass) |

The same figure on a weak beat, with the agent at least a quarter long, is counted as weak. It does not fill the strong-beat quota.

`[quotas]` in `kapell.toml` is the gate. `strong_suspensions = 20` means at least 20. A key prefixed `max_` is an upper bound (`max_dis7 = 0`). The measured counts include `strong_suspensions`, `weak_suspensions`, `dis7`, `unresolved`, `uncued_features` and `form_violations`. A missing quota is not a failure. An unmet one is.

The count is not a judgement of style. Fifty-three of the first piece's sixty-six bars had no strong-beat suspension, and `check` was clean.

### Theme coverage and form claims

Themes are declared in `kapell.toml`:

```toml
[themes]
S1 = "subjectOne"
S2 = "subjectTwo"
```

The ledger finds each theme in each voice under transposition, inversion, augmentation and diminution. Rests break a line. Repeated pitches collapse, so a tie and a re-strike match the same way. Contour must agree, and each interval may be a semitone off, which admits a tonal answer, a minor theme restated in major, and a diatonic inversion. A statement needs at least six notes and 60% of the theme, with at most 40% of its intervals altered.

`[piece] form` is checked against that ledger:

| Form | What each later subject needs |
|---|---|
| `fugue` | the subject present |
| `double-fugue` | an answer (a prime statement at a second pitch; an inversion does not count), an inversion or a stretto, and a combination with the first subject sounding at the same time |
| `triple-fugue` | the same, for both later subjects |

The form string has to be one of those three, under `[piece] form`. Any other value is not checked. Subjects are the theme labels `S1`, `S2`, and so on, unless `[form] subjects` lists them. Countersubjects are tracked in the ledger and are not subjects unless listed there.

`S2` in the first piece would fail `double-fugue`: three statements, all starting on the same C, no answer, and the combination with `S1` never turned over. Calling the piece a double fugue does not satisfy the gate.

### Featured-role cues

Every featured line needs a cue in every version's plan. Featured lines are the piece model's `subject`, `answer` and `cf` roles, plus any `[[features]]` entry in `kapell.toml` (a lament, a head imitation, anything the analysis says must be heard). The cue has to cover at least three quarters of the span. The performance guide defines what counts as a cue. A version with no cue fails `xray` with `ROLE`.

`splice` is the section gate, not part of `xray`. It checks length, boundary notes, locked spans, new unisons, and then `check` plus clashes on the section and one bar either side.

## What they do not judge

Clean totals are the entrance condition for review, not the review.

The gates do not judge:

- whether a line sings, or whether a free voice is padding;
- whether a key has been arrived at, as against merely labelled (the cadence plan is the dramaturgy's, and no command scores cadence strength yet);
- whether the tension curve matches the form, or whether the arioso is denser than the climax;
- whether a proved device can be heard;
- whether the long line crosses a seam, or whether two climaxes are the same gesture;
- beauty, character, or the fitness of the idiom.

`ACC` and `XREL` are a strict ear asking a question. Answering the question is the composer's job.

## Exemplars

The device is worth using when it can be heard. The first piece's augmented inversion was a held F, because the subject's head was a repeated note.

**Stretto.** Bach, *The Art of Fugue*, Contrapuncti 5–7: the subject enters against itself, and in Contrapunctus 7 at more than one speed. Mozart, the Fugue in C minor, K. 426: stretto and close imitation, and scarcely a bar without the head of the subject. Beethoven, Op. 110: the subject is a chain of rising fourths, so a stretto is almost the subject's own shape. A repeated-note head has no stretto closer than a long one. The first piece had none under two bars.

**Invertible counterpoint.** Bach, *The Well-Tempered Clavier* I, Fugue in C minor: the countersubject is heard above the subject and below it, and the episodes are made of that same pair. Mozart, the Jupiter finale, K. 551: in the coda each motif is passed through the voices, so the combination is heard as lines and not as a chord. Beethoven, the Grosse Fuge, Op. 133: the subject and the leaping countersubject exchange vertical place. Six proved orders, three of them heard, is a proof table and not yet a piece. The first piece heard three of its six.

**Augmentation.** Bach, *The Art of Fugue*, Contrapunctus 7: augmentation and diminution sound together, and the subject still has a profile at every speed because it outlines the triad, the scale and the leading tone. Mozart, K. 426, does not augment; it keeps one speed and uses stretto and inversion. Beethoven, the Grosse Fuge, states the subject in long notes in the Overtura before the fast fugue, and the intervals are what remain recognisable. Doubling the values of a repeated note produces a pedal.

**Combination of subjects.** Bach, *The Well-Tempered Clavier* I, Fugue in C-sharp minor: each of the three subjects enters and establishes itself before they are combined. The same plan is St Anne, BWV 552/2. In *The Art of Fugue*, Contrapunctus 9, the new subject has its own exposition, and the main subject then joins it in augmentation. Mozart, the Jupiter coda: five motifs, each already exposed, rotating through every voice. Beethoven, the Hammerklavier fugue: the late D-major cantabile subject has its own entries before it is combined with the rest. A second subject stated three times at one pitch, never answered, has not been combined with anything. It has been displayed.

**Cadence planning.** Bach, *The Well-Tempered Clavier* I, Fugue in C minor: the episodes end on the new tonic, the relative major and then the minor dominant, before the next entry, so the tonal plan is heard. Mozart's fugal choruses, the Requiem Kyrie and *Cum Sancto Spiritu* in the C minor Mass, cadence in the key they have reached before the next large entry. Beethoven, Op. 131: the fugue plants A, a semitone above C-sharp, and the D-major second movement confirms that neighbour. Op. 110 returns to A-flat on a dominant prepared at length, and the end opens into the widest register of the movement. Three root-position cadences in a 66-bar piece, none of them in the home key for the first 54 bars, means the keys were names.

**Episodes.** Bach, the C minor fugue above: about a third of its 31 bars are episodes, built from the subject head or the countersubjects, often in invertible counterpoint, and they carry the modulation. Mozart, K. 426, is the other pole: the head is almost always present, and the "episode" is the subject broken into its leap, not a new tune. Beethoven, the Grosse Fuge and the Hammerklavier fugue, builds whole sections from fragments, the trill, the leap, the syncopation. The first piece had one episode, bars 18–19, because the free material had been squeezed into the gaps between locked entries.
