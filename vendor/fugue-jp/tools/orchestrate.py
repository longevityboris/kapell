#!/usr/bin/env python3
"""Orchestrate a four-voice score for several renderers: one MIDI per renderer group.

usage:
  python3 orchestrate.py SCORE.ly PLAN.json ORCH.json OUTDIR           write OUTDIR/<group>.mid, manifest, check
  python3 orchestrate.py SCORE.ly PLAN.json ORCH.json OUTDIR --check   only re-check existing output
  options: --quiet (no per-part table)

Input
  SCORE.ly   LilyPond file with \\absolute voice variables (what perform.py reads)
  PLAN.json  perform.py's performance plan (tempo, dynamics, roles, pedal, ...)
  ORCH.json  the orchestration spec; the format is documented in tools/ORCHESTRATION.md

Output (OUTDIR)
  <group>.mid          one type-1 MIDI per group, in that renderer's own MIDI contract
                       (piano: audio/piano/README.md; quartet: audio/strings/README.md;
                       organ, orchestra: audio/<engine>/CONTRACT.md), every file with the same
                       tempo track, ticks per quarter and time zero
  <group>.<sidecar>    per-group sidecar files where a contract asks for one (organ registration)
  manifest.json        input for mix.py: groups, MIDI files, stage positions, levels
  integrity.json       the integrity report (below); the exit code is 1 if it fails
  orchestration.json   the resolved spec: each window in bars, ticks and seconds, notes per part

How it works
  perform.py is imported and run once per renderer target ("piano" velocities for the
  piano, "strings" CC1/CC11 envelopes for bowed parts) on the same plan. Its timing
  (tempo map, breaths, fermatas, humanised onsets) does not depend on the target, so
  every group shares one tempo map and a note doubled in two groups starts on the same
  tick in both. Each performed note is matched to its score note (lyparse), and the
  assignments route it, by its notated start, to parts: a note belongs to the window
  [at, until) that contains its notated start, and a note held across a hand-off
  stays with the part that started it. Nothing is composed here: every part note is
  a score note of its assigned voice, moved by whole octaves only.

Integrity check (also run by --check, independent of the routing code: it re-reads the
score with lyparse and the written MIDI files with mido)
  * every note of every part = a note of its assigned voice at the same notated onset
    (within humanising) with pitch + the declared octave, and nothing else;
  * every score note is played by at least one part (unless the spec allows gaps);
  * derived pedal-point notes sound a pitch the source voice holds at that time
    (+ octave), bridging only neighbour notes no longer than the declared bridge;
  * no hanging or overlapping same-key notes, monophonic parts stay monophonic;
  * all group files carry an identical tempo map and ticks per quarter;
  * notes outside an orchestra part's compass are errors (the renderer would play them an
    octave off) unless the spec lists the part in "allow_octave_shift"; outside the other
    renderers' compass (quartet, organ), or when allowed, they are warnings.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import itertools
import json
import math
import sys
from dataclasses import dataclass, field
from fractions import Fraction as F
from pathlib import Path

import re
import runpy

import mido

TOOLS = Path(__file__).resolve().parent
RICERCAR = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import perform  # noqa: E402
from lyparse import parse_voice  # noqa: E402

TPQ = perform.TPQ
CC_PER_LEVEL = 13            # perform.py strings: CC = 36 + (level - 1) * 13
CC_MIN = 20                  # perform.py's floor for CC1/CC11
TIMING_KEYS = {"tempo", "fermatas", "breaths", "measure", "voices", "humanize", "beat_unit"}
OCTAVES = (-24, -12, 0, 12, 24)
ART_CC20 = {"detache": 32, "normal": 32, "legato": 80, "slur": 80, "short": 112, "spiccato": 112}
ART_ALL = {"auto", "detache", "normal", "legato", "slur", "short", "spiccato", "staccato", "tenuto", "roll", "stroke"}
ART_CC20.update({"staccato": 112, "tenuto": 32, "roll": 100, "stroke": 20})
QUARTET_SHORT_S = 0.26       # render_quartet.py --short-ms default (auto articulation, CC20)
HANDOFF_SAME_KEY_LIFT_S = 0.06   # perform.py's lift before a repeated note, applied across a hand-off


# ------------------------------------------------------------------------------ renderers
QUARTET_INSTR = {"vn1": ("Violin I", 40), "vn2": ("Violin II", 40), "va": ("Viola", 41),
                 "vc": ("Cello", 42), "cb": ("Contrabass", 43)}
# orchestra: audio/orchestra/CONTRACT.md section 2 (part id, sounding compass); the renderer's own
# table (orch_common.PARTS) is used when it is importable
ORCH_PARTS = {"fl": (60, 96), "ob": (58, 91), "cl": (50, 91), "bn": (34, 75), "hn": (34, 77), "tpt": (54, 84),
              "tbn": (40, 72), "btbn": (31, 67), "tba": (26, 65), "timp": (38, 57), "vn1": (55, 100),
              "vn2": (55, 96), "va": (48, 88), "vc": (36, 81), "cb": (24, 67)}
ORCH_GM = {"fl": 73, "ob": 68, "cl": 71, "bn": 70, "hn": 60, "tpt": 56, "tbn": 57, "btbn": 57, "tba": 58,
           "timp": 47, "vn1": 40, "vn2": 40, "va": 41, "vc": 42, "cb": 43}
ORCH_SIDECAR_KEYS = ("gain_db", "players", "pan", "depth_m", "width", "part")
PLAYERS_CC16 = {"solo": 20, "a2": 64, "a4": 110}
# organ: audio/organ/CONTRACT.md section 2 (divisions and key compass: manuals 36-85, pedal 36-64)
ORGAN_DIVISIONS = {"HW": (36, 85), "POS": (36, 85), "OW": (36, 85), "PED": (36, 64)}
ORGAN_DEFAULT_DIV = {"soprano": "HW", "alto": "HW", "tenor": "POS", "bass": "PED", "pedal": "PED"}


def quartet_compass() -> dict:
    """Instrument compass as render_quartet.py plays it (its table, plus its downward stretch)."""
    try:
        sys.path.insert(0, str(RICERCAR / "audio" / "strings"))
        with contextlib.redirect_stdout(io.StringIO()):
            import render_quartet as rq  # noqa: E402
        return {k: (v["lo"] - rq.EXT_DOWN, v["hi"]) for k, v in rq.INSTR.items()}
    except Exception:  # the renderer is not importable: its documented table
        return {"vn1": (53, 100), "vn2": (53, 100), "va": (46, 91), "vc": (34, 81), "cb": (22, 67)}


def orchestra_parts() -> tuple[dict, object]:
    """(part id -> compass, track-name parser) from the orchestra renderer, else from its contract."""
    try:
        sys.path.insert(0, str(RICERCAR / "audio" / "orchestra"))
        import orch_common as oc  # noqa: E402
        return {k: (v["lo"], v["hi"]) for k, v in oc.PARTS.items()}, lambda n: oc.part_of_name(n)[0]
    except Exception:
        import re
        rx = re.compile(r"^(" + "|".join(sorted(ORCH_PARTS, key=len, reverse=True)) + r")(?:[.:_\- ](\S.*))?$", re.I)
        return dict(ORCH_PARTS), lambda n: (rx.match(n.strip()).group(1).lower() if rx.match(n.strip()) else None)


RENDERERS = {
    # target: the perform.py target that supplies velocities / CCs
    # mono: parts are single lines (a hand-off that meets a held note shortens it)
    # cc: which of perform.py's controllers are written to the group's tracks
    "piano": dict(target="piano", mono=False, cc=(), doc="audio/piano/README.md"),
    "quartet": dict(target="strings", mono=True, cc=(1, 11), doc="audio/strings/README.md"),
    "orchestra": dict(target="strings", mono=True, cc=(1, 11), doc="audio/orchestra/CONTRACT.md"),
    # the organ ignores velocity; with options.swell the strings envelope drives the swell box (CC11)
    "organ": dict(target="piano", mono=False, cc=(), doc="audio/organ/CONTRACT.md"),
}


def renderer_of(name: str) -> dict:
    if name not in RENDERERS:
        raise SystemExit(f"unknown renderer {name!r}; known: {', '.join(RENDERERS)}")
    return RENDERERS[name]


def part_track(rname: str, part: str, popts: dict) -> dict:
    """How a part appears in its group's MIDI: track name, GM program, instrument id, compass."""
    popts = popts or {}
    if rname == "quartet":
        inst = popts.get("instrument", part)
        if inst not in QUARTET_INSTR:
            raise SystemExit(f"quartet part {part!r}: instrument {inst!r} is not one of {', '.join(QUARTET_INSTR)} "
                             "(give {\"instrument\": ...})")
        return {"track": QUARTET_INSTR[inst][0], "program": QUARTET_INSTR[inst][1], "instrument": inst,
                "compass": quartet_compass().get(inst)}
    if rname == "orchestra":
        tname = popts.get("track", part)
        comp, parse = orchestra_parts()
        inst = popts.get("part") or parse(tname)
        if inst not in comp:
            raise SystemExit(f"orchestra part {part!r}: track name {tname!r} is not a part id "
                             f"({', '.join(comp)}, optionally with a tag: 'hn.1', 'fl:oct'); give {{\"part\": ...}}")
        return {"track": tname, "program": ORCH_GM.get(inst, 0), "instrument": inst, "compass": comp[inst]}
    if rname == "organ":
        tname = popts.get("track", part).strip().lower()      # the organ lower-cases track names
        div = popts.get("division") or ORGAN_DEFAULT_DIV.get(tname, "HW")
        if div not in ORGAN_DIVISIONS:
            raise SystemExit(f"organ part {part!r}: division {div!r} is not one of {', '.join(ORGAN_DIVISIONS)}")
        return {"track": tname, "program": 19, "instrument": div, "compass": ORGAN_DIVISIONS[div]}
    return {"track": popts.get("track", part), "program": int(popts.get("program", 0)), "instrument": None,
            "compass": (21, 108)}


