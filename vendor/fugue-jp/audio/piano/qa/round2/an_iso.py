#!/usr/bin/env python3
"""Isolated notes A0..C8 at velocity 80 (probe 'iso'): onset latency, tuning, damper release, clicks.

Dry stem: /tmp/pianoqa2/iso_stems/iso.wav (render timeline = MIDI time + 0.3 s lead-in).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import (SR, band_power, click_scan, db, f0_estimate, frame_energy, hp_energy_db, midi_hz, midi_notes,  # noqa
                  partial_peak_cents, read, write_json)

LEAD = 0.3
P = Path("/tmp/pianoqa2")


def main():
    x = read(P / "iso_stems/iso.wav")
    m = x.mean(axis=1)
    hp = hp_energy_db(m, 1500.0)
    full = db(frame_energy(m))
    notes = midi_notes(P / "iso.mid")
    rows = []
    for n in notes:
        k, t_on, t_off = n["key"], n["start"] + LEAD, n["end"] + LEAD
        # onset: first 1 ms frame where full-band energy comes within 20 dB of the note's peak
        a = int((t_on - 0.05) * 1000)
        pk = int(np.argmax(full[a: a + 200])) + a
        base = np.median(full[a: a + 40])
        thr = full[pk] - 20
        i = a + int(np.argmax(full[a: pk + 1] > thr))
        onset_ms = (i / 1000 - t_on) * 1000
        # tuning: partial 1 for key >= 45 (A2), harmonic-sum with inharmonicity below
        w0, w1 = t_on + 0.08, t_on + 0.95
        if k >= 45:
            cents = partial_peak_cents(m, w0, w1, k, 1, span=60)
        else:
            cents, _ = f0_estimate(m, w0, w1, k, span_cents=60)
        # damper: level of this note's partials 150-250 ms after key-up re the 100 ms before key-up
        partials = [midi_hz(k) * p for p in range(1, 9)]
        pre = band_power(m, t_off - 0.10, t_off, partials)
        post = band_power(m, t_off + 0.15, t_off + 0.25, partials)
        # natural decay reference: 200 ms earlier in the held note (same spacing)
        ref_a = band_power(m, t_off - 0.45, t_off - 0.35, partials)
        ref_b = band_power(m, t_off - 0.20, t_off - 0.10, partials)
        rows.append(dict(key=k, onset_ms=round(onset_ms, 2), rise_db=round(float(full[pk] - base), 1),
                         cents_re_et=round(cents, 2), damper_drop_db=round(float(db(post) - db(pre)), 1),
                         held_decay_db_per_200ms=round(float(db(ref_b) - db(ref_a)), 1),
                         peak_dbfs=round(float(full[pk]), 1)))
    on = np.array([r["onset_ms"] for r in rows])
    cents = np.array([r["cents_re_et"] for r in rows])
    keys = np.array([r["key"] for r in rows])
    dd = np.array([r["damper_drop_db"] for r in rows])
    # smoothness of the tuning curve: deviation from a 7-key running median
    from scipy.signal import medfilt
    sm = medfilt(cents, 7)
    dev = cents - sm
    steps = np.diff(cents)
    clicks = click_scan(x, protect=[n["start"] + LEAD for n in notes], k=12.0)
    # release clicks: those near a key-up
    offs = np.array([n["end"] + LEAD for n in notes])
    rel_clicks = [c for c in clicks if np.min(np.abs(offs - c["t"])) < 0.02]
    peaks = np.array([r["peak_dbfs"] for r in rows])
    res = dict(
        probe="iso: A0..C8, velocity 80, 1.0 s held, dry stem",
        onset_ms=dict(min=float(on.min()), max=float(on.max()), median=float(np.median(on)),
                      worst=[r for r in sorted(rows, key=lambda r: -abs(r["onset_ms"]))[:5]]),
        tuning_cents_re_ET=dict(
            A0_C1=[float(c) for c in cents[:4]], C8=float(cents[-1]),
            mid_C3_C6_range=[float(cents[(keys >= 48) & (keys <= 84)].min()), float(cents[(keys >= 48) & (keys <= 84)].max())],
            abs_max_C3_C6=float(np.abs(cents[(keys >= 48) & (keys <= 84)]).max()),
            largest_semitone_step=float(np.abs(steps).max()),
            largest_step_at=int(keys[1:][np.argmax(np.abs(steps))]),
            max_dev_from_running_median=float(np.abs(dev).max()),
            max_dev_at=int(keys[np.argmax(np.abs(dev))]),
            n_keys_dev_gt_5c=int((np.abs(dev) > 5).sum()),
        ),
        damper=dict(
            drop_db_150_250ms_after_keyup_by_range={
                "A0-E2": float(np.median(dd[keys <= 40])), "F2-E6": float(np.median(dd[(keys > 40) & (keys <= 88)])),
                "F6-C8 (no dampers)": float(np.median(dd[keys > 88]))},
            weakest_damped=sorted([r for r in rows if r["key"] <= 88], key=lambda r: r["damper_drop_db"])[-5:],
        ),
        evenness=dict(peak_dbfs_range=[float(peaks.min()), float(peaks.max())],
                      max_adjacent_key_step_db=float(np.abs(np.diff(peaks)).max()),
                      at_key=int(keys[1:][np.argmax(np.abs(np.diff(peaks)))])),
        clicks_outside_onsets=len(clicks), clicks_near_keyup=rel_clicks[:10], clicks_sample=clicks[:10],
        dc_offset=[float(x[:, 0].mean()), float(x[:, 1].mean())],
        rows=rows,
    )
    write_json(Path(__file__).parent / "results/iso.json", res)
    print({k: v for k, v in res.items() if k != "rows"})


if __name__ == "__main__":
    main()
