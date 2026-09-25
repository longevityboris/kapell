---
name: kapell
description: >
  Compose fugues, counterpoint and ricercars with kapell, and orchestrate and
  render the music. Use when composing fugues, writing counterpoint, planning
  a ricercar, orchestrating a score, or rendering music with kapell.
---

# kapell

The kit composes a piece, directs the performance and renders it. Checks, proofs and renders are commands. The notes are a model's job. Read one guide at a time. `kapell guide <name>` prints it.

## When to use

Use it to start a piece, to continue one after a killed run, to check counterpoint, or to render a version. Read the method guide before writing notes, and the counterpoint guide before changing a passage to satisfy a check. Building the kit, and other routine engineering, goes to Codex, Grok or Cursor in a git worktree and is reviewed before merge.

## The ten commands

| Command | What it does |
|---|---|
| `new DIR --brief brief.md` | planned. Project, `kapell.toml`, and a template: `fugue4`, `fugue3`, `sonata`, `variations`, `chorale-prelude`. |
| `find` | planned. Subjects, countersubjects, stretto, invertibility, combinations, augmentation. |
| `prove LAB.ly` | planned. A checker-clean lab, as one row in `design/proofs.json`. |
| `check [FILE]` | Parallels, beat-parallels, unjustified dissonances, ranges. Exit 5 on a violation. |
| `xray [FILE]` | `check`, plus clashes, unresolved sevenths and leading tones, theme coverage and the form claim, featured-role cues, quotas. |
| `splice --section N` | One section against the skeleton: length, boundaries, locks, unisons, the joins. |
| `engrave --layout all` | PDFs. Layouts: `piano`, `quartet`, `organ`, `orchestra`, `ensemble`. |
| `perform --version V` | MIDI from `plan.json` and, where the version has one, the orchestration spec. |
| `render --version V` | Audio. Kinds: `organ`, `piano`, `quartet`, `orchestra`, `ensemble` (piano and quartet). `--bars A-B` previews a passage. |
| `status` | Resume point, under 2,000 tokens: phase, open sections, last totals, quotas, next command. |

Also planned: `assemble`, `materials derive`, `skeleton build`, `qa`. Already installed, besides the ten: `jev route`, `jev park`, `doctor`, `setup`, `guide`, `agent-info`, `version`. Flags for any of them: `kapell agent-info --command X`.

A musical failure exits 5 and lists the violations. Exit 2 is the environment: run `kapell doctor`.

## Recipe

| Stage | Who | Command |
|---|---|---|
| Brief | Opus high | `new` (planned) |
| Material lab | code, then Opus high | `find`, `prove` (planned), `check` |
| Dramaturgy | Opus high | two designs, one judge |
| Outer-voice frame | one Opus high composer | `check`, `xray --bars` on the hinge |
| Inner voices | Opus medium; Opus high on episodes and pivots | `splice`, one section file per agent |
| Review, two rounds | code, then Opus high critics | `xray` first; `jev route` and `jev park` |
| Listening | code; Opus high on flagged bars | `render --version piano` |
| Performance and renders | code; Opus medium edits the plans | `perform`, `render`, `engrave --layout all` |
| Listener's guide | Opus medium | written from `xray --full` |

Tiers, the Jev measurements, and the rules for short runs are in the recipes guide. The gates for each stage are in the method guide.

## Guides

| Guide | What it holds |
|---|---|
| `method` | the recipe, stage by stage: goal, inputs, outputs, commands, who, gates |
| `counterpoint` | what `check` and `xray` enforce, what they leave to the critics, exemplars |
| `orchestration` | the five versions, their ranges, doubling, how a spec assigns a voice |
| `performance` | the plan schema, roles and boosts, dynamics, tempo, organ registration, the cue rule |
| `recipes` | the five workflows, Opus high and medium, code, Jev, worktrees, restarts |

After a usage limit, run `kapell status` and continue at the next command it names. One heavy run per usage window.
