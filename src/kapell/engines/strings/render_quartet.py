#!/usr/bin/env python3
"""Render a multi-voice MIDI file as a solo string quartet in a concert hall.

Engine: sfizz_render (float output) playing the University of Iowa MIS solo
strings (pp / mf / ff recorded layers, built into SFZ by iowa_build.py; the
second violin uses its own set taken from the next lower string).  Each
voice is rendered dry, placed on stage, convolved with a measured concert-hall
impulse response, mixed, normalised to a true peak of -1 dBFS and written as
48 kHz / 24-bit WAV plus 256 kb/s AAC (.m4a).

USAGE
  python3 render_quartet.py INPUT.mid [-o OUT_BASENAME] [options]

END TO END (the ricercar pipeline)
  python3 ../../tools/perform.py SCORE.ly PLAN.json OUT.mid --target strings
  python3 render_quartet.py OUT.mid -o out/piece

OPTIONS
  -o, --out PATH         output basename -> PATH.wav, PATH.m4a (default: next to INPUT)
  --lib iowa|vpo3        sample library (default iowa; vpo3 = Virtual Playing Orchestra 3
                         solo strings, kept for comparison, see README.md)
  --map SPEC             voice -> instrument, e.g. "soprano=vn1,alto=vn2,tenor=va,pedal=vc"
                         or by index "0=vn1,1=vn2".  Instruments: vn1 vn2 va vc cb
  --bass-double MODE     off (default) | on | auto: add a double bass an octave below the
                         cello.  auto fades it in only where the cello's dynamic level is
                         at or above --bass-threshold (tutti climaxes); a cello track may
                         also carry CC22 = doubling amount 0-127 (overrides auto)
  --bass-threshold LVL   dynamic level for auto doubling, ppp..fff or 1-8 (default ff)
  --hall NAME            detmold (default: Konzerthaus Detmold, measured, CC BY 4.0, same
                         hall as the piano renders, tail continued to 3.5 s) | synthetic | none
  --wet DB               the hall's energy relative to the dry sound, both summed over the
                         two channels, measured on the music being rendered (the reverb is
                         convolved at unit gain, measured, and scaled to this).  Default 0 dB,
                         the piano renderer's --wet-db default: C80 +4.6 dB on the
                         ricercar.  The report and the console give the hall re dry and C80
                         measured on the render
  --short-ms MS          notes shorter than this get the short (detache) stroke (default 260)
  --legato-pre-ms MS     a slurred note starts this early (default 25)
  --legato-xfade-ms MS   the note before a slur is held this long past the beat (default 5)
  --normal-pre-ms MS     a new-bow stroke starts this early (default 15)
  --cc11-depth X         CC11 gain = X * 20*log10(v/127) dB (default 0.5, see below)
  --lead-in S            silence before the first note-on (default 0.3 s, like the piano)
  --keep-start           output starts at MIDI time 0 instead (for measurements; a note that
                         starts early at time 0 loses those milliseconds)
  --stems                also write dry per-instrument stems (float WAV, same start as the mix)
  --report PATH.json     write a JSON render report (voices, articulations, layer switches,
                         levels; offset_s = MIDI time of the output's first sample)
  --peak DB              true-peak target (default -1.0 dBFS)
  QUARTET_SHORT_REL      environment variable: release (s) of a short note into the next
                         one (default 0.09)

VOICE MAPPING (first rule that applies)
  --map (exact voice name, else whole-word match, or track index); perform.py /
  SATB names (soprano -> Violin I, alto -> Violin II, tenor -> Viola, bass or
  pedal -> Cello); instrument names, whole words ("Violin II" is never Violin I);
  GM program family (40 violin, 41 viola, 42 cello, 43 contrabass) if that
  instrument is free; else a free instrument whose compass holds the voice's
  median pitch.  An instrument is never taken twice while one is free; with more
  voices than instruments a second desk of the best-fitting instrument plays
  (seated beside the first, logged).
  Notes below an instrument's compass are rescued the way an arranger would:
  dropped if another voice doubles them in unison, else the whole connected
  phrase is handed to a lower instrument that is resting at that moment (the
  old fugue's tenor dips to F2 while the pedal rests: the cello takes it),
  else transposed up an octave (reported).

MIDI CONVENTIONS (what perform.py --target strings writes)
  * One track per voice.  Velocity = accent / attack bite (127 = the recorded
    bite, low = softer, slower start, 15-41 ms; about +-2 dB).
  * CC1 = dynamic level with real timbre change, perform.py's scale:
    ppp 36, pp 49, p 62, mp 75, mf 88, f 101, ff 114, fff 127.  The pp
    recording plays up to 65, mf from 72 to 104, ff from 111 (two takes of one
    note sounding together interfere, so they only overlap in the narrow zones
    between); a volume curve moves loudness about 3.5 dB per step and a high
    shelf brightens with CC1 inside each layer.  This renderer never parks in a
    zone: it holds CC1 inside the current layer's range, switches layers with
    hysteresis (up at 70 / 109, down at 66 / 106) at the nearest note-on
    (50 ms) or, inside a held note, over 0.3 s, and restores the true CC1's
    loudness as a gain.  Linear ramps between CC events are reconstructed
    (perform.py samples every 16th note).
  * CC11 = expression gain without timbre change, X*20*log10(v/127) dB with
    X = --cc11-depth (0.5 default).  perform.py sends CC11 = CC1, so the full
    GM curve would double-count the dynamics: pp -> ff would span ~32 dB.
    With 0.5 the pp -> ff span is ~20 dB, like a real quartet in a hall.
  * CC7 = channel volume, GM curve 40*log10(v/127) dB.  CC10 pan is ignored
    (fixed stage positions).  CC64 is ignored.
  * No CC1 at all (e.g. a --target piano file): the dynamic level is taken from
    note velocities on perform.py's velocity scale.
  * Optional CC20 articulation per note (value in force at the note-on):
    0-63 normal bow stroke, 64-95 slurred, 96-127 short.  If absent it is
    inferred: a note that starts within 60 ms of the previous note's end, on a
    different pitch, and is not short, is slurred; notes shorter than
    --short-ms get the short stroke; everything else is a new bow.
  * Timing: a slurred note starts --legato-pre-ms early and fades in over
    30 ms; the note before it is held --legato-xfade-ms past the beat and
    released over 0.12 s, so the new pitch takes over about 10 ms after the
    beat.  A new-bow stroke starts --normal-pre-ms early; short strokes start
    on the beat (8 ms attack).
  * Optional CC21 release per note (value in force at the note-on): 0.03 +
    1.2*v/127 s (sfizz's release is exponential, -78 dB at that time).  If
    absent: 0.12 s into a slur, 0.09 s from a short note into the next, 0.22 s
    between other detached notes, 0.5-1.1 s before a rest.  A long note
    followed directly by a short one (dotted figures, the start of a run)
    lifts 25 ms early so the short note speaks.  A repeated key (perform.py
    lifts 60 ms early) is held, or cut back, to 12 ms before the new stroke's
    early start and released over 0.18 s: a dip of about 15 dB, not a hole.
  * A note-on without a note-off is closed at the end of its track (logged).
  * Tempo map honoured (all timing is converted to seconds before rendering).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import mido
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, resample_poly

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from iowa_common import QUARTET_DIR, SFIZZ_RENDER  # noqa: E402
from iowa_build import CC1_TARGET, LAYER_DOWN, LAYER_HOME, LAYER_UP  # noqa: E402
import hall  # noqa: E402

SR = 48000
LEVELS = {"ppp": 1, "pp": 2, "p": 3, "mp": 4, "mf": 5, "f": 6, "ff": 7, "fff": 8}
VEL_AT = {1: 22, 2: 32, 3: 44, 4: 56, 5: 68, 6: 82, 7: 98, 8: 112}      # perform.py velocity scale


def level_to_cc1(L: float) -> int:
    return int(np.clip(round(36 + 13 * (L - 1)), 0, 127))


# id: sfz, display name, stage azimuth (deg, + = left), depth (m), trim (dB), compass lo/hi
INSTR = {
    "vn1": dict(sfz="violin.sfz", name="Violin I", az=30.0, depth=0.0, trim=0.5, lo=55, hi=100),
    "vn2": dict(sfz="violin2.sfz", name="Violin II", az=10.0, depth=0.4, trim=-0.5, lo=55, hi=100),
    "va": dict(sfz="viola.sfz", name="Viola", az=-10.0, depth=0.4, trim=0.0, lo=48, hi=91),
    "vc": dict(sfz="cello.sfz", name="Cello", az=-28.0, depth=0.0, trim=0.0, lo=36, hi=81),
    "cb": dict(sfz="bass.sfz", name="Contrabass", az=-36.0, depth=1.2, trim=0.0, lo=24, hi=67),
}
ORDER = ["vn1", "vn2", "va", "vc", "cb"]
EXT_DOWN = 2            # the SFZ stretches the lowest sample this many semitones down
SATB = {"soprano": "vn1", "descant": "vn1", "alto": "vn2", "mezzo": "vn2", "tenor": "va",
        "baritone": "va", "bass": "vc", "pedal": "vc"}
NAME_KEYS = [
    ("vn1", ["violin 1", "violin i", "vln 1", "vln. 1", "vn1", "vn 1", "violino i", "violin1", "1st violin",
             "first violin"]),
    ("vn2", ["violin 2", "violin ii", "vln 2", "vln. 2", "vn2", "vn 2", "violino ii", "violin2", "2nd violin",
             "second violin"]),
    ("va", ["viola", "vla", "alto viol"]),
    ("vc", ["violoncello", "cello", "vlc", "vc"]),
    ("cb", ["contrabass", "double bass", "doublebass", "kontrabass", "contrabasso", "cb"]),
]
PROGRAM = {40: "vn", 41: "va", 42: "vc", 43: "cb"}


@dataclass
class Note:
    on: float
    off: float
    key: int
    vel: int
    art: int | None = None      # CC20 value
    rel: int | None = None      # CC21 value
    pre: float = 0.0            # the sfizz note-on runs this far ahead of `on` (s)


@dataclass
class Voice:
    name: str
    track: int
    channel: int
    notes: list = field(default_factory=list)
    cc: dict = field(default_factory=dict)       # num -> [(t, v)]
    bend: list = field(default_factory=list)     # [(t, value -8192..8191)]
    program: int | None = None
    inst: str | None = None
    desk: int = 0                                # >0: an extra desk of an instrument already in use

    @property
    def mean_pitch(self):
        return float(np.mean([n.key for n in self.notes])) if self.notes else 0.0


@dataclass
class Job:
    voice: Voice              # CC / bend source
    notes: list               # the notes this job plays
    inst: str                 # instrument id (stage position, trim)
    kind: str = "main"        # main | borrowed | double
    label: str = ""
    plan: tuple | None = None  # layer_plan() result (Iowa only)
    desk: int = 0


# ------------------------------------------------------------------ MIDI in
def tempo_map(mid: mido.MidiFile):
    """-> function tick -> seconds (honours every set_tempo in any track)."""
    changes = []
    for tr in mid.tracks:
        t = 0
        for msg in tr:
            t += msg.time
            if msg.type == "set_tempo":
                changes.append((t, msg.tempo))
    changes.sort()
    if not changes or changes[0][0] != 0:
        changes.insert(0, (0, 500000))
    ticks = [c[0] for c in changes]
    secs = [0.0]
    for i in range(1, len(changes)):
        secs.append(secs[-1] + (changes[i][0] - changes[i - 1][0]) * changes[i - 1][1] / 1e6 / mid.ticks_per_beat)
    tpb = mid.ticks_per_beat

    def f(tick):
        i = max(0, int(np.searchsorted(ticks, tick, side="right")) - 1)
        return secs[i] + (tick - ticks[i]) * changes[i][1] / 1e6 / tpb
    return f


def midi_marker(mid: mido.MidiFile) -> dict:
    for tr in mid.tracks:
        for msg in tr:
            if msg.type == "text" and msg.text.startswith("perform.py"):
                info = {"source": "perform.py"}
                for tok in msg.text.split()[1:]:
                    if "=" in tok:
                        k, v = tok.split("=", 1)
                        info[k] = v
                return info
    return {}


def read_voices(path: Path, log: list | None = None):
    """-> (voices, perform.py marker).  Note-ons are paired with note-offs first
    in, first out per key; a note-on left without a note-off is closed at the end
    of its track (at least 1 s long) and reported in `log`."""
    mid = mido.MidiFile(str(path))
    t2s = tempo_map(mid)
    voices: dict[tuple[int, int], Voice] = {}
    for ti, tr in enumerate(mid.tracks):
        name = f"track{ti}"
        tick = 0
        pending: dict[tuple[int, int], list] = {}
        for msg in tr:
            tick += msg.time
            if msg.type == "track_name":
                name = msg.name.strip() or name
                for v in voices.values():
                    if v.track == ti:
                        v.name = name
            if not hasattr(msg, "channel"):
                continue
            key = (ti, msg.channel)
            if key not in voices:
                voices[key] = Voice(name=name, track=ti, channel=msg.channel)
            v = voices[key]
            t = t2s(tick)
            if msg.type == "note_on" and msg.velocity > 0:
                pending.setdefault((msg.channel, msg.note), []).append((t, msg.velocity))
            elif msg.type in ("note_off", "note_on"):
                lst = pending.get((msg.channel, msg.note))
                if lst:
                    on, vel = lst.pop(0)
                    if t > on:
                        v.notes.append(Note(on, t, msg.note, vel))
            elif msg.type == "control_change":
                v.cc.setdefault(msg.control, []).append((t, msg.value))
            elif msg.type == "pitchwheel":
                v.bend.append((t, msg.pitch))
            elif msg.type == "program_change":
                v.program = msg.program
        t_end = t2s(tick)
        for (ch, key), lst in pending.items():
            for on, vel in lst:
                off = max(t_end, on + 1.0)
                voices[(ti, ch)].notes.append(Note(on, off, key, vel))
                if log is not None:
                    log.append(f"{voices[(ti, ch)].name}: note {key} at {on:.2f}s has no note-off, "
                               f"closed at {off:.2f}s (end of track)")
    out = [v for v in voices.values() if v.notes]
    for v in out:
        v.notes.sort(key=lambda n: (n.on, -n.key))
        for c in v.cc.values():
            c.sort(key=lambda e: e[0])
    return out, midi_marker(mid)


def _name_hit(key: str, name: str) -> bool:
    """Whole-word match: 'violin i' matches 'Violin I' and '1. Violin I' but not 'Violin II'."""
    return re.search(r"(?<![\w])" + re.escape(key) + r"(?![\w])", name) is not None


def _name_inst(nm: str) -> str | None:
    nm = " ".join(nm.lower().replace("_", " ").split())
    for inst, keys in NAME_KEYS:                        # exact names first
        if nm in keys:
            return inst
    for inst, keys in NAME_KEYS:                        # vn2 is listed before vn1 would matter only for
        if any(_name_hit(k, nm) for k in keys):         # substrings; whole words make the order irrelevant
            return inst
    return None


def median_pitch(v: Voice) -> float:
    return float(np.median([n.key for n in v.notes])) if v.notes else 0.0


def assign(voices: list[Voice], spec: str | None, log: list | None = None):
    """Voice -> instrument (see VOICE MAPPING in the module docstring).  An
    instrument is never given to two voices while another one is free; with more
    voices than the five instruments a second desk of the best-fitting instrument
    is added (same sound, seated beside the first) and logged."""
    log = log if log is not None else []
    if spec:
        for item in spec.split(","):
            if not item.strip():
                continue
            if "=" not in item:
                sys.exit(f"--map: expected voice=instrument, got {item.strip()!r} "
                         f"(e.g. soprano=vn1 or 0=vn1; instruments: {' '.join(INSTR)})")
            k, inst = (x.strip() for x in item.split("=", 1))
            if inst not in INSTR:
                sys.exit(f"--map: unknown instrument {inst!r} (use {' '.join(INSTR)})")
            exact = [v for v in voices if v.name.lower().strip() == k.lower()]
            for i, v in enumerate(voices):
                if (k.isdigit() and int(k) == i) or (not k.isdigit() and (
                        v in exact or (not exact and _name_hit(k.lower(), v.name.lower())))):
                    v.inst = inst
    taken = {v.inst for v in voices if v.inst}
    for v in voices:                                    # SATB / perform.py voice names
        nm = v.name.lower().strip()
        if not v.inst and nm in SATB and SATB[nm] not in taken:
            v.inst = SATB[nm]
            taken.add(v.inst)
    for v in voices:                                    # instrument names
        if v.inst:
            continue
        inst = _name_inst(v.name)
        if inst is not None and inst not in taken:
            v.inst = inst
            taken.add(inst)
    rest = sorted([v for v in voices if not v.inst], key=lambda v: -v.mean_pitch)

    def fam_of(v):
        return PROGRAM.get(v.program if v.program is not None else -1)

    def fits(inst, v):                                  # compass contains the voice's median pitch
        return INSTR[inst]["lo"] - EXT_DOWN <= median_pitch(v) <= INSTR[inst]["hi"]

    def centre_dist(inst, v):
        return abs(0.5 * (INSTR[inst]["lo"] + INSTR[inst]["hi"]) - median_pitch(v))
    for v in rest:                                      # 1. a free instrument of the voice's GM family
        fam = fam_of(v)
        c = [o for o in ORDER if o not in taken and fam is not None and o.startswith(fam)]
        if c:
            v.inst = c[0]
            taken.add(v.inst)
    for v in rest:                                      # 2. a free instrument whose compass fits
        if v.inst:
            continue
        free = [o for o in ORDER if o not in taken]
        c = sorted([o for o in free if fits(o, v)], key=lambda o: centre_dist(o, v)) or \
            sorted(free, key=lambda o: centre_dist(o, v))
        if c:
            v.inst = c[0]
            taken.add(v.inst)
            if fam_of(v) is not None and not v.inst.startswith(fam_of(v)):
                log.append(f"{v.name}: its GM family is already taken, plays the free "
                           f"{INSTR[v.inst]['name']} (median pitch {median_pitch(v):.0f})")
    for v in rest:                                      # 3. more voices than instruments: second desk
        if v.inst:
            continue
        fam = fam_of(v)
        c = [o for o in ORDER if fam is not None and o.startswith(fam) and fits(o, v)] or \
            sorted([o for o in ORDER if fits(o, v)], key=lambda o: centre_dist(o, v)) or \
            sorted(ORDER, key=lambda o: centre_dist(o, v))
        v.inst = c[0]
        v.desk = sum(1 for w in voices if w is not v and w.inst == v.inst)
        log.append(f"{v.name}: more voices than instruments, a second {INSTR[v.inst]['name']} desk "
                   f"plays it (median pitch {median_pitch(v):.0f})")
    return voices


# ------------------------------------------------------------ dynamics (CC1)
def ensure_cc1(v: Voice):
    """Files without CC1 (e.g. perform.py --target piano): derive the dynamic
    level from note velocities on perform.py's velocity scale."""
    if 1 in v.cc:
        return False
    lv = sorted(VEL_AT.items())
    vs = [x[1] for x in lv]
    ls = [x[0] for x in lv]
    ev = []
    for n in v.notes:
        L = float(np.interp(n.vel, vs, ls))
        ev.append((max(0.0, n.on - 0.01), level_to_cc1(L)))
    v.cc[1] = ev
    return True


