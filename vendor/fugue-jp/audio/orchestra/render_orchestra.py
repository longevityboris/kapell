#!/usr/bin/env python3
"""Render a multi-track MIDI file as a romantic symphony orchestra in a concert hall.

USAGE
  python3 render_orchestra.py IN.mid [-o OUT] [options]
      -> OUT.wav (48 kHz / 24-bit stereo, true peak -1 dBTP), OUT.m4a (AAC 256 kb/s),
         OUT.json (render report).  OUT defaults to IN without its extension.

THE CHAIN
  python3 ../../tools/perform.py SCORE.ly PLAN.json x.mid --target strings   # voices -> string orchestra
  python3 ../../tools/orchestrate.py ...                                     # or a real orchestration
  python3 render_orchestra.py x.mid -o out/x

INPUT: see CONTRACT.md (the stable interface).  In short: one track per line,
named by part ID (fl ob cl bn hn tpt tbn btbn tba timp vn1 vn2 va vc cb, with an
optional tag: "hn.2"); sounding pitch; CC1 = dynamic level on perform.py's
scale; CC11 expression, CC7 volume, velocity accent, CC16 players (solo / a2 /
a4), CC20 articulation (normal / legato / short; timpani stroke / roll), CC21
release.  A plain perform.py file renders as a string orchestra (soprano ->
Violins I, alto -> Violins II, tenor -> Violas, bass -> Cellos).

OPTIONS
  -o, --out PATH        output basename
  --stems               also write OUT.stems/<track>.wav: dry, placed on stage, float32,
                        same start, length and gain as in the mix before normalisation
  --no-reverb           dry placed mix (no hall)
  --wet DB              hall energy re the dry sound (default -5 dB, see README)
  --lead-in S           silence before the first note-on (default 0.3 s, as piano and quartet)
  --keep-start          output sample 0 = MIDI time 0 (for measurements and stem alignment)
  --sidecar JSON        per-track overrides (default: IN.orchestra.json if present)
  --seating american|german   (default american; the sidecar may set it too)
  --peak DB             true-peak target (default -1.0 dBTP)
  --no-normalize        keep the calibrated level (norm_gain_db = 0 in the report)
  --short-ms MS         notes shorter than this get the short articulation (default 260)
  --strict-range        a note outside its part's compass is an error (default: moved by octaves)
  --only PARTS          render only these part IDs, e.g. "vn1,vc"
  --jobs N              parallel sfizz renders (default 8)
  --keep-temp           keep the per-job MIDI / WAV files
  --force-set P=S,...   testing: play part P with recording set S only (compare_sets.py)

HOW IT SOUNDS THE WAY IT DOES (details and measurements in README.md)
  * Samples: per part the best free recordings found by measurement (orch_build.py
    builds them into SFZ; setup_orchestra.sh does everything once).  Every
    recorded dynamic layer is calibrated to one loudness: layers give the
    timbre, the renderer gives the loudness (BALANCE table: natural balance,
    e.g. a trumpet at f is louder than a flute at f).
  * Dynamics: the true CC1 level drives (a) the gain, (b) the choice of recorded
    layer with hysteresis, switching at a note-on (50 ms) or over 0.3 s inside a
    held note, never parking two takes of one note together, (c) a 2.2 kHz
    shelf that follows the level inside a layer (CC2 to sfizz).
  * Articulation: the quartet's rules (render_quartet.shape_articulation): slurred
    notes enter in the sustain 25 ms early while the previous note lets go just
    after the beat; short notes use staccato / spiccato recordings where the
    library has them; repeated notes re-articulate with a dip, not a hole.
  * Players: a2 / a4 = different recordings of the same instrument (Iowa + VSCO,
    plus the Westlund four-horn section for a4 horns), a few cents apart, 8-25 ms
    apart, seated side by side.  String sections stack two section recordings.
  * Stage and hall: every part has a seat (azimuth, depth); the direct sound is
    panned, delayed by the depth and attenuated 20 log10(10 / (10 + depth)); the
    hall response (Detmold Konzerthaus, measured, the piano's and quartet's hall)
    is not attenuated, so the back rows sound further away and wetter.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import mido
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from orch_common import (BUILT, GERMAN, GM_PROGRAM, PARTS, SFIZZ_RENDER, SR, VEL_AT, balance_db,  # noqa: E402
                         cc1_to_level, level_to_cc1, part_of_name, satb_part)
from render_quartet import Note, cc1_curve, cc_value_at, rel_cc, shape_articulation, tempo_map, true_peak  # noqa: E402

WET_DEFAULT = -5.0
R0 = 10.0                     # metres: direct-sound distance law 20 log10(R0 / (R0 + depth))
SHIFT = 0.5                   # s: sfizz renders in MIDI time + SHIFT (room for early note-ons)
TPB_OUT = 960
TEMPO_OUT = 500000            # 1920 ticks per second
GRID = 0.005
MASTER_DB = 0.0

# ------------------------------------------------------------ instruments
# winds / brass: the recording each player uses (a2 = first two, a4 = all; a
# "section" entry is a recording of a whole section and stands for the rest)
PLAYERS = {        # chosen by compare_sets.py (evidence/compare.json): best set first, runner-up for a2
    "fl": ["vsco", "iowa"], "ob": ["iowa", "vpo3"], "cl": ["iowa", "vsco"], "bn": ["iowa", "vpo3"],
    "hn": ["vsco", "iowa", "vpo3"], "tpt": ["vsco", "iowa"], "tbn": ["iowa", "vsco"],
    "btbn": ["iowa", "vpo3"], "tba": ["iowa", "vpo3"], "timp": ["vsco", "vpo3"],
}
SECTION_SETS = {("hn", "vpo3")}            # a recording of four horns: plays for horns 3-4 at -2 dB
# strings: every note is played by each recording of the stack (gain dB, detune cents);
# a stack only where it measured better than its parts (Violins I).  A gain of None
# marks a range fallback: that recording plays only the notes the others do not reach
# (the basses: the two sets summed on one held low note beat slowly against each
# other, a held A2 faded by 12 dB in 4 s; VSCO alone holds within 3-5 dB, probe.json).
STACK = {
    "vn1": [("vsco", -3.0, 0.0), ("vpo3", -3.0, 0.0)],
    "vn2": [("vsco", 0.0, 0.0), ("vpo3", -6.0, 3.0)],
    "va": [("vpo3", 0.0, 0.0), ("vsco", -6.0, 0.0)],
    "vc": [("vpo3", 0.0, 0.0), ("vsco", -6.0, 0.0)],
    "cb": [("vsco", 0.0, 0.0), ("vpo3", None, 0.0)],
}
# a static low-pass per part (Hz): the Iowa tuba's pp recordings carry hiss that the
# layer calibration lifts with the note (probe: energy above 5 kHz -13 dB re the pp
# note, -43 dB at ff); the tuba has nothing of its own up there
LOWPASS = {"tba": 3500.0}
PLAYER_DETUNE = [0.0, 4.0, -5.0, 7.0]
PLAYER_DELAY = [0.0, 0.012, 0.022, 0.03]
PLAYER_SEAT = [(0.0, 0.0), (-3.0, 0.4), (3.0, 0.8), (-6.0, 1.0)]    # (az offset, depth offset)
# several tracks of one part (hn.1 / hn.2, vc / vc.div) are different players or desks
# (CONTRACT section 2): each further track sits beside the first (az offset, depth
# offset, at most 1.5 m back), is detuned a few cents, starts its notes a few ms
# apart and, for winds and brass, begins its player order on the next recording,
# so two same-part tracks in unison are two instruments, not one copy added twice
TRACK_SEAT = [(0.0, 0.0), (3.0, 0.5), (-3.0, 1.0), (6.0, 1.5)]
TRACK_DETUNE = [0.0, -3.0, 3.0, -6.0]
TRACK_JITTER_MS = 8.0
# bowed strings: a new bow is not moved earlier by the sustain's onset latency.
# tune_orchestra.py's latency_ms (note-on to -6 dB below the peak of the first
# 0.6 s) measures the bowed swell into the sustain, not when the note starts:
# 54-96 ms on the section recordings, which put every string entry after a rest
# 32-90 ms before its beat (a flam against a wind doubling it).  The 15 ms bow
# pre-roll (render_quartet's normal_pre) stays.  Trombones: half the measured
# latency (the full value left them 38-46 ms early on entries).
NO_SUS_LATENCY = {"vn1", "vn2", "va", "vc", "cb"}
HALF_SUS_LATENCY = {"tbn", "btbn"}


def set_available(part: str, s: str) -> bool:
    return (BUILT / part / f"{s}.sfz").exists() and (BUILT / part / f"{s}.layers.json").exists()


_COVER: dict = {}


def coverage(part: str, s: str) -> tuple[int, int]:
    """Lowest / highest key the set's SFZ maps (its samples +-3 semitones)."""
    if (part, s) not in _COVER:
        meta = json.loads((BUILT / part / s / "meta.json").read_text())["notes"]
        keys = [m["key"] for m in meta if m["art"] in ("sus", "hit")]
        ext = 5 if part == "timp" else 3
        _COVER[(part, s)] = (min(keys) - ext, max(keys) + ext)
    return _COVER[(part, s)]


