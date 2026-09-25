"""Project status: the resume point after a usage-limit kill (C sections 3 and 4.6).

summarise(root, cfg, live=True) -> dict, under 2k tokens: phase, sections done and open, last check
totals, quotas, printed layouts, renders, recent commits, next command. Every piece degrades to
null or a warning when its input is missing; nothing here raises for an incomplete project.
"""
import ast
import json
import re
import subprocess
from pathlib import Path

from . import __version__, config

LAYOUTS = ("piano", "quartet", "organ", "orchestra", "ensemble")
AUDIO = ("*.wav", "*.m4a", "*.flac")


def _p(root: Path, cfg: dict, key: str) -> Path | None:
    rel = (cfg.get("paths") or {}).get(key)
    return (root / rel) if rel else None


def section_ids(piece_model: Path | None) -> list[dict]:
    """Read SECTIONS from piece.py without executing it: dict(id=..., title=..., bars=...) calls."""
    if not piece_model or not piece_model.is_file():
        return []
    try:
        tree = ast.parse(piece_model.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return []
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SECTIONS" for t in node.targets):
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            for elt in node.value.elts:
                fields = {}
                if isinstance(elt, ast.Call):
                    for kw in elt.keywords:
                        if kw.arg in ("id", "title", "bars") and isinstance(kw.value, ast.Constant):
                            fields[kw.arg] = kw.value.value
                elif isinstance(elt, ast.Dict):
                    for k, v in zip(elt.keys, elt.values):
                        if isinstance(k, ast.Constant) and k.value in ("id", "title", "bars") and isinstance(v, ast.Constant):
                            fields[k.value] = v.value
                if "id" in fields:
                    out.append(fields)
    return out


def sections(root: Path, cfg: dict) -> dict:
    planned = section_ids(_p(root, cfg, "piece_model"))
    sec_dir = _p(root, cfg, "sections")
    files = sorted(f.stem for f in sec_dir.glob("*.ly")) if sec_dir and sec_dir.is_dir() else []
    if not planned:
        return {"source": "files" if files else None, "total": len(files) or None,
                "done": len(files), "open": [], "bars": None}
    done = [s["id"] for s in planned if any(f == s["id"] or f.startswith(s["id"]) for f in files)]
    open_ = [s["id"] for s in planned if s["id"] not in done]
    bars = sum(s.get("bars") or 0 for s in planned) or None
    return {"source": "piece_model", "total": len(planned), "done": len(done), "open": open_, "bars": bars}


def git_info(root: Path, n: int = 3) -> dict | None:
    try:
        log = subprocess.run(["git", "-C", str(root), "log", f"-{n}", "--format=%h%x09%cs%x09%s", "--", "."],
                             capture_output=True, text=True, timeout=10)
        if log.returncode != 0:
            return None
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "."],
                               capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    commits = []
    for line in log.stdout.splitlines():
        h, d, s = (line.split("\t", 2) + ["", ""])[:3]
        commits.append(f"{h} {d} {s[:90]}{'...' if len(s) > 90 else ''}")
    return {"recent": commits, "uncommitted": len(dirty.stdout.splitlines()) if dirty.returncode == 0 else None}


def last_run(root: Path) -> dict | None:
    """Newest journal entry under runs/ (json or jsonl), trimmed to its scalar fields."""
    runs = root / "runs"
    if not runs.is_dir():
        return None
    files = sorted((f for f in runs.rglob("*") if f.suffix in (".json", ".jsonl") and f.is_file()),
                   key=lambda f: f.stat().st_mtime)
    if not files:
        return None
    f = files[-1]
    try:
        text = f.read_text(encoding="utf-8").strip()
        entry = json.loads(text.splitlines()[-1] if f.suffix == ".jsonl" else text)
    except (OSError, ValueError, IndexError):
        return {"file": str(f.relative_to(root)), "error": "unreadable"}
    if isinstance(entry, dict):
        entry = {k: v for k, v in entry.items() if isinstance(v, (str, int, float, bool)) or v is None}
    else:
        entry = {}
    return {"file": str(f.relative_to(root)), **dict(list(entry.items())[:12])}


def live_check(score: Path, cfg: dict) -> tuple[dict | None, dict | None, str | None]:
    """(check totals, suspensions {strong, weak}, error) from the analysis package, if it is there."""
    piece = cfg.get("piece") or {}
    kw = {"voices": piece.get("voices"), "measure": piece.get("measure")}
    totals = susp = None
    try:
        from .analysis import check as _check
        r = _check.run(str(score), ranges={k: v for k, v in (cfg.get("ranges") or {}).items()}, **kw)
        t = r["totals"]
        totals = {k: t.get(k) for k in ("errors", "parallels", "beat_parallels", "unjustified", "dissonances")}
        totals["violations"] = len(r.get("violations", []))
    except Exception as exc:  # noqa: BLE001 - status degrades, never fails
        return None, None, f"check unavailable: {type(exc).__name__}: {str(exc)[:120]}"
    try:
        from .analysis import suspensions as _susp
        s = _susp.count(str(score), **kw)
        susp = {"strong": s["strong"], "weak": s["weak"]}
    except Exception as exc:  # noqa: BLE001
        return totals, None, f"suspensions unavailable: {type(exc).__name__}: {str(exc)[:120]}"
    return totals, susp, None


