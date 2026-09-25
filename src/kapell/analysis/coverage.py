"""Theme-treatment ledger and form-claim check (T2 in the kit plan).

A theme is a LilyPond \\absolute variable (usually in materials.ly), declared in kapell.toml:

    [themes]
    S1 = "subjectOne"      # first S<n> label is the main subject
    S2 = "subjectTwo"
    CS1 = "csOne"

ledger(src, themes, voices, measure) finds every statement of every theme in every voice under
transposition, inversion, augmentation and diminution. Matching is by melodic line: rests split a
voice into phrases, adjacent repeated pitches are collapsed (so re-struck and tied notes match the
same way), and the interval vectors are compared with contour exact and each interval within one
semitone. That tolerance admits tonal answers, modal changes (minor theme restated in major) and
diatonic mirror inversions, and is what "the same theme" means to a listener. A statement needs at
least MIN_NOTES notes and MIN_SHARE of the theme; at most MAX_ALTERED of its intervals may be altered
(a minor theme restated in major alters about that many).

form_check(occurrences, form, subjects) tests a form claim against the ledger. For "double-fugue"
every subject after the first needs: a transposed statement (answer), an inversion or a stretto,
and a combination with the first subject (sounding at once in another voice).

Positions are "bar:beat" with 1-based quarter beats, as everywhere in the kit.
"""
from fractions import Fraction as F

from kapell.analysis.lyparse import parse_voice

MIN_NOTES = 6
MIN_SHARE = 0.6
MAX_ALTERED = 0.4
LILY = ["c", "cis", "d", "ees", "e", "f", "fis", "g", "aes", "a", "bes", "b"]


# ---------------------------------------------------------------- shared helpers (kit-wide format)

def measure_of(cfg: dict | None) -> F:
    """Bar length in whole notes from kapell.toml [piece] measure ("4/4" -> 1, "3/4" -> 3/4)."""
    m = ((cfg or {}).get("piece") or {}).get("measure", "4/4")
    return F(str(m))


def pos(t, measure=F(1)) -> str:
    """Absolute time (whole notes) -> "bar:beat" (1-based quarter beats)."""
    bar = int(t / measure) + 1
    beat = (t - (bar - 1) * measure) * 4 + 1
    return f"{bar}:{float(beat):g}"


def parse_pos(s, measure=F(1)):
    """ "bar:beat" -> absolute time in whole notes; "end" -> None."""
    s = str(s)
    if s == "end":
        return None
    bar, _, beat = s.partition(":")
    return (int(bar) - 1) * measure + (F(beat or "1") - 1) / 4


def load_voices(src: str, names, measure=F(1)) -> dict:
    out = {}
    for v in names:
        notes = parse_voice(src, v, measure)
        if notes:
            out[v] = notes
    return out


# ---------------------------------------------------------------- matching

def phrases(notes):
    """Split at rests and collapse adjacent repeated pitches: [[(midi, start, end, name, attacks)]]."""
    out, cur = [], []
    for n in notes:
        if n.midi is None:
            if cur:
                out.append(cur)
            cur = []
            continue
        if cur and cur[-1][0] == n.midi and cur[-1][2] == n.start:
            m, s, _, nm, att = cur[-1]
            cur[-1] = (m, s, n.end, nm, att + (n.start,))
        else:
            cur.append((n.midi, n.start, n.end, n.name, (n.start,)))
    if cur:
        out.append(cur)
    return out


def _theme_line(notes):
    ph = phrases(notes)
    return max(ph, key=len) if ph else []


def _sgn(x):
    return (x > 0) - (x < 0)


def _match(line, i, tint, inv):
    """Longest prefix of theme intervals tint matched from line[i]: (notes matched, altered)."""
    k, alt = 0, 0
    s = -1 if inv else 1
    while k < len(tint) and i + k + 1 < len(line):
        want = s * tint[k]
        got = line[i + k + 1][0] - line[i + k][0]
        if _sgn(got) != _sgn(want) or abs(got - want) > 1:
            break
        if got != want:
            alt += 1
        k += 1
    return k + 1, alt