# ------------------------------------------------------------ MIDI in
@dataclass
class Track:
    name: str
    index: int
    notes: list = field(default_factory=list)
    cc: dict = field(default_factory=dict)
    program: int | None = None
    part: str | None = None
    how: str = ""
    shifted: list = field(default_factory=list)
    part_index: int = 0          # index among the tracks of the same part (0 = first)


def read_tracks(path: Path, log: list) -> list[Track]:
    mid = mido.MidiFile(str(path))
    t2s = tempo_map(mid)
    split_channels = mid.type == 0
    tracks: dict = {}
    for ti, tr in enumerate(mid.tracks):
        name = f"track{ti}"
        tick = 0
        pending: dict = {}
        for msg in tr:
            tick += msg.time
            if msg.type == "track_name":
                name = msg.name.strip() or name
                for k, t in tracks.items():
                    if t.index == ti and not split_channels:
                        t.name = name
                continue
            if not hasattr(msg, "channel"):
                continue
            key = (ti, msg.channel if split_channels else 0)
            if key not in tracks:
                nm = f"{name} ch{msg.channel + 1}" if split_channels else name
                tracks[key] = Track(name=nm, index=ti)
            t = tracks[key]
            ts = t2s(tick)
            if msg.type == "note_on" and msg.velocity > 0:
                pending.setdefault((key, msg.note), []).append((ts, msg.velocity))
            elif msg.type in ("note_off", "note_on"):
                lst = pending.get((key, msg.note))
                if lst:
                    on, vel = lst.pop(0)
                    if ts > on:
                        t.notes.append(Note(on, ts, msg.note, vel))
            elif msg.type == "control_change":
                t.cc.setdefault(msg.control, []).append((ts, msg.value))
            elif msg.type == "program_change" and t.program is None:
                t.program = msg.program
        t_end = t2s(tick)
        for (key, k), lst in pending.items():
            for on, vel in lst:
                off = max(t_end, on + 1.0)
                tracks[key].notes.append(Note(on, off, k, vel))
                log.append(f"{tracks[key].name}: note {k} at {on:.2f}s has no note-off, closed at {off:.2f}s")
    out = [t for t in tracks.values() if t.notes]
    for t in out:
        t.notes.sort(key=lambda n: (n.on, -n.key))
        for c in t.cc.values():
            c.sort(key=lambda e: e[0])
    return out


