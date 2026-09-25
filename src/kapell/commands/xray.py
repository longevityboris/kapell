"""kapell xray: every checker and quality gate in one short JSON bundle (C sections 3-5).

Runs check (counterpoint), suspensions, strict (CLASH is a gate; XREL/ACC are for review),
resolution (unresolved chordal sevenths DIS7 and leading tones LT), coverage (theme ledger and the
form claim), roles (featured roles need a cue in every performance plan) and quotas. Exits 5 when
any gate fails, with the failures in data.violations. Digest by default; --full adds every item.
"""
import re
import subprocess
import sys
from pathlib import Path

from . import KapellError, Result

SPEC = {
    "name": "xray",
    "effect": "read",
    "help": "all checks + resolution, theme coverage, performance-role and quota gates in one digest; exit 5 when a gate fails",
    "runtime_s": 1.5,
    "output_tokens_typ": 900,
    "examples": [["xray"], ["xray", "score/music-voices.ly", "--bars", "49-56"], ["xray", "--full"]],
}
CAP = 12
VENDOR = Path(__file__).resolve().parents[3] / "vendor" / "fugue-jp"


def add_arguments(parser):
    parser.add_argument("score", nargs="?", help=".ly file with \\absolute voices (default: paths.score)")
    parser.add_argument("--bars", help="A-B: limit check, strict and resolution to these bars (coverage and roles stay whole-piece)")
    parser.add_argument("--voices", help="voice variables, highest first (default: piece.voices)")
    parser.add_argument("--measure", help="bar length, e.g. 4/4 (default: piece.measure)")
    parser.add_argument("--full", action="store_true", help="every item of every section, not just the digest")


def _opts(ctx, args):
    piece = (ctx.cfg or {}).get("piece") or {}
    voices = [v.strip() for v in args.voices.split(",")] if args.voices else (piece.get("voices") or
                                                                              ["soprano", "alto", "tenor", "bass"])
    measure = args.measure or piece.get("measure") or "4/4"
    ranges = {k: tuple(v) for k, v in ((ctx.cfg or {}).get("ranges") or {}).items()}
    return voices, measure, ranges


