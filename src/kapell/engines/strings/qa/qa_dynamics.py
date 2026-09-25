#!/usr/bin/env python3
"""Dynamics QA: do pp / mf / ff change timbre as well as level, are hairpins
smooth, and does voicing one line (perform.py role_level) come through?

  python3 qa_dynamics.py

A. Through the chain: perform.py qa/dyn_qa.ly qa/dyn_qa.plan.json --target strings,
   render_quartet.py --stems.  Per voice (dry stem) and for the final mix:
   RMS, K-weighted level, spectral centroid, share of energy above 2 kHz and the
   gain-matched 2-5 kHz band (each segment's spectrum scaled to equal total power,
   so a pure gain change reads 0 dB) for the pp / mf / ff phrase.
   The eight-bar held chord under pp -> ff -> pp: 5 ms level track minus its
   300 ms moving average (residual = steps / zipper / sample modulation), the
   residual's 40-60 Hz share (the renderer's 20 ms CC1 step grid), monotonicity of
   the 0.5 s level, and level and centroid against the planned CC1.
   Voicing: the viola marked "subject" (bars 19-20) vs the same bars unmarked
   (22-23): its level re the other three voices.
B. Direct CC1, no perform.py: one track per instrument (vn1 vn2 va vc cb), the
   same phrase at CC1 49 / 88 / 114 with CC11 = 127 and constant velocity 80,
   then a 9 s held note with CC1 36 -> 127 -> 36 (an event every 50 ms): isolates
   the SFZ's CC1 (layer crossfade + volume curve) from the CC11 post-gain.
C. Zipper in the engine itself: violin.sfz with every sample replaced by sfizz's
   *sine generator (all opcodes kept), a 4 s CC1 ramp as render_quartet emits it
   (20 ms, 1-step grid); the sine's envelope shows every gain step exactly.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import QA, QUARTET, SR, TMP, db, env_db, k_weight, load, midi_cc, perform, render, save, state  # noqa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iowa_common import SFIZZ_RENDER  # noqa: E402

BPM = 72
BAR = 4 * 60 / BPM
PH = {"pp": (0, 2), "mf": (3, 5), "ff": (6, 8), "subject": (18, 20), "plain": (21, 23)}
SWELL = (9, 17)                                  # bars 10-17 (0-based start bar 9, end 17)
VOICES = {"soprano": "vn1", "alto": "vn2", "tenor": "va", "bass": "vc"}


def spec(x):
    n = 1 << 14
    fr = [x[i:i + n] * np.hanning(n) for i in range(0, max(1, len(x) - n), n // 2)]
    P = np.mean([np.abs(np.fft.rfft(f, n)) ** 2 for f in fr], axis=0)
    return P, np.fft.rfftfreq(n, 1 / SR)


def timbre(x, ref_P=None):
    P, f = spec(x)
    tot = P.sum() + 1e-30
    cen = float((P * f).sum() / tot)
    hf = float(P[f > 2000].sum() / tot * 100)
    band = float(10 * np.log10(P[(f > 2000) & (f < 5000)].sum() / tot + 1e-30))   # gain-independent
    return dict(rms_db=round(db(x), 2), k_db=round(db(k_weight(x)), 2), centroid_hz=int(cen),
                hf_pct=round(hf, 2), band2_5k_db_re_total=round(band, 2))


def swell_analysis(x, t0, t1, cc_events=None):
    e, hop = env_db(x[int(t0 * SR): int(t1 * SR)], 0.005, 0.005)
    fr = SR / hop
    k = int(0.3 * fr)
    sm = np.convolve(e, np.ones(k) / k, mode="same")
    res = (e - sm)[k: -k]
    R = np.abs(np.fft.rfft(res * np.hanning(len(res)))) ** 2
    fq = np.fft.rfftfreq(len(res), 1 / fr)
    share = float(R[(fq > 40) & (fq < 60)].sum() / (R[(fq > 5) & (fq < 100)].sum() + 1e-30))
    # 0.5 s levels
    w = int(0.5 * fr)
    lv = [float(np.mean(e[i:i + w])) for i in range(0, len(e) - w, w)]
    half = len(lv) // 2
    up = np.diff(lv[:half])
    dn = np.diff(lv[half:])
    # sample-to-sample jumps of the 5 ms track larger than 1.5 dB
    jumps = int(np.sum(np.abs(np.diff(e)) > 1.5))
    out = dict(residual_rms_db=round(float(np.sqrt(np.mean(res ** 2))), 2),
               residual_share_40_60Hz=round(share, 3),
               level_range_db=round(max(lv) - min(lv), 1), levels_0p5s=[round(v, 1) for v in lv],
               rising_half_nonmonotonic_steps=int(np.sum(up < -0.3)),
               falling_half_nonmonotonic_steps=int(np.sum(dn > 0.3)),
               jumps_over_1p5db_per_5ms=jumps)
    return out


# ------------------------------------------------------------------ part A
def part_a(res):
    mid = TMP / "dyn_qa.mid"
    res["A_perform_stdout"] = perform(QA / "dyn_qa.ly", QA / "dyn_qa.plan.json", mid)
    out = TMP / "dyn_qa"
    rep = render(mid, out, "--keep-start")
    off = rep["offset_s"]
    A = {}
    stems = {inst: load(TMP / f"dyn_qa_stem_{inst}.wav") for inst in VOICES.values()}
    mix = load(Path(str(out) + ".wav"))
    for inst, x in list(stems.items()) + [("mix", mix)]:
        seg = {}
        for name in ("pp", "mf", "ff"):
            b0, b1 = PH[name]
            seg[name] = timbre(x[int((b0 * BAR - off) * SR): int((b1 * BAR - off) * SR)])
        seg["pp_to_ff"] = dict(rms_db=round(seg["ff"]["rms_db"] - seg["pp"]["rms_db"], 1),
                               k_db=round(seg["ff"]["k_db"] - seg["pp"]["k_db"], 1),
                               centroid_ratio=round(seg["ff"]["centroid_hz"] / max(seg["pp"]["centroid_hz"], 1), 2),
                               band2_5k_gain_matched_db=round(seg["ff"]["band2_5k_db_re_total"]
                                                              - seg["pp"]["band2_5k_db_re_total"], 1))
        seg["pp_to_mf_k_db"] = round(seg["mf"]["k_db"] - seg["pp"]["k_db"], 1)
        seg["mf_to_ff_k_db"] = round(seg["ff"]["k_db"] - seg["mf"]["k_db"], 1)
        t0, t1 = SWELL[0] * BAR - off + 0.3, SWELL[1] * BAR - off - 0.1
        seg["swell"] = swell_analysis(x, t0, t1)
        # centroid vs time on the swell (1 s windows)
        cens = []
        for c in np.arange(t0, t1 - 1, 0.5):
            cens.append(timbre(x[int(c * SR): int((c + 1) * SR)])["centroid_hz"])
        seg["swell"]["centroid_1s"] = cens
        A[inst] = seg
    # voicing: viola level re each other voice, marked vs unmarked
    v = {}
    for name in ("subject", "plain"):
        b0, b1 = PH[name]
        i0, i1 = int((b0 * BAR - off) * SR), int((b1 * BAR - off) * SR)
        lv = {inst: db(k_weight(x[i0:i1])) for inst, x in stems.items()}
        others = 10 * np.log10(sum(10 ** (lv[i] / 10) for i in lv if i != "va"))
        v[name] = dict(viola_k_db=round(lv["va"], 2), viola_re_other_three_db=round(lv["va"] - others, 2),
                       per_voice_k_db={i: round(l, 2) for i, l in lv.items()})
    v["viola_gain_when_marked_db"] = round(v["subject"]["viola_k_db"] - v["plain"]["viola_k_db"], 2)
    # the MIDI side: CC1 of the viola in both windows
    cc = midi_cc(mid)
    ch = 2
    for name in ("subject", "plain"):
        b0, b1 = PH[name]
        vals = [val for t, val in cc[ch][1] if b0 * BAR <= t < b1 * BAR]
        v[name]["viola_cc1_median"] = float(np.median(vals))
    A["voicing"] = v
    res["A"] = A
    res["A_render"] = rep["stdout"]


# ------------------------------------------------------------------ part B
PHRASE = [(0.0, 1.0, 0), (1.0, 1.0, 4), (2.0, 0.5, 7), (2.5, 0.5, 5), (3.0, 0.5, 4), (3.5, 0.5, 2),
          (4.0, 0.25, 0), (4.25, 0.25, 2), (4.5, 0.25, 4), (4.75, 0.25, 5), (5.0, 0.25, 7), (5.25, 0.25, 9),
          (5.5, 0.25, 11), (5.75, 0.25, 12), (6.0, 2.0, 7)]
TONIC = {"Violin I": 67, "Violin II": 64, "Viola": 55, "Cello": 43, "Contrabass": 31}
SPB = 60 / 90


def part_b(res):
    B = {}
    for name, tonic in TONIC.items():
        mf = mido.MidiFile(type=1, ticks_per_beat=960)
        t0 = mido.MidiTrack()
        t0.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(90)))
        mf.tracks.append(t0)
        tr = mido.MidiTrack()
        mf.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=name))
        ev = [(0.0, 0, mido.Message("control_change", control=11, value=127))]
        segs = {}
        b = 0.5
        for lab, cc in (("pp", 49), ("mf", 88), ("ff", 114)):
            ev.append((b - 0.2, 0, mido.Message("control_change", control=1, value=cc)))
            for s, d, o in PHRASE:
                ev.append((b + s, 2, mido.Message("note_on", note=tonic + o, velocity=80)))
                ev.append((b + s + d, 1, mido.Message("note_off", note=tonic + o, velocity=0)))
            segs[lab] = (b * SPB, (b + 8) * SPB)
            b += 11
        ev.append((b - 0.2, 0, mido.Message("control_change", control=1, value=36)))
        ev.append((b, 2, mido.Message("note_on", note=tonic + 7, velocity=80)))
        L = 9.0 / SPB
        for i in range(1, 181):
            x = i / 180
            ev.append((b + L * x, 0, mido.Message("control_change", control=1,
                                                   value=int(round(36 + 91 * (1 - abs(2 * x - 1)))))))
        ev.append((b + L, 1, mido.Message("note_off", note=tonic + 7, velocity=0)))
        segs["swell"] = (b * SPB, (b + L) * SPB)
        ev.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for beat, _, m in ev:
            tk = int(round(beat * 960))
            tr.append(m.copy(time=tk - last))
            last = tk
        tag = {"Violin I": "vn1", "Violin II": "vn2", "Viola": "va", "Cello": "vc", "Contrabass": "cb"}[name]
        mp = TMP / f"dynB_{tag}.mid"
        mf.save(str(mp))
        rep = render(mp, TMP / f"dynB_{tag}", "--keep-start")
        off = rep["offset_s"]
        got = rep["jobs"][0]["inst"]
        r = {"track_name": name, "mapped_to": got}
        if got != tag:                      # name mapping defect: render it with --map to measure anyway
            rep = render(mp, TMP / f"dynB_{tag}", "--keep-start", "--map", f"0={tag}")
        x = load(TMP / f"dynB_{tag}_stem_{tag}.wav")
        for lab in ("pp", "mf", "ff"):
            a, bb = segs[lab]
            r[lab] = timbre(x[int((a - off) * SR): int((bb - off) * SR)])
        r["pp_to_ff"] = dict(k_db=round(r["ff"]["k_db"] - r["pp"]["k_db"], 1),
                             centroid_ratio=round(r["ff"]["centroid_hz"] / max(r["pp"]["centroid_hz"], 1), 2),
                             band2_5k_gain_matched_db=round(r["ff"]["band2_5k_db_re_total"]
                                                            - r["pp"]["band2_5k_db_re_total"], 1))
        a, bb = segs["swell"]
        r["swell"] = swell_analysis(x, a - off + 0.3, bb - off - 0.1)
        cens = []
        for c in np.arange(a - off + 0.3, bb - off - 1.1, 0.5):
            cens.append(timbre(x[int(c * SR): int((c + 1) * SR)])["centroid_hz"])
        r["swell"]["centroid_1s"] = cens
        B[tag] = r
        print(tag, "pp->ff", r["pp_to_ff"], "swell resid", r["swell"]["residual_rms_db"],
              "range", r["swell"]["level_range_db"])
    res["B"] = B


# ------------------------------------------------------------------ part C
def part_c(res):
    src = (QUARTET / "violin.sfz").read_text()
    sine = re.sub(r"sample=\S+", "sample=*sine", src)
    sfz = TMP / "qa_sine_violin.sfz"               # *sine needs no sample files; the <curve> is inline
    sfz.write_text(sine)
    try:
        mf = mido.MidiFile(type=0, ticks_per_beat=960)
        tr = mido.MidiTrack()
        mf.tracks.append(tr)
        tr.append(mido.MetaMessage("set_tempo", tempo=500000))
        ev = [(0.0, mido.Message("control_change", control=1, value=49)),
              (0.001, mido.Message("control_change", control=20, value=80)),
              (0.5, mido.Message("note_on", note=69, velocity=100))]
        # render_quartet's cc1_curve for events 49 -> 114 over 4 s: one CC step per ~60 ms
        # (4 s / 65 values); emitted exactly as its job_midi would (1-unit steps)
        for i in range(1, 66):
            ev.append((1.0 + 4.0 * i / 65, mido.Message("control_change", control=1, value=49 + i)))
        ev.append((6.5, mido.Message("note_off", note=69, velocity=0)))
        last = 0
        for t, m in ev:
            tk = int(round(t * 1920))
            tr.append(m.copy(time=tk - last))
            last = tk
        mp = TMP / "zip_sine.mid"
        mf.save(str(mp))
        wav = TMP / "zip_sine.wav"
        subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(mp), "--wav", str(wav), "-s", str(SR)],
                       check=True, capture_output=True)
        x = load(wav)
        from scipy.signal import hilbert
        # analytic envelope of a longer stretch, 0.1 s cut from each end (the Hilbert
        # transform rings at a segment's edges: an 11 dB "step" in the first ms otherwise)
        env = np.abs(hilbert(x[int(0.8 * SR): int(5.3 * SR)]))[int(0.1 * SR): -int(0.1 * SR)]
        e = 20 * np.log10(env + 1e-12)
        # per-millisecond level; the largest 1 ms change vs the median change
        ms = e[::48]
        d = np.diff(ms)
        steps = np.sort(np.abs(d))[::-1]
        res["C"] = dict(level_start_db=round(float(ms[:50].mean()), 2), level_end_db=round(float(ms[-50:].mean()), 2),
                        largest_1ms_changes_db=[round(float(s), 3) for s in steps[:10]],
                        median_abs_1ms_change_db=round(float(np.median(np.abs(d))), 4),
                        n_1ms_changes_over_0p1db=int(np.sum(np.abs(d) > 0.1)),
                        note="all three layers are the same in-phase sine, so layer crossfades add in amplitude")
        # gain-step duration: how long does one 1-unit CC step take to settle in the output?
        print("C", res["C"])
    finally:
        sfz.unlink(missing_ok=True)


def main():
    TMP.mkdir(exist_ok=True)
    res = dict(state=state())
    if "--skip-a" not in sys.argv:
        part_a(res)
    else:
        import json
        res = json.loads((QA / "results" / "dynamics.json").read_text())
    for inst, s in res["A"].items():
        if inst == "voicing":
            continue
        print(inst, "pp", s["pp"], "\n   mf", s["mf"], "\n   ff", s["ff"], "\n   ", s["pp_to_ff"],
              "pp->mf", s["pp_to_mf_k_db"], "mf->ff", s["mf_to_ff_k_db"])
        sw = s["swell"]
        print("   swell", {k: sw[k] for k in sw if k not in ("levels_0p5s", "centroid_1s")})
    print("voicing", res["A"]["voicing"])
    save("dynamics.json", res)
    part_b(res)
    save("dynamics.json", res)
    part_c(res)
    p = save("dynamics.json", res)
    print("->", p)


if __name__ == "__main__":
    main()