def identify(tracks: list[Track], side: dict):
    """Contract section 2: part ID / sidecar 'part' / instrument name / GM program / SATB name."""
    n_violin_prog = 0
    for t in tracks:
        sc = side.get("tracks", {}).get(t.name, {})
        if "part" in sc and sc["part"] in PARTS:
            t.part, t.how = sc["part"], "sidecar"
            continue
        p, how = part_of_name(t.name)
        if p:
            t.part, t.how = p, how
            continue
        if t.program is not None:
            if t.program == 40:
                t.part, t.how = ("vn1" if n_violin_prog == 0 else "vn2"), "GM program 40"
                n_violin_prog += 1
                continue
            if t.program in GM_PROGRAM:
                t.part, t.how = GM_PROGRAM[t.program], f"GM program {t.program}"
                continue
        p = satb_part(t.name)
        if p:
            t.part, t.how = p, "SATB voice name"
            continue
        raise SystemExit(f"render_orchestra: cannot identify track '{t.name}' (see CONTRACT.md section 2)")


def ensure_cc1(t: Track) -> bool:
    if 1 in t.cc:
        return False
    lv = sorted(VEL_AT.items())
    ev = []
    for n in t.notes:
        L = float(np.interp(n.vel, [x[1] for x in lv], [x[0] for x in lv]))
        ev.append((max(0.0, n.on - 0.01), level_to_cc1(L)))
    t.cc[1] = ev
    return True


def fit_compass(t: Track, strict: bool):
    lo, hi = PARTS[t.part]["lo"], PARTS[t.part]["hi"]
    for n in t.notes:
        k0 = n.key
        while n.key < lo:
            n.key += 12
        while n.key > hi:
            n.key -= 12
        if n.key != k0:
            if strict:
                raise SystemExit(f"render_orchestra: {t.name}: note {k0} at {n.on:.2f}s outside {t.part} "
                                 f"compass {lo}-{hi} (--strict-range)")
            t.shifted.append((round(n.on, 3), k0, n.key))


# ------------------------------------------------------------ articulation
def articulate(t: Track, short_s: float) -> dict:
    fam = PARTS[t.part]["family"]
    if t.part == "timp":
        cnt = {"stroke": 0, "roll": 0}
        for i, n in enumerate(t.notes):
            dur = n.off - n.on
            if 20 in t.cc:
                roll = cc_value_at(t.cc[20], n.on + 1e-6, 0) >= 64
            else:
                roll = dur >= 0.9
            n.art = 100 if roll else 0
            n.pre = 0.0
            nxt = t.notes[i + 1] if i + 1 < len(t.notes) else None
            if 21 in t.cc:
                n.rel = cc_value_at(t.cc[21], n.on + 1e-6, 30)
            else:
                n.rel = rel_cc(0.45 if roll else 0.35)
            if nxt is not None and nxt.key == n.key and not roll:
                n.off = min(n.off, nxt.on)                    # same drum struck again
            cnt["roll" if roll else "stroke"] += 1
        return cnt
    counts = shape_articulation(t.notes, short_s, 0.005, art_events=t.cc.get(20), rel_events=t.cc.get(21),
                                legato_pre=0.025, normal_pre=0.015 if fam == "strings" else 0.008)
    if fam in ("winds", "brass") and 21 not in t.cc:
        cap = rel_cc(0.32)                  # a wind player stops the breath: shorter than a bow
        for n in t.notes:
            n.rel = min(n.rel, cap)
    return counts