def _entry(ev, tfirst):
    """Where a statement starts inside its collapsed first note: a long held or re-struck note
    (a cadence note that becomes the theme's head) counts from the last attack that leaves at most
    twice the theme's first-note length."""
    lim = ev[2] - 2 * (tfirst[2] - tfirst[1])
    return min((a for a in ev[4] if a >= lim), default=ev[1])


def _ratio(t0, line, i, n, tline):
    """Time scale of a matched statement relative to the theme (entry to onset of last note)."""
    tspan = tline[n - 1][1] - tline[0][1]
    vspan = line[i + n - 1][1] - t0
    if not tspan:
        return "1"
    r = vspan / tspan
    for lab, val in (("4", 4), ("2", 2), ("1", 1), ("1/2", F(1, 2)), ("1/4", F(1, 4))):
        if abs(r - val) <= val * F(1, 5):
            return lab
    return f"{float(r):.2g}"


def ledger(src: str, themes: dict, voices, measure=F(1), theme_src: str | None = None) -> list:
    """Every statement of every theme. themes: label -> variable name in theme_src (default src)."""
    tsrc = theme_src if theme_src is not None else src
    lines = {}
    for lab, var in themes.items():
        tn = parse_voice(tsrc, var, measure)
        if not tn:
            raise ValueError(f"theme {lab}: variable {var!r} not found")
        lines[lab] = _theme_line(tn)
    vox = load_voices(src, voices, measure)
    occ = []
    for lab, tline in lines.items():
        tint = [b[0] - a[0] for a, b in zip(tline, tline[1:])]
        need = max(MIN_NOTES, int(len(tline) * MIN_SHARE + 0.999))
        need = min(need, len(tline))
        for v, notes in vox.items():
            for line in phrases(notes):
                i = 0
                while i < len(line):
                    best = None
                    for inv in (False, True):
                        n, alt = _match(line, i, tint, inv)
                        if n >= need and alt <= MAX_ALTERED * (n - 1) and (best is None or n > best[0]):
                            best = (n, alt, inv)
                    if not best:
                        i += 1
                        continue
                    n, alt, inv = best
                    first, last = line[i], line[i + n - 1]
                    t0 = _entry(first, tline[0])
                    occ.append(dict(
                        theme=lab, voice=v, form="inversion" if inv else "prime",
                        scale=_ratio(t0, line, i, n, tline), at=pos(t0, measure), until=pos(last[2], measure),
                        start=first[3], level=(first[0] - tline[0][0]) % 12, notes=f"{n}/{len(tline)}",
                        altered=alt, _t0=t0, _t1=last[2]))
                    i += n - 1 if n > 1 else 1
    occ.sort(key=lambda o: (o["_t0"], o["theme"]))
    return occ


# ---------------------------------------------------------------- form claims

FORMS = {
    # each later subject must be: answered at another pitch, inverted or in stretto, combined with S1
    "double-fugue": dict(n_subjects=2, later=("answer", "inversion_or_stretto", "combination")),
    "triple-fugue": dict(n_subjects=3, later=("answer", "inversion_or_stretto", "combination")),
    "fugue": dict(n_subjects=1, later=()),
}


def _overlap(a, b):
    return a["_t0"] < b["_t1"] and b["_t0"] < a["_t1"]


def treatment(occ: list, theme: str, first: str | None = None) -> dict:
    mine = [o for o in occ if o["theme"] == theme]
    prime_levels = sorted({o["level"] for o in mine if o["form"] == "prime"})
    stretto = any(_overlap(a, b) and a["voice"] != b["voice"] for i, a in enumerate(mine) for b in mine[i + 1:])
    combo = bool(first) and any(_overlap(a, b) and a["voice"] != b["voice"]
                                for a in mine for b in occ if b["theme"] == first)
    return dict(
        statements=len(mine),
        levels=sorted({o["start"] for o in mine}),
        answer=len(prime_levels) >= 2,
        inversion=any(o["form"] == "inversion" for o in mine),
        augmentation=any(o["scale"] in ("2", "4") for o in mine),
        diminution=any(o["scale"] in ("1/2", "1/4") for o in mine),
        stretto=stretto,
        combination=combo,
    )


