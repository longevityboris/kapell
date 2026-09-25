"""Featured-role lint: every featured role needs a cue in every performance plan (C section 5).

Featured roles come from two places:
  - kapell.toml [[features]] entries {label, voice, at, until} (moments the analysis says must be
    brought out, such as an imitation or a lament in an inner voice);
  - the piece model's roles whose kind is in FEATURED_KINDS (subject, answer, cf), read from
    [paths] piece_model (piece.py: SECTIONS with section-relative roles). Set
    [checks] featured_roles = [] in kapell.toml to turn that off.

A version is a directory performance/<version>/ (the [versions] render list when given). Its cues:
  - plan.json "roles" entries for the voice whose role has a positive role_boost in that plan;
  - orchestral specs (any *.json with "assignments"): assignments and pedal_points for the voice
    that raise it (level > 0, an articulation, or a solo player) and begin or end within one beat
    of the feature, so a blanket section-long assignment does not count as bringing a line out;
    and, when the spec's "marks" come from the piece model, every piece-model role.
A feature passes when its cues cover at least MIN_COVER of its span.

Findings: {code: "ROLE", version, voice, label, at, until, cover, message}.
"""
import json
import runpy
from fractions import Fraction as F
from pathlib import Path

from kapell.analysis.coverage import measure_of, parse_pos, pos

FEATURED_KINDS = ("subject", "answer", "cf")
MIN_COVER = 0.75
INF = F(10 ** 6)


MARKS: dict = {}          # section name -> first bar, filled by lint() from the piece model


def _pos(s, measure):
    """ "bar:beat", "end", or a section mark "arioso", "expo+8", "expo+8:4" (bars after the mark)."""
    s = str(s)
    name, plus, off = s.partition("+")
    if name in MARKS:
        bar, _, beat = (off or "0").partition(":")
        return parse_pos(f"{MARKS[name] + int(bar)}:{beat or 1}", measure)
    return parse_pos(s, measure)


def _span(e, measure):
    """(start, end) of an entry; None when a position cannot be read."""
    try:
        a = _pos(e.get("at", "1:1"), measure)
        u = _pos(e["until"], measure) if e.get("until") is not None else None
    except (ValueError, TypeError):
        return None
    return a, (INF if u is None else u)


def section_marks(piece_py: Path) -> dict:
    out, bar = {}, 1
    for sec in runpy.run_path(str(piece_py)).get("SECTIONS", []):
        out[sec["id"]] = bar
        out[sec["id"].split("_", 1)[-1]] = bar
        bar += int(sec.get("bars", 0))
    return out


def piece_roles(piece_py: Path, measure=F(1), kinds=FEATURED_KINDS) -> list:
    """Absolute featured roles from a piece.py model (SECTIONS with 'bars' and relative 'roles')."""
    data = runpy.run_path(str(piece_py))
    out, off = [], 0
    for sec in data.get("SECTIONS", []):
        for r in sec.get("roles", []):
            voice, at, until, kind = r[:4]
            if kind in kinds:
                a = parse_pos(at, measure) + off * measure
                u = parse_pos(until, measure) + off * measure
                out.append(dict(label=f"{kind} ({sec['id']})", voice=voice, at=pos(a, measure),
                                until=pos(u, measure), source="piece"))
        off += int(sec.get("bars", 0))
    return out


def features(root: Path, cfg: dict) -> list:
    measure = measure_of(cfg)
    out = [dict(f, source="kapell.toml") for f in (cfg.get("features") or [])]
    kinds = (cfg.get("checks") or {}).get("featured_roles", list(FEATURED_KINDS))
    pm = (cfg.get("paths") or {}).get("piece_model")
    if kinds and pm and (Path(root) / pm).is_file() and pm.endswith(".py"):
        out += piece_roles(Path(root) / pm, measure, tuple(kinds))
    return out


def load_version(vdir: Path) -> dict:
    """{plans: [plan dicts], specs: [spec dicts]} for performance/<version>/ (top level only)."""
    plans, specs = [], []
    for f in sorted(vdir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        if "roles" in d and "voices" in d:
            plans.append(d)
        elif "assignments" in d:
            specs.append(d)
    return dict(plans=plans, specs=specs)


def _cues(ver: dict, voice: str, fa, fu, measure, source: str):
    """Spans (clipped to the feature) that bring the voice out."""
    spans = []
    for p in ver["plans"]:
        boost = p.get("role_boost") or {}
        for r in p.get("roles", []):
            if r.get("voice") == voice and (boost.get(r.get("role"), 0) or 0) > 0:
                sp = _span(r, measure)
                if sp:
                    spans.append(sp)
    tol = F(1, 4)
    for s in ver["specs"]:
        marks = str((s.get("marks") or {}).get("from", ""))
        if source == "piece" and marks.endswith(("piece.py", "piece.toml")):
            spans.append((fa, fu))
        for e in list(s.get("assignments", [])) + list(s.get("pedal_points", [])):
            if e.get("voice") != voice:
                continue
            raised = (e.get("level") or 0) > 0 or e.get("articulation") or e.get("players") == "solo"
            if not raised:
                continue
            sp = _span(e, measure)
            if not sp:
                continue
            a, u = sp
            if fa - tol <= a <= fu + tol or fa - tol <= u <= fu + tol:
                spans.append((a, u))
    return [(max(a, fa), min(u, fu)) for a, u in spans if a < fu and u > fa]


def _cover(spans, fa, fu):
    if fu <= fa:
        return 1.0
    tot, cur = F(0), fa
    for a, u in sorted(spans):
        a = max(a, cur)
        if u > a:
            tot += u - a
            cur = u
    return float(tot / (fu - fa))


def lint(root, cfg: dict, versions=None) -> dict:
    root = Path(root)
    measure = measure_of(cfg)
    feats = features(root, cfg)
    pm = (cfg.get("paths") or {}).get("piece_model")
    MARKS.clear()
    if pm and pm.endswith(".py") and (root / pm).is_file():
        MARKS.update(section_marks(root / pm))
    perf = root / (cfg.get("paths") or {}).get("performance", "performance")
    names = versions or (cfg.get("versions") or {}).get("render") or (
        sorted(d.name for d in perf.iterdir() if d.is_dir()) if perf.is_dir() else [])
    min_cover = float((cfg.get("checks") or {}).get("feature_cover", MIN_COVER))
    viol, per = [], {}
    for v in names:
        vd = perf / v
        if not vd.is_dir():
            viol.append(dict(code="ROLE", version=v, message=f"performance/{v}/ missing"))
            continue
        ver = load_version(vd)
        if not ver["plans"] and not ver["specs"]:
            viol.append(dict(code="ROLE", version=v, message=f"performance/{v}/ has no plan.json or spec"))
            continue
        miss = 0
        for f in feats:
            fa, fu = _span(f, measure)
            c = _cover(_cues(ver, f["voice"], fa, fu, measure, f.get("source", "")), fa, fu)
            if c < min_cover:
                miss += 1
                viol.append(dict(code="ROLE", version=v, voice=f["voice"], label=f.get("label", ""),
                                 at=f["at"], until=f["until"], cover=round(c, 2),
                                 message=f"{v}: {f['voice']} {f.get('label', '')} {f['at']}-{f['until']} "
                                         f"has no cue ({round(100 * c)}% covered)"))
        per[v] = dict(features=len(feats), uncued=miss)
    return dict(features=len(feats), versions=per, ok=not viol, violations=viol)