def players_of(t: Track, side: dict) -> list[int]:
    default = {"solo": 1, "a2": 2, "a4": 4}.get(side.get("tracks", {}).get(t.name, {}).get("players", "solo"), 1)
    out = []
    for n in t.notes:
        if 16 in t.cc:
            v = cc_value_at(t.cc[16], n.on + 1e-6, -1)
            k = default if v < 0 else (1 if v <= 42 else 2 if v <= 84 else 4)
        else:
            k = default
        if k == 4 and t.part != "hn":
            k = 2
        out.append(k)
    return out


# ------------------------------------------------------------ jobs
@dataclass
class Job:
    track: Track
    setname: str
    notes: list
    gain_db: float = 0.0
    detune: float = 0.0
    delay: float = 0.0
    jitter_ms: float = 0.0
    az_off: float = 0.0
    depth_off: float = 0.0
    label: str = ""
    seed: int = 0


def make_jobs(t: Track, side: dict, log: list, ti: int = 0) -> list[Job]:
    """ti: the track's index among the tracks of its part (0 = the first)."""
    part = t.part
    jobs = []
    t_az, t_depth = TRACK_SEAT[ti % len(TRACK_SEAT)]
    t_det = TRACK_DETUNE[ti % len(TRACK_DETUNE)]
    t_jit = TRACK_JITTER_MS if ti else 0.0
    if part in STACK:
        stack = [(s, g, d) for s, g, d in STACK[part] if set_available(part, s)]
        if not stack:
            raise SystemExit(f"render_orchestra: no built instrument for {part}: run setup_orchestra.sh")
        cov = {s: coverage(part, s) for s, _, _ in stack}
        main_sets = [s for s, g, _ in stack if g is not None]
        # the stack's total (power sum) is the part's calibrated level: a note only
        # some recordings reach gets that total on those recordings
        total = 10 * math.log10(sum(10 ** (g / 10) for _, g, _ in stack if g is not None))
        groups: dict = {}
        for n in t.notes:
            who = tuple(s for s in main_sets if cov[s][0] <= n.key <= cov[s][1])
            if not who:
                who = tuple(s for s, g, _ in stack if g is None and cov[s][0] <= n.key <= cov[s][1])
            if not who:                  # beyond every recording: the nearest one stretches (SFZ covers the compass)
                who = (min((s for s, _, _ in stack),
                           key=lambda s: max(cov[s][0] - n.key, n.key - cov[s][1], 0)),)
            groups.setdefault(who, []).append(n)
        for who, notes in groups.items():
            full = set(who) == set(main_sets)
            sub = 10 * math.log10(sum(10 ** ((g if g is not None else total) / 10)
                                      for s, g, _ in stack if s in who))
            for i, (s, g, d) in enumerate(stack):
                if s not in who:
                    continue
                g0 = g if g is not None else total
                gain = g0 if full else g0 + (total - sub)
                jobs.append(Job(t, s, notes, gain_db=gain, detune=d + t_det, jitter_ms=t_jit,
                                az_off=(-2.0, 2.0)[i % 2] + t_az, depth_off=0.3 * i + t_depth,
                                label=f"{t.name}/{s}" + ("" if full else "+"), seed=10 * ti + i))
        return jobs
    sets = [s for s in PLAYERS[part] if set_available(part, s)]
    if not sets:
        raise SystemExit(f"render_orchestra: no built instrument for {part}: run setup_orchestra.sh")
    np_ = players_of(t, side)
    maxp = max(np_)
    # solo recordings in player order, starting at this track's index (hn.2's player 1
    # is the recording hn.1's player 2 uses); a section recording (the four-horn
    # section) stays player 3 and stands for horns 3 and 4 together
    solo = [s for s in sets if (part, s) not in SECTION_SETS]
    section = [s for s in sets if (part, s) in SECTION_SETS]
    order = solo[ti % len(solo):] + solo[:ti % len(solo)] if solo else section
    for p in range(maxp):
        notes = [n for n, k in zip(t.notes, np_) if k > p]
        if not notes:
            continue
        if section and p >= 2:
            if p >= 3:
                continue                          # the section recording already covers horns 3 and 4
            s, gain = section[0], -2.0
        else:
            s, gain = order[p % len(order)], 0.0
        first = order[0]
        det = (PLAYER_DETUNE[p] if s == first and p else 0.0) + t_det
        jit = 8.0 if p else t_jit
        az_o, dp_o = PLAYER_SEAT[p][0] + t_az, PLAYER_SEAT[p][1] + t_depth
        lo, hi = coverage(part, s)
        inside = [n for n in notes if lo <= n.key <= hi]
        outside = [n for n in notes if not lo <= n.key <= hi]
        if outside:                                  # this recording does not reach: player 1's does
            jobs.append(Job(t, first, outside, gain_db=gain, detune=PLAYER_DETUNE[p] + t_det, delay=PLAYER_DELAY[p],
                            jitter_ms=jit, az_off=az_o, depth_off=dp_o,
                            label=f"{t.name}/p{p + 1}/{first}", seed=10 * ti + p))
        if inside:
            jobs.append(Job(t, s, inside, gain_db=gain, detune=det, delay=PLAYER_DELAY[p], jitter_ms=jit,
                            az_off=az_o, depth_off=dp_o, label=f"{t.name}/p{p + 1}/{s}", seed=10 * ti + p))
    return jobs


