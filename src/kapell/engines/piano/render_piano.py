#!/usr/bin/env python3
"""Render a multi-voice MIDI file on a sampled concert grand in a concert hall.

Usage
-----
::

    python3 render_piano.py IN.mid [-o OUT] [options]

    # the chain: LilyPond score + performance plan -> MIDI -> piano
    python3 ../../tools/perform.py SCORE.ly PLAN.json out/x.mid --target piano
    python3 render_piano.py out/x.mid -o out/x
    # the demo (old organ fugue; its pedal part sounds an octave lower, as a 16' stop)
    python3 ../../tools/perform.py ../../../fugue.ly plans/fugue_jp.plan.json out/fugue_jp.mid --target piano
    python3 render_piano.py out/fugue_jp.mid -o out/fugue_jp_piano --transpose pedal=-12

This writes ``OUT.wav`` (48 kHz, 24-bit stereo, true peak normalised to -1 dBFS)
and ``OUT.m4a`` (AAC 256 kb/s via ``afconvert``). It plays nothing through the
speakers. Run ``setup_piano.sh`` once first (samples, impulse response, sfizz).

Options: ``--wet-db`` (the hall's energy relative to the dry piano, calibrated
on the piano's long-term spectrum; default 0 dB, the hall as loud as the dry
piano: C80 +4.9 dB on the demo, clear enough for counterpoint with the hall
audible; the report gives both as measured on the render), ``--no-reverb``, ``--ir PATH``,
``--peak-db``, ``--lead-in``, ``--dyn-db`` (global dynamic offset realised
through velocity), ``--transpose VOICE=N``, ``--stems DIR``,
``--velocity-scale auto|raw|perform``, ``--cc-dynamics auto|velocity|cc11|gain|off``
(both explained under the MIDI contract), ``--no-key-sharing``, ``--no-fold``,
``--quality`` (sfizz resampler, 10 = sinc72), ``--jobs`` (parallel sfizz
instances, default 4), ``--keep-temp``, ``--no-m4a``, ``--json PATH`` (render
report: per-voice velocities, levels and stereo, key sharing, folded notes,
truncation check, hall-to-dry and C80 measured on the render, loudness, true
peak, stereo of the dry sum and the mix, warnings).

Instrument
----------
Salamander Grand Piano V3 (Yamaha C5, 48 kHz/24-bit, 16 velocity layers, hammer
noise and string-resonance release samples, pedal noises) by Alexander Holm,
CC-BY 3.0. The SFZ is re-derived by ``make_sfz.py``: attacks aligned to within
0.2 ms across layers, velocity-to-loudness continuous and monotonic over about
40 dB, keyboard evenness and intonation smoothed. It is played by sfizz
(``sfizz_render``, sinc-72 resampling, 32-bit float output), one instance per
voice, each holding the samples its keys need in RAM (disk streaming in
``sfizz_render`` can drop held notes; every stem is also checked for a note
that stops dead while held, and is rendered again if one does). Keys up to E6
have dampers: a lifted key fades with an exponential damper release of 0.35 s
(0.5 s in the bottom octave, where the strings are heavy), plus the recorded
string-resonance and hammer release samples. Keys from F6 up ring on, as on a
real grand.

The samples were recorded with a spaced pair; ``make_sfz.py`` time-aligns the
two channels of each note (one delay per note, up to 3 ms), so that no note is
anti-phase: per-note L/R correlation is +0.23 to +0.96 (it was -0.82 to +0.74,
and C5 lost 8 dB in mono). The render report gives L/R correlation and mono
fold-down for each stem, the dry sum and the mix.

Room: Detmold Konzerthaus, audience seat 163, coincident omni/figure-8 decoded
to stereo (``make_ir.py``; CC-BY 4.0, Amengual Gari et al., AES 2020); the
1.44 s measurement is continued per octave band at its own decay rate to 3.1 s,
because the bass reverberates longer than the file. Each dry channel feeds its
own side of the IR (L to L, R to R). The IR is stored at unit energy, which on
piano material is a gain of +9.4 dB (the hall's energy sits at 60-1000 Hz,
where the piano's does); ``--wet-db`` is set against that gain, measured on
the piano's long-term spectrum from the calibration JSON, so it is the hall's
energy relative to the dry piano. The report measures it on the render
(``hall.hall_re_dry_db``, within 0.2 dB of ``--wet-db`` on the demo) together
with C80 (dry plus the first 80 ms of the hall, against the rest of the hall).

Output files carry the attribution the licences require (WAV INFO chunk:
title, artist, comment, copyright, software; M4A tags written by ffmpeg with
the audio stream copied).

MIDI contract (for the performance script)
------------------------------------------
* **One voice per track, or per channel.** Every (track, channel) pair that
  holds notes becomes a voice, named after the track (``Soprano``,
  ``Alto`` ...). With several channels in one track, ``.chN`` is appended.
  Tracks that share a name stay separate voices: the second ``soprano``
  becomes ``soprano.2`` (with a warning), with its own stem, CC7 fader and
  ``--transpose`` name.
  Tempo (``set_tempo`` on any track, usually track 0) and ticks are honoured, so
  rubato may be written as a tempo map or as note timing. Both work.
* **Note velocity = hammer velocity.** This is the main expressive control. It
  selects one of 16 recorded layers (timbre: soft notes are dark, loud notes
  bright and percussive) and sets the level along a calibrated curve. Measured
  levels relative to velocity 127, averaged over C2-C6::

      velocity   13   30   42   63   86  103  115  127
      dB        -33  -27  -21  -15  -10   -6   -3    0
      marking   ppp   pp    p   mp   mf    f   ff  fff

  (exact curve: ``velocity_db``, and these velocities: ``suggested_velocities``,
  in the calibration JSON). To bring out a
  voice, raise its velocities by about 8-15 (+3 to +5 dB, brighter).
  A piano cannot swell a held note, so a crescendo means successive notes
  struck harder.
* **Velocity scale.** perform.py writes its own scale (VEL_AT: ppp 22, pp 32,
  p 44, mp 56, mf 68, f 82, ff 98, fff 112). Played raw, its "f" would be this
  piano's mf-, and the chain test's pp->ff span would be 16.9 dB instead of
  22.2 dB. ``--velocity-scale
  perform`` maps it piecewise-linearly onto the calibrated markings above
  (22->13, 32->30, 44->42, 56->63, 68->86, 82->103, 98->115, 112->127, read
  from the calibration JSON); accents and voicing offsets between anchors
  scale with the local slope.
  perform.py marks its files with a ``text`` meta event ``perform.py
  target=piano|strings`` in the tempo track, and the default ``auto`` picks
  ``perform`` for such files and ``raw`` for everything else.
* **CC11 (expression) = dynamics envelope; CC1 too, in perform.py files.**
  Default 127 = neutral, and a channel that never sends them is neutral. The
  controller value in force at each note-on moves that note's level by
  ``40*log10(cc/127)`` dB, realised as a **different hammer velocity** through
  the inverse of the calibrated curve, so the timbre follows the dynamic as on
  a real piano. Examples: 64 -> -11.9 dB, 90 -> -6 dB, 107 -> -3 dB. Notes
  that are already sounding do not change. What counts depends on who wrote
  the file (``--cc-dynamics``, default ``auto``):

  - ``perform.py --target piano`` files: ``velocity``, the lower of CC1 and
    CC11 (perform.py's convention: both mean dynamics; its piano files send
    neither today, so velocity alone carries the dynamics).
  - ``perform.py --target strings`` files: ``off``. Their velocities already
    carry the dynamic level, and the CC1/CC11 copy of the same envelope would
    count it twice. (For the piano, render ``--target piano``; a strings file
    also works, with string-style articulation and without the piano voicing
    boosts.)
  - every other file: ``cc11``, CC11 only. In General MIDI, CC1 is modulation,
    and a GM reset sends CC1=0 at the start; read as dynamics that would play
    every note at velocity 1.

  ``--cc-dynamics velocity`` applies min(CC1, CC11) to any file, ``gain``
  keeps CC1 as velocity but makes CC11 a continuous fader, ``off`` ignores
  both. A voice whose mean velocity the controllers pull below 10 (from 30 or
  more), and a render that needs more than +20 dB of make-up gain, are
  warned about, and the warnings are listed in the render report.
* **CC7 (channel volume) = mixing fader** for that voice's stem, in dB
  ``40*log10(cc7/100)``: default 100 = 0 dB, 127 = +4.2 dB, 71 = -6 dB. It
  is applied continuously with 20 ms smoothing and changes only level, not
  timbre. Use it for static balance. For musical dynamics use velocity/CC11.
* **CC64 (sustain)** on any track is the one sustain pedal of the piano.
  Values >= 64 are down, < 64 up. Half-pedalling is not modelled. Pedal-down and
  pedal-up mechanism noises are played once. Bach needs none, but light
  syncopated pedalling works.
* **One keyboard.** Voices share one physical piano. Two voices striking the
  same key less than 30 ms apart (a notated unison: perform.py's humanising and
  melody lead spread those over 0-20 ms) play one hammer blow, at the earlier
  onset and the stronger velocity, and the key is held while either voice holds
  it. Without this rule, unisons would sound doubled and comb-filtered. A voice
  striking a key that another voice has held for longer is a re-strike: the
  earlier note is released 15 ms before (so it has sounded at least 15 ms), and
  the key stays down as long as either voice holds it. ``--no-key-sharing``
  disables both rules.
* **Range.** Notes outside the 88 keys (A0-C8), for example after
  ``--transpose``, are folded back by octaves with a warning, and counted as
  ``folded_notes`` in the render report; ``--no-fold`` makes them an error.
* **Odd note events.** A note-on and note-off on the same tick (a zero-length
  note) is played as a 10 ms touch of the key: the hammer still strikes. A
  note-on without a note-off sounds for 1 s. Both are warned about and counted
  per voice in the report.
* Anything else (program changes, pitch bend, CC10 pan ...) is ignored. The
  stereo image of a piano comes from the instrument itself, low strings left
  and high strings right, as heard from the keyboard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from piano_paths import (  # noqa: E402
    CALIBRATION_JSON,
    DERIVED_SFZ,
    DERIVED_SFZ_NO_PEDAL_NOISE,
    HALL_IR,
    SALAMANDER_DIR,
    SFIZZ_RENDER,
    SR,
)

STEM_TPB = 9600
STEM_TEMPO = 500_000  # -> one tick = 52 us
RESTRIKE_GAP = 0.015
# Two voices striking one key less than this apart play one hammer blow. perform.py's
# humanising (+/-5-6 ms per note) and melody lead (8 ms) put notated unisons 0-20 ms
# apart, and no pianist re-strikes a key within 30 ms.
UNISON_WINDOW = 0.030
MIN_NOTE = 0.010
KEY_LO, KEY_HI = 21, 108  # A0..C8
FADER_SMOOTH = 0.020


# ----------------------------------------------------------------------------------------
# MIDI parsing
# ----------------------------------------------------------------------------------------
@dataclass
class Note:
    voice: str
    key: int
    start: float
    end: float
    velocity: int
    vel_eff: int = 0
    dropped: bool = False


@dataclass
class Voice:
    name: str
    notes: list = field(default_factory=list)
    cc: dict = field(default_factory=dict)  # cc number -> list[(time, value)]
    zero_length: int = 0  # note_on and note_off on the same tick: played as MIN_NOTE
    unterminated: int = 0  # note_on without note_off: played for 1 s
    renamed_from: str = ""  # track name shared with an earlier track (this voice got a ".2" suffix)


class TempoMap:
    def __init__(self, tpb: int, tempos: list[tuple[int, int]]):
        self.tpb = tpb
        tempos = sorted(tempos)
        if not tempos or tempos[0][0] != 0:
            tempos.insert(0, (0, 500_000))
        self.ticks, self.secs, self.tempo = [], [], []
        sec, last_tick, last_tempo = 0.0, 0, tempos[0][1]
        for tick, tempo in tempos:
            sec += (tick - last_tick) * last_tempo / 1e6 / tpb
            self.ticks.append(tick)
            self.secs.append(sec)
            self.tempo.append(tempo)
            last_tick, last_tempo = tick, tempo

    def seconds(self, tick: int) -> float:
        i = bisect_right(self.ticks, tick) - 1
        return self.secs[i] + (tick - self.ticks[i]) * self.tempo[i] / 1e6 / self.tpb


def load_midi(path: Path) -> dict[str, Voice]:
    mf = mido.MidiFile(path)
    abs_events = []
    tempos = []
    names = {}
    for ti, track in enumerate(mf.tracks):
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempos.append((tick, msg.tempo))
            elif msg.type == "track_name" and ti not in names:
                names[ti] = msg.name.strip().rstrip(":").strip()
            elif msg.type in ("note_on", "note_off", "control_change"):
                abs_events.append((tick, ti, msg))
    if mf.type == 2:
        raise SystemExit("MIDI type 2 (independent sequences) is not supported")
    tmap = TempoMap(mf.ticks_per_beat, tempos)

    chans_per_track: dict[int, set] = {}
    for _, ti, msg in abs_events:
        if msg.type != "control_change":
            chans_per_track.setdefault(ti, set()).add(msg.channel)

    # Every track that holds notes is its own voice (stem, CC7 fader, --transpose name), even
    # when two tracks carry the same name: the later ones become "name.2", "name.3" ...
    base_names: dict[int, str] = {}
    renamed: dict[int, str] = {}
    used: dict[str, int] = {}
    for ti in sorted(chans_per_track):
        base = names.get(ti) or f"track{ti}"
        key = base.lower()
        used[key] = used.get(key, 0) + 1
        if used[key] > 1:
            renamed[ti] = base
            base = f"{base}.{used[key]}"
            while base.lower() in used:  # a track may already be called "soprano.2"
                used[key] += 1
                base = f"{renamed[ti]}.{used[key]}"
            used[base.lower()] = 1
        base_names[ti] = base

    def vname(ti: int, ch: int) -> str:
        base = base_names.get(ti) or names.get(ti) or f"track{ti}"
        return f"{base}.ch{ch + 1}" if len(chans_per_track.get(ti, ())) > 1 else base

    voices: dict[str, Voice] = {}
    pending: dict[tuple, list] = {}
    # At one tick, note-offs come first, so that a note ending where the same key starts
    # again closes the old note, not the new one.
    abs_events.sort(key=lambda e: (e[0], 0 if e[2].type != "note_on" or e[2].velocity == 0 else 1))
    orphan_off: dict[tuple, int] = {}  # (voice, key) -> tick of a note-off that closed nothing
    cc_events = []
    for tick, ti, msg in abs_events:
        t = tmap.seconds(tick)
        if msg.type == "control_change":
            cc_events.append((t, ti, msg))
            continue
        name = vname(ti, msg.channel)
        v = voices.setdefault(name, Voice(name, renamed_from=renamed.get(ti, "")))
        k = (name, msg.note)
        if msg.type == "note_on" and msg.velocity > 0:
            if orphan_off.pop(k, None) == tick:
                # note-on and note-off on the same tick (sorted off-first above): a
                # zero-length note. A key pressed that briefly still throws the hammer.
                v.notes.append(Note(name, msg.note, t, t + MIN_NOTE, msg.velocity))
                v.zero_length += 1
            else:
                pending.setdefault(k, []).append((t, msg.velocity))
        else:
            if pending.get(k):
                st, vel = pending[k].pop(0)
                if t - st > 0:
                    v.notes.append(Note(name, msg.note, st, t, vel))
            else:
                orphan_off[k] = tick
    for (name, key), lst in pending.items():
        for st, vel in lst:  # unterminated notes: 1 s
            voices[name].notes.append(Note(name, key, st, st + 1.0, vel))
            voices[name].unterminated += 1
    # Controllers go to every voice that lives on that (track, channel); CCs on
    # note-less channels of a track apply to all voices of that track.
    for t, ti, msg in cc_events:
        targets = [vname(ti, msg.channel)] if msg.channel in chans_per_track.get(ti, ()) else [
            vname(ti, c) for c in chans_per_track.get(ti, ())
        ]
        if not targets:  # e.g. a conductor track with only CC64: apply to the whole piano
            targets = [None]
        for name in targets:
            if name is None:
                voices.setdefault("__global__", Voice("__global__")).cc.setdefault(msg.control, []).append((t, msg.value))
            elif name in voices:
                voices[name].cc.setdefault(msg.control, []).append((t, msg.value))
    for v in voices.values():
        v.notes.sort(key=lambda n: (n.start, n.key))
        for lst in v.cc.values():
            lst.sort(key=lambda e: e[0])
    return voices


def cc_value_at(events: list, t: float, default: int) -> int:
    val = default
    for et, ev in events:
        if et <= t + 1e-9:
            val = ev
        else:
            break
    return val


# ----------------------------------------------------------------------------------------
# Expression -> velocity
# ----------------------------------------------------------------------------------------
class VelocityCurve:
    def __init__(self):
        if CALIBRATION_JSON.exists():
            db = np.array(json.loads(CALIBRATION_JSON.read_text())["velocity_db"], dtype=float)
        else:  # fall back to a plain SFZ-style curve
            v = np.arange(128) / 127.0
            db = 20 * np.log10(0.27 + 0.73 * v**2)
        db = db.copy()
        for i in range(1, len(db)):  # strictly increasing for inversion
            db[i] = max(db[i], db[i - 1] + 1e-4)
        self.db = db

    def shift(self, velocity: int, delta_db: float) -> int:
        if abs(delta_db) < 1e-9:
            return int(velocity)
        target = self.db[int(np.clip(velocity, 1, 127))] + delta_db
        v = np.interp(target, self.db[1:], np.arange(1, 128))
        return int(np.clip(round(float(v)), 1, 127))


def cc_db(value: int) -> float:
    return -120.0 if value <= 0 else 40.0 * math.log10(value / 127.0)


# perform.py (ricercar/tools) maps its dynamic levels ppp..fff to velocities 22..112
# (VEL_AT). The calibrated markings of this instrument are 13..127. "--velocity-scale
# perform" maps one onto the other, piecewise linear between the level anchors, so that
# perform.py's "f" is this piano's f (velocity 103, -6 dB) and not mf- (82, -11 dB).
# Accent and voicing offsets that perform.py adds on top of a level are scaled with the
# local slope, so a voice brought out stays brought out.
PERFORM_VEL_AT = {"ppp": 22, "pp": 32, "p": 44, "mp": 56, "mf": 68, "f": 82, "ff": 98, "fff": 112}  # perform.py VEL_AT


def perform_vel_map() -> list[tuple[int, int]]:
    """perform.py's level anchors -> this piano's calibrated markings, read from the
    calibration JSON that make_sfz.py writes (so a recalibration moves the map with it)."""
    # fallback = the calibration's own suggested_velocities (make_sfz.py), used only if the
    # calibration JSON is missing
    marks = {"ppp": 13, "pp": 30, "p": 42, "mp": 63, "mf": 86, "f": 103, "ff": 115, "fff": 127}
    if CALIBRATION_JSON.exists():
        marks.update(json.loads(CALIBRATION_JSON.read_text()).get("suggested_velocities", {}))
    return [(0, 0)] + [(PERFORM_VEL_AT[k], int(marks[k])) for k in PERFORM_VEL_AT]


PERFORM_VEL_MAP = perform_vel_map()


def perform_velocity(v: int) -> int:
    xs, ys = zip(*PERFORM_VEL_MAP)
    return int(np.clip(round(float(np.interp(v, xs, ys))), 1, 127))


def midi_marker(path: Path) -> dict:
    """Read the ``perform.py target=...`` text event that perform.py writes into the
    tempo track, if present. Returns e.g. {"source": "perform.py", "target": "piano"}."""
    for track in mido.MidiFile(path).tracks:
        for msg in track:
            if msg.type == "text" and msg.text.startswith("perform.py"):
                info = {"source": "perform.py"}
                for tok in msg.text.split()[1:]:
                    if "=" in tok:
                        k, v = tok.split("=", 1)
                        info[k] = v
                return info
    return {}


# ----------------------------------------------------------------------------------------
# One keyboard shared by all voices
# ----------------------------------------------------------------------------------------
def share_keyboard(notes: list[Note]) -> dict:
    stats = {"unisons_merged": 0, "restrikes": 0}
    by_key: dict[int, list[Note]] = {}
    for n in sorted(notes, key=lambda n: (n.start, -n.vel_eff)):
        by_key.setdefault(n.key, []).append(n)
    for key, lst in by_key.items():
        active: Note | None = None
        for n in lst:
            if active is not None and n.start < active.end - 1e-6:
                if n.start - active.start <= UNISON_WINDOW:
                    # struck together: one key, one hammer blow, at the earlier onset (the
                    # voice that leads), with the stronger velocity, held while either
                    # voice holds it
                    active.vel_eff = max(active.vel_eff, n.vel_eff)
                    active.end = max(active.end, n.end)
                    n.dropped = True
                    stats["unisons_merged"] += 1
                    continue
                # re-strike of a held key
                held_until = active.end
                active.end = max(active.start + MIN_NOTE, n.start - RESTRIKE_GAP)
                n.end = max(n.end, held_until)
                stats["restrikes"] += 1
            active = n
    return stats


# ----------------------------------------------------------------------------------------
# Stems
# ----------------------------------------------------------------------------------------
def pedal_events(voices: dict[str, Voice]) -> list[tuple[float, int]]:
    ev = []
    for v in voices.values():
        ev += v.cc.get(64, [])
    ev.sort()
    out, state = [], 0
    for t, val in ev:
        s = 127 if val >= 64 else 0
        if s != state:
            out.append((t, s))
            state = s
    return out


def write_stem_midi(path: Path, notes: list[Note], pedal: list, transpose: int, lead_in: float) -> None:
    mf = mido.MidiFile(type=0, ticks_per_beat=STEM_TPB)
    tr = mido.MidiTrack()
    mf.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=STEM_TEMPO, time=0))
    ev = []
    ticks_per_sec = STEM_TPB * 1e6 / STEM_TEMPO
    for n in notes:
        if n.dropped:
            continue
        key = n.key + transpose
        while key < KEY_LO:  # main() has already folded (and reported) such notes
            key += 12
        while key > KEY_HI:
            key -= 12
        ev.append((n.start + lead_in, 2, mido.Message("note_on", note=key, velocity=n.vel_eff)))
        ev.append((n.end + lead_in, 1, mido.Message("note_off", note=key, velocity=64)))
    for t, val in pedal:
        # pedal changes sort before notes at the same instant
        ev.append((t + lead_in, 0, mido.Message("control_change", control=64, value=val)))
    ev.sort(key=lambda e: (e[0], e[1]))
    now = 0
    for t, _, msg in ev:
        tick = int(round(t * ticks_per_sec))
        msg.time = max(0, tick - now)
        now = max(now, tick)
        tr.append(msg)
    tr.append(mido.MetaMessage("end_of_track", time=int(ticks_per_sec)))
    mf.save(path)


def check_instrument() -> None:
    """Refuse to render with a derived SFZ written by another version of make_sfz.py."""
    for p in (SFIZZ_RENDER, DERIVED_SFZ, DERIVED_SFZ_NO_PEDAL_NOISE):
        if not Path(p).exists():
            raise SystemExit(f"missing {p} -- run setup_piano.sh first")
    want = hashlib.sha256((Path(__file__).resolve().parent / "make_sfz.py").read_bytes()).hexdigest()
    for p in (DERIVED_SFZ, DERIVED_SFZ_NO_PEDAL_NOISE):
        with open(p) as f:
            head = "".join(f.readline() for _ in range(20))
        if f"sha256={want}" not in head:
            raise SystemExit(f"{p.name} was written by a different make_sfz.py -- run ./setup_piano.sh "
                             "(it regenerates the derived instrument)")


def check_hall_ir(path: Path) -> dict:
    """The default hall IR must come from the current make_ir.py (its JSON records the
    script's SHA-256, as the derived SFZ does). A custom --ir is used as it is."""
    meta = Path(str(path).rsplit(".", 1)[0] + ".json")
    info = json.loads(meta.read_text()) if meta.exists() else {}
    if Path(path).resolve() == Path(HALL_IR).resolve():
        want = hashlib.sha256((Path(__file__).resolve().parent / "make_ir.py").read_bytes()).hexdigest()
        if info.get("make_ir.py sha256") != want:
            raise SystemExit(f"{Path(path).name} was written by a different make_ir.py -- run ./setup_piano.sh "
                             "(it rebuilds the hall IR)")
    return info


def prune_sfz(src: Path, keys: set[int], dst: Path) -> Path | None:
    """Copy of the derived SFZ without the regions that no key of this stem can trigger.

    The derived SFZ loads every sample into RAM (hint_ram_based=1: sfizz_render's disk
    streaming drops notes). One voice of a fugue uses a small part of the keyboard, so
    dropping the other regions cuts load time and memory several-fold. Regions without
    a key range (the pedal noises) are kept. The audio is bit-identical to a render with
    the full file. Sample paths stay relative to the library via default_path.
    """
    if any(c.isspace() for c in str(SALAMANDER_DIR)):
        return src  # default_path with blanks is not portable across SFZ parsers
    out, group_lo, group_hi = [], None, None
    for line in src.read_text().split("\n"):
        s = line.strip()
        if s.startswith("<control>"):
            out.append(f"<control> default_path={SALAMANDER_DIR}/ " + s[len("<control>"):].strip())
            continue
        if s.startswith("<group>"):
            ops = dict(t.split("=", 1) for t in s[len("<group>"):].split() if "=" in t)
            group_lo, group_hi = ops.get("lokey"), ops.get("hikey")
        elif s.startswith("<region>"):
            ops = dict(t.split("=", 1) for t in s[len("<region>"):].split() if "=" in t)
            lo = ops.get("lokey", ops.get("key", group_lo))
            hi = ops.get("hikey", ops.get("key", group_hi))
            if lo is not None and hi is not None and int(lo) >= 0:
                if not any(int(lo) <= k <= int(hi) for k in keys):
                    continue
        out.append(line)
    if not any(l.lstrip().startswith("<region>") for l in out):
        return None  # nothing this stem can trigger (e.g. every note merged into another voice)
    if not any(l.startswith("<control> default_path=") for l in out):
        out.insert(0, f"<control> default_path={SALAMANDER_DIR}/")
    dst.write_text("\n".join(out))
    return dst


def run_sfizz(sfz: Path | None, mid: Path, wav: Path, quality: int) -> None:
    if sfz is None:  # a stem with nothing to play
        sf.write(wav, np.zeros((SR, 2), dtype=np.float32), SR, subtype="FLOAT")
        return
    cmd = [str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(mid), "--wav", str(wav),
           "-s", str(SR), "-q", str(quality), "-p", "512", "-b", "256"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not wav.exists():
        raise RuntimeError(f"sfizz_render failed for {mid}:\n{r.stdout}\n{r.stderr}")


def sounding_intervals(notes: list[Note], pedal: list, lead_in: float) -> list[tuple[float, float]]:
    """(start, end) in stem seconds while each note should sound: key down, extended to the
    next pedal release if the sustain pedal is down at the note-off."""
    downs = [(t, v) for t, v in pedal]
    out = []
    for n in notes:
        if n.dropped:
            continue
        end = n.end
        state = 0
        for t, v in downs:
            if t <= n.end + 1e-9:
                state = v
            else:
                break
        if state:
            ups = [t for t, v in downs if t > n.end and v == 0]
            end = ups[0] if ups else n.end + 5.0
        out.append((n.start + lead_in, end + lead_in))
    return out


def find_truncations(x: np.ndarray, intervals: list[tuple[float, float]]) -> list[dict]:
    """Notes that stop dead while they should sound (a sampler streaming underrun).

    1 ms frames; a truncation is a fall of more than 25 dB from the mean power of the
    10 frames before a frame boundary to the mean of the 10 frames after it (so a single
    quiet frame at a zero crossing of a bass note does not count), from a level within
    50 dB of the stem's loudest frame, at a time some note of the stem is held (or
    sustained by the pedal). A damper release (0.35 s envelope) falls about 2 dB in 10 ms.
    """
    m = x.mean(axis=1) if x.ndim == 2 else x
    fr = SR // 1000
    nf = len(m) // fr
    if nf < 30:
        return []
    p = (m[: nf * fr].reshape(nf, fr) ** 2).mean(axis=1) + 1e-30
    top = 10 * np.log10(p.max())
    k = np.ones(10) / 10
    before = 10 * np.log10(np.convolve(p, k, mode="full")[:nf])
    after = 10 * np.log10(np.convolve(p[::-1], k, mode="full")[:nf][::-1])
    d = after[1:] - before[:-1]
    cand = np.nonzero((d < -25) & (before[:-1] > top - 50))[0]
    out, last = [], -100
    for i in cand:
        t = (i + 1) / 1000
        if i - last > 20 and any(a + 0.003 < t < b + 0.002 for a, b in intervals):
            out.append({"t": round(t, 3), "drop_db": round(float(d[i]), 1),
                        "level_re_stem_max_db": round(float(before[i] - top), 1)})
        last = i
    return out


def fader(events: list, n: int, default: int, to_db, lead_in: float) -> np.ndarray | None:
    if not events:
        return None
    step = np.full(n, to_db(default), dtype=np.float64)
    for t, val in events:
        i = int(round((t + lead_in) * SR))
        if i < n:
            step[max(i, 0):] = to_db(val)
    w = int(FADER_SMOOTH * SR)
    kernel = np.ones(w) / w
    sm = np.convolve(np.concatenate([np.full(w, step[0]), step]), kernel, mode="full")[w : w + n]
    return 10 ** (sm / 20.0)


# ----------------------------------------------------------------------------------------
# Output processing
# ----------------------------------------------------------------------------------------
def true_peak(x: np.ndarray) -> float:
    up = ss.resample_poly(x, 4, 1, axis=0)
    return float(np.abs(up).max())


WET_DB_DEFAULT = 0.0  # hall energy = dry piano energy; the demo measures C80 +4.9 dB (see README)
IR_DIRECT = 48  # make_ir.py starts the IR 1 ms before the (removed) direct sound


def hall_gain_on_piano_db(ir: np.ndarray) -> float | None:
    """Energy gain of the IR (L->L, R->R) on the piano's long-term spectrum, in dB.

    The IR is scaled to unit energy, which is a gain of 0 dB for white noise. A piano puts
    most of its energy at 60-1000 Hz, where this hall's reverberation is strongest, so on
    piano material the same IR is about 9 dB louder. --wet-db is set against this gain, so
    that it is the hall's energy relative to the dry piano. The spectrum (1/3 octaves) is the
    one make_sfz.py measured on the samples (calibration JSON, "piano_ltas")."""
    if not CALIBRATION_JSON.exists():
        return None
    lt = json.loads(CALIBRATION_JSON.read_text()).get("piano_ltas")
    if not lt:
        return None
    centres = np.array(lt["centres_hz"])
    p = 10 ** (np.array(lt["energy_db"]) / 10)
    nfft = 1 << int(math.ceil(math.log2(len(ir))))
    h = (np.abs(np.fft.rfft(ir, nfft, axis=0)) ** 2).mean(axis=1)  # mean |H|^2 of white noise = IR energy
    f = np.fft.rfftfreq(nfft, 1 / SR)
    hb = np.array([h[(f >= c * 2 ** (-1 / 6)) & (f < c * 2 ** (1 / 6))].mean() for c in centres])
    return float(10 * np.log10(np.sum(p * hb) / np.sum(p)))


def hall_program_stats(dry: np.ndarray, wet: np.ndarray, ir: np.ndarray, g: float) -> dict:
    """Measured on this render: hall energy relative to the dry sum, and clarity C80 (dry
    sum plus the first 80 ms of the hall against the rest of the hall), broadband."""
    n80 = IR_DIRECT + int(0.080 * SR)
    early = np.stack([ss.fftconvolve(dry[:, c], ir[:n80, c]) for c in range(2)], axis=1)
    e_dry = float(np.sum(dry**2))
    e_wet = g * g * float(np.sum(wet**2))
    e_early_total = float(np.sum((np.pad(dry, ((0, len(early) - len(dry)), (0, 0))) + g * early) ** 2))
    late = wet.copy()
    late[: len(early)] -= early
    e_late = g * g * float(np.sum(late**2))
    return {"hall_re_dry_db": round(10 * math.log10(e_wet / e_dry), 1),
            "c80_db": round(10 * math.log10(e_early_total / e_late), 1)}


def measure_file(path: Path) -> dict | None:
    """EBU R128 integrated loudness, loudness range and true peak of a written file (ffmpeg)."""
    if shutil.which("ffmpeg") is None:
        return None
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-filter_complex",
                        "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    summary = r.stderr[r.stderr.rfind("Summary:"):]
    out = {}
    for key, label in (("integrated_lufs", "I:"), ("lra_lu", "LRA:"), ("true_peak_dbtp", "Peak:")):
        for line in summary.splitlines():
            if line.strip().startswith(label):
                try:
                    out[key] = float(line.split()[1])
                except ValueError:
                    pass
                break
    return out or None


# Attribution carried inside every render (CC-BY requires crediting the sample and IR authors).
CREDIT = (
    "Piano: Salamander Grand Piano V3 (Yamaha C5) by Alexander Holm, CC-BY 3.0 "
    "(https://creativecommons.org/licenses/by/3.0/), FLAC/SFZ packaging by FreePats. "
    "Hall: Detmold Konzerthaus impulse response from the Open Database of Spatial Room Impulse "
    "Responses at Detmold University of Music, S. V. Amengual Gari, B. Sahin, D. Eddy, M. Kob "
    "(AES 149th Convention, 2020), CC-BY 4.0 (https://zenodo.org/records/4116247). "
    "Rendered with sfizz (BSD-2-Clause) by ricercar/audio/piano/render_piano.py."
)
COPYRIGHT = ("Samples: Salamander Grand Piano V3, Alexander Holm, CC-BY 3.0. "
             "Impulse response: Detmold SRIR database, Amengual Gari et al., CC-BY 4.0.")
SOFTWARE = "ricercar render_piano.py + sfizz"


def tag_m4a(m4a: Path, title: str) -> bool:
    """Write the credit into the .m4a (remux with ffmpeg, audio stream copied untouched)."""
    if shutil.which("ffmpeg") is None:
        return False
    tmp = m4a.with_name(m4a.stem + ".tagging.m4a")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(m4a), "-map", "0",
                        "-c", "copy", "-map_metadata", "0", "-metadata", f"title={title}",
                        "-metadata", "artist=Salamander Grand Piano V3 (Alexander Holm), rendered by render_piano.py",
                        "-metadata", f"comment={CREDIT}", "-metadata", f"copyright={COPYRIGHT}",
                        "-metadata", f"encoder={SOFTWARE}", str(tmp)], capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, m4a)
    return True


