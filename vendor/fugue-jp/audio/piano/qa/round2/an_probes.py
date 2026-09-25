#!/usr/bin/env python3
"""Analyses of the small adversarial probes (stemend_top, stemend_pedal, repeat, keyshare, fast16)."""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import SR, band_power, click_scan, db, frame_energy, hp_energy_db, midi_hz, midi_notes, read, write_json  # noqa

P = Path("/tmp/pianoqa2")
LEAD = 0.3


def end_profile(path):
    x = read(path)
    m = x.mean(axis=1)
    env = db(frame_energy(m, 10.0))
    top = env.max()
    n = len(env)
    last = env[-50:]
    # abrupt stop: the last 10 ms frames vs 100 ms earlier
    return dict(duration_s=round(len(m) / SR, 2), last_100ms_db_re_peak=round(float(env[-10:].mean() - top), 1),
                level_0p5s_before_end_db_re_peak=round(float(env[-60:-50].mean() - top), 1),
                slope_last_0p5s_db_per_s=round(float(np.polyfit(np.arange(len(last)) / 100, last, 1)[0]), 1),
                abs_last_sample=float(np.abs(x[-1]).max()),
                max_abs_last_10ms_dbfs=round(20 * math.log10(float(np.abs(x[-480:]).max()) + 1e-20), 1))


def stemend():
    out = {}
    for p, stem in (("stemend_top", "top"), ("stemend_pedal", "chord")):
        out[p] = dict(final=end_profile(P / f"{p}.wav"), dry_stem=end_profile(P / f"{p}_stems/{stem}.wav"))
    return out


def repeat():
    meta = json.loads((P / "repeat.meta.json").read_text())
    x = read(P / "repeat_stems/rep.wav")
    notes = midi_notes(P / "repeat.mid")
    ons = [n["start"] + LEAD for n in notes]
    cl = click_scan(x, protect=ons, k=12.0, protect_ms=8.0)
    m = x.mean(axis=1)
    hp = hp_energy_db(m, 4000.0)
    out = {"clicks_outside_onsets": cl[:20], "n_clicks": len(cl), "segments": {}}
    for lab, (t0, t1) in meta["segments"].items():
        seg_notes = [n for n in notes if t0 - 1e-6 <= n["start"] < t1]
        rises = []
        for n in seg_notes:
            t = n["start"] + LEAD
            parts = [midi_hz(n["key"]) * q for q in range(1, 9)]
            rises.append(float(db(band_power(m, t + 0.005, t + 0.045, parts)) - db(band_power(m, t - 0.045, t - 0.005, parts))))
        # level after the run: pedal/no-damper segments should ring, damped ones stop
        a = int((t1 + LEAD + 0.4) * 1000)
        pk = float(db(frame_energy(m[int((t0 + LEAD) * SR):int((t1 + LEAD) * SR)])).max())
        out["segments"][lab] = dict(n=len(seg_notes), onset_rise_db_min=round(min(rises), 1), onset_rise_db_median=round(float(np.median(rises)), 1),
                                    clicks=[c for c in cl if t0 + LEAD <= c["t"] <= t1 + LEAD + 2.0],
                                    level_0p4s_after_run_db_re_run_peak=round(float(db(frame_energy(m))[a:a + 50].mean()) - pk, 1))
    return out


def keyshare():
    meta = json.loads((P / "keyshare.meta.json").read_text())
    xa = read(P / "keyshare_stems/A.wav")
    xb = read(P / "keyshare_stems/B.wav")
    n = max(len(xa), len(xb))
    xa = np.pad(xa, ((0, n - len(xa)), (0, 0)))
    xb = np.pad(xb, ((0, n - len(xb)), (0, 0)))
    m = (xa + xb).mean(axis=1)
    hp = hp_energy_db(m, 1500.0)
    rows = []
    for c in meta["cases"]:
        t = c["t"] + LEAD
        seg = hp[int(t * 1000) - 20:int(t * 1000) + 400]
        sl = seg[4:] - seg[:-4]
        # attack events: 4 ms rises of more than 15 dB, merged within 10 ms
        ev = []
        for i in np.nonzero(sl > 15)[0]:
            tt = (i + 2 - 20) / 1000
            if not ev or tt - ev[-1] > 0.010:
                ev.append(tt)
        e300 = float(db(frame_energy(m[int(t * SR):int((t + 0.3) * SR)], 290.0))[0])
        rows.append(dict(offset_ms=round(c["offset"] * 1000), attacks_ms=[round(e * 1000, 1) for e in ev],
                         energy_0_300ms_db=round(e300, 2),
                         in_A=float(db(frame_energy(xa[int(t * SR):int((t + 0.3) * SR)].mean(axis=1), 290.0))[0]),
                         in_B=float(db(frame_energy(xb[int(t * SR):int((t + 0.3) * SR)].mean(axis=1), 290.0))[0])))
    return rows


def fast16():
    meta = json.loads((P / "fast16.meta.json").read_text())
    notes = midi_notes(P / "fast16.mid")
    out = {}
    for src, path in (("dry_stem", P / "fast16_stems/run.wav"), ("final_mix", P / "fast16.wav")):
        m = read(path).mean(axis=1)
        res = {}
        for lab, (t0, t1, d16) in meta["segments"].items():
            sn = [n for n in notes if t0 - 1e-6 <= n["start"] < t1]
            bleed, dips = [], []
            for a, b in zip(sn[:-1], sn[1:]):
                ta, tb = a["start"] + LEAD, b["start"] + LEAD
                pa = [midi_hz(a["key"]) * q for q in range(1, 9)]
                pb = [midi_hz(b["key"]) * q for q in range(1, 9)]
                pa_own = [f for f in pa if all(abs(f / g - 1) > 0.03 for g in pb)]
                pb_own = [f for f in pb if all(abs(f / g - 1) > 0.03 for g in pa)]
                w0, w1 = tb + 0.02, tb + min(0.07, d16 - 0.005)
                bleed.append(float(db(band_power(m, w0, w1, pa_own)) - db(band_power(m, w0, w1, pb_own))))
            res[lab] = dict(sixteenth_ms=round(d16 * 1000), prev_note_bleed_db_median=round(float(np.median(bleed)), 1),
                            prev_note_bleed_db_worst=round(float(np.max(bleed)), 1))
        out[src] = res
    return out


def main():
    res = dict(stemend=stemend(), repeat=repeat(), keyshare=keyshare(), fast16=fast16())
    write_json(Path(__file__).parent / "results/probes.json", res)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