# ------------------------------------------------------------ layer plan
def cc_grid(events, t_end: float, default: int = 88):
    pts = cc1_curve(events, t_end) or [(0.0, default)]
    n = int(t_end / GRID) + 2
    T = np.arange(n) * GRID
    pt = np.array([p[0] for p in pts])
    pv = np.array([p[1] for p in pts], dtype=float)
    idx = np.clip(np.searchsorted(pt, T + 1e-9, side="right") - 1, 0, len(pv) - 1)
    return T, pv[idx]


def layer_plan(T: np.ndarray, c: np.ndarray, note_ons, anchors: list[int], home: list, snap: float = 0.35,
               xf_on: float = 0.05, xf_held: float = 0.3) -> np.ndarray:
    """The CC value sfizz receives for one articulation's layer crossfade: held
    inside the playing layer's home range; layer changes (hysteresis +-2 around
    the midpoint of two anchors) happen at the nearest note-on within +-snap
    (xf_on seconds) or else over xf_held seconds (a swell inside a held note).
    Generalises render_quartet.layer_plan to any number of layers."""
    nl = len(anchors)
    if nl == 1:
        return np.full(len(T), float(anchors[0]))
    mids = [(anchors[i] + anchors[i + 1]) / 2 for i in range(nl - 1)]

    def nearest(v):
        return int(sum(v >= m for m in mids))
    state = nearest(c[0])
    switches = []
    for i in range(1, len(T)):
        new = state
        while new < nl - 1 and c[i] >= mids[new] + 2:
            new += 1
        while new > 0 and c[i] <= mids[new - 1] - 2:
            new -= 1
        if new != state:
            switches.append((T[i], state, new))
            state = new
    ons = np.array(sorted(note_ons)) if len(note_ons) else np.zeros(0)
    wins = []
    last_end = -1.0
    for ts, fr, to in switches:
        near = ons[np.abs(ons - ts) <= snap] if len(ons) else ons
        if len(near):
            tn = float(near[np.argmin(np.abs(near - ts))])
            a, b = tn - 0.005, tn - 0.005 + xf_on
        else:
            a, b = ts - xf_held / 2, ts + xf_held / 2
        if a < last_end:
            a, b = last_end, last_end + (b - a)
        wins.append((max(0.0, a), max(0.0, b), fr, to))
        last_end = b
    layer_at = np.full(len(T), nearest(c[0]))
    for a, b, fr, to in wins:
        layer_at[T >= b] = to
    lo = np.array([home[k][0] for k in layer_at], dtype=float)
    hi = np.array([home[k][1] for k in layer_at], dtype=float)
    out = np.clip(c, lo, hi)
    for a, b, fr, to in wins:
        m = (T >= a) & (T < b)
        if not m.any():
            continue
        va = float(np.clip(c[m][0], *home[fr]))
        vb = float(np.clip(c[m][-1], *home[to]))
        out[m] = va + (vb - va) * (T[m] - a) / max(1e-9, b - a)
    return np.round(out)


def sec2tick(t: float) -> int:
    return int(round(max(0.0, t) * TPB_OUT * 1e6 / TEMPO_OUT))


