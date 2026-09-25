# Recipes and tiers

Five piece recipes, all planned: `design`, `compose`, `review`, `render`, `finish`. Each one will be a workflow that reads its arguments from `kapell workflow args RECIPE` (planned): the project root, the section cards, and the tier of every stage. `tiers.json` is the one file that sets model and effort. It is planned too. Until those workflows exist, a session follows the same stages by hand and runs the commands itself. The stage gates are in the method guide.

| Recipe | What it runs | Who |
|---|---|---|
| `design` | brief, material search, proofs, two dramaturgies, one judge | Opus high; code for `find`, `prove`, `check` |
| `compose` | the outer-voice frame, then one agent per section, then `splice` | Opus high for the frame, the episodes and the pivots; Opus medium for ordinary filling; code for `splice` and `check` |
| `review` | `xray`, then the critics, then the fixers; two rounds | code for the gate; Opus high for the Bach, arc and theme critics; Opus medium for fixes; Jev to route and to park |
| `render` | plans, `perform`, `render` of all five kinds, `qa` | code; Opus medium edits the plans and reads a failed QA report |
| `finish` | `engrave --layout all`, the listener's guide | code engraves; Opus medium writes the guide |

`qa`, `find`, `prove`, `assemble`, `skeleton build` and `workflow` are planned. `check`, `xray`, `splice`, `engrave`, `perform`, `render`, `status` and `jev` exist.

A review round loops until no major finding remains, or until both rounds have run. Skipping the second round is how the unresolved seventh at the hinge of the first piece survived. A killed round stays unfinished in `kapell status`. It is not marked done.

## Model tiers

Every musical agent is Opus 5.5. Effort is the only dial. Sonnet and Haiku are not used. Anything a command can decide, the command decides.

| Effort | Work |
|---|---|
| Opus, high | the brief; choosing the materials; dramaturgy and the judge; the outer-voice frame; episodes and pivotal bars; the Bach, arc and theme critics |
| Opus, medium | routine inner-voice filling against the frame; local fixes once a finding names the bar; joining sections; editing derived performance plans; reading an audio-QA report; idiom review; the listener's guide and the README |
| Code | `check`, `xray`, `splice`, search, proofs, engraving, `perform`, `render`, `qa`, counting, loudness, and the resume line. The counterpoint reviewer is this row. There is no agent in that role. |
| Jev | routing a finding to the notes or to the performance plan; parking a finding it calls minor. Nothing else. |

Jev is `jev-1.13.0`, pinned in `kapell.toml` when a project sets it. It runs as `akm run --only TYPESAFE_API_KEY -- kapell jev …`, so the key stays in the keychain. Jev returns a choice and a confidence. It does not write notes, prose or numbers.

Measured on 672 labelled decisions from the first piece ($0.021, median 0.63 s):

| Decision | Result | Use |
|---|---|---|
| Route a finding to the notes or to the performance | 0.86 of 100; 0.90 when confidence is at least 0.9, which covered 84% | Act at confidence ≥ 0.9. Below that, the orchestrator routes it. |
| Call a finding minor | 36 of 37 calls were minor | Park those for a batch pass. A call of "major" is about half wrong. Everything called major goes to a reviewer. Never drop a major. |
| Which of two passages is better | 0.47 on LilyPond, 0.56 on a pitch grid | Do not ask. Chance, and it flips with the order of the pair. |
| Does this passage contain an error? | AUC 0.54 | Do not ask. `check` catches the parallels and the clashes it was shown. |
| Severity as a classifier | 0.67, against 0.68 for always answering "minor" | Do not classify. The minor calls above are the only severity fact that is usable. |
| Which design is better | placed the clear loser last; the top three were inside the noise | Do not let it pick a winner. |
| Which section a finding belongs to | 0.89, the same as a regex on the first bar number | Code does this from `bar:beat`. Jev only when the regex finds no bar, and only at confidence ≥ 0.9 (0.96 at that gate). |

On the notes themselves, 78% of Jev's answers had confidence under 0.5, and none reached 0.9. It is a dispatcher.

## Who writes the code

Codex, Grok and Cursor build the kit and do other routine engineering. Each one works in its own git worktree, on files no other agent is editing, and the result is reviewed before it is merged. They do not take the high-effort stages. A musical fill, a critic and a design stay on Opus in the composing session.

One section file per composer. Do not run two agents on the same file.

## Short runs

An agent task is about 20 minutes: at most 40 turns, and at most about 150,000 tokens of context. The agents that ran 60 to 116 minutes on the first piece cost three to four times the agents that ran 10 to 25 minutes, because they re-read a large design on every turn.

Each composer and each fixer gets a section card under 3,000 tokens (`kapell skeleton build`, planned), not the whole design. `check` and `xray` print a digest unless `--full` is asked for. Renders and searches run as commands, outside the agent's turn. A turn that waits on a render is how the context was written again from scratch.

One heavy run per usage window. A heavy run is a design, a frame, or a review round: the stage that used to be a 100-minute agent. When the window kills it, the next window starts from `kapell status`.

## Restart

`kapell status` is the resume point, under 2,000 tokens: the phase, which sections are done and which are open, the last check totals, the quotas, the layouts and renders still missing, and the next command. `kapell status --no-check` skips the live check when only the phase is needed.

A fresh session runs `status` before it reads a score or a design. It continues at the next command. It does not re-derive the piece from the beginning, and it does not re-read the repository to find out where the work stopped. Each finished stage is a committed checkpoint, so a restart skips what already happened.
