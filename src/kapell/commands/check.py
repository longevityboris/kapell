"""kapell check: counterpoint check of a score or a spliced section (digest: totals + violations)."""
from pathlib import Path

from . import KapellError, Result
from .splice import _cfg_path, need, piece_opts, resolve_section

SPEC = {
    "name": "check",
    "effect": "read",
    "help": "counterpoint check: parallels, beat-parallels, unjustified dissonances, ranges; exit 5 on violations",
    "runtime_s": 0.1,
    "output_tokens_typ": 150,
    "examples": [["check"], ["check", "score/music-voices.ly", "--bars", "49-56"], ["check", "--section", "3"],
                 ["check", "--full"]],
}
CAP = 40  # violation lines in the digest


def add_arguments(parser):
    parser.add_argument("score", nargs="?", help=".ly file with \\absolute voices (default: paths.score)")
    parser.add_argument("--section", help="check a section spliced into the skeleton (number or file), bars A-1..B+1")
    parser.add_argument("--voices", help="voice variables, highest first (default: piece.voices)")
    parser.add_argument("--bars", help="A-B: only report inside these bars")
    parser.add_argument("--measure", help="bar length, e.g. 4/4 or 3/4 (default: piece.measure)")
    parser.add_argument("--range", action="append", metavar="NAME=LO-HI", help="MIDI range for a voice (default: [ranges])")
    parser.add_argument("--full", action="store_true", help="add review lines (CROS, DIR, MEL, D4?) and every dissonance")


def _bars(spec):
    from ..analysis import parse_bars
    try:
        return parse_bars(spec)
    except ValueError:
        raise KapellError("bad_input", f"--bars {spec!r}: expected A-B", "--bars 49-56", 3)


def run(args, ctx):
    from ..analysis import check, splice

    voices, measure, ranges = piece_opts(ctx, args)
    bars = _bars(args.bars)
    src, label = None, None
    if args.section:
        if args.score:
            raise KapellError("bad_input", "use a score or --section, not both", exit_code=3)
        section = resolve_section(ctx, args.section)
        skeleton = need(_cfg_path(ctx, "skeleton"), "skeleton", "skeleton")
        try:
            src, a, b, _ = splice.spliced_source(str(section), str(skeleton), voices)
        except ValueError as exc:
            raise KapellError("bad_input", f"{section}: {exc}", "add a line '% bars A-B' to the section file", 3)
        n = splice.nbars(splice.read_bars(src, voices))
        bars = bars or (max(1, a - 1), min(n, b + 1))
        label = f"{section} spliced into {skeleton.name}"
        path = None
    else:
        path = Path(args.score) if args.score else _cfg_path(ctx, "score")
        if path is None:
            raise KapellError("bad_input", "no score given and no kapell project found",
                              "kapell check FILE.ly, or run inside a project with [paths] score", 3)
        if not path.is_file():
            raise KapellError("bad_input", f"score not found: {path}", "check the path or [paths] score", 3)
        label = str(path)
    try:
        r = check.run(path, voices=voices, bars=bars, measure=measure, ranges=ranges, src=src)
    except ValueError as exc:
        raise KapellError("bad_input", str(exc), "check --measure and --range syntax", 3)
    viol = [v["line"] for v in r["violations"]]
    data = {"file": label, "totals": r["totals"], "violations": viol if args.full else viol[:CAP]}
    if bars:
        data["bars"] = f"{bars[0]}-{bars[1]}"
    if not args.full and len(viol) > CAP:
        data["violations_truncated"] = len(viol) - CAP
    if args.full:
        data["review"] = [x["line"] for x in r["review"]]
        data["dissonance_lines"] = [x["line"] for x in r["dissonances"]]
    elif r["review"] or len(viol) > CAP:
        data["hint"] = "kapell check --full lists the review lines (CROS, DIR, MEL, D4?) and every dissonance"
    return Result("fail", data) if viol else data