def job_midi(job: Job, T: np.ndarray, c_true: np.ndarray, t_end: float) -> tuple[mido.MidiFile, dict]:
    layers = json.loads((BUILT / job.track.part / f"{job.setname}.layers.json").read_text())
    rng = random.Random(1000 * job.seed + job.track.index)
    ev = []
    stats = {}
    # articulation of each note -> which recorded articulation plays it
    for art, spec in layers.items():
        ons = [n.on for n in job.notes if art_of(n, layers) == art]
        c_sfz = layer_plan(T, c_true, ons, spec["anchors"], spec["home"])
        cc = spec["cc"]
        keep = np.concatenate([[True], np.diff(c_sfz) != 0])
        ev.append((0, 0, mido.Message("control_change", control=cc, value=int(c_sfz[0]))))
        for t, v in zip(T[keep], c_sfz[keep]):
            ev.append((sec2tick(t + SHIFT), 1, mido.Message("control_change", control=cc, value=int(v))))
        lay_idx = [int(np.searchsorted([(a + b) / 2 for a, b in zip(spec["anchors"], spec["anchors"][1:])], v))
                   for v in c_sfz[keep]]
        stats[art] = dict(switches=int(sum(1 for x, y in zip(lay_idx, lay_idx[1:]) if x != y)), notes=len(ons))
    keep = np.concatenate([[True], np.abs(np.diff(c_true)) >= 1])
    for t, v in zip(T[keep], c_true[keep]):
        ev.append((sec2tick(t + SHIFT), 1, mido.Message("control_change", control=2, value=int(v))))
    if job.detune:
        ev.append((0, 0, mido.Message("pitchwheel", pitch=int(np.clip(8192 * job.detune / 200, -8192, 8191)))))
    timed = []
    for n in job.notes:
        d = job.delay + (rng.uniform(0, job.jitter_ms) / 1000 if job.jitter_ms else 0.0)
        # measured onset latency of this recording (tune_orchestra.py), except for a
        # slurred note (it already enters in the sustain, render_quartet's timing)
        spec = layers[art_of(n, layers)]
        lat_ms = spec.get("latency_ms") or 0.0
        if (n.art or 0) >= 96 and spec.get("latency_short_ms") is not None:
            lat_ms = spec["latency_short_ms"]              # a short note cut from the sustain speaks sooner
        art = n.art or 0
        if 64 <= art < 96 or (job.track.part in NO_SUS_LATENCY and art < 96):
            lat = 0.0
        else:
            lat = min(0.10, max(0.0, lat_ms / 1000 - 0.012))
            if job.track.part in HALF_SUS_LATENCY and art < 96:
                lat *= 0.5
        ton = sec2tick(n.on - n.pre - lat + d + SHIFT)
        toff = max(sec2tick(n.off + d + SHIFT), ton + 1)
        timed.append([ton, toff, n])
    # a note-off of a key releases every voice of that key in sfizz: a repeated
    # note whose (pre-rolled) note-on comes before the previous note-off of the
    # same key would be killed, so that previous note-off moves to just before it
    last_of_key: dict = {}
    for item in sorted(timed, key=lambda z: z[0]):
        k = item[2].key
        if k in last_of_key and last_of_key[k][1] >= item[0]:
            prev = last_of_key[k]
            prev[1] = max(prev[0] + 1, item[0] - 1)
        last_of_key[k] = item
    for ton, toff, n in timed:
        ev.append((ton, 2, mido.Message("control_change", control=20, value=int(n.art or 0))))
        ev.append((ton, 2, mido.Message("control_change", control=21, value=int(n.rel if n.rel is not None else 30))))
        ev.append((ton, 4, mido.Message("note_on", note=int(n.key), velocity=int(np.clip(n.vel, 1, 127)))))
        ev.append((toff, 3, mido.Message("note_off", note=int(n.key), velocity=0)))
    ev.sort(key=lambda e: (e[0], e[1]))
    mid = mido.MidiFile(type=0, ticks_per_beat=TPB_OUT)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("set_tempo", tempo=TEMPO_OUT))
    last = 0
    for tick, _, msg in ev:
        tr.append(msg.copy(time=tick - last))
        last = tick
    tr.append(mido.MetaMessage("end_of_track", time=sec2tick(3.0)))
    mid.tracks.append(tr)
    return mid, stats


def art_of(n: Note, layers: dict) -> str:
    a = n.art or 0
    if "hit" in layers or "roll" in layers:
        return "roll" if a >= 64 and "roll" in layers else "hit"
    if a >= 96 and "stac" in layers:
        return "stac"
    return "sus"


def run_sfizz(sfz: Path, midi_path: Path, wav: Path) -> np.ndarray:
    cmd = [str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(midi_path), "--wav", str(wav),
           "-s", str(SR), "-p", "256", "-q", "3"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not wav.exists():
        raise RuntimeError(f"sfizz_render failed for {midi_path.name}: {r.stdout}\n{r.stderr}")
    x, fs = sf.read(str(wav), dtype="float32", always_2d=True)
    assert fs == SR
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return x


# ------------------------------------------------------------ gains, stage
def smooth(x: np.ndarray, w: int) -> np.ndarray:
    if w <= 1:
        return x
    k = np.ones(w) / w
    return np.convolve(np.concatenate([np.full(w, x[0]), x, np.full(w, x[-1])]), k, mode="same")[w:-w]


def gain_curve(job: Job, T: np.ndarray, c_true: np.ndarray, n: int, side: dict) -> np.ndarray:
    """Linear gain per output sample (render time = MIDI time + SHIFT)."""
    t = job.track
    L = cc1_to_level(c_true)
    db = np.array([balance_db(t.part, x) for x in L]) + MASTER_DB + job.gain_db
    db += float(side.get("tracks", {}).get(t.name, {}).get("gain_db", 0.0))
    for num, f in ((11, lambda v: 0.5 * 20 * math.log10(max(v, 1) / 127)),
                   (7, lambda v: 40 * math.log10(max(v, 1) / 127))):
        if num in t.cc:
            Tn, v = cc_grid(t.cc[num], T[-1], 127)
            v = np.interp(T, Tn, v)
            db += np.array([f(x) for x in v])
    db = smooth(db, int(0.02 / GRID))
    ts = np.arange(n) / SR - SHIFT - job.delay
    return (10 ** (np.interp(ts, T, db) / 20)).astype(np.float32)


def seat(part: str, seating: str, side_tr: dict) -> tuple[float, float, float]:
    p = dict(PARTS[part])
    if seating == "german" and part in GERMAN:
        p.update(GERMAN[part])
    az = p["az"] if "pan" not in side_tr else -45.0 * float(side_tr["pan"])
    return az, float(side_tr.get("depth_m", p["depth"])), float(side_tr.get("width", p["width"]))


_AIR = butter(1, 5000, btype="highpass", fs=SR, output="sos")


def place(y: np.ndarray, az: float, depth: float, width: float) -> np.ndarray:
    """Direct sound on stage: constant-power pan, own width, delay, distance loss, air."""
    m = y.mean(axis=1)
    s = 0.5 * (y[:, 0] - y[:, 1]) * width
    p = float(np.clip(-az / 45.0, -1, 1))
    th = (p + 1) * np.pi / 4
    out = np.stack([m * np.cos(th) + s, m * np.sin(th) - s], axis=1) * np.sqrt(2) * 0.7071
    g = R0 / (R0 + depth)
    air = 1 - 10 ** (-0.25 * depth / 20)                  # -0.25 dB/m above ~5 kHz
    if air > 0:
        out = out - air * sosfilt(_AIR, out, axis=0)
    d = int(round(depth / 343.0 * SR))
    out = np.concatenate([np.zeros((d, 2), np.float32), out[: len(out) - d]]) * g
    return out.astype(np.float32)


# ------------------------------------------------------------ output
def stem_name(track: str) -> str:
    """CONTRACT section 1: the stem file of a track is <name>.wav with every character
    that is not a letter, digit, '.', '_' or '-' replaced by '_' ('fl:oct' -> fl_oct.wav)."""
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in track)


