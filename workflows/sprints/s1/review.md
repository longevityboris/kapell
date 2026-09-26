You are working in /Users/biobook/Music/llm-music/kapell-wt/s1-review, a git worktree (branch s1-review) of kapell, a Python CLI composition kit. Do NOT commit; leave your changes in the working tree for review.

Goal: finish phase 1 of the kit: review what the five build lanes wrote and fix what is wrong.
Spec: /Users/biobook/Music/llm-music/fugue-jp/docs/kit/C_packaging_architecture.md sections 3 (envelope, exit codes, manifest, commands), 4 (short digests by default), 5 (known-gap checks), 8 (layout, no absolute paths) and 10 (tests). Contracts you must keep: src/kapell/commands/__init__.py, src/kapell/config.py, src/kapell/project.py.
Fixture: The Neighbour at /Users/biobook/Music/llm-music/fugue-jp/ricercar (read only; it has kapell.toml).

Steps:
1. Run: PYTHONPATH=src python3 -m pytest tests -q   (currently 129 pass, 2 skip, 1 xfail).
2. From the fixture directory, run every command with PYTHONPATH=<worktree>/src python3 -m kapell ...: status, doctor, agent-info, version, guide, check, splice --section 7, xray, xray --full, perform --version beethoven_piano, render --version piano --bars 1-8, engrave --layout piano. Note crashes, wrong exit codes, outputs that are not short by default, envelope violations.
3. grep src/ for absolute paths (/Users/...) and import-time side effects; fix them.
4. Fix everything you found. Do NOT edit src/kapell/piece/engrave.py or templates/layouts/ (another lane owns them).
5. Keep all tests green and add tests for what you fixed.
Finish with a short report: what you found, what you fixed, what is left, final pytest line.
