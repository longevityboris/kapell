#!/usr/bin/env python3
"""Dynamics QA: do dynamics change timbre and loudness, not just gain?

Score qa/dyn_qa.ly (three voices): the same phrase at pp, mf, ff; a repeated chord under a
pp -> ff -> pp hairpin; the phrase at mf with the tenor voiced, then without.

Two renders:
* direct: MIDI written here from the parsed score with calibrated raw velocities
  (pp 29, mf 86, ff 115; hairpin 20 -> 120 -> 20 per chord; tenor +16 when voiced)
* chain:  perform.py qa/dyn_qa.ly qa/dyn_qa.plan.json --target piano -> render_piano.py

Per segment: RMS of the final render (with hall), spectral centroid and HF ratio
(>2 kHz re total) of the dry stem sum, octave bands after gain-matching to ff.
Hairpin: per chord K-weighted attack level (0-150 ms) and HF ratio; monotonicity, largest
step against the ramp. Voicing: tenor attack level relative to soprano and bass.
CC11 in --cc-dynamics gain mode: a held chord under a fast CC11 ramp -> envelope smoothness.

    python3 qa/qa_dynamics.py      # writes qa/results/dynamics.json
"""

from __future__ import annotations

import json
import sys
from fractions import Fraction as F
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, PERFORM, QA, SR, TMP, db, kweight, midi_notes, perform, read, render, rms_db, save, write_midi  # noqa: E402

sys.path.insert(0, str(PERFORM.parent))
from lyparse import parse_voice  # noqa: E402

LY = QA / "dyn_qa.ly"
PLAN = QA / "dyn_qa.plan.json"
BPM = 80
BAR = 4 * 60 / BPM
SEGMENTS = {"pp": (1, 3), "mf": (4, 6), "ff": (7, 9), "hairpin": (10, 18), "voiced": (19, 21), "unvoiced": (22, 24)}
BANDS = [(63, 125), (125, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 16000)]


def direct_midi(path: Path) -> None:
    src = LY.read_text()
    tracks = {}
    for v in ("soprano", "tenor", "bass"):
        evs = []
        for n in parse_voice(src, v, F(1)):
            if n.midi is None:
                continue
            bar = n.bar
            t = float(n.start) * BAR
            if bar < 4:
                vel = 29
            elif bar < 7:
                vel = 86
            elif bar < 10:
                vel = 115
            elif bar < 18:
                q = float(n.start - 9) * 4  # quarter index 0..31 in the hairpin
                vel = 20 + 100 * (q / 15) if q <= 15 else 120 - 100 * ((q - 16) / 15)
                vel = int(round(min(120, max(20, vel))))
            else:
                vel = 86 + (16 if (v == "tenor" and bar < 22) else 0)
            dur = float(n.dur) * BAR
            evs.append((t, mido.Message("note_on", note=n.midi, velocity=int(vel))))
            evs.append((t + dur - 0.03, mido.Message("note_off", note=n.midi, velocity=0)))
        tracks[v] = evs
    write_midi(path, tracks, tempo=int(60e6 / BPM))


def spectrum(x: np.ndarray):
    m = x.mean(axis=1)
    n = 1 << int(np.ceil(np.log2(len(m))))
    p = np.abs(np.fft.rfft(m * np.hanning(len(m)), n)) ** 2
    return np.fft.rfftfreq(n, 1 / SR), p


def centroid_hf(x: np.ndarray) -> tuple[float, float]:
    f, p = spectrum(x)
    sel = f > 30
    return float((f[sel] * p[sel]).sum() / p[sel].sum()), db(p[f > 2000].sum() / p[sel].sum())


def bands(x: np.ndarray) -> list[float]:
    f, p = spectrum(x)
    return [db(p[(f >= lo) & (f < hi)].sum()) for lo, hi in BANDS]