# ------------------------------------------------------------------------------ spec
@dataclass
class Window:
    idx: int
    kind: str                  # "line" or "pedal"
    voice: str
    part: str
    group: str
    a: F                       # notated start (whole notes from the piece's start), inclusive
    u: F                       # notated end, exclusive
    at: str
    until: str
    octave: int = 0
    level: float = 0.0         # dynamic steps (1 = p -> mp); piano: hammer velocity, bowed: CC1/CC11
    accent: float = 0.0        # velocity offset (perform.py units)
    articulation: str = "auto"
    players: str | None = None  # orchestra winds/brass: solo | a2 | a4 (CC16)
    pedal: dict = field(default_factory=dict)


@dataclass
class Spec:
    path: Path
    d: dict
    plan: perform.Plan
    groups: dict               # group -> {"renderer": name, "parts": {part: opts}, "options": {...}}
    part_group: dict           # part -> group
    windows: list
    end: F
    marks: dict = field(default_factory=dict)

    def part_windows(self, part):
        return sorted([w for w in self.windows if w.part == part], key=lambda w: w.a)


def fmt_pos(plan: perform.Plan, x: F) -> str:
    bar = int(x / plan.measure) + 1
    beat = (x - (bar - 1) * plan.measure) * 4 + 1
    return f"{bar}:{float(beat):g}"


MARK_RE = re.compile(r"^([A-Za-z_][\w.]*?)(?:([+-]\d+)(?::(\d+(?:\.\d+)?))?)?$")


def load_marks(d: dict, spec_path: Path, plan: perform.Plan, end: F) -> dict:
    """Named positions: {"from": FILE} reads section lengths (a Python file with SECTIONS =
    [{"id", "bars"}, ...], such as design/final-lab/piece.py, or a JSON list of the same, or a
    JSON {name: "bar:beat"}), plus explicit {name: "bar:beat"} entries. A section id "sec05_inversa"
    is also available as "inversa"."""
    m = d.get("marks", {}) or {}
    marks = {}
    src = m.get("from")
    if src:
        path = Path(src) if Path(src).is_absolute() else (Path(spec_path).parent / src)
        if path.suffix == ".py":
            with contextlib.redirect_stdout(io.StringIO()):
                secs = runpy.run_path(str(path), run_name="orchestrate_marks")["SECTIONS"]
        else:
            secs = json.loads(path.read_text())
        if isinstance(secs, dict):
            for k, v in secs.items():
                marks[k] = plan.pos(v)
        else:
            bar = 1
            for sec in secs:
                names = [sec["id"]]
                mm = re.match(r"sec\d+_(.+)$", sec["id"])
                if mm:
                    names.append(mm.group(1))
                for nm in names:
                    marks[nm] = (bar - 1) * plan.measure
                bar += int(sec["bars"])
            total = (bar - 1) * plan.measure
            if total != end:
                raise SystemExit(f"marks from {path}: the sections add up to {bar - 1} bars, the score has "
                                 f"{float(end / plan.measure):g}; the score and the section list disagree")
    for k, v in m.items():
        if k != "from":
            marks[k] = plan.pos(v)
    return marks


