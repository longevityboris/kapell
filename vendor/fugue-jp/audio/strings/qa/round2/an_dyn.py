#!/usr/bin/env python3
"""Round-2 dynamics proof through perform.py (dyn/dyn_r2.ly, dyn/dyn_r2.plan.json).

  python3 an_dyn.py [--reuse]      (renders into /tmp/sqa2/dyn*, dry stems, --keep-start)

Per instrument (dry stems, MIDI time):
  * the same phrase at pp / mf / ff (bars 1-2, 4-5, 7-8): RMS (dB), spectral centroid,
    gain-matched band levels (<500 Hz, 0.5-2 kHz, 2-5 kHz, 5-10 kHz re the segment's
    total), i.e. what changes besides gain;
  * the eight-bar held note under pp -> ff -> pp (bars 10-17): level and centroid vs the
    CC1 the MIDI sends (correlations), level steps between 50 ms frames, deviation from a
    1 s smooth of the level, the same around the layer switches, and envelope modulation
    at 10-100 Hz (zipper) re a held note at fixed CC1 (edge probe, if present);
  * voicing: bars 19-20 with violin II (alto) as "subject" vs the same render without
    roles; bars 22-23 (no role in either) calibrate the two renders' normalisation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import savgol_filter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import (R2, SR, TMP, band_share, centroid, db, interharmonic_db, midi_voices, perform, render, rms_env,  # noqa: E402
                    save)

BAR = 4 * 60 / 72
INST = [("soprano", "vn1"), ("alto", "vn2"), ("tenor", "va"), ("bass", "vc")]
HELD = {"vn1": 81, "vn2": 62, "va": 48, "vc": 36}


def seg(x, b0, b1):
    return x[int((b0 - 1) * BAR * SR): int((b1 - 1) * BAR * SR)]


def active(x, thr_db=-40):
    t, e = rms_env(x, 0.02, 0.01)
    keep = e > e.max() + thr_db
    idx = np.repeat(keep, int(0.01 * SR))
    return x[: len(idx)][idx[: len(x)]] if len(idx) else x


def bands(x):
    tot = np.sum(x ** 2)
    out = {}
    for lo, hi, nm in ((0, 500, "lt500"), (500, 2000, "0.5-2k"), (2000, 5000, "2-5k"), (5000, 10000, "5-10k")):
        out[nm] = round(float(db(band_share(x, lo, hi))), 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    D = R2 / "dyn"
    TMP.mkdir(exist_ok=True)
    if not a.reuse:
        perform(D / "dyn_r2.ly", D / "dyn_r2.plan.json", TMP / "dyn.mid")
        perform(D / "dyn_r2.ly", D / "dyn_r2_noroles.plan.json", TMP / "dyn_noroles.mid")
        render(TMP / "dyn.mid", TMP / "dyn", "--keep-start", keep_temp=False)
        render(TMP / "dyn_noroles.mid", TMP / "dyn_noroles", "--keep-start", keep_temp=False)
    midi = midi_voices(TMP / "dyn.mid")
    cc1 = {v["name"]: v["cc"].get(1, []) for v in midi.values()}
    res = dict(phrase={}, hairpin={}, voicing={})
    base = {}
    base_p = TMP / "edge_long.json"
    if base_p.exists():
        base = json.loads(base_p.read_text()).get("fixed_mod", {})
    for voice, tag in INST:
        x, sr = sf.read(str(TMP / f"dyn_stem_{tag}.wav"), always_2d=True)
        x = x.mean(axis=1)
        # ---- phrase at three levels
        ph = {}
        for lvl, (b0, b1) in (("pp", (1, 3)), ("mf", (4, 6)), ("ff", (7, 9))):
            s = active(seg(x, b0, b1))
            ph[lvl] = dict(rms_db=round(float(db(np.mean(s ** 2))), 2), centroid_hz=round(centroid(s), 1), bands=bands(s))
        ph["pp_to_ff_db"] = round(ph["ff"]["rms_db"] - ph["pp"]["rms_db"], 2)
        ph["centroid_ratio_ff_pp"] = round(ph["ff"]["centroid_hz"] / ph["pp"]["centroid_hz"], 3)
        ph["gain_matched_2_5k_ff_minus_pp_db"] = round(ph["ff"]["bands"]["2-5k"] - ph["pp"]["bands"]["2-5k"], 2)
        ph["gain_matched_5_10k_ff_minus_pp_db"] = round(ph["ff"]["bands"]["5-10k"] - ph["pp"]["bands"]["5-10k"], 2)
        res["phrase"][tag] = ph
        # ---- held note hairpin, bars 10-17 (+ release margin excluded)
        t0, t1 = 9 * BAR + 0.3, 17 * BAR - 0.1
        h = x[int(t0 * SR): int(t1 * SR)]
        te, e = rms_env(h, 0.05, 0.01)
        te = te + t0
        c_ev = cc1[voice]
        c_t = np.array([c for c, _ in c_ev])
        c_v = np.array([v for _, v in c_ev], dtype=float)
        c_at = np.interp(te, c_t, c_v)
        # centroid per 0.25 s
        W = int(0.25 * SR)
        cents_t, cents_v = [], []
        for s0 in range(0, len(h) - W, W):
            cents_t.append(t0 + (s0 + W / 2) / SR)
            cents_v.append(centroid(h[s0: s0 + W]))
        cents_t, cents_v = np.array(cents_t), np.array(cents_v)
        c_at_c = np.interp(cents_t, c_t, c_v)
        sm = savgol_filter(e, 101, 2)                  # 1 s smooth
        dev = e - sm
        step = np.abs(e[5:] - e[:-5])                  # 50 ms steps
        # layer switches: where CC1 crosses 70 / 109 up, 66 / 106 down
        sw = []
        for thr_up, thr_dn in ((70, 66), (109, 106)):
            up = np.flatnonzero((c_at[:-1] < thr_up) & (c_at[1:] >= thr_up))
            dn = np.flatnonzero((c_at[:-1] > thr_dn) & (c_at[1:] <= thr_dn))
            sw += [float(te[i]) for i in np.concatenate([up, dn])]
        near = np.zeros(len(te), bool)
        for s_ in sw:
            near |= np.abs(te - s_) < 0.5
        # zipper: modulation spectrum of the 2 ms log envelope, 10-100 Hz band, per second of signal
        te2, e2 = rms_env(h, 0.004, 0.002)
        ed = e2 - savgol_filter(e2, 251, 2)
        F = np.abs(np.fft.rfft(ed * np.hanning(len(ed)))) ** 2
        fm = np.fft.rfftfreq(len(ed), 0.002)
        mod = float(db(F[(fm >= 10) & (fm <= 100)].sum() / F[(fm > 0.5) & (fm < 10)].sum()))
        ih = interharmonic_db(h, HELD[tag])
        # level per dynamic step (CC1 13 per step), rise and fall halves
        half = te < 13 * BAR
        slope_up = np.polyfit(c_at[half & (te > 9 * BAR + 1)], e[half & (te > 9 * BAR + 1)], 1)[0] * 13
        slope_dn = np.polyfit(c_at[~half], e[~half], 1)[0] * 13
        # monotonicity over 0.5 s blocks
        blk = [float(np.mean(e[(te >= b) & (te < b + 0.5)])) for b in np.arange(t0, t1 - 0.5, 0.5)]
        bt = np.arange(t0, t1 - 0.5, 0.5)
        d = np.diff(blk)
        nonmono_up = int(np.sum(d[bt[1:] < 13 * BAR - 0.5] < -0.3))
        nonmono_dn = int(np.sum(d[bt[1:] > 13 * BAR + 0.5] > 0.3))
        res["hairpin"][tag] = dict(
            range_db=round(float(np.percentile(e, 98) - np.percentile(e, 2)), 1),
            corr_level_cc1=round(float(np.corrcoef(e, c_at)[0, 1]), 3),
            corr_centroid_cc1=round(float(np.corrcoef(cents_v, c_at_c)[0, 1]), 3),
            centroid_at_min_cc1_hz=round(float(cents_v[np.argmin(c_at_c)]), 0),
            centroid_at_max_cc1_hz=round(float(cents_v[np.argmax(c_at_c)]), 0),
            db_per_dynamic_step_up=round(float(slope_up), 2), db_per_dynamic_step_down=round(float(slope_dn), 2),
            max_step_50ms_db=round(float(step.max()), 2), p99_step_50ms_db=round(float(np.percentile(step, 99)), 2),
            max_dev_from_1s_smooth_db=round(float(np.abs(dev).max()), 2),
            max_dev_near_layer_switch_db=round(float(np.abs(dev[near]).max()), 2) if near.any() else None,
            max_dev_elsewhere_db=round(float(np.abs(dev[~near]).max()), 2),
            layer_switch_times=[round(s_, 2) for s_ in sorted(sw)],
            nonmonotonic_0p5s_blocks=dict(rise=nonmono_up, fall=nonmono_dn, of=len(d)),
            zipper_mod_10_100hz_re_0p5_10hz_db=round(mod, 1),
            interharmonic_median_db=round(float(np.median(ih)), 1), interharmonic_p95_db=round(float(np.percentile(ih, 95)), 1),
            interharmonic_max_db=round(float(ih.max()), 1),
            fixed_cc1_baseline=base.get(tag))
        # ---- voicing
    y = {}
    for nm in ("dyn", "dyn_noroles"):
        for voice, tag in INST:
            z, _ = sf.read(str(TMP / f"{nm}_stem_{tag}.wav"), always_2d=True)
            y[(nm, tag)] = z.mean(axis=1)
    cal = []
    for voice, tag in INST:
        cal.append(db(np.mean(seg(y[("dyn", tag)], 22, 24) ** 2)) - db(np.mean(seg(y[("dyn_noroles", tag)], 22, 24) ** 2)))
    cal = float(np.median(cal))
    for voice, tag in INST:
        s1, s0 = seg(y[("dyn", tag)], 19, 21), seg(y[("dyn_noroles", tag)], 19, 21)
        res["voicing"][tag] = dict(
            lift_db=round(float(db(np.mean(s1 ** 2)) - db(np.mean(s0 ** 2)) - cal), 2),
            centroid_hz=[round(centroid(active(s0)), 0), round(centroid(active(s1)), 0)])
    # alto re the other three in bars 19-20, with and without the role
    def share(nm):
        e = {tag: np.mean(seg(y[(nm, tag)], 19, 21) ** 2) for _, tag in INST}
        return round(float(db(e["vn2"] / np.mean([e[t] for t in ("vn1", "va", "vc")]))), 2)
    res["voicing"]["vn2_re_mean_of_others_db"] = dict(with_role=share("dyn"), without=share("dyn_noroles"))
    res["voicing"]["normalisation_offset_db"] = round(cal, 3)
    save("dyn.json", res)
    for tag, p in res["phrase"].items():
        print(tag, {k: (v["rms_db"], v["centroid_hz"]) for k, v in p.items() if isinstance(v, dict)},
              "pp->ff", p["pp_to_ff_db"], "cent ratio", p["centroid_ratio_ff_pp"], "2-5k gm", p["gain_matched_2_5k_ff_minus_pp_db"])
    for tag, h in res["hairpin"].items():
        print(tag, h)
    print(res["voicing"])


if __name__ == "__main__":
    main()