def analyse(tag: str, mid: Path, extra=()) -> dict:
    out = TMP / f"dyn_{tag}"
    rep = render(mid, out, *extra)
    mix = read(Path(str(out) + ".wav"))
    stems = {p.stem: read(p) for p in Path(str(out) + "_stems").glob("*.wav")}
    n = max(len(s) for s in stems.values())
    dry = sum(np.pad(s, ((0, n - len(s)), (0, 0))) for s in stems.values())
    notes = midi_notes(mid)
    # segment windows in seconds from the MIDI itself (first onset .. last offset + 0.4 s)
    def win(b0, b1):
        ns = [x for x in notes if b0 <= 1 + int((x["start"] + 1e-3) / BAR) < b1]
        return ns[0]["start"] + LEAD_IN, max(x["end"] for x in ns) + LEAD_IN + 0.4
    res = {"render": {k: rep[k] for k in ("velocity_scale", "normalise_gain_db", "rms_dbfs")},
           "velocity_eff": {v: rep["voices"][v]["velocity_eff_range"] for v in rep["voices"]}, "segments": {}}
    for s in ("pp", "mf", "ff"):
        a, b = win(*SEGMENTS[s])
        seg_mix, seg_dry = mix[int(a * SR): int(b * SR)], dry[int(a * SR): int(b * SR)]
        cen, hf = centroid_hf(seg_dry)
        res["segments"][s] = dict(rms_dbfs=round(rms_db(seg_mix), 2), centroid_hz=round(cen, 1), hf_ratio_db=round(hf, 2),
                                  bands_db=bands(seg_dry), vel_range=[min(x["vel"] for x in notes if a - LEAD_IN - 1e-3 <= x["start"] < b - LEAD_IN),
                                                                      max(x["vel"] for x in notes if a - LEAD_IN - 1e-3 <= x["start"] < b - LEAD_IN)])
    ffb = np.array(res["segments"]["ff"]["bands_db"])
    for s in ("pp", "mf", "ff"):
        sb = np.array(res["segments"][s]["bands_db"])
        # gain-match on total dry energy, then band difference to ff
        g = db(np.sum(10 ** (ffb / 10))) - db(np.sum(10 ** (sb / 10)))
        res["segments"][s]["gain_matched_band_diff_to_ff_db"] = {f"{lo}": round(float(sb[i] + g - ffb[i]), 1) for i, (lo, _) in enumerate(BANDS)}
        del res["segments"][s]["bands_db"]
    # hairpin: per chord (quarter) attack level and HF of the dry sum
    hp = [x for x in notes if 10 <= 1 + int((x["start"] + 1e-3) / BAR) < 18]
    onsets = sorted({round(x["start"], 3) for x in hp})
    lv, hfs, ctrl = [], [], []
    for t in onsets:
        a = t + LEAD_IN
        seg = dry[int(a * SR): int((a + 0.15) * SR)]
        lv.append(rms_db(kweight(seg)))
        hfs.append(centroid_hf(seg)[1])
        ctrl.append(max(x["vel"] for x in hp if abs(x["start"] - t) < 0.02))
    lv, hfs, ctrl = np.array(lv), np.array(hfs), np.array(ctrl)
    up, down = slice(0, 16), slice(16, 32)
    d_up, d_dn = np.diff(lv[up]), np.diff(lv[down])
    res["hairpin"] = dict(level_db=[round(v, 1) for v in lv], hf_db=[round(v, 1) for v in hfs], control=ctrl.tolist(),
                          level_span_db=round(float(lv.max() - lv.min()), 1), hf_span_db=round(float(hfs.max() - hfs.min()), 1),
                          corr_level_control=round(float(np.corrcoef(lv, ctrl)[0, 1]), 3),
                          max_step_up_db=round(float(d_up.max()), 2), worst_step_against_up_db=round(float(d_up.min()), 2),
                          max_step_down_db=round(float(-d_dn.min()), 2), worst_step_against_down_db=round(float(-d_dn.max()), 2))
    # voicing: attack level of each voice's notes (its own stem, 0-100 ms K-weighted) in voiced vs unvoiced
    vo = {}
    for s in ("voiced", "unvoiced"):
        b0, b1 = SEGMENTS[s]
        per = {}
        for v, st in stems.items():
            ns = [x for x in notes if x["voice"] == v and b0 <= 1 + int((x["start"] + 1e-3) / BAR) < b1]
            per[v] = round(float(np.median([rms_db(kweight(st[int((x["start"] + LEAD_IN) * SR): int((x["start"] + LEAD_IN + 0.1) * SR)])) for x in ns])), 1)
        a, b = win(b0, b1)
        seg = stems["tenor"][int(a * SR): int(b * SR)]
        per["tenor_centroid_hz"] = round(centroid_hf(seg)[0], 1)
        vo[s] = per
    vo["tenor_gain_db"] = round(vo["voiced"]["tenor"] - vo["unvoiced"]["tenor"], 1)
    vo["tenor_minus_soprano_voiced_db"] = round(vo["voiced"]["tenor"] - vo["voiced"]["soprano"], 1)
    vo["tenor_minus_soprano_unvoiced_db"] = round(vo["unvoiced"]["tenor"] - vo["unvoiced"]["soprano"], 1)
    res["voicing"] = vo
    return res


