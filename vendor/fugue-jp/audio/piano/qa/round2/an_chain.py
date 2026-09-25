#!/usr/bin/env python3
"""End-to-end chain check: perform.py MIDI -> render_piano.py -> stems / mix.

usage: an_chain.py ORIG.mid RENDER.json STEMS_DIR OUT.json [--transpose voice=N ...]

1. What the renderer sent to sfizz (the stem MIDIs kept with --keep-temp) against the
   perform.py MIDI (own parser): every note present, onset/offset times preserved to the tick,
   velocity mapped by perform.py's anchors -> the calibration's suggested velocities.
2. What sfizz played (dry stems) against the ORIGINAL MIDI: onset of every note (steepest
   rise of the >1.5 kHz energy, 1 ms frames), rise of the note's own partials, pitch (harmonic
   sum, +-40 cents) and octave check (energy at the odd partials and at the half-partials of the
   expected pitch), damper release where the voice then rests, silence after the last note.
3. The same note-onset audibility in the final mix (all voices + hall).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import (SR, band_power, db, f0_estimate, frame_energy, hp_energy_db, midi_hz, midi_notes,  # noqa: E402
                  partial_peak_cents, read, write_json)

LEAD = 0.3
CAL = Path.home() / "Music/SampleLibraries/SalamanderGrandPiano/SalamanderGrandPiano-SFZ+FLAC-V3+20200602/SalamanderGrandPiano-Ricercar.calibration.json"
PERF_ANCHORS = [(0, 0), (22, "ppp"), (32, "pp"), (44, "p"), (56, "mp"), (68, "mf"), (82, "f"), (98, "ff"), (112, "fff")]


def perf_map(v, sug):
    xs = [a for a, _ in PERF_ANCHORS]
    ys = [0 if b == 0 else sug[b] for _, b in PERF_ANCHORS]
    return int(np.clip(round(float(np.interp(v, xs, ys))), 1, 127))


def main():
    orig_p, rep_p, stems_p, out_p = map(Path, sys.argv[1:5])
    transpose = {}
    for a in sys.argv[5:]:
        if "=" in a:
            k, v = a.split("=")
            transpose[k] = int(v)
    rep = json.loads(rep_p.read_text())
    tmp = Path(rep["temp"])
    names = list(rep["voices"])
    sug = json.loads(CAL.read_text())["suggested_velocities"]
    orig = midi_notes(orig_p)
    by_voice = {}
    for n in orig:
        by_voice.setdefault(n["name"], []).append(n)
    vscale = rep["velocity_scale"]

    # ---- 1. renderer transformation -------------------------------------------------------
    stem_notes = {nm: midi_notes(tmp / f"stem{i:02d}.mid") for i, nm in enumerate(names)}
    trans = {"missing": [], "merged_unison": 0, "restruck_shortened": 0, "timing_err_ms_max": 0.0,
             "velocity_mismatch": [], "found": 0}
    for nm, lst in by_voice.items():
        tr = transpose.get(nm, 0)
        for n in lst:
            key = n["key"] + tr
            t = n["start"] + LEAD
            cand = [s for s in stem_notes[nm] if s["key"] == key and abs(s["start"] - t) < 0.0015]
            if cand:
                s = cand[0]
                trans["found"] += 1
                trans["timing_err_ms_max"] = max(trans["timing_err_ms_max"], abs(s["start"] - t) * 1000)
                if abs(s["end"] - (n["end"] + LEAD)) > 0.0015:
                    trans["restruck_shortened"] += 1
                want = perf_map(n["vel"], sug) if vscale == "perform" else n["vel"]
                if abs(s["vel"] - want) > 1:  # CC dynamics could move it; perform.py piano files carry none
                    trans["velocity_mismatch"].append((nm, key, round(n["start"], 3), n["vel"], s["vel"], want))
                continue
            other = [(o, s) for o, sl in stem_notes.items() for s in sl
                     if s["key"] == key and -0.031 < s["start"] - t <= 0.0015]
            if other:
                trans["merged_unison"] += 1
            else:
                trans["missing"].append((nm, key, round(n["start"], 3)))
    stem_total = sum(len(v) for v in stem_notes.values())

    # ---- 2. stems -------------------------------------------------------------------------
    per_voice = {}
    all_rows = []
    for i, nm in enumerate(names):
        x = read(stems_p / f"{nm}.wav")
        m = x.mean(axis=1)
        hp = hp_energy_db(m, 1500.0)
        full = db(frame_energy(m))
        top = full.max()
        tr = transpose.get(nm, 0)
        lst = [n for n in by_voice[nm]]
        sounding_keys = [(s["start"], s["end"], s["key"]) for s in stem_notes[nm]]
        rows = []
        for j, n in enumerate(lst):
            key = n["key"] + tr
            t_on, t_off = n["start"] + LEAD, n["end"] + LEAD
            # if this note was merged into another voice's blow, skip audio checks here
            if not any(s[2] == key and abs(s[0] - t_on) < 0.0015 for s in sounding_keys):
                continue
            on, slope = _onset(hp, t_on)
            parts = [midi_hz(key) * p for p in range(1, 9)]
            # audibility: rise of this note's partials that the previous note of the voice does not share
            prev = [s for s in sounding_keys if s[0] < t_on - 0.001 and s[1] > t_on - 0.45]
            pp = [midi_hz(s[2]) * q for s in prev for q in range(1, 21)]
            own = [f for f in [midi_hz(key) * q for q in range(1, 11)] if all(abs(f / g - 1) > 0.02 for g in pp)] or parts
            W = max(0.06, min(0.2, n["end"] - n["start"] - 0.03))
            rise = db(band_power(m, t_on + 0.02, t_on + 0.02 + W, own, rel_bw=0.006)) - \
                db(band_power(m, t_on - 0.02 - W, t_on - 0.02, own, rel_bw=0.006))
            row = dict(voice=nm, key=key, t=round(t_on, 3), dur=round(n["end"] - n["start"], 3), vel=n["vel"],
                       onset_ms=round((on - t_on) * 1000, 1), hp_slope_db=round(slope, 1), partial_rise_db=round(float(rise), 1))
            d = n["end"] - n["start"]
            if d >= 0.14:
                w1 = t_on + 0.03 + min(d - 0.05, 0.45)
                # partial 1 from A2 up (the harmonic sum trades f0 against inharmonicity in short
                # windows and reads the treble up to 12 cents sharp); harmonic sum with B below
                if key >= 45:
                    c = partial_peak_cents(m, t_on + 0.03, w1, key, 1, span=40)
                else:
                    c, _ = f0_estimate(m, t_on + 0.03, w1, key, span_cents=40)
                row["cents"] = round(c, 1)
                f = midi_hz(key)
                odd = band_power(m, t_on + 0.03, w1, [f, 3 * f, 5 * f])
                even = band_power(m, t_on + 0.03, w1, [2 * f, 4 * f, 6 * f])
                half = band_power(m, t_on + 0.03, w1, [0.5 * f, 1.5 * f, 2.5 * f])
                row["odd_re_even_db"] = round(float(db(odd) - db(even)), 1)
                row["half_re_even_db"] = round(float(db(half) - db(even)), 1)
            # damper: next note in this voice starts >= 0.3 s after key-up
            nxt = lst[j + 1]["start"] + LEAD if j + 1 < len(lst) else 1e9
            if nxt - t_off >= 0.3:
                pre = band_power(m, t_off - 0.08, t_off - 0.005, parts)
                post = band_power(m, t_off + 0.15, t_off + 0.25, parts)
                row["release_drop_db"] = round(float(db(post) - db(pre)), 1)
                row["gap_s"] = round(min(nxt - t_off, 99), 2)
            rows.append(row)
        # silence after the last key-up (+1.5 s) re the stem's loudest 1 ms frame
        last_off = max(s[1] for s in sounding_keys)
        a = int((last_off + 1.5) * 1000)
        tail = float(full[a:a + 500].mean()) - top if a + 500 < len(full) else None
        per_voice[nm] = _summ(rows)
        per_voice[nm]["level_1p5s_after_last_keyup_db_re_peak"] = None if tail is None else round(tail, 1)
        per_voice[nm]["dc"] = [float(x[:, 0].mean()), float(x[:, 1].mean())]
        all_rows += rows

    # ---- 3. final mix: onsets audible over the other voices and the hall ------------------
    mix = read(Path(rep["wav"]))
    mm = mix.mean(axis=1)
    mix_rise = []
    for r in all_rows:
        parts = [midi_hz(r["key"]) * p for p in range(1, 9)]
        t = r["t"]
        mix_rise.append(float(db(band_power(mm, t + 0.01, t + 0.08, parts)) - db(band_power(mm, t - 0.08, t - 0.01, parts))))
        r["mix_partial_rise_db"] = round(mix_rise[-1], 1)
    mr = np.array(mix_rise)
    res = dict(
        input=str(orig_p), render=str(rep_p), velocity_scale=vscale,
        transformation=dict(orig_notes=len(orig), stem_notes=stem_total,
                            **{k: v for k, v in trans.items() if k != "velocity_mismatch"},
                            velocity_mismatch=trans["velocity_mismatch"][:10],
                            n_velocity_mismatch=len(trans["velocity_mismatch"])),
        voices=per_voice,
        all=_summ(all_rows),
        mix_onset_partial_rise_db=dict(min=round(float(mr.min()), 1), p5=round(float(np.percentile(mr, 5)), 1),
                                       median=round(float(np.median(mr)), 1), n_below_3db=int((mr < 3).sum()),
                                       weakest=sorted(all_rows, key=lambda r: r["mix_partial_rise_db"])[:8]),
        rows=all_rows,
    )
    write_json(out_p, res)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1)[:6000])


def _onset(hp, t):
    a, b = int((t - 0.03) * 1000), int((t + 0.05) * 1000)
    idx = np.arange(max(a, 3), min(b, len(hp) - 4))
    slope = hp[idx + 2] - hp[idx - 2]
    k = int(np.argmax(slope))
    return idx[k] / 1000.0, float(slope[k])


def _summ(rows):
    if not rows:
        return {}
    on = np.array([r["onset_ms"] for r in rows if r["key"] >= 36] or [0.0])
    rise = np.array([r["partial_rise_db"] for r in rows])
    c = np.array([r["cents"] for r in rows if "cents" in r])
    oe = np.array([r["odd_re_even_db"] for r in rows if "odd_re_even_db" in r])
    he = np.array([r["half_re_even_db"] for r in rows if "half_re_even_db" in r])
    rel = np.array([r["release_drop_db"] for r in rows if "release_drop_db" in r])
    return dict(
        n=len(rows),
        onset_ms=dict(median=float(np.median(on)), p95_abs=float(np.percentile(np.abs(on), 95)), max_abs=float(np.abs(on).max()),
                      n_over_20ms=int((np.abs(on) > 20).sum()),
                      note="keys >= C2 only: the >1.5 kHz attack slope of soft bass notes in legato is too weak to time",
                      worst=[{k: r[k] for k in ("voice", "key", "t", "onset_ms", "hp_slope_db", "partial_rise_db")}
                             for r in sorted([r for r in rows if r["key"] >= 36], key=lambda r: -abs(r["onset_ms"]))[:4]]),
        partial_rise_db=dict(min=float(rise.min()), p5=float(np.percentile(rise, 5)), median=float(np.median(rise)),
                             n_below_3db=int((rise < 3).sum()),
                             weakest=[{k: r[k] for k in ("voice", "key", "t", "vel", "partial_rise_db")}
                                      for r in sorted(rows, key=lambda r: r["partial_rise_db"])[:4]]),
        cents=dict(n=len(c), median=float(np.median(c)) if len(c) else None,
                   p5=float(np.percentile(c, 5)) if len(c) else None, p95=float(np.percentile(c, 95)) if len(c) else None,
                   n_abs_over_15=int((np.abs(c) > 15).sum())) if len(c) else {},
        octave_check=dict(odd_re_even_median_db=float(np.median(oe)) if len(oe) else None,
                          half_re_even_median_db=float(np.median(he)) if len(he) else None),
        release_drop_db=dict(n=len(rel), median=float(np.median(rel)) if len(rel) else None,
                             weakest=float(rel.max()) if len(rel) else None),
    )


if __name__ == "__main__":
    main()