def cc1_curve(events, t_end: float, step: float = 0.02, max_ramp: float = 0.6):
    """Reconstruct the continuous CC1 curve: perform.py samples a hairpin every
    16th note, so consecutive events closer than max_ramp are joined by linear
    ramps (each event is the value reached at its time); longer gaps hold the
    value and ramp over the last 60 ms.  Returns [(t, value)] at <= step spacing."""
    if not events:
        return []
    out = [(0.0, events[0][1])] if events[0][0] > 0 else []
    for (t0, v0), (t1, v1) in zip(events, events[1:]):
        out.append((t0, v0))
        if v1 == v0 or t1 <= t0:
            continue
        a = t0 if t1 - t0 <= max_ramp else max(t0, t1 - 0.06)
        n = max(1, int((t1 - a) / step))
        for i in range(1, n):
            x = a + (t1 - a) * i / n
            val = v0 + (v1 - v0) * i / n
            out.append((x, int(round(val))))
    out.append(events[-1])
    ded = []
    for t, val in out:
        if not ded or val != ded[-1][1]:
            ded.append((t, val))
    return ded


def cc_value_at(events, t: float, default: int) -> int:
    val = default
    for te, v in events or []:
        if te > t:
            break
        val = v
    return val


# ------------------------------------------------------ compass (range) rescue
def rescue_range(voices: list[Voice], jobs_out: list, log: list):
    """Notes below an instrument's compass: drop unison doublings, hand connected
    phrases to a resting lower instrument, else transpose up an octave."""
    by_inst: dict[str, list[Voice]] = {}
    for v in voices:
        by_inst.setdefault(v.inst, []).append(v)
    all_notes = [(v, n) for v in voices for n in v.notes]
    for v in voices:
        lo = INSTR[v.inst]["lo"] - EXT_DOWN
        low = [n for n in v.notes if n.key < lo]
        if not low:
            continue
        moved = set()
        for n in low:
            if id(n) in moved:
                continue
            twin = [m for (w, m) in all_notes if w is not v and m.key == n.key and m.on < n.off - 0.05
                    and m.off > n.on + 0.05]
            if twin:
                v.notes.remove(n)
                log.append(f"{v.name}: {n.key} at {n.on:.2f}s below {INSTR[v.inst]['name']} compass, "
                           f"doubled in unison by another voice -> dropped")
                continue
            # a lower instrument of the ensemble that is resting around this phrase
            lower = [i for i in ORDER[ORDER.index(v.inst) + 1:] if i in by_inst]
            done = False
            for li in lower:
                others = by_inst[li]
                if n.key < INSTR[li]["lo"] - EXT_DOWN:
                    continue

                def free(a, b, others=others):
                    # the lower player may still be finishing a note as the phrase begins (hand-off)
                    return not any(m.on < b + 0.15 and m.off > a + 0.04 for o in others for m in o.notes)
                if not free(n.on, n.off):
                    continue
                # grow the phrase through connected notes while the lower instrument rests
                i = v.notes.index(n)
                j0 = i
                while j0 > 0 and v.notes[j0].on - v.notes[j0 - 1].off < 0.35 and free(v.notes[j0 - 1].on,
                                                                                       v.notes[j0 - 1].off):
                    j0 -= 1
                j1 = i
                while j1 + 1 < len(v.notes) and v.notes[j1 + 1].on - v.notes[j1].off < 0.35 and \
                        free(v.notes[j1 + 1].on, v.notes[j1 + 1].off):
                    j1 += 1
                phrase = v.notes[j0: j1 + 1]
                if any(m.key > INSTR[li]["hi"] for m in phrase):
                    continue
                for m in phrase:
                    moved.add(id(m))
                    v.notes.remove(m)
                jobs_out.append(Job(voice=v, notes=phrase, inst=li, kind="borrowed",
                                    label=f"{v.name} on {INSTR[li]['name']}"))
                log.append(f"{v.name}: {len(phrase)} notes {phrase[0].on:.2f}-{phrase[-1].off:.2f}s "
                           f"(down to {min(m.key for m in phrase)}) handed to the resting {INSTR[li]['name']}")
                done = True
                break
            if not done:
                while n.key < lo:
                    n.key += 12
                log.append(f"{v.name}: note at {n.on:.2f}s below compass, no free lower instrument -> "
                           f"transposed up to {n.key}")


