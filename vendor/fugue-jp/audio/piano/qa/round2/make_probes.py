#!/usr/bin/env python3
"""Round-2 adversarial probe MIDI files for render_piano.py (written to /tmp/pianoqa2).

Every probe is a plain type-1 MIDI without the perform.py marker, so the renderer
reads velocities on its own calibrated scale (``--velocity-scale auto`` -> raw).
Times below are seconds at 120 bpm, 480 ticks per beat (1 tick = 1/960 s).

  iso        every key A0..C8 once, velocity 80, 1.0 s held, 1.6 s apart (onset, pitch, release)
  velsweep   C2, C4, C6 on separate tracks, velocity 1..127 step 2, 0.45 s held, 0.6 s apart
  stemend    a short C7 (no damper) as the very last event; and a pedal held to the end
  repeat     fast repeated notes on one key (note_polyphony=2 voice stealing), with and without pedal
  fast16     16th-note scales at quarter = 66, 100, 144 in the bass and the tenor register
  keyshare   two voices on one key: unison offsets 0-45 ms, re-strike of a held key
  oddities   type-0 multi-channel file, velocity-0 note-offs, same-key overlaps in one voice,
             duplicate track names, CC64 on a conductor track, tempo change mid-note
"""
from __future__ import annotations

import json
from pathlib import Path

import mido

OUT = Path("/tmp/pianoqa2")
TPB = 480
TPS = 960  # ticks per second at 120 bpm


def tk(sec: float) -> int:
    return int(round(sec * TPS))


def track(name: str | None, events: list, channel: int = 0) -> mido.MidiTrack:
    """events: (sec, kind, a, b) with kind on/off/cc."""
    tr = mido.MidiTrack()
    if name is not None:
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
    ev = []
    for e in events:
        sec, kind = e[0], e[1]
        ch = e[4] if len(e) > 4 else channel
        if kind == "on":
            ev.append((tk(sec), 2, mido.Message("note_on", note=e[2], velocity=e[3], channel=ch)))
        elif kind == "off":
            ev.append((tk(sec), 1, mido.Message("note_off", note=e[2], velocity=0, channel=ch)))
        elif kind == "off0":  # note_on velocity 0 as note-off
            ev.append((tk(sec), 1, mido.Message("note_on", note=e[2], velocity=0, channel=ch)))
        elif kind == "cc":
            ev.append((tk(sec), 0, mido.Message("control_change", control=e[2], value=e[3], channel=ch)))
    ev.sort(key=lambda x: (x[0], x[1]))
    now = 0
    for t, _, m in ev:
        m.time = t - now
        now = t
        tr.append(m)
    return tr


def save(name: str, tracks: list, meta: dict, tempo_events=None, mtype=1) -> None:
    mf = mido.MidiFile(type=mtype, ticks_per_beat=TPB)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage("track_name", name="tempo", time=0))
    now = 0
    for tick, us in tempo_events or [(0, 500000)]:
        t0.append(mido.MetaMessage("set_tempo", tempo=us, time=tick - now))
        now = tick
    if mtype == 0:
        # merge everything into one track
        merged = mido.merge_tracks([t0] + tracks)
        mf.tracks.append(merged)
    else:
        mf.tracks.append(t0)
        mf.tracks.extend(tracks)
    mf.save(OUT / f"{name}.mid")
    (OUT / f"{name}.meta.json").write_text(json.dumps(meta, indent=1))


