"""kapell render: a version of the piece through its engine, written outside git."""
from kapell.commands import KapellError
from kapell.engines import pipeline

SPEC = {
    "name": "render",
    "effect": "execute",
    "help": "render a version (score + plan + spec -> engine -> wav/m4a) into renders_dir(piece)/<version>/",
    "runtime_s": "17-240",
    "output_tokens_typ": 250,
    "examples": [["render", "--version", "organ", "--bars", "1-8"], ["render", "--version", "piano"],
                 ["render", "--version", "beethoven_quartet", "--stems"]],
}


def add_arguments(p):
    p.add_argument("--version", required=True,
                   help="a folder under performance/ or a kind: " + "|".join(pipeline.KINDS)
                        + " (a kind resolves to the one folder of that kind in [versions].render)")
    p.add_argument("--bars", help="A-B: render only the notes that start in these bars (a quick preview)")
    p.add_argument("--stems", action="store_true", help="keep the dry per-voice / per-group stems")


def run(args, ctx):
    if ctx.root is None:
        raise KapellError("no_project", "no kapell.toml above the working directory", "cd into a piece, or run kapell new")
    v = pipeline.resolve_version(ctx.root, ctx.cfg, args.version)
    return pipeline.render_version(ctx.root, ctx.cfg, v, pipeline.parse_bars(args.bars), args.stems)