# ------------------------------------------------------- articulation logic
def rel_cc(seconds: float) -> int:
    return int(np.clip(round((seconds - 0.03) / 1.2 * 127), 0, 127))


SHORT_REL = float(os.environ.get("QUARTET_SHORT_REL", "0.09"))   # release of a short note into the next
NORMAL_PRE_MS = 15.0
WET_DEFAULT = 0.0     # hall energy = dry energy on this music, as render_piano.py's --wet-db 0


def shape_articulation(notes: list[Note], short_s: float, xfade_s: float, art_events=None, rel_events=None,
                       legato_pre: float = 0.025, normal_pre: float = 0.0):
    """Per note: articulation (CC20), release (CC21) and how far the sfizz
    note-on runs ahead of the musical note-on (Note.pre).

    CC20 / CC21 given in the MIDI (art_events / rel_events) are read per note at
    its note-on; otherwise they are inferred.  Timing rules (the numbers are the
    defaults; see the module docstring):
      * a slurred note starts legato_pre early (its 30 ms fade-in is centred on
        the beat) and the previous note is held xfade_s past the beat, so the new
        pitch takes over on the beat instead of 60-70 ms late;
      * a normal (new-bow) stroke starts normal_pre early;
      * a repeated key (gap under 80 ms) is held to 12 ms before the new stroke
        and released over 0.18 s: a re-articulation dip of about 15 dB rather
        than a hole of silence; a note-off that would come later (a same-key
        note meeting the next within 27 ms, or overlapping it) is moved to that
        point, because a note-off after the new note-on ends both notes;
      * a long note directly followed by a short one lifts 25 ms early."""
    counts = {"normal": 0, "legato": 0, "short": 0}
    for i, n in enumerate(notes):
        prev = notes[i - 1] if i else None
        dur = n.off - n.on
        chord_prev = prev is not None and abs(n.on - prev.on) < 0.03
        connected_in = (prev is not None and not chord_prev and n.on - prev.off < 0.06
                        and prev.key != n.key)
        if art_events:
            n.art = cc_value_at(art_events, n.on + 1e-6, 0)
        elif n.art is None:
            if dur < short_s:
                n.art = 112
            elif connected_in:
                n.art = 80
            else:
                n.art = 0
        if rel_events:
            n.rel = cc_value_at(rel_events, n.on + 1e-6, 30)
        counts["short" if n.art >= 96 else "legato" if n.art >= 64 else "normal"] += 1
        pre = legato_pre if 64 <= n.art < 96 else normal_pre if n.art < 64 else 0.0
        if prev is not None and not chord_prev:
            pre = min(pre, max(0.0, n.on - prev.on - 0.03))       # never before the previous note-on
        n.pre = pre
    for i, n in enumerate(notes):
        nxt = notes[i + 1] if i + 1 < len(notes) else None
        dur = n.off - n.on
        chord_next = nxt is not None and abs(nxt.on - n.on) < 0.03
        slur_out = nxt is not None and not chord_next and 64 <= (nxt.art or 0) < 96 and nxt.on - n.off < 0.06 \
            and nxt.key != n.key
        gap = (nxt.on - n.off) if nxt is not None and not chord_next else 99.0
        if slur_out:
            n.off = max(n.off, nxt.on + xfade_s)
            rel = 0.12
        elif gap < 0.08 and nxt.key == n.key:
            # repeated note: re-articulate with a dip, not a hole (perform.py lifts 60 ms early).
            # The note-off always lands before the new stroke's sfizz note-on (nxt.on - nxt.pre):
            # a same-key note-off after it ends the new note too (a hand-off onto the same key
            # 3 ms apart silenced a 2.2 s viola note)
            n.off = min(max(n.off, min(nxt.on - nxt.pre - 0.012, n.on + 0.9 * (nxt.on - n.on))),
                        nxt.on - nxt.pre - 0.012)
            rel = 0.18
        elif gap < 0.08 and dur >= short_s and (nxt.art or 0) >= 96:
            # into a detached short note (a dotted figure, a run): lift the bow a
            # moment early so the short note speaks instead of drowning in a release
            n.off = max(n.on + 0.6 * dur, min(n.off, nxt.on - 0.025))
            rel = SHORT_REL
        elif gap < 0.08:
            rel = SHORT_REL if dur < short_s else 0.22
        elif dur < short_s:
            rel = 0.25
        else:
            rel = float(np.clip(0.45 + 0.25 * dur, 0.5, 1.1))
        if not rel_events:
            n.rel = rel_cc(rel)
    return counts