def export(y: np.ndarray, out: Path, peak_db: float | None):
    tp = true_peak(y)
    g = (10 ** (peak_db / 20) / tp) if peak_db is not None else 1.0
    y = y * g
    wav, m4a = out.with_suffix(".wav"), out.with_suffix(".m4a")
    wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(wav), y.astype(np.float32), SR, subtype="PCM_24")
    if m4a.exists():
        m4a.unlink()
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "256000", str(wav), str(m4a)], check=True)
    return wav, m4a, 20 * math.log10(g), 20 * math.log10(true_peak(y))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("midi", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--stems", action="store_true")
    ap.add_argument("--no-reverb", action="store_true")
    ap.add_argument("--wet", type=float, default=None)
    ap.add_argument("--lead-in", type=float, default=0.3)
    ap.add_argument("--keep-start", action="store_true")
    ap.add_argument("--sidecar", type=Path)
    ap.add_argument("--seating", choices=["american", "german"])
    ap.add_argument("--peak", type=float, default=-1.0)
    ap.add_argument("--no-normalize", action="store_true")
    ap.add_argument("--short-ms", type=float, default=260.0)
    ap.add_argument("--strict-range", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--force-set", default="")
    a = ap.parse_args(argv)
    for spec in [x for x in a.force_set.split(",") if x]:
        p_, s_ = spec.split("=")
        PLAYERS[p_] = [s_]
        if p_ in STACK:
            STACK[p_] = [(s_, 0.0, 0.0)]
            _COVER[(p_, s_)] = (0, 127)          # testing a set alone: it plays everything it maps
    out = a.out or a.midi.with_suffix("")
    side_p = a.sidecar or a.midi.with_name(a.midi.stem + ".orchestra.json")
    side = json.loads(side_p.read_text()) if side_p.exists() else {}
    seating = a.seating or side.get("seating", "american")
    wet_db = a.wet if a.wet is not None else float(side.get("hall", {}).get("wet_db", WET_DEFAULT))
    log: list = []

    tracks = read_tracks(a.midi, log)
    identify(tracks, side)
    only = {p for p in a.only.split(",") if p}
    if only:
        tracks = [t for t in tracks if t.part in only]
    if not tracks:
        raise SystemExit("render_orchestra: no notes to render")
    t_end = max(n.off for t in tracks for n in t.notes) + 1.0
    arts = {}
    for t in tracks:
        if ensure_cc1(t):
            log.append(f"{t.name}: no CC1, dynamic level taken from the velocities")
        fit_compass(t, a.strict_range)
        arts[t.name] = articulate(t, a.short_ms / 1000)
        winds_chord = PARTS[t.part]["family"] in ("winds", "brass") and any(
            abs(x.on - y.on) < 0.02 for x, y in zip(t.notes, t.notes[1:]))
        if winds_chord:
            log.append(f"warning: {t.name}: chords on a {t.part} track (rendered, but one player plays one note)")
    seen: dict = {}
    jobs = []
    for t in tracks:                             # each track's index among the tracks of its part
        ti = seen.get(t.part, 0)
        seen[t.part] = ti + 1
        t.part_index = ti
        jobs += make_jobs(t, side, log, ti)
    grids = {t.name: cc_grid(t.cc.get(1, []), t_end + 1.0) for t in tracks}

    tmp = Path(tempfile.mkdtemp(prefix="orch_"))
    n_out = int((t_end + SHIFT + 4.5) * SR)
    dry = np.zeros((n_out, 2), np.float32)
    bus: dict = {}                               # hall input per IR side
    stems: dict = {}
    job_rep = []

    def render(ji: int):
        j = jobs[ji]
        T, c = grids[j.track.name]
        mid, stats = job_midi(j, T, c, t_end)
        mp = tmp / f"job{ji:03d}.mid"
        wp = tmp / f"job{ji:03d}.wav"
        mid.save(str(mp))
        x = run_sfizz(BUILT / j.track.part / f"{j.setname}.sfz", mp, wp)
        if not a.keep_temp:
            wp.unlink(missing_ok=True)
        return ji, x, stats

    with ThreadPoolExecutor(max(1, a.jobs)) as ex:
        futs = [ex.submit(render, i) for i in range(len(jobs))]
        for f in as_completed(futs):
            ji, x, stats = f.result()
            j = jobs[ji]
            T, c = grids[j.track.name]
            y = np.zeros((n_out, 2), np.float32)
            m = min(n_out, len(x))
            y[:m] = x[:m]
            if j.track.part in LOWPASS:
                y = sosfilt(butter(4, LOWPASS[j.track.part], btype="lowpass", fs=SR, output="sos"),
                            y, axis=0).astype(np.float32)
            y *= gain_curve(j, T, c, n_out, side)[:, None]
            az, depth, width = seat(j.track.part, seating, side.get("tracks", {}).get(j.track.name, {}))
            az += j.az_off
            depth += j.depth_off
            placed = place(y, az, depth, width)
            dry += placed
            if a.stems:
                stems.setdefault(j.track.name, np.zeros((n_out, 2), np.float32))
                stems[j.track.name] += placed
            if not a.no_reverb:
                d = int(round(depth / 343.0 * SR))
                key = "L" if az >= 0 else "R"
                bus.setdefault(key, np.zeros(n_out, np.float32))
                bus[key][d:] += y.mean(axis=1)[: n_out - d]
            act = np.abs(y.mean(axis=1)) > 1e-5
            job_rep.append(dict(label=j.label, part=j.track.part, set=j.setname, notes=len(j.notes),
                                gain_db=round(j.gain_db, 2), detune_c=j.detune, delay_ms=round(1000 * j.delay, 1),
                                seat_az=round(az, 1), seat_depth_m=round(depth, 2), layers=stats,
                                rms_db_active=round(10 * math.log10(float(np.mean(y.mean(axis=1)[act] ** 2)) + 1e-20), 2)
                                if act.any() else None))
    mix = dry
    c80 = None
    if not a.no_reverb:
        import hall                      # audio/strings/hall.py: Detmold IR, tail extended, unit energy
        h = hall.Hall("detmold", SR)
        g = 10 ** (wet_db / 20)
        from scipy.signal import fftconvolve
        wet = np.zeros_like(dry)
        for key, sig in bus.items():
            ir = h.ir if key == "L" else h.mirror
            for ch in range(2):
                wet[:, ch] += g * fftconvolve(sig, ir[:, ch])[:n_out].astype(np.float32)
        mix = dry + wet
        c80 = h.c80(g)
    # trim: lead-in before the first note-on, tail to -80 dB
    first_on = min(n.on for t in tracks for n in t.notes)
    sh = int(SHIFT * SR)
    first = sh if a.keep_start else max(0, int(round((first_on - a.lead_in) * SR)) + sh)
    env = np.max(np.abs(mix), axis=1)
    idx = np.flatnonzero(env > env.max() * 10 ** (-80 / 20))
    last = int(idx[-1]) if len(idx) else len(mix)
    mix = mix[first: min(len(mix), last + int(0.3 * SR))]
    fade = int(0.3 * SR)
    mix[-fade:] *= (np.linspace(1, 0, fade) ** 2)[:, None]
    wav, m4a, norm_db, tp = export(mix, out, None if a.no_normalize else a.peak)
    offset_s = (first - sh) / SR
    stem_names = {}
    if a.stems:
        sd = out.parent / (out.name + ".stems")
        sd.mkdir(parents=True, exist_ok=True)
        for name, y in stems.items():
            safe = stem_name(name)
            stem_names[safe] = name
            sf.write(str(sd / f"{safe}.wav"), y[first: first + len(mix)], SR, subtype="FLOAT")
    rep = dict(midi=str(a.midi), out=str(wav), duration_s=round(len(mix) / SR, 3), offset_s=round(offset_s, 4),
               lead_in_s=0.0 if a.keep_start else a.lead_in, norm_gain_db=round(norm_db, 3),
               true_peak_dbtp=round(tp, 2), hall=None if a.no_reverb else "detmold", wet_db=wet_db,
               c80_db=None if c80 is None else round(c80, 2), seating=seating, sidecar=str(side_p) if side else None,
               stems=stem_names or None,
               tracks=[dict(name=t.name, part=t.part, part_index=t.part_index, identified_by=t.how, notes=len(t.notes),
                            articulation=arts[t.name], octave_shifted=t.shifted,
                            note_list=[(round(n.on, 4), round(n.off, 4), n.key, n.vel, n.art) for n in t.notes])
                       for t in tracks],
               jobs=sorted(job_rep, key=lambda r: r["label"]), warnings=log)
    out.with_suffix(".json").write_text(json.dumps(rep, indent=1))
    print(f"{len(tracks)} tracks, {len(jobs)} jobs, {sum(len(t.notes) for t in tracks)} notes; "
          f"wet {wet_db:+.1f} dB" + (f" (C80 {c80:+.1f} dB)" if c80 is not None else " (dry)")
          + f"; true peak {tp:+.2f} dBTP -> {wav} ({len(mix) / SR:.1f} s)")
    for w in log:
        print("  " + w)
    if a.keep_temp:
        print("temp:", tmp)
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return rep


if __name__ == "__main__":
    main()
