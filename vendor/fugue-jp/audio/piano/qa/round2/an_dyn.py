#!/usr/bin/env python3
"""Dynamics through the whole chain: qa/round2/dyn/dyn2.ly + dyn2.plan.json -> perform.py -> render_piano.py.

usage: an_dyn.py BASE OUT.json      (BASE.wav, BASE_stems/, BASE.mid; quarter = 80, bar = 3 s)

Segments (the same phrase, three voices): pp bars 1-2, mf bars 4-5, ff bars 7-8.
RMS of the final file; spectral centroid, HF ratio (>2 kHz) and octave-band levels of the dry
stem sum (the hall does not colour it). "Gain-matched" band levels bring each segment to the ff
segment's overall level: a pure gain change would leave every band at 0 dB.
Hairpin bars 10-17 (pp -> ff -> pp over repeated notes at constant pitch): per quarter beat,
level and HF ratio; monotonic? largest step against the ramp? correlation with the plan.
Voicing bars 19-20 (alto free) vs 22-23 (alto subject): alto stem re the other two stems.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import SR, midi_notes, read, write_json  # noqa: E402

LEAD = 0.3
BAR = 3.0
Q = 0.75


def seg(x, t0, t1):
    return x[int((t0 + LEAD) * SR):int((t1 + LEAD) * SR)]


def rms_db(x):
    return float(10 * np.log10(np.mean(x ** 2) + 1e-30))


def spec(x):
    m = x.mean(axis=1) if x.ndim == 2 else x
    f, p = ss.welch(m, SR, nperseg=8192)
    tot = p.sum()
    cen = float((f * p).sum() / tot)
    hf = float(10 * np.log10(p[f > 2000].sum() / tot))
    bands = {}
    for fc in (125, 250, 500, 1000, 2000, 4000, 8000):
        sel = (f >= fc / 2 ** 0.5) & (f < fc * 2 ** 0.5)
        bands[fc] = float(10 * np.log10(p[sel].sum() + 1e-30))
    return cen, hf, bands, float(10 * np.log10(tot))


def main():
    base, out = Path(sys.argv[1]), Path(sys.argv[2])
    mix = read(base.with_suffix(".wav"))
    rep = json.loads(Path(str(base) + ".render.json").read_text())
    names = list(rep["voices"])
    stems = {n: read(Path(str(base) + "_stems") / f"{n}.wav") for n in names}
    L = max(len(s) for s in stems.values())
    stems = {n: np.pad(s, ((0, L - len(s)), (0, 0))) for n, s in stems.items()}
    dry = sum(stems.values())
    midi = midi_notes(Path(str(base) + ".mid"))
    res = {"render": rep.get("wav"), "velocity_scale": rep["velocity_scale"], "cc_dynamics": rep["cc_dynamics"],
           "segments": {}}
    ref = None
    for lab, b0 in (("ff", 7), ("pp", 1), ("mf", 4)):
        t0, t1 = (b0 - 1) * BAR, (b0 + 1) * BAR
        vel = [n["vel"] for n in midi if t0 - 0.05 <= n["start"] < t1]
        cen, hf, bands, tot = spec(seg(dry, t0, t1))
        cen_mix, hf_mix, _, _ = spec(seg(mix, t0, t1))
        if ref is None:
            ref = (bands, tot)
        gm = {fc: round(bands[fc] - tot - (ref[0][fc] - ref[1]), 1) for fc in bands}
        res["segments"][lab] = dict(bars=f"{b0}-{b0 + 1}", midi_velocity_mean=round(float(np.mean(vel)), 1),
                                    rms_final_dbfs=round(rms_db(seg(mix, t0, t1)), 1),
                                    centroid_dry_hz=round(cen), hf_ratio_dry_db=round(hf, 1),
                                    centroid_final_hz=round(cen_mix), hf_ratio_final_db=round(hf_mix, 1),
                                    band_re_ff_after_gain_match_db=gm)
    s = res["segments"]
    res["segments"] = {k: s[k] for k in ("pp", "mf", "ff")}
    res["pp_to_ff"] = dict(rms_span_db=round(s["ff"]["rms_final_dbfs"] - s["pp"]["rms_final_dbfs"], 1),
                           centroid_ratio=round(s["ff"]["centroid_dry_hz"] / s["pp"]["centroid_dry_hz"], 2),
                           hf_ratio_span_db=round(s["ff"]["hf_ratio_dry_db"] - s["pp"]["hf_ratio_dry_db"], 1))
    # hairpin
    lv, hfv, plan = [], [], []
    for k in range(32):
        t0 = 9 * BAR + k * Q
        x = seg(dry, t0, t0 + Q)
        lv.append(rms_db(seg(mix, t0, t0 + Q)))
        hfv.append(spec(x)[1])
        # plan level: pp(2) -> ff(7) over 16 beats, back over 16
        plan.append(2 + 5 * (k / 16) if k < 16 else 7 - 5 * ((k - 16) / 16))
    lv, hfv, plan = map(np.array, (lv, hfv, plan))
    up, dn = np.diff(lv[:16]), np.diff(lv[16:])
    # expected average step per beat
    res["hairpin"] = dict(
        level_db_per_beat=[round(float(v), 1) for v in lv],
        hf_ratio_db_per_beat=[round(float(v), 1) for v in hfv],
        level_span_db=round(float(lv.max() - lv.min()), 1), hf_span_db=round(float(hfv.max() - hfv.min()), 1),
        corr_level_plan=round(float(np.corrcoef(lv, plan)[0, 1]), 3),
        corr_hf_plan=round(float(np.corrcoef(hfv, plan)[0, 1]), 3),
        crescendo_steps_against_ramp=[round(float(d), 2) for d in up if d < 0],
        diminuendo_steps_against_ramp=[round(float(d), 2) for d in dn if d > 0],
        largest_step_db=round(float(np.abs(np.diff(lv)).max()), 2),
        mean_abs_step_db=round(float(np.abs(np.diff(lv)).mean()), 2),
    )
    # voicing
    vo = {}
    for lab, b0 in (("alto_free", 19), ("alto_subject", 22)):
        t0, t1 = (b0 - 1) * BAR, (b0 + 1) * BAR
        a = rms_db(seg(stems["alto"], t0, t1))
        others = [rms_db(seg(stems[n], t0, t1)) for n in names if n != "alto"]
        vel = [n["vel"] for n in midi if n["name"] == "alto" and t0 - 0.05 <= n["start"] < t1]
        vo[lab] = dict(alto_velocity_mean=round(float(np.mean(vel)), 1), alto_rms_dbfs=round(a, 1),
                       alto_re_loudest_other_db=round(a - max(others), 1),
                       alto_re_mean_other_db=round(a - 10 * math.log10(np.mean([10 ** (o / 10) for o in others])), 1),
                       alto_centroid_hz=round(spec(seg(stems["alto"], t0, t1))[0]))
    vo["gain_db"] = round(vo["alto_subject"]["alto_re_mean_other_db"] - vo["alto_free"]["alto_re_mean_other_db"], 1)
    res["voicing"] = vo
    write_json(out, res)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