def write_outputs(x: np.ndarray, out: Path, make_m4a: bool) -> dict:
    wav = out.with_suffix(".wav")
    # TPDF dither to 24 bit
    lsb = 2.0 ** -23
    d = (np.random.default_rng(0).random(x.shape) - np.random.default_rng(1).random(x.shape)) * lsb
    # RIFF INFO chunk (INAM/IART/ICMT/ICOP/ISFT); libsndfile needs the strings before the data.
    with sf.SoundFile(wav, "w", SR, x.shape[1], subtype="PCM_24", format="WAV") as f:
        f.title = out.name
        f.artist = "Salamander Grand Piano V3 (Alexander Holm), rendered by render_piano.py"
        f.comment = CREDIT
        f.copyright = COPYRIGHT
        f.software = SOFTWARE
        f.write(np.clip(x + d, -1, 1 - lsb))
    res = {"wav": str(wav)}
    if make_m4a:
        m4a = out.with_suffix(".m4a")
        if m4a.exists():
            m4a.unlink()
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "256000", str(wav), str(m4a)], check=True)
        res["m4a"] = str(m4a)
        res["m4a_tagged"] = tag_m4a(m4a, out.name)
    return res


def stereo_stats(x: np.ndarray) -> dict:
    """L/R correlation, mono fold-down level re stereo (overall, and the worst 1 s window
    within 30 dB of the loudest one), and balance (R minus L, dB)."""
    L, R = x[:, 0], x[:, 1]
    eL, eR = float(np.sum(L * L)), float(np.sum(R * R))
    if eL <= 0 or eR <= 0:
        return {}
    w = SR
    nw = len(L) // w
    worst = None
    if nw:
        Lw, Rw = L[: nw * w].reshape(nw, w), R[: nw * w].reshape(nw, w)
        st = np.mean((Lw**2 + Rw**2) / 2, axis=1) + 1e-30
        mo = np.mean(((Lw + Rw) / 2) ** 2, axis=1) + 1e-30
        loud = st > st.max() * 1e-3
        worst = round(float(np.min(10 * np.log10(mo[loud] / st[loud]))), 2)
    return {
        "lr_correlation": round(float(np.sum(L * R) / math.sqrt(eL * eR)), 3),
        "mono_fold_db": round(float(10 * np.log10(np.mean(((L + R) / 2) ** 2) / np.mean((L * L + R * R) / 2))), 2),
        "mono_fold_worst_1s_db": worst,
        "balance_r_minus_l_db": round(10 * math.log10(eR / eL), 2),
    }


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="Render multi-voice MIDI on a sampled concert grand (see docstring).",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("midi", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="output path without extension (default: next to the MIDI)")
    ap.add_argument("--wet-db", type=float, default=WET_DB_DEFAULT,
                    help=f"hall energy relative to the dry piano, on the piano's long-term spectrum (default "
                    f"{WET_DB_DEFAULT:g} dB; the render report gives the value and C80 measured on the render)")
    ap.add_argument("--no-reverb", action="store_true")
    ap.add_argument("--ir", type=Path, default=HALL_IR)
    ap.add_argument("--peak-db", type=float, default=-1.0, help="true-peak target (default -1 dBFS)")
    ap.add_argument("--lead-in", type=float, default=0.3, help="silence before the first note (s)")
    ap.add_argument("--dyn-db", type=float, default=0.0, help="global dynamic offset in dB, realised via velocity")
    ap.add_argument("--transpose", action="append", default=[], metavar="VOICE=N",
                    help="transpose one voice by N semitones (repeatable), e.g. pedal=-12")
    ap.add_argument("--stems", type=Path, help="write each voice's dry stem (float WAV) into this directory")
    ap.add_argument("--velocity-scale", choices=["auto", "raw", "perform"], default="auto",
                    help="raw: velocities are this piano's calibrated scale; perform: perform.py's scale "
                    "(pp 32, f 82, ff 98), remapped; auto (default): perform if the file was written by "
                    "perform.py, else raw")
    ap.add_argument("--cc-dynamics", choices=["auto", "velocity", "cc11", "gain", "off"], default="auto",
                    help="velocity: min(CC1, CC11) at each note-on -> hammer velocity; cc11: CC11 only -> "
                    "hammer velocity, CC1 ignored (General MIDI: CC1 is modulation); gain: CC1 -> velocity, "
                    "CC11 -> continuous fader; off: ignore CC1/CC11; auto (default): velocity for perform.py "
                    "--target piano files, off for perform.py --target strings files (their velocities already "
                    "carry the dynamics), cc11 for every other file")
    ap.add_argument("--cc11-mode", choices=["velocity", "gain"], help=argparse.SUPPRESS)  # old name
    ap.add_argument("--no-key-sharing", action="store_true")
    ap.add_argument("--no-fold", action="store_true",
                    help="fail on notes outside A0-C8 instead of folding them back by octaves (with a warning)")
    ap.add_argument("--quality", type=int, default=10, help="sfizz resampling quality 1-10 (10 = sinc72)")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 4),
                    help="parallel sfizz_render instances (default 4; each holds its voice's samples in RAM)")
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--no-m4a", action="store_true")
    ap.add_argument("--json", type=Path, help="write a JSON render report here")
    args = ap.parse_args(argv)

    check_instrument()
    if not args.no_reverb:
        check_hall_ir(args.ir)

    out = args.out or args.midi.with_suffix("")
    out.parent.mkdir(parents=True, exist_ok=True)
    transpose_arg = {}
    for t in args.transpose:
        k, v = t.split("=")
        transpose_arg[k.strip()] = int(v)

    marker = midi_marker(args.midi)
    vscale = args.velocity_scale
    if vscale == "auto":
        vscale = "perform" if marker.get("source") == "perform.py" else "raw"
    ccdyn = args.cc_dynamics
    if args.cc11_mode and ccdyn == "auto":
        ccdyn = args.cc11_mode
    if ccdyn == "auto":
        if marker.get("target") == "strings":
            ccdyn = "off"  # the velocities already carry the envelope that CC1/CC11 repeat
        elif marker.get("source") == "perform.py":
            ccdyn = "velocity"  # perform.py's convention: CC1 and CC11 both mean dynamics
        else:
            ccdyn = "cc11"  # General MIDI: CC11 is expression, CC1 is modulation (a GM reset sends CC1=0)
    print(f"velocity scale: {vscale}; CC dynamics: {ccdyn}"
          + (f"; written by perform.py --target {marker.get('target')}" if marker else ""))
    warnings: list[str] = []

    def warn(msg: str) -> None:
        warnings.append(msg)
        print(f"warning: {msg}", file=sys.stderr)

    voices = load_midi(args.midi)
    glob = voices.pop("__global__", None)
    if glob is not None:  # global CCs (e.g. CC64 on a conductor track)
        for v in voices.values():
            for cc, ev in glob.cc.items():
                v.cc.setdefault(cc, []).extend(ev)
                v.cc[cc].sort()
    voices = {k: v for k, v in voices.items() if v.notes}
    if not voices:
        raise SystemExit("no notes found")
    for v in voices.values():
        if v.renamed_from:
            warn(f"track {v.renamed_from!r} appears more than once; this one is voice {v.name!r} (its own stem, "
                 "CC7 fader and --transpose name)")
        if v.zero_length:
            warn(f"{v.name}: {v.zero_length} zero-length note(s) (note-on and note-off on one tick) "
                 f"played as {MIN_NOTE * 1000:.0f} ms")
        if v.unterminated:
            warn(f"{v.name}: {v.unterminated} note(s) without note-off played for 1 s")
    # Voice names match case-insensitively (perform.py writes "pedal", other files "Pedal").
    transpose = {}
    for name, semis in transpose_arg.items():
        hits = [v for v in voices if v.lower() == name.lower()]
        if not hits:
            raise SystemExit(f"--transpose: no voice named {name!r}; voices are {list(voices)}")
        for h in hits:
            transpose[h] = semis

    curve = VelocityCurve()
    all_notes = []
    cc_shift: dict[str, float] = {}
    for v in voices.values():
        cc1, cc11 = v.cc.get(1, []), v.cc.get(11, [])
        scaled, shifts = [], []
        for n in v.notes:
            vel = perform_velocity(n.velocity) if vscale == "perform" else n.velocity
            dyn = 127
            if ccdyn in ("velocity", "gain"):  # CC1 as dynamics (perform.py's convention)
                dyn = cc_value_at(cc1, n.start, 127)
            if ccdyn in ("velocity", "cc11"):  # CC11 (expression) at note-on
                dyn = min(dyn, cc_value_at(cc11, n.start, 127))
            delta = args.dyn_db + cc_db(dyn)
            n.vel_eff = curve.shift(vel, delta)
            scaled.append(vel)
            shifts.append(cc_db(dyn))
            all_notes.append(n)
        cc_shift[v.name] = float(np.mean(shifts))
        # A controller that silences a voice is almost always a misread file (for example a
        # General MIDI CC1=0 modulation reset read as dynamics with --cc-dynamics velocity).
        vin, veff = float(np.mean(scaled)), float(np.mean([n.vel_eff for n in v.notes]))
        if veff < 10 and vin >= 30:
            warn(f"{v.name}: mean velocity {vin:.0f} becomes {veff:.0f} (nearly silent): "
                 f"CC dynamics ({ccdyn}) move it by {cc_shift[v.name]:+.0f} dB on average"
                 + (f", --dyn-db by {args.dyn_db:+.0f} dB" if args.dyn_db else "")
                 + "; if the file uses CC1 as modulation or CC11 as a fader, try --cc-dynamics cc11 or off")

    # Key sharing works on sounding pitches. A note pushed off the keyboard (A0-C8), for
    # example by --transpose, is folded back by octaves, with a warning, or refused with
    # --no-fold.
    folded: dict[str, dict] = {}
    for n in all_notes:
        k = n.key + transpose.get(n.voice, 0)
        if not KEY_LO <= k <= KEY_HI:
            f = folded.setdefault(n.voice, {"notes": 0, "requested_range": [k, k]})
            f["notes"] += 1
            f["requested_range"] = [min(f["requested_range"][0], k), max(f["requested_range"][1], k)]
            while k < KEY_LO:
                k += 12
            while k > KEY_HI:
                k -= 12
        n.key = k
    for name, f in folded.items():
        lo, hi = f["requested_range"]
        msg = (f"{name}: {f['notes']} note(s) outside the keyboard A0-C8 (MIDI {lo}..{hi}"
               + (f", transpose {transpose[name]:+d}" if transpose.get(name) else "") + ")")
        if args.no_fold:
            raise SystemExit(f"{msg}; --no-fold refuses to fold them into range")
        warn(f"{msg} folded back by octaves")
    share = {"unisons_merged": 0, "restrikes": 0} if args.no_key_sharing else share_keyboard(all_notes)
    pedal = pedal_events(voices)

    tmp = Path(tempfile.mkdtemp(prefix="piano_render_"))
    names = list(voices)
    jobs = []
    for i, name in enumerate(names):
        mid = tmp / f"stem{i:02d}.mid"
        wav = tmp / f"stem{i:02d}.wav"
        write_stem_midi(mid, voices[name].notes, pedal, 0, args.lead_in)
        keys = {n.key for n in voices[name].notes if not n.dropped}
        sfz = prune_sfz(DERIVED_SFZ if i == 0 else DERIVED_SFZ_NO_PEDAL_NOISE, keys, tmp / f"stem{i:02d}.sfz")
        jobs.append((sfz, mid, wav))
    print(f"rendering {len(names)} voice stem(s) with sfizz: {', '.join(names)}")
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        list(ex.map(lambda j: run_sfizz(j[0], j[1], j[2], args.quality), jobs))

    # Guard against dropped notes: a stem in which a held note stops dead is rendered again.
    truncation = {"checked_stems": len(jobs), "rerendered": {}, "found": {}}
    for i, (name, j) in enumerate(zip(names, jobs)):
        spans = sounding_intervals(voices[name].notes, pedal, args.lead_in)
        for attempt in range(3):
            x = sf.read(j[2], dtype="float64", always_2d=True)[0]
            hits = find_truncations(x, spans)
            if not hits:
                break
            truncation["found"].setdefault(name, []).append(hits)
            if attempt == 2:
                raise SystemExit(f"{name}: notes stop while held after 3 renders ({hits[:3]}); "
                                 f"stem kept in {tmp}")
            warn(f"{name}: {len(hits)} note(s) cut while held at {[h['t'] for h in hits][:5]} s; rendering again")
            truncation["rerendered"][name] = attempt + 1
            run_sfizz(j[0], j[1], j[2], args.quality)

    stems = [sf.read(j[2], dtype="float64", always_2d=True)[0] for j in jobs]
    n = max(len(s) for s in stems)
    ir = None
    hall_gain = None
    if not args.no_reverb:
        ir, ir_sr = sf.read(args.ir, dtype="float64", always_2d=True)
        assert ir_sr == SR, "IR must be 48 kHz"
        hall_gain = hall_gain_on_piano_db(ir)
        if hall_gain is None:
            warn("no piano spectrum in the calibration JSON: --wet-db is taken against the IR's white-noise gain")
            hall_gain = 0.0
    tail = 0 if ir is None else len(ir)
    dry = np.zeros((n + tail, 2))
    report_voices = {}
    for name, s in zip(names, stems):
        v = voices[name]
        s = np.pad(s, ((0, n + tail - len(s)), (0, 0)))
        g7 = fader(v.cc.get(7, []), len(s), 100, lambda c: -120.0 if c <= 0 else 40 * math.log10(c / 100), args.lead_in)
        if g7 is not None:
            s *= g7[:, None]
        if ccdyn == "gain":
            g11 = fader(v.cc.get(11, []), len(s), 127, cc_db, args.lead_in)
            if g11 is not None:
                s *= g11[:, None]
        dry += s
        vel = [x.vel_eff for x in v.notes if not x.dropped]
        report_voices[name] = {
            "notes": len(vel),
            "velocity_in_mean": round(float(np.mean([x.velocity for x in v.notes])), 1),
            "velocity_in_range": [int(min(x.velocity for x in v.notes)), int(max(x.velocity for x in v.notes))],
            "velocity_eff_mean": round(float(np.mean(vel)), 1) if vel else None,
            "velocity_eff_range": [int(min(vel)), int(max(vel))] if vel else None,
            "cc_dynamics_db_mean": round(cc_shift[name], 2),
            "rms_dbfs_prenorm": round(float(10 * np.log10(np.mean(s**2) + 1e-20)), 2),
            "transpose": transpose.get(name, 0),
            "zero_length_notes": v.zero_length,
            "unterminated_notes": v.unterminated,
            "folded_notes": folded.get(name, {}).get("notes", 0),
            "stereo": stereo_stats(s[:n]),
        }
        if args.stems:
            args.stems.mkdir(parents=True, exist_ok=True)
            sf.write(args.stems / f"{name.replace('/', '_')}.wav", s[:n].astype(np.float32), SR, subtype="FLOAT")

    stereo_dry = stereo_stats(dry[:n])
    mix = dry.copy()
    hall = None
    if ir is not None:
        g = 10 ** ((args.wet_db - hall_gain) / 20)
        # L->L, R->R: each side of the piano excites its own side of the hall IR.
        wet = np.stack([ss.fftconvolve(dry[:n, c], ir[:, c]) for c in range(2)], axis=1)
        mix[: len(wet)] += g * wet[: len(mix)]
        hall = {"wet_db": args.wet_db, "ir_gain_on_piano_spectrum_db": round(hall_gain, 2),
                "ir_scale_db": round(20 * math.log10(g), 2), **hall_program_stats(dry[:n], wet, ir, g)}
        del wet

    # Remove DC/rumble, trim the silent tail, normalise the true peak.
    mix = ss.sosfilt(ss.butter(2, 18, "high", fs=SR, output="sos"), mix, axis=0)
    env = np.abs(mix).max(axis=1)
    thr = env.max() * 10 ** (-80 / 20)
    last = int(np.nonzero(env > thr)[0][-1]) + int(0.05 * SR)
    mix = mix[: min(last, len(mix))]
    fade = min(int(0.05 * SR), len(mix))
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    tp = true_peak(mix)
    gain = 10 ** (args.peak_db / 20) / tp
    mix *= gain
    if 20 * math.log10(gain) > 20:
        warn(f"the render needed {20 * math.log10(gain):+.1f} dB of make-up gain to reach {args.peak_db:g} dBTP: "
             "it is nearly silent before normalisation (check velocities, CC1/CC11/CC7, --cc-dynamics)")
    files = write_outputs(mix, out, not args.no_m4a)

    if not args.keep_temp:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        files["temp"] = str(tmp)

    report = {
        "input": str(args.midi),
        **files,
        "midi_marker": marker or None,
        "velocity_scale": vscale,
        "cc_dynamics": ccdyn,
        "duration_s": round(len(mix) / SR, 2),
        "voices": report_voices,
        "key_sharing": share,
        "folded_notes": folded,
        "truncation_check": truncation,
        "pedal_changes": len(pedal),
        "wet_db": None if ir is None else args.wet_db,
        "c80_db": None if hall is None else hall["c80_db"],
        "hall": hall,
        "normalise_gain_db": round(20 * math.log10(gain), 2),
        "true_peak_dbfs": args.peak_db,
        "rms_dbfs": round(float(10 * np.log10(np.mean(mix**2))), 2),
        "stereo": {"dry": stereo_dry, "mix": stereo_stats(mix)},
        "measured": {k: measure_file(Path(files[k])) for k in ("wav", "m4a") if k in files},
        "warnings": warnings,
    }
    print(json.dumps(report, indent=1))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    main()
