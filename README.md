# kapell

A composition kit for agent-written counterpoint: material search, proofs, quality analysis, expressive performance and sampled rendering (organ, piano, string quartet, orchestra, piano + quartet).

Under construction. The design is in [longevityboris/jurassic-fugue/docs/kit](https://github.com/longevityboris/jurassic-fugue/tree/main/docs/kit); the first project and regression fixture is *The Neighbour* in that repo.

## Usage

Install (editable, from a checkout): `uv tool install --force --editable /path/to/kapell`. Then run `kapell <command>` from anywhere inside a project (a directory with `kapell.toml`; commands walk up to find it, or pass `--project DIR`). `python3 -m kapell` works too.

```
kapell status            # phase, sections done/open, last check totals, quotas, layouts, renders, next command
kapell doctor [--full]   # lilypond, sfizz_render, sample libraries and IRs, Jev key present, Python deps, broken commands
kapell agent-info [--command X]   # machine-readable manifest built from every command's SPEC
kapell guide [NAME]      # raw markdown guide; lists guides without a name
kapell version           # kit version and the project's kit pin
```

Output is a JSON envelope whenever stdout is not a terminal (or with `--json`): `{"version":"1","status":"success"|"no_results"|"partial_success"|"fail","data":{...}}`, or `{"version":"1","status":"error","error":{"code","message","suggestion"}}`. `--json` and `--quiet` work anywhere on the line. `guide NAME` is the one exception: it prints raw markdown.

Exit codes: 0 ok; 1 transient (retry); 2 config or environment (run `kapell doctor`); 3 bad input; 4 rate limited; 5 a musical check failed, with the violations in `data`. So `until kapell check …; do …; done` works in a shell loop.

Commands are plug-ins: each module in `src/kapell/commands/` defines `SPEC`, `add_arguments(parser)` and `run(args, ctx)` (see that package's docstring). A module that fails to import still appears as a verb that exits 2 with the import error, and `kapell doctor` lists it.

## Tests

Run `PYTHONPATH=src python3 -m pytest tests -q`. Golden tests read a temporary Git archive of
The Neighbour at revision `9b343c0ce827389007127f0ccb1da090e15b782c`, before its bar-54 repair.
This keeps the known-gap regressions stable while the piece continues to change. Set
`KAPELL_FIXTURE_NEIGHBOUR` to its checkout; `KAPELL_FIXTURE_REVISION` explicitly overrides the pin.
Tests never alter that checkout. Audio tests require `KAPELL_ENGINE_TESTS=1` and current derived
sample-library assets; generator changes require rebuilding those assets with the engine setup scripts.
