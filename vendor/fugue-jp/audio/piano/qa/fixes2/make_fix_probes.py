#!/usr/bin/env python3
"""Probe MIDI files for re-checking the QA round-2 defects after the fixes (written to /tmp/pianofix2).

Reuses the round-2 probe generator (qa/round2/make_probes.py: iso, velsweep, fast16,
odd_names, ...) with its output directory redirected, and recreates the two probes the
round-2 QA wrote by hand:

  gm_cc1reset  General MIDI style file (no perform.py marker): per track CC121, CC1=0
               (modulation reset), CC7=100, CC11=127 at t=0, then notes at velocity 100
  ffchord_end  ff chord C2 G2 C3 E3 G3 C4, velocity 120, 0.4 s, then nothing (hall tail)
  pedal_rel    C4-E4-G4 lifted one after the other under the sustain pedal, then the same
               without pedal (hammer-noise release samples at key-up, not at pedal-up)
"""
from __future__ import annotations

import sys
from pathlib import Path

import mido

OUT = Path("/tmp/pianofix2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "round2"))
import make_probes  # noqa: E402


def gm_cc1reset() -> None:
    mf = mido.MidiFile(type=1, ticks_per_beat=480)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    mf.tracks.append(t0)
    for ch, (name, keys) in enumerate((("Piano RH", [72, 74, 76, 77, 79, 77, 76, 74]),
                                       ("Piano LH", [48, 43, 48, 43, 48, 43, 48, 36]))):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        tr.append(mido.Message("program_change", channel=ch, program=0, time=0))
        for cc, val in ((121, 0), (1, 0), (7, 100), (11, 127)):
            tr.append(mido.Message("control_change", channel=ch, control=cc, value=val, time=0))
        gap = 0
        for k in keys:
            tr.append(mido.Message("note_on", channel=ch, note=k, velocity=100, time=gap))
            tr.append(mido.Message("note_off", channel=ch, note=k, velocity=0, time=440))
            gap = 40
        mf.tracks.append(tr)
    mf.save(OUT / "gm_cc1reset.mid")


def ffchord_end() -> None:
    mf = mido.MidiFile(type=1, ticks_per_beat=480)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    mf.tracks.append(t0)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name="chord", time=0))
    keys = [36, 43, 48, 52, 55, 60]
    for i, k in enumerate(keys):
        tr.append(mido.Message("note_on", note=k, velocity=120, time=480 if i == 0 else 0))
    for i, k in enumerate(keys):
        tr.append(mido.Message("note_off", note=k, velocity=0, time=384 if i == 0 else 0))  # 0.4 s
    mf.tracks.append(tr)
    mf.save(OUT / "ffchord_end.mid")


def pedal_rel() -> None:
    """Keys lifted at 1.0, 1.5, 2.0 s under the pedal (pedal up at 3.0 s); the same chord
    without pedal from 5 s (keys lifted at 6.0, 6.5, 7.0 s)."""
    ev = [(0.4, "cc", 64, 127), (3.0, "cc", 64, 0)]
    for base, ped in ((0.5, True), (5.5, False)):
        for i, k in enumerate((60, 64, 67)):
            ev += [(base, "on", k, 70), (base + 0.5 + 0.5 * i, "off", k, 0)]
    make_probes.save("pedal_rel", [make_probes.track("rel", ev)],
                     {"pedal": [0.4, 3.0], "keyups_pedal": [1.0, 1.5, 2.0], "keyups_dry": [6.0, 6.5, 7.0]})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    make_probes.OUT = OUT
    make_probes.main()
    gm_cc1reset()
    ffchord_end()
    pedal_rel()
    print("probes in", OUT)


if __name__ == "__main__":
    main()