def load_spec(spec_path: Path, plan: perform.Plan, end: F) -> Spec:
    d = json.loads(Path(spec_path).read_text())
    marks = load_marks(d, spec_path, plan, end)
    if "groups" not in d or not d["groups"]:
        raise SystemExit(f"{spec_path}: no 'groups'")
    groups, part_group = {}, {}
    for g, gd in d["groups"].items():
        renderer_of(gd.get("renderer", g))
        parts = gd.get("parts", [])
        parts = {p: {} for p in parts} if isinstance(parts, list) else dict(parts)
        if not parts:
            raise SystemExit(f"group {g!r}: no parts")
        for p, po in parts.items():
            if p in part_group:
                raise SystemExit(f"part {p!r} is declared in groups {part_group[p]!r} and {g!r}; part names "
                                 "must be unique")
            part_group[p] = g
            part_track(gd.get("renderer", g), p, po)          # validates the part for its renderer
        tracks = [part_track(gd.get("renderer", g), p, po)["track"] for p, po in parts.items()]
        dup = {t for t in tracks if tracks.count(t) > 1}
        if dup:
            raise SystemExit(f"group {g!r}: parts share the track name(s) {sorted(dup)}")
        bad = TIMING_KEYS & set(gd.get("plan_overrides", {}))
        if bad:
            raise SystemExit(f"group {g!r}: plan_overrides may not change {sorted(bad)}: every group shares one "
                             "tempo map and one set of humanised onsets")
        groups[g] = {"renderer": gd.get("renderer", g), "parts": parts, "options": gd.get("options", {}),
                     "plan_overrides": gd.get("plan_overrides", {})}

    def pos(s, default):
        return resolve_pos(s if s is not None else default, plan, end, marks)

    def part_of(p):
        if p in part_group:
            return p
        if "." in p:
            g, q = p.split(".", 1)
            if part_group.get(q) == g:
                return q
        raise SystemExit(f"unknown part {p!r}; parts: {', '.join(part_group)}")

    windows = []
    items = [("line", x) for x in d.get("assignments", [])] + [("pedal", x) for x in d.get("pedal_points", [])]
    for i, (kind, x) in enumerate(items):
        v = x.get("voice")
        if v not in plan.voices:
            raise SystemExit(f"{kind} #{i}: voice {v!r} is not one of {plan.voices}")
        p = part_of(x.get("part", ""))
        a, u = pos(x.get("at"), "1:1"), pos(x.get("until"), "end")
        if not a < u:
            raise SystemExit(f"{kind} #{i} ({v} -> {p}): 'at' {x.get('at')} is not before 'until' {x.get('until')}")
        octv = int(x.get("octave", 0))
        if octv not in OCTAVES:
            raise SystemExit(f"{kind} #{i} ({v} -> {p}): octave {octv} must be one of {OCTAVES} (octave doublings only)")
        art = x.get("articulation", "auto")
        if art not in ART_ALL:
            raise SystemExit(f"{kind} #{i}: articulation {art!r} not in {sorted(ART_ALL)}")
        pl = x.get("players")
        if pl is not None and pl not in PLAYERS_CC16:
            raise SystemExit(f"{kind} #{i}: players {pl!r} not in {sorted(PLAYERS_CC16)}")
        ped = {}
        if kind == "pedal":
            ped = {"mode": x.get("mode", "sustain"), "bridge": F(str(x.get("bridge", 1))) / 4,
                   "min_beats": F(str(x.get("min_beats", 2))) / 4, "pitch": x.get("pitch", "auto"),
                   "rate": x.get("rate", 8.0)}
            if ped["mode"] not in ("sustain", "repeat"):
                raise SystemExit(f"pedal point #{i}: mode {ped['mode']!r} (sustain | repeat)")
        windows.append(Window(i, kind, v, p, part_group[p], a, u, fmt_pos(plan, a), fmt_pos(plan, u), octv,
                              float(x.get("level", 0.0)), float(x.get("accent", 0.0)), art, pl, ped))
    # One part plays one window at a time (a hand-off is two windows that touch).
    for p in part_group:
        ws = sorted([w for w in windows if w.part == p], key=lambda w: w.a)
        for w1, w2 in zip(ws, ws[1:]):
            if w2.a < w1.u:
                raise SystemExit(f"part {p!r}: windows overlap ({w1.voice} {w1.at}-{w1.until} and "
                                 f"{w2.voice} {w2.at}-{w2.until}); split them or use another part")
    # positions inside group options (piano pedal spans, organ registration) may use marks too;
    # perform.py and the organ read plain "bar:beat", so they are rewritten here
    for gd in groups.values():
        ped = gd["options"].get("pedal")
        if isinstance(ped, list):
            gd["options"]["pedal"] = [dict(x, **{k: fmt_pos(plan, resolve_pos(x[k], plan, end, marks))
                                                 for k in ("at", "until") if k in x}) for x in ped]
        reg = gd["options"].get("registration")
        if isinstance(reg, dict):
            for key in ("changes", "manual_changes"):
                reg[key] = [dict(x, at=fmt_pos(plan, resolve_pos(x["at"], plan, end, marks))) if "at" in x else x
                            for x in reg.get(key, [])]
    d["allow_uncovered"] = [dict(x, **{k: fmt_pos(plan, resolve_pos(x[k], plan, end, marks)) if x[k] != "end"
                                       else "end" for k in ("at", "until") if k in x})
                            for x in d.get("allow_uncovered", [])]
    return Spec(Path(spec_path), d, plan, groups, part_group, windows, end, marks)


def resolve_pos(s: str, plan: perform.Plan, end: F, marks: dict) -> F:
    """"bar:beat" | "end" | "MARK" | "MARK+N" | "MARK-N" | "MARK+N:beat" (N bars after the mark, then
    the beat within that bar)."""
    if s == "end":
        return end
    if re.match(r"^\d+:\d+(?:\.\d+)?(?:/\d+)?$", str(s)):
        return plan.pos(s)
    mm = MARK_RE.match(str(s))
    if not mm or mm.group(1) not in marks:
        known = ", ".join(sorted(marks)) or "none"
        raise SystemExit(f"bad position {s!r}: expected \"bar:beat\", \"end\" or MARK[+N[:beat]] "
                         f"(marks: {known})")
    x = marks[mm.group(1)]
    if mm.group(2):
        x += int(mm.group(2)) * plan.measure
    if mm.group(3):
        x += (F(mm.group(3)) - 1) / 4
    return x


# ------------------------------------------------------------------------------ perform.py
@dataclass
class PNote:
    on: int
    off: int
    pitch: int
    vel: int
    start: F
    end: F
    voice: str


def run_perform(score: Path, plan_d: dict, target: str, workdir: Path) -> Path:
    """perform.py (imported) on a plan variant; output cached by content hash."""
    blob = json.dumps(plan_d, sort_keys=True)
    h = hashlib.sha256((blob + target + Path(score).read_text()).encode()).hexdigest()[:12]
    plan_path = workdir / f"plan_{target}_{h}.json"
    out = workdir / f"perform_{target}_{h}.mid"
    plan_path.write_text(blob)
    with contextlib.redirect_stdout(io.StringIO()):
        perform.build(str(score), str(plan_path), str(out), target)
    return out


