#!/usr/bin/env python3
"""Generate the dynamics proof MIDI files for the quartet renderer.

For each instrument the same short phrase (quarters, eighths, a sixteenth run
and a held half note) is played three times, at pp (CC1 = 49), mf (CC1 = 88)
and ff (CC1 = 114) -- perform.py's scale, where each recorded layer plays
alone -- all with the same velocity (90) so that only CC1 differs.
Then one note is held for 9 s while CC1 sweeps 40 -> 124 -> 40 (crescendo and
diminuendo).  A JSON sidecar lists every segment's start/end time so
measure_dynamics.py can report RMS and timbre per segment.

Usage:
  python3 make_test_midi.py OUTDIR            # dyn_<inst>.mid for vn/va/vc/cb + dyn_quartet.mid
Tracks are named "Violin I", "Violin II", "Viola", "Cello", "Contrabass" so
render_quartet.py maps them automatically.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import mido

TPB = 960
BPM = 96
SPB = 60.0 / BPM

# phrase in beats: (start, dur, semitone offset from tonic)
PHRASE = [
    (0.0, 1.0, 0), (1.0, 1.0, 4), (2.0, 0.5, 7), (2.5, 0.5, 5), (3.0, 0.5, 4), (3.5, 0.5, 2),
    (4.0, 0.25, 0), (4.25, 0.25, 2), (4.5, 0.25, 4), (4.75, 0.25, 5),
    (5.0, 0.25, 7), (5.25, 0.25, 9), (5.5, 0.25, 11), (5.75, 0.25, 12),
    (6.0, 2.0, 7),
]
PHRASE_BEATS = 8.0
GAP_BEATS = 2.0
SWELL_BEATS = 14.4          # 9 s at 96 bpm
TONIC = {"Violin I": 67, "Violin II": 67, "Viola": 60, "Cello": 48, "Contrabass": 36}
SHORT = {"Violin I": "vn1", "Violin II": "vn2", "Viola": "va", "Cello": "vc", "Contrabass": "cb"}
LEVELS = [("pp", 49), ("mf", 88), ("ff", 114)]
SWELL_LO, SWELL_HI = 40, 124


def track_events(name: str, tonic: int):
    ev = []                      # (beat, order, msg)
    segs = []
    b = 0.0
    ev.append((0.0, 0, mido.Message("control_change", control=11, value=127)))
    for label, cc in LEVELS:
        ev.append((b, 0, mido.Message("control_change", control=1, value=cc)))
        for (s, d, off) in PHRASE:
            ev.append((b + s, 2, mido.Message("note_on", note=tonic + off, velocity=90)))
            ev.append((b + s + d, 1, mido.Message("note_off", note=tonic + off, velocity=0)))
        segs.append(dict(label=label, cc1=cc, start=b * SPB, end=(b + PHRASE_BEATS) * SPB))
        b += PHRASE_BEATS + GAP_BEATS
    # crescendo / diminuendo on a held note (the dominant)
    ev.append((b, 0, mido.Message("control_change", control=1, value=SWELL_LO)))
    ev.append((b + 0.01, 2, mido.Message("note_on", note=tonic + 7, velocity=70)))
    steps = 200
    for i in range(1, steps + 1):
        t = b + SWELL_BEATS * i / steps
        x = i / steps
        v = round(SWELL_LO + (SWELL_HI - SWELL_LO) * (1 - abs(2 * x - 1)))
        ev.append((t, 0, mido.Message("control_change", control=1, value=v)))
    ev.append((b + SWELL_BEATS, 1, mido.Message("note_off", note=tonic + 7, velocity=0)))
    segs.append(dict(label="swell", cc1=f"{SWELL_LO}-{SWELL_HI}-{SWELL_LO}", lo=SWELL_LO, hi=SWELL_HI,
                     start=b * SPB, end=(b + SWELL_BEATS) * SPB))
    return ev, segs, b + SWELL_BEATS + 3


def write(path: Path, names: list[str], offset_beats: dict | None = None):
    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
    mid.tracks.append(meta)
    side = {}
    for ch, name in enumerate(names):
        ev, segs, total = track_events(name, TONIC[name])
        shift = (offset_beats or {}).get(name, 0.0)
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        tr.append(mido.Message("program_change", program={"Violin I": 40, "Violin II": 40, "Viola": 41,
                                                          "Cello": 42, "Contrabass": 43}[name], channel=ch))
        ev.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for beat, _, msg in ev:
            tick = int(round((beat + shift) * TPB))
            tr.append(msg.copy(channel=ch, time=tick - last))
            last = tick
        tr.append(mido.MetaMessage("end_of_track", time=int(3 * TPB)))
        mid.tracks.append(tr)
        side[name] = [dict(s, start=s["start"] + shift * SPB, end=s["end"] + shift * SPB) for s in segs]
    mid.save(str(path))
    path.with_suffix(".json").write_text(json.dumps(side, indent=1))
    return path


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name in ["Violin I", "Viola", "Cello", "Contrabass"]:
        print(write(out / f"dyn_{SHORT[name]}.mid", [name]))
    print(write(out / "dyn_quartet.mid", ["Violin I", "Violin II", "Viola", "Cello"]))


if __name__ == "__main__":
    main()