def _check(path, voices, bars, measure, ranges, full):
    try:
        from ..analysis import check
    except ImportError:
        cmd = [sys.executable, str(VENDOR / "tools" / "check.py"), str(path), "--voices", ",".join(voices)]
        for k, (lo, hi) in ranges.items():
            cmd += ["--range", f"{k}={lo}-{hi}"]
        if bars:
            cmd += ["--bars", f"{bars[0]}-{bars[1]}"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
        m = re.search(r"errors (\d+), parallels (\d+), beat-par (\d+), unjustified (\d+)", out)
        if not m:
            raise KapellError("check_failed", "vendored check.py gave no totals line", "run kapell doctor", 1)
        e, p, b, u = map(int, m.groups())
        viol = [ln for ln in out.splitlines() if ln.startswith(("ERR", "PAR!", "BEAT", "DIS!"))]
        return dict(source="vendored-subprocess", totals=dict(errors=e, parallels=p, beat_parallels=b, unjustified=u),
                    violations=viol if full else viol[:CAP])
    r = check.run(str(path), voices=voices, bars=bars, measure=measure, ranges=ranges)
    t = r["totals"]
    viol = [v["line"] for v in r["violations"]]
    out = dict(source="module", totals={k: t[k] for k in ("errors", "parallels", "beat_parallels", "unjustified",
                                                          "crossings", "directs", "melodic")},
               violations=viol if full else viol[:CAP])
    if full:
        out["review"] = [x["line"] for x in r["review"]]
    return out


def _strict(path, voices, bars, measure, full):
    try:
        from ..analysis import strict
    except ImportError:
        cmd = [sys.executable, str(VENDOR / "design" / "final-lab" / "strict.py"), str(path)]
        if bars:
            cmd += ["--bars", f"{bars[0]}-{bars[1]}"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
        m = re.search(r"clash (\d+), xrel (\d+), acc (\d+), acc2 (\d+)", out)
        if not m:
            raise KapellError("check_failed", "vendored strict.py gave no summary line", "run kapell doctor", 1)
        c, x, a, a2 = map(int, m.groups())
        return dict(source="vendored-subprocess", clash=c, xrel=x, acc=a, acc2=a2)
    r = strict.run(str(path), voices=voices, bars=bars, measure=measure)
    out = dict(source="module", clash=r["clash"], xrel=r["xrel"], acc=r["acc"], acc2=r["acc2"])
    clashes = [i["line"] for i in r["items"] if i.get("kind") == "CLASH"]
    if clashes:
        out["clashes"] = clashes[:CAP]
    if full:
        out["items"] = [i["line"] for i in r["items"]]
    return out


def run(args, ctx):
    from ..analysis import coverage, parse_bars, quotas, resolution, roles

    voices, measure, ranges = _opts(ctx, args)
    try:
        bars = parse_bars(args.bars)
    except ValueError:
        raise KapellError("bad_input", f"--bars {args.bars!r}: expected A-B", "--bars 49-56", 3)
    cfg = ctx.cfg or {}
    if args.score:
        path = Path(args.score)
    elif ctx.root is not None and (cfg.get("paths") or {}).get("score"):
        path = Path(ctx.root) / cfg["paths"]["score"]
    else:
        raise KapellError("bad_input", "no score given and no kapell project found",
                          "kapell xray FILE.ly, or run inside a project with [paths] score", 3)
    if not path.is_file():
        raise KapellError("bad_input", f"score not found: {path}", "check the path or [paths] score", 3)
    try:
        mfrac = coverage.measure_of({"piece": {"measure": measure}})
    except (ValueError, ZeroDivisionError):
        raise KapellError("bad_input", f"--measure {measure!r}: expected e.g. 4/4", "--measure 3/4", 3)
    full = bool(args.full)
    src = path.read_text()
    data = {"file": str(path)}
    if bars:
        data["bars"] = f"{bars[0]}-{bars[1]}"
    gates, viol = {}, []

    ck = _check(path, voices, bars, measure, ranges, full)
    data["check"] = ck
    t = ck["totals"]
    gates["check"] = not (t["errors"] or t["parallels"] or t["beat_parallels"] or t["unjustified"])
    viol += ck["violations"][:CAP]
    if not full:
        ck["violations"] = len(ck["violations"])

    sus = quotas.suspensions(path, voices=voices, measure=measure)
    data["suspensions"] = sus

    st = _strict(path, voices, bars, measure, full)
    data["strict"] = st
    gates["strict_clash"] = st["clash"] == 0
    viol += st.get("clashes", [])

    beats = int((cfg.get("checks") or {}).get("resolution_beats") or 4)
    res = resolution.check(src, voices, mfrac, beats, bars)
    counts = {}
    for f in res:
        counts[f["code"]] = counts.get(f["code"], 0) + 1
    res_lines = [f"{f['code']} {f['at']} {f['message']}" for f in res]
    data["resolution"] = dict(beats=beats, counts=counts)
    if full:
        data["resolution"]["items"] = res_lines
    gates["resolution"] = not res
    viol += res_lines[:CAP]

    measured = dict(strong_suspensions=sus["strong"], weak_suspensions=sus["weak"],
                    dis7=counts.get("DIS7", 0), unresolved=len(res), clash=st["clash"])

    if ctx.root is not None and cfg:
        try:
            cov = coverage.run_project(ctx.root, cfg, path, full)
        except (OSError, ValueError, KeyError) as exc:
            cov = dict(error=str(exc), ok=False, violations=[dict(code="FORM", message=f"coverage: {exc}")])
        data["coverage"] = cov
        if "skipped" not in cov:
            gates["form"] = cov["ok"]
            measured["form_violations"] = len(cov["violations"])
        viol += [v["message"] for v in cov.get("violations", [])]
        if not full and "violations" in cov:
            cov["violations"] = len(cov["violations"])

        try:
            rl = roles.lint(ctx.root, cfg)
        except (OSError, ValueError, KeyError) as exc:
            rl = dict(error=str(exc), ok=False, violations=[dict(code="ROLE", message=f"roles: {exc}")])
        msgs = [v["message"] for v in rl["violations"]]
        data["roles"] = dict(features=rl.get("features"), ok=rl["ok"],
                             uncued={v: x["uncued"] for v, x in (rl.get("versions") or {}).items()})
        if full:
            data["roles"]["violations"] = msgs
        gates["roles"] = rl["ok"]
        measured["uncued_features"] = len(rl["violations"])
        viol += msgs[:CAP]

        q = quotas.evaluate(cfg.get("quotas") or {}, measured)
        data["quotas"] = q["quotas"]
        gates["quotas"] = q["ok"]
        viol += [v["message"] for v in q["violations"]]
    else:
        data["note"] = "no kapell project: coverage, roles and quotas skipped"

    data["gates"] = gates
    failed = [k for k, ok in gates.items() if not ok]
    data["failed"] = failed
    if failed:
        data["violations"] = viol
        if not full:
            data["hint"] = "kapell xray --full lists every item"
        return Result("fail", data)
    return data