def abs_events(track):
    t = 0
    for m in track:
        t += m.time
        yield t, m


def tempo_list(mid: mido.MidiFile):
    return [(t, m.tempo) for tr in mid.tracks for t, m in abs_events(tr) if m.type == "set_tempo"]


def read_perform(path: Path, plan: perform.Plan, score_notes: dict) -> dict:
    """perform.py MIDI -> {"tempo_track": [...], "tempo": [...], "voices": {v: {"notes", "cc"}}};
    each note carries its notated start/end (matched note-on by note-on to the score)."""
    mid = mido.MidiFile(str(path))
    assert mid.ticks_per_beat == TPQ
    out = {"tempo_track": list(mid.tracks[0]), "tempo": tempo_list(mid), "voices": {}}
    for tr in mid.tracks[1:]:
        name = next((m.name for m in tr if m.type == "track_name"), None)
        if name not in score_notes:
            continue
        ons, offs, cc = [], {}, {}
        for t, m in abs_events(tr):
            if m.type == "note_on" and m.velocity > 0:
                ons.append((t, m.note, m.velocity))
            elif m.type in ("note_off", "note_on"):
                offs.setdefault(m.note, []).append(t)
            elif m.type == "control_change":
                cc.setdefault(m.control, []).append((t, m.value))
        sounding = [n for n in score_notes[name] if n.midi is not None]
        if len(sounding) != len(ons):
            raise SystemExit(f"{name}: perform.py wrote {len(ons)} notes, the score has {len(sounding)}")
        notes = []
        for (t, key, vel), sn in zip(ons, sounding):
            if key != sn.midi:
                raise SystemExit(f"{name}: note order mismatch at {sn} (MIDI key {key})")
            lst = [x for x in offs.get(key, []) if x >= t]
            if not lst:
                raise SystemExit(f"{name}: note {sn} has no note-off")
            off = lst[0]
            offs[key].remove(off)
            notes.append(PNote(t, off, key, vel, sn.start, sn.end, name))
        out["voices"][name] = {"notes": notes, "cc": cc}
    return out


# ------------------------------------------------------------------------------ routing
def tick_of(x: F) -> int:
    return int(round(x * 4 * TPQ))