# ------------------------------------------------------------- per job MIDI
TPB_OUT = 960
TEMPO_OUT = 500000                      # 120 bpm -> 1920 ticks per second


def sec2tick(t: float) -> int:
    return int(round(max(0.0, t) * TPB_OUT * 1e6 / TEMPO_OUT))


# ------------------------------------------------ dynamic layers (Iowa SFZ)
LAYERS = ("pp", "mf", "ff")
GRID = 0.005


def cc1_target_db(v):
    """Loudness (dB re the ff layer) the Iowa SFZ produces at CC1 = v."""
    return np.interp(v, [p[0] for p in CC1_TARGET], [p[1] for p in CC1_TARGET])


def _layer_of(c: float) -> str:
    return "pp" if c < 68 else "mf" if c < 107.5 else "ff"


def layer_plan(cc1_events, note_ons, t_end: float, snap: float = 0.35, xf_on: float = 0.05,
               xf_held: float = 0.3):
    """Keep sfizz out of the layer crossfade zones.

    Two recordings of one note sounding together interfere, so the Iowa SFZ only
    crossfades its pp / mf / ff layers in two narrow CC1 zones (iowa_build.XF).
    This decides which layer plays when (hysteresis LAYER_UP / LAYER_DOWN on the
    true CC1), holds the CC1 sent to sfizz inside that layer's home range, and
    crosses a zone quickly: in xf_on seconds starting at the nearest note-on within
    +-snap of the moment the level crosses over (the new note simply starts in the
    new layer), otherwise in xf_held seconds (a swell inside a held note).
    Returns (times, c_true, c_sfz) on a GRID-second grid; the loudness difference
    cc1_target_db(c_true) - cc1_target_db(c_sfz) is restored as a gain."""
    pts = cc1_curve(cc1_events, t_end) or [(0.0, 88)]
    n = int(t_end / GRID) + 2
    T = np.arange(n) * GRID
    pt = np.array([p[0] for p in pts])
    pv = np.array([p[1] for p in pts], dtype=float)
    idx = np.clip(np.searchsorted(pt, T + 1e-9, side="right") - 1, 0, len(pv) - 1)
    c = pv[idx]
    # 1. layer switches with hysteresis
    state = _layer_of(c[0])
    switches = []                                        # (time, from, to)
    for i in range(1, n):
        new = state
        if state == "pp" and c[i] >= LAYER_UP["pp"]:
            new = "ff" if c[i] >= LAYER_UP["mf"] else "mf"
        elif state == "mf" and c[i] >= LAYER_UP["mf"]:
            new = "ff"
        elif state == "mf" and c[i] <= LAYER_DOWN["mf"]:
            new = "pp"
        elif state == "ff" and c[i] <= LAYER_DOWN["ff"]:
            new = "pp" if c[i] <= LAYER_DOWN["mf"] else "mf"
        if new != state:
            switches.append((T[i], state, new))
            state = new
    # 2. when: at a nearby note-on, else a slow crossfade centred on the crossing
    ons = np.array(sorted(note_ons)) if len(note_ons) else np.zeros(0)
    wins = []                                            # (a, b, from, to)
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
    # 3. the CC1 sfizz receives
    def home(layer, v):
        lo, hi = LAYER_HOME[layer]
        return np.clip(v, lo, hi)
    layer_at = np.empty(n, dtype=object)
    layer_at[:] = _layer_of(c[0])
    for a, b, fr, to in wins:
        layer_at[T >= b] = to
    c_sfz = np.array([home(layer_at[i], c[i]) for i in range(n)], dtype=float)
    for a, b, fr, to in wins:
        m = (T >= a) & (T < b)
        if not m.any():
            continue
        ia, ib = int(np.flatnonzero(m)[0]), min(n - 1, int(np.flatnonzero(m)[-1]) + 1)
        va, vb = float(home(fr, c[ia])), float(home(to, c[ib]))
        c_sfz[m] = va + (vb - va) * (T[m] - a) / max(1e-9, b - a)
    return T, c, np.round(c_sfz)


