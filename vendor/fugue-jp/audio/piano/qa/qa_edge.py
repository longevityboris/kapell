#!/usr/bin/env python3
"""MIDI-contract edge cases and artefact probes for render_piano.py.

    python3 qa/qa_edge.py      # writes qa/results/edge.json

1. unison_offsets: two voices strike the same key 0/3/6/10/15/25 ms apart
   (perform.py's humanise is +-5..6 ms per note, plus an 8 ms lead for
   subject/answer roles). Reports what key sharing did and the level and
   double-attack of the result against a single note.
2. repeats: 8 (and 16) repeated 16ths on one key with and without CC64 held
   (derived SFZ has note_polyphony=2): click scan at every onset.
3. zero_length: note_on and note_off on the same tick.
4. type0: one track, 4 channels -> voice names.
5. conductor_cc: CC64 on a note-less conductor track; CC7 fader jump.
6. transpose_fold: a pedal note that falls below A0 after --transpose.
7. strings_target: perform.py --target strings file rendered with auto.
8. bad_transpose: --transpose on a voice that does not exist.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, PIANO, SR, TMP, db, f0_estimate, onset_flux, read, render, rms_db, save, write_midi  # noqa: E402

N = mido.Message


def click_scan(x: np.ndarray, times: list[float], win: float = 0.004) -> list[float]:
    """Crest of the 2nd difference (HF impulse) around each event vs its local 50 ms background, dB."""
    m = x.mean(axis=1)
    d2 = np.abs(np.diff(m, 2))
    out = []
    for t in times:
        i = int(t * SR)
        a = d2[max(0, i - int(win * SR)): i + int(win * SR)]
        bg = d2[max(0, i - int(0.06 * SR)): max(1, i - int(0.01 * SR))]
        out.append(round(20 * np.log10((a.max() + 1e-12) / (np.sqrt(np.mean(bg ** 2)) + 1e-12)), 1))
    return out


def unison_offsets() -> dict:
    res = {}
    for off_ms in (0, 3, 6, 10, 15, 25):
        t0, off = 0.5, off_ms / 1000
        tracks = {"soprano": [(t0 + off, N("note_on", note=67, velocity=70)), (t0 + off + 0.4, N("note_off", note=67, velocity=0))],
                  "alto": [(t0, N("note_on", note=67, velocity=66)), (t0 + 0.42, N("note_off", note=67, velocity=0))]}
        mid = TMP / f"unison_{off_ms}.mid"
        write_midi(mid, tracks)
        rep = render(mid, TMP / f"unison_{off_ms}", "--no-reverb", "--no-m4a", "--peak-db", "-20")
        x = sum(read(TMP / f"unison_{off_ms}_stems" / f"{v}.wav") for v in ("soprano", "alto")
                if (TMP / f"unison_{off_ms}_stems" / f"{v}.wav").exists())
        a = int((t0 + LEAD_IN) * SR)
        ft, flux = onset_flux(x[a - 2400: a + 4800])
        pk, _ = ss.find_peaks(flux, height=flux.max() * 0.3)
        res[off_ms] = dict(key_sharing=rep["key_sharing"],
                           voices={v: rep["voices"][v]["notes"] for v in rep["voices"]},
                           rms_0_300ms_db=round(rms_db(x[a: a + int(0.3 * SR)]), 2),
                           onset_peaks_ms=[round(float(ft[p] * 1000 - 50), 1) for p in pk])
    # reference: one note alone at the same gain
    mid = TMP / "unison_ref.mid"
    write_midi(mid, {"soprano": [(0.5, N("note_on", note=67, velocity=70)), (0.9, N("note_off", note=67, velocity=0))]})
    render(mid, TMP / "unison_ref", "--no-reverb", "--no-m4a", "--peak-db", "-20")
    # the renderer normalises the true peak, so compare un-normalised stems instead
    x = read(TMP / "unison_ref_stems" / "soprano.wav")
    a = int((0.5 + LEAD_IN) * SR)
    res["single_note_rms_0_300ms_db"] = round(rms_db(x[a: a + int(0.3 * SR)]), 2)
    return res


def repeats() -> dict:
    res = {}
    for pedal in (False, True):
        for n in (8, 16):
            evs, times = [], []
            if pedal:
                evs.append((0.3, N("control_change", control=64, value=127)))
            for i in range(n):
                t = 0.5 + i * 0.125
                evs.append((t, N("note_on", note=60, velocity=80)))
                evs.append((t + 0.1, N("note_off", note=60, velocity=0)))
                times.append(t)
            if pedal:
                evs.append((0.5 + n * 0.125 + 0.5, N("control_change", control=64, value=0)))
            mid = TMP / f"repeat_{n}_{int(pedal)}.mid"
            write_midi(mid, {"solo": evs})
            render(mid, TMP / f"repeat_{n}_{int(pedal)}", "--no-reverb", "--no-m4a")
            x = read(TMP / f"repeat_{n}_{int(pedal)}_stems" / "solo.wav")
            on = [t + LEAD_IN for t in times]
            offs = [t + LEAD_IN + 0.1 for t in times]
            # level of each strike (first 50 ms) to see stealing / pile-up
            lv = [round(rms_db(x[int(t * SR): int((t + 0.05) * SR)]), 1) for t in on]
            res[f"n{n}_pedal{int(pedal)}"] = dict(onset_click_db=click_scan(x, on), noteoff_click_db=click_scan(x, offs),
                                                  strike_level_db=lv)
    # reference click crest for isolated attacks (single notes)
    return res


def zero_length() -> dict:
    # key 60 note_on/note_off at the same tick at t=0.5; key 60 again 0.6..0.9 s
    mf = mido.MidiFile(type=1, ticks_per_beat=480)
    t0 = mido.MidiTrack(); t0.append(mido.MetaMessage("set_tempo", tempo=500000, time=0)); mf.tracks.append(t0)
    tr = mido.MidiTrack(); mf.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name="solo", time=0))
    tr += [N("note_on", note=60, velocity=80, time=480), N("note_off", note=60, velocity=0, time=0),
           N("note_on", note=64, velocity=80, time=96), N("note_off", note=64, velocity=0, time=288),
           N("note_on", note=60, velocity=80, time=480), N("note_off", note=60, velocity=0, time=240)]
    p = TMP / "zero_length.mid"
    mf.save(p)
    rep = render(p, TMP / "zero_length", "--no-reverb", "--no-m4a", "--keep-temp")
    stem = mido.MidiFile(Path(rep["temp"]) / "stem00.mid")
    t, ev = 0.0, []
    for m in stem:
        t += m.time
        if m.type in ("note_on", "note_off"):
            ev.append((round(t - LEAD_IN, 3), m.type, m.note))
    return dict(input="C4 zero-length at 0.5 s; E4 0.6-0.9 s; C4 1.4-1.65 s (tpb 480, 120 bpm)", stem_events=ev,
                notes=rep["voices"]["solo"]["notes"])


def type0() -> dict:
    mf = mido.MidiFile(type=0, ticks_per_beat=480)
    tr = mido.MidiTrack(); mf.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name="Piece", time=0))
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    for ch, k in enumerate((72, 67, 60, 48)):
        tr.append(N("note_on", channel=ch, note=k, velocity=70, time=0))
    tr.append(N("note_off", channel=0, note=72, velocity=0, time=480))
    for ch, k in enumerate((67, 60, 48), start=1):
        tr.append(N("note_off", channel=ch, note=k, velocity=0, time=0))
    p = TMP / "type0.mid"
    mf.save(p)
    rep = render(p, TMP / "type0", "--no-reverb", "--no-m4a")
    return dict(voices=list(rep["voices"]))


def conductor_cc() -> dict:
    """CC64 on a note-less conductor track must reach every voice; CC7 100->50 mid-note (-12 dB)."""
    mf = mido.MidiFile(type=1, ticks_per_beat=480)
    t0 = mido.MidiTrack(); mf.tracks.append(t0)
    t0 += [mido.MetaMessage("track_name", name="conductor", time=0), mido.MetaMessage("set_tempo", tempo=500000, time=0),
           N("control_change", channel=15, control=64, value=127, time=0),
           N("control_change", channel=15, control=64, value=0, time=1920)]
    for name, ch, k in (("upper", 0, 72), ("lower", 1, 48)):
        tr = mido.MidiTrack(); mf.tracks.append(tr)
        tr += [mido.MetaMessage("track_name", name=name, time=0), N("note_on", channel=ch, note=k, velocity=90, time=0),
               N("note_off", channel=ch, note=k, velocity=0, time=240)]
        if name == "upper":
            tr += [N("note_on", channel=ch, note=76, velocity=90, time=480), N("control_change", channel=ch, control=7, value=50, time=480),
                   N("note_off", channel=ch, note=76, velocity=0, time=480)]
    p = TMP / "conductor.mid"
    mf.save(p)
    rep = render(p, TMP / "conductor", "--no-reverb", "--no-m4a")
    up = read(TMP / "conductor_stems" / "upper.wav")
    lo = read(TMP / "conductor_stems" / "lower.wav")
    # pedal: C3 released at 0.25 s but pedal down until 2.0 s -> still ringing at 1.0 s
    lvl_lo_05 = rms_db(lo[int((LEAD_IN + 0.1) * SR): int((LEAD_IN + 0.2) * SR)])
    lvl_lo_10 = rms_db(lo[int((LEAD_IN + 1.0) * SR): int((LEAD_IN + 1.1) * SR)])
    # CC7 step at 1.25 s on E5 (struck at 0.75 s): 10 ms level trace around the step
    tstep = LEAD_IN + 1.25
    tr = [round(rms_db(up[int((tstep + d) * SR): int((tstep + d + 0.005) * SR)]), 1) for d in np.arange(-0.02, 0.04, 0.005)]
    return dict(pedal_changes=rep["pedal_changes"], lower_level_0p1s_db=round(lvl_lo_05, 1),
                lower_level_1p0s_db=round(lvl_lo_10, 1),
                cc7_step_trace_db_5ms=tr, cc7_click_db=click_scan(up, [tstep], win=0.03)[0])


def transpose_fold() -> dict:
    tracks = {"pedal": [(0.5, N("note_on", note=30, velocity=80)), (1.5, N("note_off", note=30, velocity=0)),
                        (2.0, N("note_on", note=22, velocity=80)), (3.0, N("note_off", note=22, velocity=0))]}
    p = TMP / "fold.mid"
    write_midi(p, tracks)
    r = subprocess.run([sys.executable, str(PIANO / "render_piano.py"), str(p), "-o", str(TMP / "fold"), "--no-reverb",
                        "--no-m4a", "--transpose", "pedal=-12", "--stems", str(TMP / "fold_stems"), "--keep-temp",
                        "--json", str(TMP / "fold.render.json")], capture_output=True, text=True)
    rep = json.loads((TMP / "fold.render.json").read_text())
    x = read(TMP / "fold_stems" / "pedal.wav")
    warn = [l for l in r.stdout.splitlines() + r.stderr.splitlines() if "warn" in l.lower()]
    out = {"warning_printed": bool(warn), "warnings": warn}
    stem = mido.MidiFile(Path(rep["temp"]) / "stem00.mid")
    out["stem_keys"] = [m.note for m in stem if m.type == "note_on"]
    out["requested_keys"] = [30 - 12, 22 - 12]
    seg = x[int((2.0 + LEAD_IN + 0.2) * SR): int((2.0 + LEAD_IN + 0.9) * SR)]
    # which octave actually sounds: compare partial energy at A#-1 (would be 14.6 Hz, impossible) vs A#0 (29.1 Hz)
    out["note2_partial2_hz"] = round(f0_estimate(seg, 22, 2) * 2, 2)
    return out


def strings_target() -> dict:
    ly = PIANO / "tests" / "chain_test.ly"
    plan = PIANO / "tests" / "chain_test.plan.json"
    mid = TMP / "chain_strings.mid"
    subprocess.run([sys.executable, str(PIANO.parents[1] / "tools" / "perform.py"), str(ly), str(plan), str(mid),
                    "--target", "strings"], check=True, capture_output=True)
    rep = render(mid, TMP / "chain_strings", "--no-m4a")
    rep_p = json.loads((PIANO / "out" / "chain_test.render.json").read_text()) if (PIANO / "out" / "chain_test.render.json").exists() else None
    return dict(velocity_scale=rep["velocity_scale"], cc_dynamics=rep["cc_dynamics"],
                voices={v: rep["voices"][v]["velocity_eff_range"] for v in rep["voices"]},
                piano_target_voices=None if rep_p is None else {v: rep_p["voices"][v]["velocity_eff_range"] for v in rep_p["voices"]})


def bad_transpose() -> dict:
    p = TMP / "type0.mid"
    r = subprocess.run([sys.executable, str(PIANO / "render_piano.py"), str(p), "-o", str(TMP / "bad"), "--no-m4a",
                        "--transpose", "tuba=-12"], capture_output=True, text=True)
    return dict(returncode=r.returncode, message=(r.stderr or r.stdout).strip().splitlines()[-1:])


def main() -> None:
    TMP.mkdir(exist_ok=True)
    res = {}
    for f in (unison_offsets, repeats, zero_length, type0, conductor_cc, transpose_fold, strings_target, bad_transpose):
        try:
            res[f.__name__] = f()
        except Exception as e:  # keep going; the failure itself is a finding
            res[f.__name__] = {"error": repr(e)[:2000]}
        print(f.__name__, json.dumps(res[f.__name__])[:1500])
    save("edge", res)


if __name__ == "__main__":
    main()