def form_check(occ: list, form: str | None, subjects: list) -> list:
    """Violations of the form claim: [{code, theme, missing, message}]."""
    rule = FORMS.get(form or "")
    if not rule or not subjects:
        return []
    out = []
    if len(subjects) < rule["n_subjects"]:
        out.append(dict(code="FORM", theme=None, missing=["subject"],
                        message=f"form {form!r} needs {rule['n_subjects']} subjects; kapell.toml [themes] declares {len(subjects)}"))
        return out
    first = subjects[0]
    for s in subjects[1:rule["n_subjects"]]:
        tr = treatment(occ, s, first)
        mine = [o for o in occ if o["theme"] == s]
        missing = []
        if not mine:
            missing = ["statement"]
        else:
            if "answer" in rule["later"] and not tr["answer"]:
                missing.append("answer")
            if "inversion_or_stretto" in rule["later"] and not (tr["inversion"] or tr["stretto"]):
                missing.append("inversion_or_stretto")
            if "combination" in rule["later"] and not tr["combination"]:
                missing.append(f"combination_with_{first}")
        if missing:
            where = ", ".join(f"{o['at']} {o['voice']} on {o['start']}" for o in mine[:6])
            one = ", all at one pitch" if mine and not tr["answer"] else ""
            out.append(dict(code="FORM", theme=s, missing=missing,
                            message=f"{form}: {s} heard {len(mine)} times{one} ({where}); missing {', '.join(missing)}"))
    return out


def subjects_of(themes: dict, cfg: dict | None = None) -> list:
    explicit = ((cfg or {}).get("form") or {}).get("subjects")
    if explicit:
        return list(explicit)
    return [k for k in themes if k[:1] == "S" and k[1:].isdigit()]


def summarize(occ: list, themes: dict, form: str | None, subjects: list, full: bool = False) -> dict:
    first = subjects[0] if subjects else None
    per = {}
    for lab in themes:
        tr = treatment(occ, lab, first if lab != first else None)
        forms = {}
        for o in occ:
            if o["theme"] == lab:
                key = o["form"] if o["scale"] == "1" else f"{o['form']}x{o['scale']}"
                forms[key] = forms.get(key, 0) + 1
        per[lab] = dict(statements=tr["statements"], forms=forms, levels=tr["levels"],
                        stretto=tr["stretto"], **({"combined_with_" + first: tr["combination"]}
                                                   if first and lab != first else {}))
    viol = form_check(occ, form, subjects)
    out = dict(form=form, subjects=subjects, themes=per, ok=not viol, violations=viol)
    if full:
        out["occurrences"] = [{k: v for k, v in o.items() if not k.startswith("_")} for o in occ]
    return out


def run_project(root, cfg: dict, score=None, full: bool = False) -> dict:
    """Ledger + form claim for a kapell project (reads [themes], [paths] materials, [piece] form)."""
    from pathlib import Path
    themes = dict(cfg.get("themes") or {})
    if not themes:
        return dict(skipped="no [themes] in kapell.toml", ok=True, violations=[])
    measure = measure_of(cfg)
    root = Path(root)
    paths = cfg.get("paths") or {}
    score = Path(score) if score else root / paths.get("score", "score/music-voices.ly")
    mats = root / paths["materials"] if paths.get("materials") else score
    voices = (cfg.get("piece") or {}).get("voices") or ["soprano", "alto", "tenor", "bass"]
    occ = ledger(score.read_text(), themes, voices, measure, mats.read_text())
    subjects = subjects_of(themes, cfg)
    return summarize(occ, themes, (cfg.get("piece") or {}).get("form"), subjects, full)
