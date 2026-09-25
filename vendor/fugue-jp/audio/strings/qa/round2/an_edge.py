#!/usr/bin/env python3
"""Round-2 adversarial probes for render_quartet.py (small MIDIs under /tmp/sqa2/edge).

  python3 an_edge.py [--only NAME ...] [--reuse]

  long      one note per instrument held 20 s at fixed CC1/CC11 88: keeps sounding past the
            10 s sample (loop), level steps / wander, pitch drift, clicks at the loop seam;
            also the fixed-level zipper baseline an_dyn.py compares against
  unison    violin I + II on the same key: C4 and G3 (both desks play the SAME Iowa
            recording) vs A4 and E5 (different recordings): beating / comb depth in the sum
  ranges    compass edges and beyond: vn1 52 (below the stretched G3) and 101, vc 34 and 33
  dense     32nd notes at 120 bpm (62.5 ms): scales, a repeated key, then a 16th run
  type0     a type-0 file, four channels, no track names, programs 40 40 41 42
  overlap   the same key re-struck before its note-off in one voice (FIFO pairing), and a
            zero-length note
  cc7       CC7 ramp 127 -> 20 on a held note (GM curve 40*log10(v/127))
  bend      pitch bend +8191 / -8192 on a held note (bend range +-200 c in the SFZ)
  determinism  the 'long' MIDI rendered twice: sample-identical?
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mido
import numpy as np
import soundfile as sf
from scipy.signal import savgol_filter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import (SR, TMP, cents, db, hp, hz, interharmonic_db, pitch_fft, pitch_yin, render, rms_env, save,
                    yin_track)  # noqa: E402

E = TMP / "edge"
TPB = 960
TPS = 1920                     # ticks per second at 120 bpm


def mk(tracks, path, type_=1, names=True, tempo=500000):
    """tracks: [(name, channel, program, [(t_s, msg)])] -> MIDI file (seconds at 120 bpm unless tempo)."""
    mf = mido.MidiFile(type=type_, ticks_per_beat=TPB)
    tps = TPB * 1e6 / tempo
    if type_ == 0:
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
        ev = []
        for name, ch, prog, evs in tracks:
            ev.append((0.0, -1, mido.Message("program_change", channel=ch, program=prog)))
            ev += [(t, 0, m.copy(channel=ch)) for t, m in evs]
        ev.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for t, _, m in ev:
            tk = int(round(t * tps))
            tr.append(m.copy(time=tk - last))
            last = tk
        mf.tracks.append(tr)
    else:
        t0 = mido.MidiTrack()
        t0.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
        mf.tracks.append(t0)
        for name, ch, prog, evs in tracks:
            tr = mido.MidiTrack()
            if names:
                tr.append(mido.MetaMessage("track_name", name=name, time=0))
            tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
            last = 0
            for t, m in sorted(evs, key=lambda e: (e[0], e[1].type != "control_change", e[1].type == "note_on")):
                tk = int(round(t * tps))
                tr.append(m.copy(channel=ch, time=tk - last))
                last = tk
            mf.tracks.append(tr)
    mf.save(str(path))


def cc(t, num, v):
    return (t, mido.Message("control_change", control=num, value=v))


def note(t0, t1, k, vel=80):
    return [(t0, mido.Message("note_on", note=k, velocity=vel)), (t1, mido.Message("note_off", note=k, velocity=0))]


VOICES = [("soprano", 0, 40), ("alto", 1, 40), ("tenor", 2, 41), ("bass", 3, 42)]


def base_cc(level=88):
    return [cc(0.0, 1, level), cc(0.0, 11, level)]


def build(name):
    p = E / f"{name}.mid"
    if name in ("long", "determinism"):
        keys = [81, 62, 48, 36]            # the held keys of dyn/dyn_r2.ly (zipper baseline)
        make = [(nm, ch, pr, base_cc() + note(0.5, 20.5, k)) for (nm, ch, pr), k in zip(VOICES, keys)]
        mk(make, p)
    elif name == "unison":
        ev1 = base_cc() + note(0.5, 3.5, 60) + note(4.5, 7.5, 55) + note(8.5, 11.5, 69) + note(12.5, 15.5, 76)
        mk([("soprano", 0, 40, ev1), ("alto", 1, 40, list(ev1))], p)
    elif name == "ranges":
        s = base_cc() + note(0.5, 1.5, 53) + note(2.0, 3.0, 54) + note(3.5, 4.5, 52) + note(5.0, 6.0, 100) + note(6.5, 7.5, 101)
        b = base_cc() + note(0.5, 1.5, 36) + note(2.0, 3.0, 34) + note(3.5, 4.5, 33) + note(5.0, 6.0, 81)
        mk([("soprano", 0, 40, s), ("bass", 3, 42, b)], p)
    elif name == "dense":
        ev = base_cc(101)
        t = 0.5
        scale = [67, 69, 71, 72, 74, 76, 78, 79, 81, 83, 84, 86, 88, 86, 84, 83, 81, 79, 78, 76, 74, 72, 71, 69, 67]
        for k in scale:
            ev += note(t, t + 0.0625, k, 90)
            t += 0.0625
        t += 0.5
        for i in range(8):
            ev += note(t, t + 0.0625 - 0.02, 74, 90)
            t += 0.0625
        t += 0.5
        for k in scale:
            ev += note(t, t + 0.125, k, 90)
            t += 0.125
        cel = base_cc(101)
        t = 0.5
        for k in [36, 38, 40, 41, 43, 45, 47, 48, 50, 48, 47, 45, 43, 41, 40, 38, 36]:
            cel += note(t, t + 0.125, k, 90)
            t += 0.125
        mk([("soprano", 0, 40, ev), ("bass", 3, 42, cel)], p)
    elif name == "type0":
        tr = []
        for (nm, ch, pr), ks in zip(VOICES, ([72, 74, 76], [64, 65, 67], [55, 57, 59], [43, 41, 40])):
            ev = base_cc()
            for i, k in enumerate(ks):
                ev += note(0.5 + i, 1.4 + i, k)
            tr.append((nm, ch, pr, ev))
        mk(tr, p, type_=0)
    elif name == "overlap":
        ev = base_cc() + [(0.5, mido.Message("note_on", note=72, velocity=80)),
                          (1.0, mido.Message("note_on", note=72, velocity=80)),
                          (1.5, mido.Message("note_off", note=72, velocity=0)),
                          (3.0, mido.Message("note_off", note=72, velocity=0))]
        ev += [(4.0, mido.Message("note_on", note=76, velocity=80)), (4.0, mido.Message("note_off", note=76, velocity=0))]
        ev += note(5.0, 6.0, 74)
        mk([("soprano", 0, 40, ev)], p)
    elif name == "cc7":
        ev = base_cc() + note(0.5, 8.5, 69) + [cc(0.0, 7, 127)]
        for i in range(0, 41):
            ev.append(cc(3.0 + i * 0.05, 7, int(round(127 - (127 - 20) * i / 40))))
        mk([("soprano", 0, 40, ev)], p)
    elif name == "bend":
        ev = base_cc() + note(0.5, 6.5, 69) + [(0.0, mido.Message("pitchwheel", pitch=0)),
                                                (2.5, mido.Message("pitchwheel", pitch=8191)),
                                                (4.5, mido.Message("pitchwheel", pitch=-8192))]
        mk([("soprano", 0, 40, ev)], p)
    return p


def stems(out, tags):
    d = {}
    for t in tags:
        f = Path(f"{out}_stem_{t}.wav")
        if f.exists():
            x, _ = sf.read(str(f), always_2d=True)
            d[t] = x
    return d


def an_long(rep, out):
    res = {}
    fixed_mod = {}
    st = stems(out, ["vn1", "vn2", "va", "vc"])
    for tag, k in zip(["vn1", "vn2", "va", "vc"], [81, 62, 48, 36]):
        x = st[tag].mean(axis=1)
        t, e = rms_env(x, 0.05, 0.01)
        m = (t > 1.0) & (t < 20.3)
        em = e[m]
        sm = savgol_filter(em, 101, 2)
        step = np.abs(em[5:] - em[:-5])
        blocks = []
        for b in np.arange(1.0, 20.0, 1.0):
            s = x[int(b * SR): int((b + 1) * SR)]
            c1, c2 = cents(pitch_fft(s, k), k), cents(pitch_yin(s, k), k)
            blocks.append(round(0.5 * (c1 + c2), 1) if c1 is not None and c2 is not None else c1)
        # level per 2 s block (sample end ~10 s, loop 7.25-9.75 s in sample time)
        lv = [round(float(db(np.mean(x[int(b * SR): int((b + 2) * SR)] ** 2))), 1) for b in np.arange(1.0, 20.0, 2.0)]
        # sounding at the end?
        end_db = float(db(np.mean(x[int(19.5 * SR): int(20.4 * SR)] ** 2)) - db(np.mean(x[int(2 * SR): int(6 * SR)] ** 2)))
        # zipper baseline (same measure as an_dyn.py)
        h = x[int(1.0 * SR): int(20.3 * SR)]
        te2, e2 = rms_env(h, 0.004, 0.002)
        ed = e2 - savgol_filter(e2, 251, 2)
        F = np.abs(np.fft.rfft(ed * np.hanning(len(ed)))) ** 2
        fm = np.fft.rfftfreq(len(ed), 0.002)
        fixed_mod[tag] = dict(mod_10_100hz_db=round(float(db(F[(fm >= 10) & (fm <= 100)].sum() / F[(fm > 0.5) & (fm < 10)].sum())), 1),
                              interharmonic_median_db=round(float(np.median(interharmonic_db(h, k))), 1),
                              interharmonic_p95_db=round(float(np.percentile(interharmonic_db(h, k), 95)), 1))
        # clicks: 6 kHz high-pass, 1 ms peaks re the 50 ms local RMS
        y = hp(x, 6000)
        a = np.abs(y)
        W = int(0.001 * SR)
        pk = np.maximum.reduceat(a[: len(a) // W * W], np.arange(0, len(a) // W * W, W))
        loc = np.sqrt(np.convolve(y[: len(pk) * W] ** 2, np.ones(int(0.05 * SR)) / int(0.05 * SR), "same"))[::W][: len(pk)]
        ratio = db(pk ** 2 / np.maximum(loc ** 2, 1e-20))
        tt = np.arange(len(pk)) * 0.001
        mm = (tt > 1.0) & (tt < 20.3)
        res[tag] = dict(key=k, max_step_50ms_db=round(float(step.max()), 2), p99_step_db=round(float(np.percentile(step, 99)), 2),
                        wander_p2_p98_db=round(float(np.percentile(em, 98) - np.percentile(em, 2)), 1),
                        max_dev_1s_smooth_db=round(float(np.abs(em - sm).max()), 2),
                        level_2s_blocks_db=lv, pitch_1s_blocks_c=blocks,
                        pitch_drift_c=round(float(max(blocks) - min(blocks)), 1),
                        level_at_20s_re_2_6s_db=round(end_db, 1),
                        hf_peak_re_local_max_db=round(float(ratio[mm].max()), 1),
                        hf_peaks_over_15db=int(np.sum(ratio[mm] > 15)))
    return dict(per_inst=res, fixed_mod=fixed_mod)


def an_unison(rep, out):
    st = stems(out, ["vn1", "vn2"])
    a, b = st["vn1"].mean(axis=1), st["vn2"].mean(axis=1)
    res = {}
    for k, (t0, t1), shared in ((60, (0.5, 3.5), True), (55, (4.5, 7.5), True), (69, (8.5, 11.5), False),
                                (76, (12.5, 15.5), False)):
        sa, sb = a[int((t0 + 0.4) * SR): int((t1 - 0.1) * SR)], b[int((t0 + 0.4) * SR): int((t1 - 0.1) * SR)]
        s = sa + sb
        _, es = rms_env(s, 0.05, 0.01)
        _, ea = rms_env(sa, 0.05, 0.01)
        _, eb = rms_env(sb, 0.05, 0.01)
        inc = db(10 ** (ea / 10) + 10 ** (eb / 10))           # incoherent (energy) sum
        gain = es - inc                                        # +3 dB = coherent in phase, -inf = cancel
        corr = float(np.corrcoef(sa, sb)[0, 1])
        res[str(k)] = dict(same_recording=shared, waveform_corr=round(corr, 3),
                           sum_re_energy_sum_db=dict(min=round(float(gain.min()), 1), max=round(float(gain.max()), 1),
                                                     p5=round(float(np.percentile(gain, 5)), 1),
                                                     p95=round(float(np.percentile(gain, 95)), 1)),
                           sum_wander_db=round(float(np.percentile(es, 98) - np.percentile(es, 2)), 1),
                           single_wander_db=round(float(np.percentile(ea, 98) - np.percentile(ea, 2)), 1))
    # the final mix: mono sum of the unison, same measure
    mix, _ = sf.read(f"{out}.wav", always_2d=True)
    off = rep["offset_s"]
    for k, (t0, t1) in ((60, (0.5, 3.5)), (69, (8.5, 11.5))):
        m = mix[int((t0 + 0.4 - off) * SR): int((t1 - 0.1 - off) * SR)].mean(axis=1)
        _, em = rms_env(m, 0.05, 0.01)
        res[str(k)]["mix_mono_wander_db"] = round(float(np.percentile(em, 98) - np.percentile(em, 2)), 1)
    return res


def an_ranges(rep, out):
    res = dict(log=[l for l in rep["notes"]], jobs=[(j["label"], j["inst"], j["kind"], [n[2] for n in j["note_list"]])
                                                     for j in rep["jobs"]])
    st = stems(out, ["vn1", "vn2", "va", "vc", "cb"])
    mix = sum(v.mean(axis=1) for v in st.values())
    rows = []
    for (t0, t1, k_in) in ((0.5, 1.5, 53), (2.0, 3.0, 54), (3.5, 4.5, 52), (5.0, 6.0, 100), (6.5, 7.5, 101),
                           (0.5, 1.5, 36), (2.0, 3.0, 34), (3.5, 4.5, 33), (5.0, 6.0, 81)):
        # which key actually sounds: search -12, 0, +12 around the input key in the job's note lists
        played = [n[2] for j in rep["jobs"] for n in j["note_list"] if abs(n[0] - t0) < 1e-3 and (n[2] - k_in) % 12 == 0]
        k_out = played[0] if played else None
        row = dict(t=t0, key_in=k_in, key_rendered=k_out)
        if k_out is not None:
            inst = [j["inst"] for j in rep["jobs"] for n in j["note_list"] if abs(n[0] - t0) < 1e-3 and n[2] == k_out][0]
            s = st[inst].mean(axis=1)[int((t0 + 0.3) * SR): int((t1 - 0.1) * SR)]
            c1, c2 = cents(pitch_fft(s, k_out), k_out), cents(pitch_yin(s, k_out), k_out)
            row["cents_fft"] = None if c1 is None else round(c1, 1)
            row["cents_yin"] = None if c2 is None else round(c2, 1)
            row["level_db"] = round(float(db(np.mean(s ** 2))), 1)
        rows.append(row)
    res["rows"] = rows
    return res


def an_dense(rep, out):
    st = stems(out, ["vn1", "vc"])
    res = {}
    mid = mido.MidiFile(str(E / "dense.mid"))
    from lib_r2 import midi_voices, pitch_switch
    mv = midi_voices(E / "dense.mid")
    for ch, tag in ((0, "vn1"), (3, "vc")):
        x = st[tag].mean(axis=1)
        notes = mv[ch]["notes"]
        rows = []
        for i, n in enumerate(notes):
            if i == 0:
                continue
            p = notes[i - 1]
            if p["key"] == n["key"]:
                # repeated key: dip between strokes
                t, e = rms_env(x, 0.005, 0.001)
                m_in = (t > p["on"] + 0.015) & (t < p["off"])
                m = (t > n["on"] - 0.03) & (t < n["on"] + 0.02)
                rows.append(dict(on=round(n["on"], 3), key=n["key"], repeat=True,
                                 dip_db=round(float(np.median(e[m_in]) - e[m].min()), 1) if m_in.any() and m.any() else None))
                continue
            sw = pitch_switch(x, n["on"], p["key"], n["key"], span=(-0.05, 0.08))
            s = x[int((n["on"] + 0.015) * SR): int((n["off"]) * SR)]
            rows.append(dict(on=round(n["on"], 3), key=n["key"], switch_ms=None if sw is None else round(1000 * sw, 1)))
        sws = [r["switch_ms"] for r in rows if not r.get("repeat")]
        ok = [s for s in sws if s is not None]
        res[tag] = dict(n=len(rows), switch_found=len(ok), switch_missing=len(sws) - len(ok),
                        switch_median_ms=round(float(np.median(ok)), 1) if ok else None,
                        switch_p90_ms=round(float(np.percentile(ok, 90)), 1) if ok else None,
                        switch_max_ms=round(float(max(ok)), 1) if ok else None,
                        repeats=[r for r in rows if r.get("repeat")],
                        missing=[r for r in rows if not r.get("repeat") and r["switch_ms"] is None][:10])
    res["articulation"] = {j["label"]: j["articulation"] for j in rep["jobs"]}
    return res


def an_type0(rep, out):
    return dict(jobs=[(j["label"], j["inst"], sorted({n[2] for n in j["note_list"]})) for j in rep["jobs"]], notes=rep["notes"])


def an_overlap(rep, out):
    st = stems(out, ["vn1"])
    x = st["vn1"].mean(axis=1)
    t, e = rms_env(x, 0.05, 0.01)
    ref = float(np.median(e[(t > 0.7) & (t < 1.4)]))
    lv = {f"{s:.1f}s": round(float(np.median(e[(t > s - 0.05) & (t < s + 0.05)]) - ref), 1) for s in (1.2, 1.7, 2.0, 2.5, 2.9, 3.3, 4.2)}
    return dict(note_list=rep["jobs"][0]["note_list"], log=rep["notes"], level_re_first_note_db=lv,
                expected="72 sounds 0.5-3.0 s (two strokes: 0.5-1.5 and 1.0-3.0); a zero-length 76 at 4.0; 74 at 5-6 s")


def an_cc7(rep, out):
    st = stems(out, ["vn1"])
    x = st["vn1"].mean(axis=1)
    t, e = rms_env(x, 0.1, 0.02)
    ref = float(np.median(e[(t > 1.5) & (t < 2.9)]))
    got = float(np.median(e[(t > 5.5) & (t < 8.0)]) - ref)
    return dict(expected_db=round(40 * np.log10(20 / 127), 1), measured_db=round(got, 1))


def an_bend(rep, out):
    st = stems(out, ["vn1"])
    x = st["vn1"].mean(axis=1)
    r = {}
    for nm, (a, b), exp in (("0", (1.0, 2.4), 0), ("+8191", (3.0, 4.4), 200), ("-8192", (5.0, 6.4), -200)):
        s = x[int(a * SR): int(b * SR)]
        k = 69 + exp // 100
        c1, c2 = cents(pitch_fft(s, k), k), cents(pitch_yin(s, k), k)
        r[nm] = dict(expected_c=exp, measured_fft_c=None if c1 is None else round(c1 + exp, 1),
                     measured_yin_c=None if c2 is None else round(c2 + exp, 1))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    E.mkdir(parents=True, exist_ok=True)
    names = a.only or ["long", "unison", "ranges", "dense", "type0", "overlap", "cc7", "bend", "determinism"]
    reps = {}

    def go(nm):
        p = build(nm)
        out = E / nm
        if a.reuse and Path(f"{out}.json").exists():
            return nm, json.loads(Path(f"{out}.json").read_text())
        return nm, render(p, out, "--keep-start", keep_temp=(nm in ("long", "determinism")))
    with ThreadPoolExecutor(3) as ex:
        for nm, rep in ex.map(go, names):
            reps[nm] = rep
    res = {}
    fn = dict(long=an_long, unison=an_unison, ranges=an_ranges, dense=an_dense, type0=an_type0, overlap=an_overlap,
              cc7=an_cc7, bend=an_bend)
    for nm in names:
        if nm in fn:
            res[nm] = fn[nm](reps[nm], E / nm)
            print(nm, json.dumps(res[nm], default=float)[:1500])
    if "long" in reps and "determinism" in reps and "temp" in reps["long"] and "temp" in reps["determinism"]:
        diffs = {}
        for i, j in enumerate(reps["long"]["jobs"]):
            x1, _ = sf.read(str(Path(reps["long"]["temp"]) / f"j{i}_{j['inst']}.wav"))
            x2, _ = sf.read(str(Path(reps["determinism"]["temp"]) / f"j{i}_{j['inst']}.wav"))
            n = min(len(x1), len(x2))
            d = x1[:n] - x2[:n]
            diffs[j["inst"]] = dict(identical=bool(len(x1) == len(x2) and not d.any()),
                                    diff_re_signal_db=round(float(db(np.mean(d ** 2) / np.mean(x1[:n] ** 2))), 1))
        res["determinism"] = diffs
        print("determinism", diffs)
    if "long" in res:
        (TMP / "edge_long.json").write_text(json.dumps(res["long"]))
    old = {}
    rp = Path(__file__).resolve().parent / "results" / "edge.json"
    if rp.exists() and a.only:
        old = json.loads(rp.read_text())
        old.pop("state", None)
    old.update(res)
    save("edge.json", old)


if __name__ == "__main__":
    main()