class TempoMap:
    def __init__(self, tempos):
        self.pts = []              # (tick, seconds, us per quarter)
        s, lt, us = 0.0, 0, 500000
        for t, tempo in sorted(tempos):
            s += (t - lt) * us / 1e6 / TPQ
            self.pts.append((t, s, tempo))
            lt, us = t, tempo
        if not self.pts or self.pts[0][0] > 0:
            self.pts.insert(0, (0, 0.0, 500000))

    def sec(self, tick):
        lo, hi = 0, len(self.pts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.pts[mid][0] <= tick:
                lo = mid
            else:
                hi = mid - 1
        t, s, us = self.pts[lo]
        return s + (tick - t) * us / 1e6 / TPQ


def pedal_notes(w: Window, src: list, plan: perform.Plan):
    """Derived sustained pedal part: the pitch the voice holds in the window, merged over repeats
    and bridged over neighbour notes no longer than `bridge`; runs shorter than min_beats dropped.
    -> list of (first source note, last source note, pitch before octave)."""
    ns = [n for n in src if w.a <= n.start < w.u]
    if not ns:
        return []
    if w.pedal["pitch"] == "auto":
        held = {}
        for n in ns:
            held[n.pitch] = held.get(n.pitch, 0) + (min(n.end, w.u) - n.start)
        P = max(held, key=lambda k: held[k])
    else:
        P = int(w.pedal["pitch"])
        if P not in {n.pitch for n in ns}:
            raise SystemExit(f"pedal point {w.voice}->{w.part}: pitch {P} is not sounded by {w.voice} in "
                             f"{w.at}-{w.until}")
    runs, cur = [], None
    for n in ns:
        if n.pitch == P:
            if cur is not None and n.start - cur[1].end <= w.pedal["bridge"]:
                cur[1] = n
            else:
                if cur is not None:
                    runs.append(cur)
                cur = [n, n]
        # a non-pedal note: the run survives it if the next pedal note comes within `bridge`
    if cur is not None:
        runs.append(cur)
    return [(r[0], r[1], P) for r in runs if r[1].end - r[0].start >= w.pedal["min_beats"]]


def build(score: Path, plan_path: Path, spec_path: Path, outdir: Path, quiet=False) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    work = outdir / "perform"
    work.mkdir(exist_ok=True)
    plan_d = json.loads(Path(plan_path).read_text())
    plan = perform.Plan(plan_d)
    src = Path(score).read_text()
    score_notes = {v: parse_voice(src, v, plan.measure) for v in plan.voices}
    missing = [v for v, n in score_notes.items() if not n]
    if missing:
        raise SystemExit(f"{score}: no \\absolute variable for {missing}")
    end = max(n[-1].end for n in score_notes.values())
    spec = load_spec(spec_path, plan, end)
    warnings = []

    # one perform.py run per (target, plan variant)
    perf_cache, group_perf = {}, {}
    for g, gd in spec.groups.items():
        r = dict(renderer_of(gd["renderer"]))
        if gd["renderer"] == "organ" and gd["options"].get("swell"):
            r["target"] = "strings"          # its CC11 envelope drives the swell box of enclosed divisions
        gd["target"] = r["target"]
        variant = copy.deepcopy(plan_d)
        variant.update(copy.deepcopy(gd["plan_overrides"]))
        if gd["renderer"] == "piano":
            ped = gd["options"].get("pedal", "plan")
            if ped == "none":
                variant["pedal"] = []
            elif isinstance(ped, list):
                variant["pedal"] = ped
        key = (r["target"], json.dumps(variant, sort_keys=True))
        if key not in perf_cache:
            path = run_perform(score, variant, r["target"], work)
            perf_cache[key] = (read_perform(path, plan, score_notes), perform.Plan(variant))
        group_perf[g] = perf_cache[key]
    tempos = {json.dumps(p[0]["tempo"]) for p in perf_cache.values()}
    if len(tempos) != 1:
        raise SystemExit("perform.py produced different tempo maps for different targets")
    # doubled notes start together: the humanised onsets must not depend on the target
    runs = list(perf_cache.values())
    for p, _ in runs[1:]:
        for v in plan.voices:
            a = [n.on for n in runs[0][0]["voices"][v]["notes"]]
            b = [n.on for n in p["voices"][v]["notes"]]
            if a != b:
                raise SystemExit(f"{v}: note-on ticks differ between perform.py targets")
    tmap = TempoMap(runs[0][0]["tempo"])

    resolved = {"spec": str(spec_path), "score": str(score), "plan": str(plan_path),
                "score_sha256": hashlib.sha256(Path(score).read_bytes()).hexdigest()[:16],
                "plan_sha256": hashlib.sha256(Path(plan_path).read_bytes()).hexdigest()[:16],
                "duration_s": round(tmap.sec(tick_of(end)), 3), "bars": float(end / plan.measure),
                "marks": {k: {"at": fmt_pos(plan, v), "t_s": round(tmap.sec(tick_of(v)), 3)}
                          for k, v in sorted(spec.marks.items(), key=lambda kv: kv[1])},
                "groups": {}}
    group_files = {}
    for g, gd in spec.groups.items():
        rname = gd["renderer"]
        perf, gplan = group_perf[g]
        mid = mido.MidiFile(type=1, ticks_per_beat=TPQ)
        tt = mido.MidiTrack()
        for m in perf["tempo_track"]:
            if m.type == "end_of_track":
                continue
            tt.append(m.copy())
        # after perform.py's own marker, which the renderers read
        tt.insert(2, mido.MetaMessage("text", text=f"orchestrate.py group={g} renderer={rname} "
                                      f"spec={spec_path.name}", time=0))
        mid.tracks.append(tt)
        level_fns = {v: gplan.level_fn(v) for v in plan.voices}
        # the orchestra contract gives channels no meaning (each track is its own
        # line), so a symphony orchestra may have more than 15 tracks: reuse channels
        chans = [c for c in range(16) if c != 9]
        ch_iter = itertools.cycle(chans) if rname == "orchestra" else iter(chans)
        ginfo = {"renderer": rname, "midi": f"{g}.mid", "parts": {}}
        # the piano's sustain pedal: perform.py's CC64 (same on every voice track), kept only
        # where the piano plays, so no pedal noise sounds while it rests
        pedal_pairs = []
        if rname == "piano":
            cc64 = perf["voices"][plan.voices[0]]["cc"].get(64, [])
            down = None
            for t, val in cc64:
                if val >= 64 and down is None:
                    down = t
                elif val < 64 and down is not None:
                    pedal_pairs.append((down, t))
                    down = None
            act = [(tick_of(w.a), tick_of(w.u)) for w in spec.windows if w.group == g]
            kept = [pp for pp in pedal_pairs if any(a <= pp[0] < b for a, b in act)]
            if len(kept) < len(pedal_pairs):
                warnings.append(f"{g}: {len(pedal_pairs) - len(kept)} pedal changes dropped where the piano rests")
            pedal_pairs = kept
        for pi, (part, popts) in enumerate(gd["parts"].items()):
            ch = next(ch_iter)
            popts = popts or {}
            pt = part_track(rname, part, popts)
            inst, tname, prog = pt["instrument"], pt["track"], pt["program"]
            mono = RENDERERS[rname]["mono"] and not popts.get("divisi")
            tr = mido.MidiTrack()
            tr.append(mido.MetaMessage("track_name", name=tname, time=0))
            tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
            evs = []           # (tick, prio, kind, a, b)
            notes_out = []     # (on, off, pitch, vel, window) in play order
            for w in spec.part_windows(part):
                srcn = perf["voices"][w.voice]["notes"]
                if w.kind == "line":
                    sel = [n for n in srcn if w.a <= n.start < w.u]
                    for n in sel:
                        vel = n.vel + w.accent
                        if rname == "piano" and w.level:
                            L0 = level_fns[w.voice](n.start)
                            vel += perform.vel_of_level(L0 + w.level) - perform.vel_of_level(L0)
                        notes_out.append([n.on, n.off, n.pitch + w.octave, int(max(1, min(127, round(vel)))), w, n])
                else:
                    for first, last, P in pedal_notes(w, srcn, plan):
                        vel = first.vel + w.accent
                        if rname == "piano" and w.level:
                            L0 = level_fns[w.voice](first.start)
                            vel += perform.vel_of_level(L0 + w.level) - perform.vel_of_level(L0)
                        vel = int(max(1, min(127, round(vel))))
                        if w.pedal["mode"] == "sustain":
                            notes_out.append([first.on, last.off, P + w.octave, vel, w, first])
                        else:      # repeat: re-struck at `rate` per second, a roll for tuned percussion
                            t0, t1 = tmap.sec(first.on), tmap.sec(last.off)
                            k = max(1, int((t1 - t0) * float(w.pedal["rate"])))
                            ticks = [first.on] + [sec_to_tick(tmap, t0 + (t1 - t0) * i / k) for i in range(1, k)]
                            for i, tk in enumerate(ticks):
                                nx = ticks[i + 1] if i + 1 < len(ticks) else last.off
                                notes_out.append([tk, max(tk + 1, nx - 1), P + w.octave, vel, w, first])
            notes_out.sort(key=lambda x: (x[0], x[2]))
            # articulation hints
            trunc = 0
            for i, x in enumerate(notes_out):
                w = x[4]
                nxt = notes_out[i + 1] if i + 1 < len(notes_out) else None
                if w.articulation in ("short", "spiccato", "staccato") and rname == "piano":
                    x[1] = x[0] + max(30, (x[1] - x[0]) // 2)
                elif w.articulation in ("legato", "slur", "tenuto") and rname == "piano" and nxt is not None \
                        and nxt[4] is w and 0 <= nxt[0] - x[1] < TPQ // 2:
                    x[1] = nxt[0] + 40
            if mono:
                relift = 0
                for i in range(len(notes_out) - 1):
                    x, y = notes_out[i], notes_out[i + 1]
                    if y[0] < x[1] and y[4] is x[4]:
                        continue           # perform.py's own legato overlap (humanised onset vs exact release)
                    if y[0] < x[1]:        # a note held across a hand-off meets the next window's first note
                        if y[0] - x[0] < TPQ // 8:
                            raise SystemExit(f"part {part!r}: two notes start together at tick {x[0]} "
                                             f"({x[4].voice} and {y[4].voice}); a {rname} part is one line")
                        trunc += 1
                        x[1] = y[0] - 1
                    if y[2] == x[2] and y[4].voice != x[4].voice \
                            and tmap.sec(y[0]) - tmap.sec(x[1]) < HANDOFF_SAME_KEY_LIFT_S:
                        # a hand-off onto the same key: lift the earlier note as perform.py does for a
                        # repeated note inside one voice (which it cannot see across voices), so the
                        # renderer re-attacks the key instead of meeting a note-off at the new note-on
                        lift = max(tmap.sec(x[0]) + 0.04, tmap.sec(y[0]) - HANDOFF_SAME_KEY_LIFT_S)
                        x[1] = max(x[0] + 1, min(x[1], sec_to_tick(tmap, lift)))
                        relift += 1
                if trunc:
                    warnings.append(f"{part}: {trunc} note(s) held across a hand-off shortened to the next note")
                if relift:
                    warnings.append(f"{part}: {relift} hand-off(s) onto the same key: the earlier note released "
                                    f"{int(HANDOFF_SAME_KEY_LIFT_S * 1000)} ms before the next")
            # bowed / wind articulation: CC20 per note (once any window gives one, every note needs a
            # value, because the renderers stop inferring as soon as a track carries CC20)
            cc20, cc16 = {}, {}
            if rname in ("quartet", "orchestra") and any(x[4].articulation != "auto" for x in notes_out):
                prev = None
                for x in notes_out:
                    art = x[4].articulation
                    dur = tmap.sec(x[1]) - tmap.sec(x[0])
                    if art in ART_CC20:
                        val = ART_CC20[art]
                    elif inst == "timp":   # render_orchestra.py: 0.9 s or longer is a roll
                        val = 100 if dur >= 0.9 else 20
                    else:                  # the renderers' own inference
                        conn = prev is not None and tmap.sec(x[0]) - tmap.sec(prev[1]) < 0.06 and prev[2] != x[2]
                        val = 112 if dur < QUARTET_SHORT_S else 80 if conn else 0
                    cc20[x[0]] = val
                    prev = x
            # winds and brass: players (CC16) per note once any window names them
            if rname == "orchestra" and any(x[4].players for x in notes_out):
                for x in notes_out:
                    cc16[x[0]] = PLAYERS_CC16[x[4].players or popts.get("players", "solo")]
            for x in notes_out:
                evs.append((x[0], 1, "on", x[2], x[3]))
                evs.append((x[1], 0, "off", x[2], 0))
            for t, val in cc20.items():
                evs.append((t, -1, "cc", 20, val))
            for t, val in cc16.items():
                evs.append((t, -1, "cc", 16, val))
            # bowed parts: the dynamic envelope (CC1 + CC11) of whichever voice the part plays,
            # plus the window's level; while the part rests, the envelope of its next window
            pw = spec.part_windows(part)
            ccs = RENDERERS[rname]["cc"] or ((11,) if gd["target"] == "strings" else ())
            if ccs and pw:
                grid = sorted({t for v in plan.voices for t, _ in perf["voices"][v]["cc"].get(1, [])})
                look = {}
                for v in plan.voices:
                    for c in (1, 11):
                        look[(v, c)] = dict(perf["voices"][v]["cc"].get(c, []))
                last = {c: None for c in ccs}
                for t in grid:
                    x = F(round(t / (TPQ // 4)), 16)      # CC events sit on perform.py's 16th grid
                    w = next((w for w in pw if w.a <= x < w.u), None) or next((w for w in pw if w.a > x), None) \
                        or pw[-1]
                    for c in ccs:
                        v0 = look[(w.voice, c)].get(t)
                        if v0 is None:
                            continue
                        val = int(max(CC_MIN, min(127, round(v0 + CC_PER_LEVEL * w.level))))
                        if val != last[c]:
                            evs.append((t, -1, "cc", c, val))
                            last[c] = val
            if rname == "piano" and pi == 0:
                for a, b in pedal_pairs:
                    evs.append((a, 2, "cc", 64, 127))
                    evs.append((b, -2, "cc", 64, 0))
            evs.sort(key=lambda e: (e[0], e[1]))
            lt = 0
            for t, _, kind, a, b in evs:
                if kind == "on":
                    msg = mido.Message("note_on", channel=ch, note=a, velocity=b, time=t - lt)
                elif kind == "off":
                    msg = mido.Message("note_off", channel=ch, note=a, velocity=0, time=t - lt)
                else:
                    msg = mido.Message("control_change", channel=ch, control=a, value=b, time=t - lt)
                tr.append(msg)
                lt = t
            mid.tracks.append(tr)
            ginfo["parts"][part] = {
                "track": tname, "channel": ch, "program": prog, "instrument": inst,
                "notes": len(notes_out),
                "range": [min(x[2] for x in notes_out), max(x[2] for x in notes_out)] if notes_out else None,
                "windows": [{"kind": w.kind, "voice": w.voice, "at": w.at, "until": w.until, "octave": w.octave,
                             "level": w.level, "articulation": w.articulation,
                             "t0_s": round(tmap.sec(tick_of(w.a)), 3), "t1_s": round(tmap.sec(tick_of(w.u)), 3)}
                            for w in pw],
            }
        path = outdir / f"{g}.mid"
        mid.save(str(path))
        group_files[g] = path
        side = write_sidecar(g, gd, plan_d, outdir)
        if side:
            ginfo["sidecar"] = side.name
        if rname == "piano":
            ginfo["pedal_changes"] = len(pedal_pairs)
        resolved["groups"][g] = ginfo

    (outdir / "orchestration.json").write_text(json.dumps(resolved, indent=1))
    write_manifest(spec, outdir, resolved)
    rep = check(score, plan_path, spec_path, outdir)
    rep["warnings"] = warnings + rep["warnings"]
    (outdir / "integrity.json").write_text(json.dumps(rep, indent=1))
    if not quiet:
        print_summary(resolved, rep)
    return rep


def write_sidecar(g: str, gd: dict, plan_d: dict, outdir: Path) -> Path | None:
    """Per-group sidecar files the renderers read (always rewritten, so no stale one is picked up).
    orchestra: <group>.orchestra.json next to the MIDI (render_orchestra.py reads x.orchestra.json);
    organ: <group>.registration.json (render_organ.py --registration)."""
    rname, opts = gd["renderer"], gd["options"]
    if rname == "orchestra":
        side = copy.deepcopy(opts.get("sidecar", {}))
        for part, popts in gd["parts"].items():
            popts = popts or {}
            extra = {k: popts[k] for k in ORCH_SIDECAR_KEYS if k in popts}
            if extra:
                side.setdefault("tracks", {}).setdefault(part_track(rname, part, popts)["track"], {}).update(extra)
        path = outdir / f"{g}.orchestra.json"
        path.write_text(json.dumps(side, indent=1))
        return path
    if rname == "organ":
        reg = copy.deepcopy(opts.get("registration", {}))
        reg.setdefault("measure", str(plan_d.get("measure", "1")))
        plan = perform.Plan(plan_d)
        for key in ("changes", "manual_changes"):
            for ch in reg.get(key, []):
                if "at" in ch:
                    plan.pos(ch["at"])       # raises on a malformed position
        manuals = reg.setdefault("manuals", {})
        for part, popts in gd["parts"].items():
            pt = part_track(rname, part, popts)
            manuals.setdefault(pt["track"], pt["instrument"])
        if opts.get("swell") and "enclosed" not in reg:
            reg["enclosed"] = ["POS"]
        path = outdir / f"{g}.registration.json"
        path.write_text(json.dumps(reg, indent=1))
        return path
    return None


def sec_to_tick(tmap: TempoMap, s: float) -> int:
    lo, hi = 0, len(tmap.pts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tmap.pts[mid][1] <= s:
            lo = mid
        else:
            hi = mid - 1
    t, s0, us = tmap.pts[lo]
    return int(round(t + (s - s0) * 1e6 / us * TPQ))


def write_manifest(spec: Spec, outdir: Path, resolved: dict):
    mixd = spec.d.get("mix", {})
    man = {
        "title": spec.d.get("title", spec.path.stem),
        "orchestration": str(Path("orchestration.json")),
        "out": mixd.get("out", f"../{outdir.name}"),
        "lead_in": mixd.get("lead_in", 0.5),
        "peak_dbtp": mixd.get("peak_dbtp", -1.0),
        "hall": mixd.get("hall", "detmold"),
        "reference_group": mixd.get("reference_group", next(iter(spec.groups))),
        "groups": {},
    }
    for g, gi in resolved["groups"].items():
        gm = dict(mixd.get("groups", {}).get(g, {}))
        man["groups"][g] = {"renderer": gi["renderer"], "midi": gi["midi"],
                            "parts": {p: {"track": x["track"], "instrument": x["instrument"]}
                                      for p, x in gi["parts"].items()}, **gm}
    (outdir / "manifest.json").write_text(json.dumps(man, indent=1))


# ------------------------------------------------------------------------------ integrity
def read_group_midi(path: Path):
    """-> (tempo list, ticks per quarter, {track name: {"notes": [(on, off, key)], "hanging": n,
    "overlaps": n}})"""
    mid = mido.MidiFile(str(path))
    tracks = {}
    for tr in mid.tracks:
        name = next((m.name for m in tr if m.type == "track_name"), None)
        if not any(m.type == "note_on" for m in tr):
            continue
        pend, notes, overlaps = {}, [], 0
        for t, m in abs_events(tr):
            if m.type == "note_on" and m.velocity > 0:
                if pend.get(m.note):
                    overlaps += 1
                pend.setdefault(m.note, []).append(t)
            elif m.type in ("note_off", "note_on"):
                if pend.get(m.note):
                    notes.append((pend[m.note].pop(0), t, m.note))
        hanging = sum(len(x) for x in pend.values())
        tracks[name] = {"notes": sorted(notes), "hanging": hanging, "overlaps": overlaps}
    return tempo_list(mid), mid.ticks_per_beat, tracks


def check(score: Path, plan_path: Path, spec_path: Path, outdir: Path) -> dict:
    plan = perform.Plan(json.loads(Path(plan_path).read_text()))
    src = Path(score).read_text()
    sn = {v: parse_voice(src, v, plan.measure) for v in plan.voices}
    end = max(n[-1].end for n in sn.values())
    spec = load_spec(spec_path, plan, end)
    sounding = {v: [n for n in ns if n.midi is not None] for v, ns in sn.items()}
    shortest = min(n.dur for ns in sounding.values() for n in ns)
    tol = int(min(60, tick_of(shortest) // 3))     # humanising + melody lead: under 20 ms, a few ticks
    errors, warnings = [], []
    parts_rep = {}
    covered = {v: [False] * len(ns) for v, ns in sounding.items()}
    tempo_ref, tpq_ref = None, None
    for g, gd in spec.groups.items():
        path = outdir / f"{g}.mid"
        if not path.exists():
            errors.append(f"{g}: {path} missing")
            continue
        tempos, tpq, tracks = read_group_midi(path)
        if tempo_ref is None:
            tempo_ref, tpq_ref = tempos, tpq
        elif tempos != tempo_ref or tpq != tpq_ref:
            errors.append(f"{g}: tempo map or ticks per quarter differ from the first group's")
        if tpq != TPQ:
            errors.append(f"{g}: ticks per quarter {tpq}, expected {TPQ}")
        for part, popts in gd["parts"].items():
            popts = popts or {}
            pt = part_track(gd["renderer"], part, popts)
            inst, tname = pt["instrument"], pt["track"]
            got = tracks.get(tname, {"notes": [], "hanging": 0, "overlaps": 0})
            actual = list(got["notes"])
            used = [False] * len(actual)
            pr = {"expected": 0, "matched": 0, "missing": [], "extra": [], "pedal_notes": 0, "shortened": 0}
            if got["hanging"]:
                errors.append(f"{part}: {got['hanging']} note-on(s) without note-off")
            if got["overlaps"]:
                errors.append(f"{part}: {got['overlaps']} note-on(s) on a key that is still sounding")
            ws = sorted([w for w in spec.windows if w.part == part], key=lambda w: w.a)
            by_key = {}
            for i, (on, off, key) in enumerate(actual):
                by_key.setdefault(key, []).append(i)
            for w in ws:
                if w.kind != "line":
                    continue
                for j, n in enumerate(sounding[w.voice]):
                    if not w.a <= n.start < w.u:
                        continue
                    pr["expected"] += 1
                    t0, t1, key = tick_of(n.start), tick_of(n.end), n.midi + w.octave
                    cand = [i for i in by_key.get(key, []) if not used[i] and abs(actual[i][0] - t0) <= tol]
                    if not cand:
                        pr["missing"].append(f"{w.voice} {fmt_pos(plan, n.start)} {n.name}{w.octave:+d}")
                        continue
                    i = min(cand, key=lambda i: abs(actual[i][0] - t0))
                    used[i] = True
                    pr["matched"] += 1
                    covered[w.voice][j] = True
                    on, off, _ = actual[i]
                    slack = TPQ // 2 if w.articulation in ("legato", "slur", "tenuto") else tol
                    if off > t1 + slack:
                        errors.append(f"{part}: {w.voice} {fmt_pos(plan, n.start)} {n.name} lasts past its notated end")
                    if off - on < 0.5 * (t1 - t0) and w.articulation in ("auto", "legato", "slur", "tenuto"):
                        pr["shortened"] += 1
            # pedal points: each remaining note must be a held pitch of the source voice
            for w in ws:
                if w.kind != "pedal":
                    continue
                vn = sounding[w.voice]
                for i, (on, off, key) in enumerate(actual):
                    if used[i] or not tick_of(w.a) - tol <= on < tick_of(w.u):
                        continue
                    P = key - w.octave
                    x0, x1 = F(on, 4 * TPQ), F(off, 4 * TPQ)
                    first = [n for n in vn if abs(tick_of(n.start) - on) <= tol and n.midi == P]
                    first = first or [n for n in vn if n.start <= x0 < n.end and n.midi == P]
                    if not first:
                        continue
                    inside = sorted([n for n in vn if n.end > x0 and n.start < x1], key=lambda n: n.start)
                    # every stretch of other notes under the pedal must fit the bridge
                    bad, stretch = False, F(0)
                    for n in inside:
                        if n.midi != P:
                            stretch += n.dur
                        else:
                            bad |= stretch > w.pedal["bridge"]
                            stretch = F(0)
                    held = [n for n in inside if n.midi == P]
                    bad |= stretch > w.pedal["bridge"] or not held
                    if held and off > tick_of(max(n.end for n in held)) + tol:
                        bad = True
                    if bad:
                        errors.append(f"{part}: pedal note {key} at {fmt_pos(plan, x0)} is not a pitch {w.voice} "
                                      f"holds (bridge {float(w.pedal['bridge'] * 4):g} beats)")
                    used[i] = True
                    pr["pedal_notes"] += 1
            for i, (on, off, key) in enumerate(actual):
                if not used[i]:
                    pr["extra"].append(f"key {key} at {fmt_pos(plan, F(on, 4 * TPQ))}")
            if pr["missing"]:
                errors.append(f"{part}: {len(pr['missing'])} assigned note(s) missing: {pr['missing'][:5]}")
            if pr["extra"]:
                errors.append(f"{part}: {len(pr['extra'])} note(s) that no assignment accounts for: "
                              f"{pr['extra'][:5]}")
            if pr["shortened"]:
                warnings.append(f"{part}: {pr['shortened']} note(s) sound less than half their notated length")
            if RENDERERS[gd["renderer"]]["mono"] and not popts.get("divisi"):
                # perform.py lets a bowed note overlap the next by its humanising (under 20 ms)
                poly = sum(1 for a, b in zip(actual, actual[1:]) if b[0] < a[1] - tol)
                if poly:
                    errors.append(f"{part}: {poly} overlapping notes in a single-line part")
            keys = [k for _, _, k in actual]
            if keys:
                pr["range"] = [min(keys), max(keys)]
                lo, hi = pt["compass"] or (0, 127)
                out_of = [(on, k) for on, _, k in actual if not lo <= k <= hi]
                if out_of:
                    where = ", ".join(f"{fmt_pos(plan, F(on, 4 * TPQ))} key {k}" for on, k in out_of[:5])
                    msg = (f"{part}: {len(out_of)} note(s) outside the {inst or gd['renderer']} compass "
                           f"{lo}-{hi} (lowest {min(keys)}, highest {max(keys)}; {where}); the renderer moves "
                           "them by octaves")
                    # the orchestra renderer plays such a note an octave off (render.json
                    # tracks[].octave_shifted): a wrong-octave note, so an error unless the spec
                    # accepts it for this part ("allow_octave_shift": ["vn2", ...] or true)
                    allow = spec.d.get("allow_octave_shift", [])
                    allowed_part = allow is True or part in allow or f"{g}.{part}" in allow
                    if gd["renderer"] == "orchestra" and not allowed_part:
                        errors.append(msg + ": they would sound in the wrong octave. Give those bars to a part "
                                      "whose compass holds them (the alto reaches F3 = 53, below vn2 and ob: va, cl), "
                                      "split the window, or list the part in \"allow_octave_shift\"")
                    else:
                        warnings.append(msg)
            parts_rep[part] = {"track": tname, "expected": pr["expected"], "matched": pr["matched"],
                               "pedal_notes": pr["pedal_notes"], "missing": len(pr["missing"]),
                               "extra": len(pr["extra"]), "shortened": pr["shortened"], "range": pr.get("range")}
            if pr["missing"] or pr["extra"]:
                parts_rep[part]["missing_list"] = pr["missing"][:20]
                parts_rep[part]["extra_list"] = pr["extra"][:20]
    cov = {}
    allowed = spec.d.get("allow_uncovered", [])
    for v, flags in covered.items():
        unc = [n for n, f in zip(sounding[v], flags) if not f]
        ok_unc = [n for n in unc if any(a.get("voice", v) == v and plan.pos(a.get("at", "1:1")) <= n.start <
                                        (end if a.get("until", "end") == "end" else plan.pos(a["until"]))
                                        for a in allowed)]
        bad = [n for n in unc if n not in ok_unc]
        cov[v] = {"notes": len(flags), "covered": sum(flags), "allowed_gaps": len(ok_unc),
                  "uncovered": [f"{fmt_pos(plan, n.start)} {n.name}" for n in bad[:20]]}
        if bad:
            errors.append(f"{v}: {len(bad)} score note(s) played by no part: "
                          f"{[fmt_pos(plan, n.start) + ' ' + n.name for n in bad[:5]]}")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "onset_tolerance_ticks": tol,
            "tempo_changes": len(tempo_ref or []), "parts": parts_rep, "coverage": cov}


def window_label(w: dict) -> str:
    s = w["voice"][0].upper() + (f"{w['octave']:+d}" if w["octave"] else "") + ("(ped)" if w["kind"] == "pedal" else "")
    return f"{s} {w['at']}-{w['until']}"


def print_summary(resolved: dict, rep: dict):
    print(f"{resolved['spec']}: {resolved['duration_s']:.1f} s")
    for g, gi in resolved["groups"].items():
        print(f"  {g} ({gi['renderer']}) -> {gi['midi']}")
        for p, x in gi["parts"].items():
            ws = ", ".join(window_label(w) for w in x["windows"])
            rng = x["range"] or ["-", "-"]
            print(f"    {p:12s} {x['track']:10s} {x['notes']:4d} notes  keys {rng[0]}-{rng[1]}  {ws}")
    cov = ", ".join(f"{v} {c['covered']}/{c['notes']}" for v, c in rep["coverage"].items())
    print(f"  integrity: {'OK' if rep['ok'] else 'FAILED'}; coverage {cov}")
    for e in rep["errors"]:
        print("  error:", e)
    for w in rep["warnings"]:
        print("  warning:", w)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("score", type=Path)
    ap.add_argument("plan", type=Path)
    ap.add_argument("spec", type=Path)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--check", action="store_true", help="only check existing output in OUTDIR")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        rep = check(a.score, a.plan, a.spec, a.outdir)
        (a.outdir / "integrity.json").write_text(json.dumps(rep, indent=1))
        print(f"integrity: {'OK' if rep['ok'] else 'FAILED'}")
        for e in rep["errors"]:
            print("  error:", e)
        for w in rep["warnings"]:
            print("  warning:", w)
    else:
        rep = build(a.score, a.plan, a.spec, a.outdir, a.quiet)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
