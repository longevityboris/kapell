"""kapell engrave: print the score's layouts with lilypond.

A layout is the project's score/<layout>.ly when it exists (The Neighbour has piano.ly and
quartet.ly), else the kit's templates/layouts/<layout>.ly filled with the piece's title and
compiled against the project's score folder (include path), so music-global.ly and
music-voices.ly are shared. `all` prints every layout that exists either way.
"""
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from kapell.commands import KapellError

SPEC = {
    "name": "engrave",
    "effect": "write",
    "help": "print score layouts (piano|quartet|organ|orchestra|ensemble|all) to PDF with lilypond",
    "runtime_s": 12,
    "output_tokens_typ": 120,
    "examples": [["engrave", "--layout", "all"], ["engrave", "--layout", "piano", "--out", "/tmp/scores"]],
}
LAYOUTS = ("piano", "quartet", "organ", "orchestra", "ensemble")
TEMPLATES = Path(__file__).resolve().parents[3] / "templates" / "layouts"


def add_arguments(p):
    p.add_argument("--layout", default="all", choices=LAYOUTS + ("all",))
    p.add_argument("--out", help="output folder (default: [paths].scores_out, else score/out)")


def sources(root: Path, cfg: dict) -> dict:
    score_dir = (root / cfg.get("paths", {}).get("score", "score/music-voices.ly")).parent
    out = {}
    for name in LAYOUTS:
        if (score_dir / f"{name}.ly").is_file():
            out[name] = ("project", score_dir / f"{name}.ly")
        elif (TEMPLATES / f"{name}.ly").is_file():
            out[name] = ("template", TEMPLATES / f"{name}.ly")
    return out


def run(args, ctx):
    if ctx.root is None:
        raise KapellError("no_project", "no kapell.toml above the working directory", "cd into a piece")
    lily = shutil.which("lilypond")
    if not lily:
        raise KapellError("no_lilypond", "lilypond is not on PATH", "brew install lilypond; kapell doctor", exit_code=2)
    cfg = ctx.cfg
    score_dir = (ctx.root / cfg.get("paths", {}).get("score", "score/music-voices.ly")).parent
    out_dir = Path(args.out).expanduser().resolve() if args.out else ctx.root / cfg.get("paths", {}).get("scores_out", "score/out")
    out_dir.mkdir(parents=True, exist_ok=True)
    have = sources(ctx.root, cfg)
    want = list(have) if args.layout == "all" else [args.layout]
    missing = [w for w in want if w not in have]
    if missing and args.layout != "all":
        raise KapellError("no_layout", f"no layout {missing[0]!r}: neither score/{missing[0]}.ly nor a kit template",
                          f"available: {sorted(have)}")
    piece = cfg.get("piece", {})
    done, failed = {}, {}
    with tempfile.TemporaryDirectory(prefix="kapell-engrave-") as tmp:
        for name in want:
            kind, src = have[name]
            if kind == "template":
                text = src.read_text().replace("@TITLE@", piece.get("name", ctx.root.name)).replace(
                    "@SUBTITLE@", piece.get("subtitle", ""))
                src = Path(tmp) / f"{name}.ly"
                src.write_text(text)
            t0 = time.time()
            r = subprocess.run([lily, "-s", "-I", str(score_dir), "-o", str(out_dir / name), str(src)],
                               cwd=score_dir, capture_output=True, text=True, timeout=600)
            pdf = out_dir / f"{name}.pdf"
            if r.returncode == 0 and pdf.is_file():
                pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))
                done[name] = {"source": kind, "pdf": str(pdf), "pages": pages, "s": round(time.time() - t0, 1)}
            else:
                failed[name] = (r.stderr.strip().splitlines() or ["?"])[-1][:200]
    data = {"out": str(out_dir), "printed": done, "not_available": missing}
    if failed:
        data["failed"] = failed
        raise KapellError("engrave_failed", f"lilypond failed: {failed}", "run lilypond on the layout by hand for the full log",
                          exit_code=3)
    return data
