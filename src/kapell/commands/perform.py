"""kapell perform: the version's performance MIDI (perform.py / orchestrate.py and its helpers), no audio."""
from kapell.commands import KapellError
from kapell.engines import pipeline

SPEC = {
    "name": "perform",
    "effect": "write",
    "help": "build a version's performance MIDI and scoring sidecars into renders_dir(piece)/<version>/build/",
    "runtime_s": 3,
    "output_tokens_typ": 150,
    "examples": [["perform", "--version", "organ"], ["perform", "--version", "beethoven_piano"]],
}


def add_arguments(p):
    p.add_argument("--version", required=True, help="a folder under performance/ or a kind: " + "|".join(pipeline.KINDS))


def run(args, ctx):
    if ctx.root is None:
        raise KapellError("no_project", "no kapell.toml above the working directory", "cd into a piece, or run kapell new")
    v = pipeline.resolve_version(ctx.root, ctx.cfg, args.version)
    out = pipeline.outdir(ctx.root, ctx.cfg, v)
    steps = pipeline.Steps(out / "perform.log")
    perf = pipeline.perform_version(ctx.root, ctx.cfg, v, steps, out / "build")
    data = {"version": v["name"], "kind": v["kind"], "build": str(out / "build"), "steps": steps.done}
    if "midi" in perf:
        n = pipeline.note_counts(perf["midi"])
        data.update(midi=str(perf["midi"]), notes=sum(n.values()), per_voice=n)
    else:
        import json
        m = json.loads(perf["manifest"].read_text())
        data.update(manifest=str(perf["manifest"]),
                    per_group={g: sum(pipeline.note_counts(out / "build" / gd["midi"]).values()) for g, gd in m["groups"].items()})
    return data
