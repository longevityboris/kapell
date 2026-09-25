#!/usr/bin/env python3
"""Write the piano dynamics/voicing test MIDI and its segment map.

Usage::

    python3 make_test_midi.py [-o out/dynamics_test.mid]

Writes ``dynamics_test.mid`` (type 1: conductor track plus four voice tracks,
Soprano/Alto/Tenor/Bass on channels 1-4, quarter = 108) and
``dynamics_test.segments.json``, which ``analyse_dynamics.py`` reads.

Segments, all using the ricercar theme (bars 1-4, B-flat major) or material
derived from it:

1. ``pp``, 2. ``mf``, 3. ``ff``: the same phrase (theme in the soprano over a
   bass line), at the calibrated pp, mf and ff velocities of make_sfz.py
   (``suggested_velocities`` in the calibration JSON: 30 / 86 / 115).
4. ``cresc_velocity``: a B-flat chord (F3 B-flat3 D4 F4) repeated 29 times
   in eighths. The velocity rises 18 -> 120 and falls back. A piano cannot
   swell a held note, so this is how a pianist makes a crescendo. Repeating
   one chord keeps pitch from confounding the timbre measurement.
5. ``cresc_cc11``: the same chords at a constant velocity of 120, with the
   dynamic shaped only by CC11 (36 -> 127 -> 36). This proves that
   expression is realised as hammer velocity, so timbre changes too.
6. ``voicing_flat``: four-part texture, theme head in the tenor (an inner
   voice), all voices at velocity 60.
7. ``voicing_tenor``: the same, tenor at 80 and the other voices at 56. This
   is the pianist's "bring out the inner voice".
8. ``pedal``: a B-flat arpeggio under CC64 (pedal down, up at the end), to
   exercise the sustain pedal, pedal noises and delayed damping.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mido

TPB = 480
BPM = 108
Q = 60.0 / BPM  # seconds per quarter
GAP_Q = 4  # quarters of silence between segments

# theme bars 1-4 (sounding pitch), (midi, quarters)
THEME = [(70, 3), (70, 0.5), (69, 0.5), (70, 3), (70, 0.5), (69, 0.5),
         (70, 1.5), (72, 0.5), (72, 1.5), (75, 0.5), (75, 3), (74, 0.5), (70, 0.5)]
BASS = [(46, 4), (50, 2), (46, 2), (51, 2), (48, 2), (41, 3), (46, 1)]
CHORD = [53, 58, 62, 65]  # F3 B-flat3 D4 F4, repeated so that pitch does not confound timbre
HITS = 29


def calibrated_marks() -> dict:
    """pp/mf/ff velocities of the derived instrument (make_sfz.py's calibration JSON)."""
    marks = {"pp": 29, "mf": 86, "ff": 115}
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from piano_paths import CALIBRATION_JSON
        marks.update({k: v for k, v in json.loads(CALIBRATION_JSON.read_text())["suggested_velocities"].items()
                      if k in marks})
    except (OSError, KeyError, ImportError):
        pass
    return marks


MARKS = calibrated_marks()


def main() -> None:
    ap = argparse.ArgumentParser(description="write the dynamics test MIDI")
    ap.add_argument("-o", "--out", type=Path, default=Path(__file__).resolve().parent / "out" / "dynamics_test.mid")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    names = ["Soprano", "Alto", "Tenor", "Bass"]
    ev = {n: [] for n in names}  # (quarter, order, msg)
    segs = []
    t = 1.0  # quarters

    def note(voice, start, dur, key, vel, legato=0.97):
        ch = names.index(voice)
        ev[voice].append((start, 1, mido.Message("note_on", channel=ch, note=key, velocity=vel)))
        ev[voice].append((start + dur * legato, 0, mido.Message("note_off", channel=ch, note=key, velocity=64)))

    def cc(voice, at, num, val):
        ev[voice].append((at, 0, mido.Message("control_change", channel=names.index(voice), control=num, value=val)))

    # 1-3: same phrase at pp, mf, ff
    for label, vel in [("pp", MARKS["pp"]), ("mf", MARKS["mf"]), ("ff", MARKS["ff"])]:
        s = t
        x = t
        for key, d in THEME:
            note("Soprano", x, d, key, vel)
            x += d
        x = t
        for key, d in BASS:
            note("Bass", x, d, key, vel)
            x += d
        segs.append({"name": label, "start_q": s, "end_q": x, "velocity": vel, "kind": "phrase"})
        t = x + GAP_Q

    # 4: crescendo/diminuendo by velocity
    s = t
    n = HITS
    notes = []
    for i in range(n):
        frac = i / ((n - 1) / 2) if i <= (n - 1) / 2 else (n - 1 - i) / ((n - 1) / 2)
        vel = int(round(18 + (120 - 18) * frac))
        for key in CHORD:
            note("Soprano", t + 0.5 * i, 0.5, key, vel, legato=0.85)
        notes.append({"t_q": t + 0.5 * i, "keys": CHORD, "velocity": vel})
    segs.append({"name": "cresc_velocity", "start_q": s, "end_q": t + 0.5 * n, "notes": notes, "kind": "ramp"})
    t = t + 0.5 * n + GAP_Q

    # 5: crescendo/diminuendo by CC11 only (constant velocity 120)
    s = t
    notes = []
    for i in range(n):
        frac = i / ((n - 1) / 2) if i <= (n - 1) / 2 else (n - 1 - i) / ((n - 1) / 2)
        val = int(round(36 + (127 - 36) * frac))
        cc("Alto", t + 0.5 * i - 0.01, 11, val)
        for key in CHORD:
            note("Alto", t + 0.5 * i, 0.5, key, 120, legato=0.85)
        notes.append({"t_q": t + 0.5 * i, "keys": CHORD, "velocity": 120, "cc11": val})
    cc("Alto", t + 0.5 * n, 11, 127)
    segs.append({"name": "cresc_cc11", "start_q": s, "end_q": t + 0.5 * n, "notes": notes, "kind": "ramp"})
    t = t + 0.5 * n + GAP_Q

    # 6-7: voicing (theme head in the tenor, inner voice)
    tenor = [(58, 3), (58, 0.5), (57, 0.5), (58, 3), (58, 0.5), (57, 0.5)]
    sop = [(74, 4), (75, 2), (74, 2)]
    alto = [(65, 4), (67, 2), (65, 2)]
    bass = [(46, 4), (51, 2), (46, 2)]
    for label, vt, vo in [("voicing_flat", 60, 60), ("voicing_tenor", 80, 56)]:
        s = t
        for voice, line, vel in [("Soprano", sop, vo), ("Alto", alto, vo), ("Tenor", tenor, vt), ("Bass", bass, vo)]:
            x = t
            for key, d in line:
                note(voice, x, d, key, vel)
                x += d
        segs.append({"name": label, "start_q": s, "end_q": x, "tenor_velocity": vt, "others_velocity": vo,
                     "kind": "voicing"})
        t = x + GAP_Q

    # 8: pedal
    s = t
    cc("Bass", t - 0.25, 64, 127)
    for i, key in enumerate([46, 53, 58, 62, 65, 70, 74, 77]):
        note("Bass" if key < 60 else "Tenor", t + 0.5 * i, 0.5, key, 70, legato=0.6)
    cc("Bass", t + 8, 64, 0)
    segs.append({"name": "pedal", "start_q": s, "end_q": t + 8, "kind": "pedal"})
    t = t + 8 + GAP_Q

    mf = mido.MidiFile(type=1, ticks_per_beat=TPB)
    cond = mido.MidiTrack()
    cond.append(mido.MetaMessage("track_name", name="dynamics test", time=0))
    cond.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM), time=0))
    last = 0
    for sg in segs:
        tick = int(round(sg["start_q"] * TPB))
        cond.append(mido.MetaMessage("marker", text=sg["name"], time=tick - last))
        last = tick
    mf.tracks.append(cond)
    for name in names:
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        now = 0
        for q, _, msg in sorted(ev[name], key=lambda e: (e[0], e[1])):
            tick = int(round(q * TPB))
            msg.time = tick - now
            now = tick
            tr.append(msg)
        mf.tracks.append(tr)
    mf.save(args.out)

    for sg in segs:
        sg["start_s"] = sg["start_q"] * Q
        sg["end_s"] = sg["end_q"] * Q
        for nt in sg.get("notes", []):
            nt["t_s"] = nt["t_q"] * Q
    seg_path = args.out.with_suffix(".segments.json")
    seg_path.write_text(json.dumps({"bpm": BPM, "segments": segs}, indent=1))
    print(f"wrote {args.out} ({t * Q:.1f} s) and {seg_path}")


if __name__ == "__main__":
    main()
