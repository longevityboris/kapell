"""kapell splice: verify one composed section against the skeleton (seams, locks, keeps, unisons, joins)."""
from pathlib import Path

from . import KapellError, Result
from .. import project

SPEC = {
    "name": "splice",
    "effect": "read",
    "help": "verify a section against the skeleton: seams, locked/kept notes, unisons, check+strict on the joins",
    "runtime_s": 0.3,
    "output_tokens_typ": 200,
    "examples": [["splice", "--section", "3"], ["splice", "--section", "score/sections/sec03_stretto_liquidation.ly"]],
}


def add_arguments(parser):
    parser.add_argument("--section", required=True, help="section number (1-based, from paths.sections) or a section .ly file")
    parser.add_argument("--base", help="score to splice into (default: the skeleton, paths.skeleton)")
    parser.add_argument("--skeleton", help="skeleton .ly (default: paths.skeleton)")
    parser.add_argument("--plan", help="plan.json with roles and keep items (default: paths.plan)")
    parser.add_argument("--voices", help="voice variables, highest first (default: piece.voices)")
    parser.add_argument("--full", action="store_true", help="include review lines and the full report")


def _cfg_path(ctx, key):
    try:
        return project.path(ctx.root, ctx.cfg, key) if ctx.root is not None else None
    except (KeyError, TypeError):
        return None


def resolve_section(ctx, spec) -> Path:
    """A section number (paths.sections, sorted, 'secNN_*.ly' preferred) or a file path."""
    s = str(spec)
    if not s.isdigit():
        p = Path(s).expanduser()
        if not p.is_file():
            raise KapellError("bad_input", f"section file not found: {s}", "pass a section number or an existing .ly file", 3)
        return p
    d = _cfg_path(ctx, "sections")
    if d is None or not d.is_dir():
        raise KapellError("config_missing", "no sections directory (kapell.toml [paths] sections)",
                          "run inside a kapell project or pass the section file", 2)
    n = int(s)
    hits = sorted(d.glob(f"sec{n:02d}_*.ly")) or sorted(d.glob(f"sec{n}_*.ly"))
    if hits:
        return hits[0]
    files = sorted(d.glob("*.ly"))
    if not 1 <= n <= len(files):
        raise KapellError("bad_input", f"section {n} not found in {d} ({len(files)} files)",
                          f"use 1..{len(files)}", 3)
    return files[n - 1]


def piece_opts(ctx, args=None):
    """voices / measure / ranges from flags, falling back to kapell.toml [piece] and [ranges]."""
    piece = (ctx.cfg or {}).get("piece") or {}
    voices = getattr(args, "voices", None) or piece.get("voices")
    measure = getattr(args, "measure", None) or piece.get("measure")
    ranges = dict((ctx.cfg or {}).get("ranges") or {})
    for r in getattr(args, "range", None) or []:
        try:
            name, lohi = r.split("=")
            lo, hi = lohi.split("-")
            ranges[name] = (int(lo), int(hi))
        except ValueError:
            raise KapellError("bad_input", f"--range {r!r}: expected name=lo-hi (MIDI numbers)", "--range soprano=60-84", 3)
    return voices, measure, ranges


def need(p, what, key):
    if p is None or not Path(p).is_file():
        raise KapellError("config_missing", f"no {what} found ({p or f'kapell.toml [paths] {key} unset'})",
                          f"pass --{key} or set [paths] {key} in kapell.toml", 2)
    return Path(p)


def run(args, ctx):
    from ..analysis import splice

    section = resolve_section(ctx, args.section)
    skeleton = need(args.skeleton or _cfg_path(ctx, "skeleton"), "skeleton", "skeleton")
    plan = need(args.plan or _cfg_path(ctx, "plan"), "plan", "plan")
    voices, measure, ranges = piece_opts(ctx, args)
    try:
        r = splice.check_section(str(section), str(skeleton), str(plan), base=args.base, voices=voices,
                                 ranges=ranges, measure=measure)
    except ValueError as exc:
        raise KapellError("bad_input", f"{section}: {exc}", "add a line '% bars A-B' to the section file", 3)
    data = {"section": r["section"], "bars": r["bars"], "checked": r["checked"], "pass": r["pass"],
            "failures": [f["line"] for f in r["failures"]], "check": r["check"], "strict": r["strict"],
            "known_unisons": len(r["known_unisons"])}
    if args.full:
        data["review"] = r["review"]
        data["known_unisons"] = r["known_unisons"]
        data["report"] = r["lines"]
    return data if r["pass"] else Result("fail", {**data, "violations": data["failures"]})
