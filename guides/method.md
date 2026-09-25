# Composing

The first piece was correct and still missed the music. Its subject was the tune copied out, so stretto, inversion and augmentation had nothing to hold. The second subject was stated three times at one pitch and never answered. Three root-position cadences in 66 bars left the named keys unconfirmed, and the hinge between two section composers left a dominant seventh unresolved. Two bars were an episode. The checkers measured correctness, and the devices lived in the proofs.

Positions are `bar:beat`, 1-based quarter-note beats (`12:2.5`). A check that fails exits 5. Tiers and restarts are in the recipes guide.

## 0. Brief

**Goal.** One page: the source, the constraints, the works that are the model, the duration, and the forces.

**Inputs.** The tune or other source, and the constraints the piece actually has.

**Outputs.** `brief.md`. `kapell new` writes `kapell.toml`, the folders and the template.

**Commands.** `kapell new DIR --brief brief.md [--template fugue4|fugue3|sonata|variations|chorale-prelude]` (planned).

**Who.** Opus, high effort.

**Gates.** The brief says what the source is for. The tune is the cantus firmus and the stock of cells. It is not the fugue subject. The brief names the form (`fugue`, `double-fugue` or `triple-fugue`), the duration, which of the five versions will be rendered, and the model (an arc such as Op. 110, a combination such as the Jupiter finale, a change of metre such as St Anne).

## 1. Material lab

**Goal.** A subject with contrapuntal potential, and the countersubjects, strettos and combinations the form will use.

**Inputs.** The brief and the source tune.

**Outputs.** `materials/materials.ly`, `materials/materials.json`, a short potential report, and `design/proofs.json`.

**Commands.** `kapell materials derive --subject S` (planned) writes the answer, inversion, augmentation, diminution and retrograde. `kapell find` (planned) searches subjects, countersubjects (`find cs --invertible 8,10,12`), stretto, combinations and augmentation. `kapell prove LAB.ly` (planned) appends one row to the proof table. `kapell check` on every lab that is kept.

**Who.** Code searches and scores. Opus, high effort, picks the subject, the second subject and the countersubjects, and says why.

**Gates.** The subject is not the tune in its own rhythm. It has a clean stretto closer than two bars at some interval, an inversion that is not a repeated note, and an augmentation that still has a melodic shape. Every combination the form will claim is proved: 0 errors, 0 parallels, 0 beat-parallels, 0 unjustified dissonances, 0 clashes. The blueprint cites proof ids.

Jev does not pick among these. On this project's own passages it chose the better reading at 0.47 to 0.56, which is chance.

## 2. Dramaturgy

**Goal.** The drama and the lines, written before the piece is divided into sections.

**Inputs.** The brief, the materials, the proofs.

**Outputs.** A design of about 200 lines, not a blueprint of several hundred. A tension curve, a cadence plan, a theme-treatment plan, a register arc, a metre and tempo plan, and the quotas in `kapell.toml`.

**Commands.** No command writes the design. `kapell skeleton build` (planned) may then write the skeleton, `plan.json` and the section cards. It locks entries only.

**Who.** Opus, high effort. Two designs, then one judge at the same effort. The judge is Opus. Jev does not rank designs: on the four proposals for the first piece it could only place a clear loser last (recipes guide).

**Gates.**

- Every named key has a cadence that confirms it, with a strength (root-position authentic, imperfect, half, plagal, deceptive). A key that will only be asserted by an entry is not a key in this plan.
- The hinge of the piece is one cadence with an owner. In *The Neighbour* that bar was a V4/2 whose seventh rose, written across a section boundary.
- Each subject after the first is given an answer at another pitch, an inversion or a stretto, and a combination with the first subject. State the orders that will actually be heard.
- The register arc includes the arrival. The arrival is not lower and smaller than the climax it answers.
- Entries are locked. The bars between them are free, and each free span has a target: episode, suspension count, cadence. A beat-sized window is not a span.
- The design says how many strong-beat suspensions the piece owes, and `kapell.toml` `[quotas]` records it. Twenty was the first piece's target. It reached 18, in 13 bars.
- Each device has an audibility note: how the ear will separate it (rhythm, register, or a gap). A device that cannot be separated does not go in the plan.
- One climax strategy. Two climaxes that are the same gesture are one climax written twice.

## 3. Outer-voice frame

**Goal.** One composer writes the soprano and the bass of the whole piece, figured, in one pass. The long line, the cadences and the hinge have one owner.

**Inputs.** The dramaturgy, the materials at pitch, the locked entries.

**Outputs.** `frame.ly`.

**Commands.** `kapell check` on the frame. `kapell xray --bars` on the hinge and on every structural cadence. A long-line analyser is not a command yet; the composer reads the outer voices across the seams.

**Who.** One composer, Opus, high effort, and one revision. Not a section agent.

**Gates.** Soprano and bass cross every seam, including the hinge. `xray` reports no `DIS7` and no `LT` on those bars: a chordal seventh resolves down by step in the same voice or by a real hand-off, and the leading tone of a dominant seventh in the top voice rises when the root falls a fifth. The cadence under the arrival is the one the dramaturgy named. The figuring is specific enough that a later voice can hang a 7-6, 4-3, 9-8 or 2-3 on it.

A two-voice frame will still fail the form-coverage and featured-role gates, because the inner entries and the performance plans do not exist yet. Those two gates start at the review. Do not "fix" them by faking inner parts into the frame.

## 4. Inner voices

**Goal.** The inner voices and the episodes, against the frame, the locked entries and the free-span targets.

**Inputs.** The frame, and a section card per agent. `kapell skeleton build` (planned) writes `design/cards/secNN.md`, under 3,000 tokens: that section's paragraph, its roles, its boundary notes, its keep items, the materials at pitch, and the neighbouring chords. The agent reads the card. It does not read the whole design on every turn.