def job_midi(job: Job, transpose: int = 0, shift: float = 0.0) -> mido.MidiFile:
    """One job (voice x instrument) as a MIDI file for sfizz_render: CC1 (the
    layer plan's c_sfz, or the reconstructed CC1 curve), per-note CC20 / CC21 just
    before each note-on, note-ons Note.pre early, pitch bend."""
    v = job.voice
    ev = []   # (tick, prio, msg)
    if job.plan is not None:
        T, _, c_sfz = job.plan
        keep = np.concatenate([[True], np.diff(c_sfz) != 0])
        cc1 = [(float(t), int(x)) for t, x in zip(T[keep], c_sfz[keep])]
    else:
        cc1 = cc1_curve(v.cc.get(1, []), max(n.off for n in job.notes) + 2.0)
    ev.append((0, 0, mido.Message("control_change", control=1, value=cc1[0][1] if cc1 else 88)))
    for t, val in cc1:
        ev.append((sec2tick(t + shift), 1, mido.Message("control_change", control=1, value=int(val))))
    for t, val in v.bend:
        ev.append((sec2tick(t + shift), 1, mido.Message("pitchwheel", pitch=val)))
    for n in job.notes:
        k = n.key + transpose
        if not 0 <= k <= 127:
            continue
        ton, toff = sec2tick(n.on - n.pre + shift), sec2tick(n.off + shift)
        if n.art is not None:
            ev.append((ton, 2, mido.Message("control_change", control=20, value=int(n.art))))
        if n.rel is not None:
            ev.append((ton, 2, mido.Message("control_change", control=21, value=int(n.rel))))
        ev.append((ton, 4, mido.Message("note_on", note=k, velocity=int(np.clip(n.vel, 1, 127)))))
        ev.append((max(toff, ton + 1), 3, mido.Message("note_off", note=k, velocity=0)))
    ev.sort(key=lambda e: (e[0], e[1]))
    mid = mido.MidiFile(type=0, ticks_per_beat=TPB_OUT)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("set_tempo", tempo=TEMPO_OUT))
    last = 0
    for tick, _, msg in ev:
        tr.append(msg.copy(time=tick - last))
        last = tick
    tr.append(mido.MetaMessage("end_of_track", time=TPB_OUT))
    mid.tracks.append(tr)
    return mid