def cc11_gain_zipper() -> dict:
    """Held C major chord at velocity 100, CC11 ramps 127 -> 30 -> 127 in single steps every 10 ms,
    rendered with --cc-dynamics gain (continuous fader) and --no-reverb.
    Compare against the same chord without CC: the ratio of the two envelopes is the fader;
    its 1 ms-resolution derivative and residual after 50 ms smoothing expose zipper steps."""
    evs = {"chord": []}
    for k in (48, 60, 64, 67):
        evs["chord"] += [(0.2, mido.Message("note_on", note=k, velocity=100)), (6.0, mido.Message("note_off", note=k, velocity=0))]
    ref = TMP / "cc11_ref.mid"
    write_midi(ref, evs)
    ramp = list(range(127, 29, -1)) + list(range(30, 128))
    evs2 = {"chord": list(evs["chord"]) + [(1.0 + i * 0.01, mido.Message("control_change", control=11, value=v)) for i, v in enumerate(ramp)]}
    rmid = TMP / "cc11_ramp.mid"
    write_midi(rmid, evs2)
    render(ref, TMP / "cc11_ref", "--no-reverb", "--no-m4a", "--cc-dynamics", "gain")
    render(rmid, TMP / "cc11_ramp", "--no-reverb", "--no-m4a", "--cc-dynamics", "gain")
    a = read(TMP / "cc11_ref_stems" / "chord.wav")
    b = read(TMP / "cc11_ramp_stems" / "chord.wav")
    n = min(len(a), len(b))
    # instantaneous gain from sample ratio is ill-conditioned; use 1 ms RMS frames
    fr = SR // 1000
    i0, i1 = int((1.0 + LEAD_IN - 0.05) * SR), int((1.0 + LEAD_IN + len(ramp) * 0.01 + 0.05) * SR)
    ga = np.array([rms_db(a[i:i + fr]) for i in range(i0, i1, fr)])
    gb = np.array([rms_db(b[i:i + fr]) for i in range(i0, i1, fr)])
    g = gb - ga
    sm = np.convolve(g, np.ones(50) / 50, mode="same")
    resid = (g - sm)[60:-60]
    expected = [40 * np.log10(v / 127) for v in ramp]
    return dict(fader_span_db=round(float(g.max() - g.min()), 1), expected_span_db=round(float(max(expected) - min(expected)), 1),
                max_change_per_ms_db=round(float(np.abs(np.diff(g)).max()), 3),
                residual_after_50ms_smoothing_db_rms=round(float(np.sqrt(np.mean(resid ** 2))), 3))


def main() -> None:
    TMP.mkdir(exist_ok=True)
    res = {}
    dmid = TMP / "dyn_direct.mid"
    direct_midi(dmid)
    res["direct"] = analyse("direct", dmid)
    cmid = TMP / "dyn_chain.mid"
    perform(LY, PLAN, cmid, "piano")
    res["chain"] = analyse("chain", cmid)
    res["chain_raw_scale"] = analyse("chain_raw", cmid, ("--velocity-scale", "raw"))
    res["cc11_gain_zipper"] = cc11_gain_zipper()
    save("dynamics", res)
    for k in ("direct", "chain", "chain_raw_scale"):
        r = res[k]
        print(k, {s: (v["rms_dbfs"], v["centroid_hz"], v["hf_ratio_db"], v["vel_range"]) for s, v in r["segments"].items()})
        print("   gain-matched 4k/8k vs ff:", {s: (v["gain_matched_band_diff_to_ff_db"]["4000"], v["gain_matched_band_diff_to_ff_db"]["8000"]) for s, v in r["segments"].items()})
        h = r["hairpin"]
        print("   hairpin", {x: h[x] for x in ("level_span_db", "hf_span_db", "corr_level_control", "max_step_up_db", "worst_step_against_up_db", "max_step_down_db", "worst_step_against_down_db")})
        print("   voicing", r["voicing"])
    print("cc11", res["cc11_gain_zipper"])


if __name__ == "__main__":
    main()