**Outputs.** `score/sections/secNN_*.ly`.

**Commands.** `kapell splice --section N` on each section. `kapell check` and `kapell xray` on the assembled score once `kapell assemble` (planned) has joined them. Until `assemble` exists, join the sections with the project's own assembler and then run `check` and `xray`.

**Who.** Parallel agents, one section file each. Opus, medium effort, for ordinary filling. Opus, high effort, for an episode and for any bar the dramaturgy marked as a pivot. A suspension planner that proposes 7-6 and 4-3 chains is not a command yet; the quota is the target, and `xray` counts the result.

**Gates.** `splice` passes. That means:

- each voice is exactly the section's length, with a `% bars A-B` line;
- the first attack and the last note of every voice match the skeleton, including ties in and out;
- subject, answer and cantus notes are unchanged, and a countersubject changes only inside its landing window;
- no new unison;
- on the section and one bar either side, 0 errors, 0 parallels, 0 beat-parallels, 0 unjustified dissonances, 0 clashes.

The episode section contains the episode the design asked for. The strong-suspension count is moving toward the quota. Places the design called thin are still thin.

### Rules for every section

These are the composer rules, carried over from the first piece.

1. The voice holds notes, rests, ties and bar checks. Dynamics, tempo and articulation go in the plan.
2. Do not change a locked span. Keep items stay.
3. A new review item (`D4?`, `DIR`, `MEL`, `XREL`) gets one line at the top of the file saying why it is there. A new `ACC2` is a prepared suspension, a pedal, or a chord seventh.
4. Free voices move in the gaps of the thematic lines and hold where those lines move. They are built from the piece's own cells. Prefer a prepared suspension to a passing note. No chordal padding. Parallel thirds or sixths for no more than two beats. Four real voices, unless the template says otherwise.
5. Ranges live in `kapell.toml` `[ranges]`, as MIDI numbers. The first piece used soprano 60–84, alto 53–77, tenor 48–72, bass 36–62.

## 5. Review, two rounds

**Goal.** The whole piece, twice. The second round is part of the recipe. The first piece skipped it, and the unresolved seventh at the hinge shipped.

**Inputs.** The score, and the `xray` digest. Critics read the numbers before they read the notes.

**Outputs.** `reviews/round-N/*.json`, findings with a place (`secNN` and `bar:beat`) and a concrete fix, then a revised score.

**Commands.** `kapell xray` at the start of each round, and `kapell xray --full` when a total needs its lines. `kapell jev route` and `kapell jev park` send each finding to the notes or to the performance plan, and park the ones Jev calls minor. `kapell splice` and `kapell check` after each fix. `kapell status` records the round.

**Who.** Code runs the counterpoint gate. There is no counterpoint-reviewer agent. The Bach, arc and theme critics are Opus, high effort. Fixers are Opus, medium effort, and each fixer sees its own findings plus its card. Jev routes and parks. It does not decide whether a revision is better.

**Gates.** Both rounds ran. `xray` is green on every gate: check, clash, resolution, form, featured roles, quotas. Every major finding is fixed or answered in the notes. A round that did not run is an unfinished stage. `kapell status` is where the next session picks it up.

## 6. Listening

**Goal.** Hear the piece against the curve, and rewrite only the bars that disagree with it.

**Inputs.** The revised score and a piano plan.

**Outputs.** A render, and a short list of flagged bars.

**Commands.** `kapell render --version piano`, and `--bars A-B` for a passage. `--stems` when a device may be inaudible. `kapell qa --version piano` (planned) compares measured loudness and density with the dramaturgy. Until `qa` exists, read the render's report and compare it yourself.

**Who.** Code renders and measures. Opus, medium effort, reads the report. Opus, high effort, only on the flagged bars.

**Gates.** Measured loudness and density follow the curve from stage 2. On the first piece the curve was inverted: the arioso was the densest stretch, the approach to the second climax was sparser than the music around it, and the hinge was the weakest cadence. A device that cannot be separated on the stems is rewritten or dropped from the listener's guide. That piece listed "answer against its mirror" as something to hear; the heads were repeated notes, and the mirror could not be heard.

## 7. Performance and renders

**Goal.** Five performances of the same notes, with every featured line brought out, and a score of each.

**Inputs.** The ledger (`xray --full`), the tension curve, the score.

**Outputs.** `performance/<version>/plan.json`, an orchestration spec where the version needs one, and the audio. A deriver that writes the plan from the ledger is planned. Until it exists, write the plan from the ledger and the curve, then let `xray` check the cues.

**Commands.** `kapell perform --version V` and `kapell render --version V` for `organ`, `piano`, `quartet`, `orchestra` and `ensemble`. `kapell engrave --layout all`. `kapell qa --version V` (planned) for loudness, balance, clipping, tuning and duration. Thresholds are code.

**Who.** Code performs, renders and measures. Opus, medium effort, edits the plans and reviews the idiom of each version.

**Gates.** `xray` roles passes for every version: each featured line has a cue covering at least three quarters of its span (performance guide). Five renders exist. Five layouts exist. The first piece printed piano and quartet only.

## 8. Listener's guide

**Goal.** A guide a listener can use, generated from the ledger and then edited.

**Inputs.** `kapell xray --full` (the theme ledger) and the timings of one render.

**Outputs.** `NOTES.md`: the idea, a form table timed from the piano render, the five versions, and the devices worth hearing.

**Commands.** `kapell xray --full`. No command writes the guide.

**Who.** Opus, medium effort.

**Gates.** Every device in the guide is a row in the ledger, in a form the ledger names, and it survived the listening stage. A paper device is not listed. Timings come from the render report, not from multiplying beats by a tempo. The form claimed in the prose is the form `xray` accepted.