def plan_gain(plan, n: int) -> np.ndarray:
    """Linear gain per sample restoring the loudness of the true CC1 where the layer
    plan holds sfizz's CC1 elsewhere (10 ms smoothing, like sfizz's CC smoothing)."""
    T, c, c_sfz = plan
    db = cc1_target_db(c) - cc1_target_db(c_sfz)
    x = np.interp(np.arange(n) / SR, T, db, right=db[-1])
    w = int(0.01 * SR)
    x = np.convolve(np.concatenate([np.full(w, x[0]), x, np.full(w, x[-1])]), np.ones(w) / w, mode="same")[w:-w]
    return 10 ** (x / 20)


def run_sfizz(sfz: Path, midi_path: Path, wav: Path):
    cmd = [str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(midi_path), "--wav", str(wav),
           "-s", str(SR), "-p", "256", "-q", "3"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not wav.exists():
        raise RuntimeError(f"sfizz_render failed for {midi_path.name}: {r.stdout}\n{r.stderr}")
    x, fs = sf.read(str(wav), dtype="float32", always_2d=True)
    assert fs == SR
    return x


# --------------------------------------------------------- CC gain envelopes
def gain_envelope(events, n: int, default: int, to_db, smooth_s: float = 0.03):
    """Piecewise-linear (between events <= 0.6 s apart) CC curve -> linear gain per sample."""
    pts = cc1_curve(sorted(events or []), n / SR)
    db = np.full(n, to_db(default), dtype=np.float64)
    for t, val in pts:
        i = int(t * SR)
        if i < n:
            db[i:] = to_db(val)
    w = max(1, int(smooth_s * SR))
    k = np.ones(w) / w
    db = np.convolve(np.concatenate([np.full(w, db[0]), db, np.full(w, db[-1])]), k, mode="same")[w:-w]
    return 10 ** (db / 20)


def bass_envelope(cello: Voice, n: int, mode: str, threshold_cc1: int):
    if mode == "off":
        return None
    if mode == "on":
        return np.ones(n)
    g = np.zeros(n)
    if 22 in cello.cc:                               # explicit doubling amount
        for t, val in sorted(cello.cc[22]):
            g[int(t * SR):] = val / 127.0
    else:
        lo = threshold_cc1 - 10
        for t, val in cc1_curve(cello.cc.get(1, []), n / SR):
            g[int(t * SR):] = np.clip((val - lo) / 10.0, 0, 1)
    w = int(0.6 * SR)                                # never pops in
    k = np.hanning(w)
    k /= k.sum()
    g = np.convolve(np.concatenate([np.full(w, g[0]), g, np.full(w, g[-1])]), k, mode="same")[w:-w]
    return g if g.max() > 1e-3 else None


# ------------------------------------------------------------------- output
def true_peak(x: np.ndarray) -> float:
    up = resample_poly(x, 4, 1, axis=0)
    return float(np.max(np.abs(up)))


def export(y: np.ndarray, out: Path, peak_db: float):
    tp = true_peak(y)
    y = y * (10 ** (peak_db / 20) / tp)
    wav = out.with_suffix(".wav")
    m4a = out.with_suffix(".m4a")
    wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(wav), y.astype(np.float32), SR, subtype="PCM_24")
    if m4a.exists():
        m4a.unlink()
    if shutil.which("afconvert"):
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "256000", str(wav), str(m4a)], check=True)
    else:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "256k",
                        str(m4a)], check=True)
    return wav, m4a, 20 * math.log10(tp), 20 * math.log10(true_peak(y))


# --------------------------------------------------------------------- main
def parse_level(s: str) -> float:
    return float(LEVELS.get(s, s))