def quotas(cfg: dict, susp: dict | None) -> dict:
    out = {}
    actual = {"strong_suspensions": susp and susp.get("strong"), "weak_suspensions": susp and susp.get("weak")}
    for name, target in (cfg.get("quotas") or {}).items():
        a = actual.get(name)
        out[name] = {"target": target, "actual": a, "ok": (a >= target) if isinstance(a, int) else None}
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def renders(root: Path, cfg: dict) -> dict:
    versions = list((cfg.get("versions") or {}).get("render") or [])
    if not versions:
        return {"planned": [], "done": [], "missing": []}
    perf = _p(root, cfg, "performance") or root / "performance"
    names = {root.name, _slug((cfg.get("piece") or {}).get("name", "")), _slug(root.name)} - {""}
    done = []
    for v in versions:
        places = [perf / v] + [config.renders_dir(n) / v for n in names]
        if any(p.is_dir() and any(next(p.glob(g), None) for g in AUDIO) for p in places):
            done.append(v)
    return {"planned": len(versions), "done": done, "missing": [v for v in versions if v not in done]}


def layouts(root: Path, cfg: dict) -> dict:
    out_dir = _p(root, cfg, "scores_out") or root / "score" / "out"
    printed = [l for l in LAYOUTS if (out_dir / f"{l}.pdf").is_file()]
    return {"printed": printed, "missing": [l for l in LAYOUTS if l not in printed]}


def _next(phase: str, secs: dict, rend: dict) -> dict:
    table = {
        "materials": ("kapell materials derive --subject S", "no materials file yet"),
        "design": ("kapell skeleton build", "no skeleton or plan yet"),
        "compose": (f"compose {secs['open'][0]} from its card, then kapell check --section N" if secs.get("open")
                    else "compose the open sections, then kapell check", "sections still open"),
        "assemble": ("kapell assemble", "all sections written; no assembled score"),
        "revise": ("kapell check", "the last check found violations"),
        "review": ("kapell xray", "quotas unmet or checks not run: review before performing"),
        "engrave": ("kapell engrave --layout all", "layouts not printed yet"),
        "render": (f"kapell render --version {rend['missing'][0]}" if rend.get("missing") else "kapell render",
                   "versions not rendered yet"),
        "finished": ("kapell xray", "everything is in place; x-ray to confirm"),
    }
    cmd, why = table[phase]
    return {"command": cmd, "why": why}


def summarise(root: Path | None, cfg: dict, live: bool = True) -> dict:
    if root is None:
        return {"project": None, "phase": "none",
                "next": {"command": "kapell new DIR --brief brief.md",
                         "why": "no kapell.toml here or in any parent directory (or pass --project DIR)"}}
    piece = cfg.get("piece") or {}
    warnings = []
    pin = (cfg.get("kapell") or {}).get("kit")
    if pin and __version__.split(".")[: len(str(pin).split("."))] != str(pin).split("."):
        warnings.append(f"project pins kit {pin}, installed kit is {__version__}")
    if not cfg.get("paths"):
        warnings.append("kapell.toml has no [paths] table; most checks cannot find their inputs")

    secs = sections(root, cfg)
    score = _p(root, cfg, "score")
    have = {k: bool((p := _p(root, cfg, k)) and p.exists()) for k in ("materials", "skeleton", "plan")}
    have["score"] = bool(score and score.is_file())

    totals = susp = None
    if have["score"] and live:
        totals, susp, err = live_check(score, cfg)
        if err:
            warnings.append(err)
    lay = layouts(root, cfg)
    rend = renders(root, cfg)
    quo = quotas(cfg, susp)

    if not have["materials"] and not have["skeleton"] and not secs["done"]:
        phase = "materials"
    elif not (have["skeleton"] or have["plan"]) and not secs["done"]:
        phase = "design"
    elif secs.get("open"):
        phase = "compose"
    elif not have["score"]:
        phase = "assemble"
    elif totals and totals.get("violations"):
        phase = "revise"
    elif totals is None or any(q["ok"] is False for q in quo.values()):
        phase = "review"
    elif lay["missing"]:
        phase = "engrave"
    elif rend["missing"]:
        phase = "render"
    else:
        phase = "finished"

    data = {
        "project": {"name": piece.get("name") or root.name, "root": str(root), "form": piece.get("form"),
                    "key": piece.get("key"), "voices": len(piece.get("voices") or []) or None},
        "phase": phase,
        "sections": secs,
        "files": have,
        "last_check": ({"source": "live", **totals} if totals else None),
        "suspensions": susp,
        "quotas": quo,
        "layouts": lay,
        "renders": rend,
        "last_run": last_run(root),
        "git": git_info(root),
        "next": _next(phase, secs, rend),
    }
    if warnings:
        data["warnings"] = warnings
    return data