def notes(seq):
    ev = []
    for st, key, dur, vel in seq:
        ev += [(st, "on", key, vel), (st + dur, "off", key, 0)]
    return ev


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # iso
    seq = [(0.5 + 1.6 * i, k, 1.0, 80) for i, k in enumerate(range(21, 109))]
    save("iso", [track("iso", notes(seq))], {"notes": seq})

    # velsweep: one track per key
    trs, meta = [], {}
    t = 0.5
    for key, nm in ((36, "c2"), (60, "c4"), (84, "c6")):
        s = []
        for v in range(1, 128, 2):
            s.append((t, key, 0.45, v))
            t += 0.6
        trs.append(track(nm, notes(s)))
        meta[nm] = s
        t += 1.0
    save("velsweep", trs, meta)

    # stemend: a C7 as the last event (ampeg_release=5 group), then a pedal never released
    save("stemend_top", [track("top", notes([(0.5, 96, 0.2, 90)]))], {"notes": [(0.5, 96, 0.2, 90)]})
    ped = notes([(0.5, 48, 0.3, 90), (0.5, 55, 0.3, 90), (0.5, 64, 0.3, 90)]) + [(0.2, "cc", 64, 127)]
    save("stemend_pedal", [track("chord", ped)], {"notes": [(0.5, k, 0.3, 90) for k in (48, 55, 64)],
                                                  "pedal_down": 0.2})

    # repeat: 16 repeated 16ths at quarter = 150 (0.1 s), 80 ms held
    s, cc, segs = [], [], {}
    t = 0.5
    for label, key, pedal in (("c4_dry", 60, False), ("c2_dry", 36, False), ("c4_pedal", 60, True),
                              ("g6_nodamper", 91, False), ("c4_legato_overlap", 60, False)):
        t0 = t
        if pedal:
            cc.append((t - 0.05, "cc", 64, 127))
        for i in range(16):
            dur = 0.08 if label != "c4_legato_overlap" else 0.14  # overlap: the next on before this off
            s.append((t, key, dur, 70 + (i % 4) * 8))
            t += 0.1
        if pedal:
            cc.append((t + 0.3, "cc", 64, 0))
        segs[label] = [t0, t]
        t += 2.5
    # c4_legato_overlap: same key, on before off in ONE voice -> tests FIFO pairing + restrike
    save("repeat", [track("rep", notes(s) + cc)], {"notes": s, "segments": segs})

    # fast16: scales C2..C3 up and down in 16ths
    s, segs = [], {}
    t = 0.5
    scale = [36, 38, 40, 41, 43, 45, 47, 48, 50, 52, 53, 55, 57, 59, 60]
    for q in (66, 100, 144):
        for base, reg in ((0, "bass"), (12, "tenor")):
            d16 = 60.0 / q / 4
            t0 = t
            run = scale + scale[-2::-1]
            for k in run:
                s.append((t, k + base, d16 - 0.012, 72))
                t += d16
            segs[f"{reg}_q{q}"] = [t0, t, d16]
            t += 2.0
    save("fast16", [track("run", notes(s))], {"notes": s, "segments": segs})

    # keyshare: voice A holds C4 1.0 s; voice B strikes C4 at offsets
    a, b, cases = [], [], []
    t = 0.5
    for off in (0.0, 0.010, 0.020, 0.029, 0.031, 0.045, 0.300):
        a.append((t, 60, 1.0, 60))
        b.append((t + off, 60, 0.5, 90))
        cases.append({"t": t, "offset": off})
        t += 3.0
    save("keyshare", [track("A", notes(a)), track("B", notes(b))], {"cases": cases, "A": a, "B": b})

    # oddities
    ev0 = notes([(0.5, 60, 0.5, 80)])  # ch 1
    ev1 = [(0.5, "on", 64, 80, 1), (1.0, "off0", 64, 0, 1)]  # ch 2, vel-0 note-off
    ev2 = [(0.5, "on", 67, 80, 2), (0.7, "on", 67, 80, 2), (0.9, "off", 67, 0, 2), (1.3, "off", 67, 0, 2)]
    tr = track("multi", ev0 + ev1 + ev2)
    save("odd_type0", [tr], {"channels": 3}, mtype=0)
    # duplicate names, unnamed track, conductor CC64, tempo change mid-note
    t_a = track("soprano", notes([(0.5, 72, 1.0, 80)]))
    t_b = track("soprano", notes([(0.6, 76, 1.0, 80)]))
    t_c = track(None, notes([(0.5, 48, 1.0, 80)]))
    t_d = track("conductor", [(0.4, "cc", 64, 127), (2.5, "cc", 64, 0)])
    # tempo 120 -> 60 at tick 960 (1.0 s): a note 0.5..(tick 1440) lasts 0.5 + 1.0 = 1.5 s
    save("odd_names", [t_a, t_b, t_c, t_d], {"tempo_change_at_s": 1.0},
         tempo_events=[(0, 500000), (960, 1000000)])


if __name__ == "__main__":
    main()