def sfz_for(lib: str, inst: str, sfz_dir: Path) -> Path:
    if lib == "vpo3":
        import vpo3
        return vpo3.VPO3_SFZ[vpo3.INST_PATCH[inst]]
    p = sfz_dir / INSTR[inst]["sfz"]
    return p if p.exists() else sfz_dir / "violin.sfz" if inst == "vn2" else p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 epilog="Full MIDI conventions: python3 -c 'import render_quartet as r; print(r.__doc__)'",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("midi", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--lib", choices=["iowa", "vpo3"], default="iowa")
    ap.add_argument("--map")
    ap.add_argument("--bass-double", choices=["off", "on", "auto"], default="off")
    ap.add_argument("--bass-threshold", default="ff")
    ap.add_argument("--bass-level", type=float, default=-5.0, help="doubling bass trim in dB (default -5)")
    ap.add_argument("--hall", choices=["detmold", "synthetic", "none"], default="detmold")
    ap.add_argument("--wet", type=float, default=WET_DEFAULT,
                    help=f"hall energy relative to the dry sound, measured on this music (both channels), dB "
                         f"(default {WET_DEFAULT:g})")
    ap.add_argument("--short-ms", type=float, default=260.0)
    ap.add_argument("--legato-xfade-ms", type=float, default=5.0,
                    help="a slurred note's predecessor is held this long past the new note's beat (default 5)")
    ap.add_argument("--legato-pre-ms", type=float, default=25.0,
                    help="a slurred note starts this early, so its 30 ms fade-in ends on the beat (default 25)")
    ap.add_argument("--normal-pre-ms", type=float, default=NORMAL_PRE_MS,
                    help=f"a new-bow stroke starts this early (default {NORMAL_PRE_MS:g})")
    ap.add_argument("--cc11-depth", type=float, default=0.5)
    ap.add_argument("--stems", action="store_true")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--lead-in", type=float, default=0.3, help="silence before the first note-on (s, default 0.3)")
    ap.add_argument("--keep-start", action="store_true",
                    help="output starts at MIDI time 0 (no lead-in trim; for measurements)")
    ap.add_argument("--peak", type=float, default=-1.0)
    ap.add_argument("--sfz-dir", type=Path, default=QUARTET_DIR)
    a = ap.parse_args(argv)

    if not SFIZZ_RENDER.exists():
        sys.exit(f"missing {SFIZZ_RENDER}: run setup_strings.sh")
    out = a.out or a.midi.with_suffix("")
    log = []
    voices, marker = read_voices(a.midi, log)
    if not voices:
        sys.exit("no notes found")
    assign(voices, a.map, log)
    if marker:
        log.insert(0, f"MIDI written by perform.py (target={marker.get('target')})")
    for v in voices:
        if ensure_cc1(v):
            log.append(f"{v.name}: no CC1, dynamic level taken from note velocities")
    jobs: list[Job] = []
    rescue_range(voices, jobs, log)
    for v in voices:
        if v.notes:
            jobs.insert(0, Job(voice=v, notes=v.notes, inst=v.inst, kind="main", label=v.name, desk=v.desk))
    art_counts = {}
    for j in jobs:
        c = shape_articulation(j.notes, a.short_ms / 1000.0, a.legato_xfade_ms / 1000.0,
                               j.voice.cc.get(20), j.voice.cc.get(21),
                               legato_pre=a.legato_pre_ms / 1000.0, normal_pre=a.normal_pre_ms / 1000.0)
        art_counts[j.label] = c
    for j in jobs:                                    # compass check for what is left
        lo = INSTR[j.inst]["lo"] - EXT_DOWN
        hi = INSTR[j.inst]["hi"]
        bad = [n for n in j.notes if not lo <= n.key <= hi]
        for n in bad:
            while n.key < lo:
                n.key += 12
            while n.key > hi:
                n.key -= 12
        if bad:
            log.append(f"{j.label}: {len(bad)} notes outside the {INSTR[j.inst]['name']} compass octave-shifted")
    cello = next((v for v in voices if v.inst == "vc"), None)
    if cello is not None and not any(v.inst == "cb" for v in voices) and a.bass_double != "off":
        cn = [Note(n.on, n.off, n.key, n.vel, n.art, n.rel, n.pre) for j in jobs if j.inst == "vc" for n in j.notes]
        cn.sort(key=lambda n: n.on)
        cn = [n for n in cn if n.key - 12 >= INSTR["cb"]["lo"] - EXT_DOWN]
        if cn:
            jobs.append(Job(voice=cello, notes=cn, inst="cb", kind="double", label="Contrabass 8vb (doubling)"))
    t_end = max(n.off for j in jobs for n in j.notes) + 2.0
    if a.lib == "iowa":
        for j in jobs:
            j.plan = layer_plan(j.voice.cc.get(1, []), [n.on - n.pre for n in j.notes], t_end)

    # sfizz renders in "render time" = MIDI time + SHIFT, so notes that start
    # early (Note.pre) at MIDI time 0 still have room
    shift_s = max(0.5, a.lead_in + 0.05)
    tmp = Path(tempfile.mkdtemp(prefix="quartet_"))
    tasks = []
    for i, j in enumerate(jobs):
        mp = tmp / f"j{i}_{j.inst}.mid"
        job_midi(j, transpose=-12 if j.kind == "double" else 0, shift=shift_s).save(str(mp))
        tasks.append((sfz_for(a.lib, j.inst, a.sfz_dir), mp, tmp / f"j{i}_{j.inst}.wav"))

    print(f"{a.midi.name}: {len(voices)} voices, library {a.lib}")
    for j in jobs:
        ks = [n.key for n in j.notes]
        c = art_counts.get(j.label, {})
        print(f"  {j.label:28s} -> {INSTR[j.inst]['name']:11s} {len(ks):4d} notes, keys {min(ks)}-{max(ks)}"
              + (f"  (normal {c.get('normal', 0)}, legato {c.get('legato', 0)}, short {c.get('short', 0)})"
                 if c else ""))
    for line in log:
        print("  note:", line)
    with ThreadPoolExecutor(min(6, os.cpu_count() or 4)) as ex:
        stems = list(ex.map(lambda t: run_sfizz(*t), tasks))
    sh = int(round(shift_s * SR))
    if a.keep_temp:        # kept job files are in MIDI time (sfizz rendered them shift_s later)
        for j, (_, mid_path, wav_path), x in zip(jobs, tasks, stems):
            sf.write(str(wav_path), x[sh:], SR, subtype="FLOAT")
            job_midi(j, transpose=-12 if j.kind == "double" else 0, shift=0.0).save(str(mid_path))

    n = max(len(s) for s in stems) + int(4.0 * SR)
    reverb = None if a.hall == "none" else hall.Hall(a.hall, SR)
    dry = np.zeros((n, 2))
    wet = np.zeros((n, 2))                     # the hall at unit gain (IR at unit energy), scaled below
    early = np.zeros((n, 2)) if reverb is not None else None
    stem_out = {}
    level_report = {}
    thr_cc1 = level_to_cc1(parse_level(a.bass_threshold))
    for j, x in zip(jobs, stems):
        y = np.zeros((n, 2))
        y[: len(x)] = x
        # CC curves are in MIDI time; the stems in render time (MIDI time + shift)
        g = np.ones(n)
        gm = gain_envelope(j.voice.cc.get(7), n - sh, 127, lambda v: 40 * math.log10(max(v, 1) / 127))
        gm *= gain_envelope(j.voice.cc.get(11), n - sh, 127,
                            lambda v: a.cc11_depth * 20 * math.log10(max(v, 1) / 127))
        if j.plan is not None:
            gm *= plan_gain(j.plan, n - sh)
        g[sh:] = gm
        g[:sh] = gm[0]
        g *= 10 ** (INSTR[j.inst]["trim"] / 20)
        if j.kind == "double":
            env = bass_envelope(j.voice, n - sh, a.bass_double, thr_cc1)
            if env is None:
                log.append("bass doubling: cello never reaches the threshold, nothing added")
                continue
            g[sh:] *= env * 10 ** (a.bass_level / 20)
            g[:sh] *= env[0] * 10 ** (a.bass_level / 20)
        y *= g[:, None]
        stem_out.setdefault(j.inst, np.zeros((n, 2)))
        stem_out[j.inst] += y
        az = INSTR[j.inst]["az"] + (-8.0 * j.desk if INSTR[j.inst]["az"] >= 0 else 8.0 * j.desk)
        dry += hall.place_dry(y, az, depth=INSTR[j.inst]["depth"] + 0.5 * j.desk)
        if reverb is not None:
            mono = y.mean(axis=1)
            wet += reverb.source(mono, az, 0.0)
            early += reverb.early(mono, az)
    hall_rep = None
    c80 = None
    if reverb is not None:
        # --wet is the hall's energy re the dry sound on THIS music: the unit-energy IR is 0 dB
        # re dry only for white noise (round-2 QA: +5.0 dB on the ricercar, whose energy sits
        # where the hall rings longest), so measure the unit-gain hall here and scale it
        e_dry = float(np.sum(dry ** 2))
        unit_db = 10 * math.log10(max(float(np.sum(wet ** 2)), 1e-30) / max(e_dry, 1e-30))
        ir_scale_db = a.wet - unit_db
        g_wet = 10 ** (ir_scale_db / 20)
        c80 = reverb.program_c80(dry, wet, early, g_wet)
        wet *= g_wet
        hall_rep = dict(wet_db=a.wet, ir_gain_on_this_music_db=round(unit_db, 2), ir_scale_db=round(ir_scale_db, 2),
                        hall_re_dry_db=round(10 * math.log10(float(np.sum(wet ** 2)) / e_dry), 2) + 0.0,   # no "-0.0"
                        c80_db=round(c80, 2), c80_impulse_db=round(reverb.c80(g_wet), 2))
        del early
    mix = dry + wet
    for inst, y in stem_out.items():
        mono = y.mean(axis=1)
        act = np.abs(mono) > 1e-5
        level_report[INSTR[inst]["name"]] = round(10 * math.log10(np.mean(mono[act] ** 2) + 1e-20), 2) \
            if act.any() else None
    env = np.max(np.abs(mix), axis=1)
    thr = env.max() * 10 ** (-80 / 20)
    idx = np.flatnonzero(env > thr)
    first_on = min(n_.on for j in jobs for n_ in j.notes)
    if a.keep_start:
        first = sh
    else:
        first = max(0, int(round((first_on - a.lead_in) * SR)) + sh)
    last = int(idx[-1]) if len(idx) else len(mix)
    mix = mix[first: min(len(mix), last + int(0.3 * SR))]
    fade = int(0.3 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    wav, m4a, tp_pre, tp_post = export(mix, out, a.peak)
    offset_s = (first - sh) / SR                       # MIDI time of the output's first sample
    print(f"hall={a.hall}" + (f" {hall_rep['hall_re_dry_db'] + 0.0:+.1f} dB re dry on this music (IR {hall_rep['ir_scale_db']:+.1f} dB), "
                              f"C80 {c80:+.1f} dB" if hall_rep else "")
          + f"  true peak {tp_post:+.2f} dBTP  -> {wav}, {m4a.name}  ({len(mix) / SR:.1f} s)")
    if a.stems:
        norm = 10 ** (a.peak / 20) / 10 ** (tp_pre / 20)
        for inst, y in stem_out.items():
            p = out.parent / f"{out.name}_stem_{inst}.wav"
            sf.write(str(p), (y[first: first + len(mix)] * norm).astype(np.float32), SR, subtype="FLOAT")
    if a.report:
        switches = {}
        for j in jobs:
            if j.plan is not None:
                lay = [_layer_of(v) for v in j.plan[2]]
                switches[j.label] = sum(1 for x, y in zip(lay, lay[1:]) if x != y)
        rep = dict(midi=str(a.midi), lib=a.lib, hall=a.hall, wet_db=a.wet if hall_rep else None,
                   c80_db=round(c80, 2) if c80 is not None else None, hall_stats=hall_rep, duration_s=len(mix) / SR,
                   true_peak_dbtp=tp_post, offset_s=offset_s, lead_in_s=0.0 if a.keep_start else a.lead_in,
                   layer_switches=switches,
                   jobs=[dict(label=j.label, inst=j.inst, kind=j.kind, desk=j.desk, notes=len(j.notes),
                              articulation=art_counts.get(j.label),
                              note_list=[(round(n_.on, 4), round(n_.off, 4), n_.key, n_.vel, n_.art)
                                         for n_ in j.notes],
                              pre_ms=[round(1000 * n_.pre, 1) for n_ in j.notes]) for j in jobs],
                   cc1={v.inst: [(round(t, 3), val) for t, val in v.cc.get(1, [])] for v in voices},
                   stem_rms_db_when_active=level_report, notes=log)
        a.report.write_text(json.dumps(rep, indent=1))
    if a.keep_temp:
        print("temp:", tmp)
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return wav, m4a


if __name__ == "__main__":
    main()
