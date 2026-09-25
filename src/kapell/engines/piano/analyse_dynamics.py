#!/usr/bin/env python3
"""Measure the dynamics test render: loudness and timbre per segment.

Usage::

    python3 make_test_midi.py
    python3 render_piano.py out/dynamics_test.mid -o out/dynamics_test --stems out/dynamics_test_stems
    python3 analyse_dynamics.py            # defaults match the two commands above
    python3 analyse_dynamics.py --json out/dynamics_test.analysis.json

With --wav/--stems/--segments it also analyses the chain test (make_chain_test.py):
phrase segments are compared with the one named ff, ramp segments are tabulated per
note or per window, and the voicing section runs only when those segments exist.
``run_tests.sh`` runs both tests end to end.

The script answers one question: do dynamics change the timbre, or only the
gain? For every segment it reports

* **RMS** (dBFS, stereo) of the final normalised render,
* **spectral centroid** and **HF ratio** (energy above 2 kHz relative to the
  total, in dB) of the dry stem sum,
* for pp/mf/ff: octave-band spectra after **gain matching** to ff. A pure gain
  change would leave every band at 0 dB.

For the two crescendo passages (one repeated chord, so pitch is constant) it
prints the level and HF ratio of every chord.
For the voicing pair it gives the per-voice stem levels. Gain cannot move the
centroid or the HF ratio: both are ratios within one spectrum. So differences
there show that the sampler really changes layer (timbre).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import scipy.signal as ss
import soundfile as sf

HERE = Path(__file__).resolve().parent
BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


def rms_db(x: np.ndarray) -> float:
    return float(10 * np.log10(np.mean(np.sum(x**2, axis=1)) + 1e-20))


def spectrum(x: np.ndarray, sr: int):
    m = x.mean(axis=1)
    n = 1 << int(np.ceil(np.log2(len(m))))
    p = np.abs(np.fft.rfft(m * np.hanning(len(m)), n)) ** 2
    f = np.fft.rfftfreq(n, 1 / sr)
    return f, p


def centroid(x, sr) -> float:
    f, p = spectrum(x, sr)
    sel = f > 30
    return float((f[sel] * p[sel]).sum() / p[sel].sum())


def hf_ratio(x, sr, fc=2000) -> float:
    f, p = spectrum(x, sr)
    return float(10 * np.log10(p[f > fc].sum() / p[f > 30].sum()))


def octave_bands(x, sr) -> np.ndarray:
    f, p = spectrum(x, sr)
    return np.array([10 * np.log10(p[(f >= fc / np.sqrt(2)) & (f < fc * np.sqrt(2))].sum() + 1e-30) for fc in BANDS])


def main() -> None:
    ap = argparse.ArgumentParser(description="analyse the dynamics test render")
    ap.add_argument("--wav", type=Path, default=HERE / "out" / "dynamics_test.wav")
    ap.add_argument("--stems", type=Path, default=HERE / "out" / "dynamics_test_stems")
    ap.add_argument("--segments", type=Path, default=HERE / "out" / "dynamics_test.segments.json")
    ap.add_argument("--lead-in", type=float, default=0.3)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    segs = json.loads(args.segments.read_text())["segments"]
    mix, sr = sf.read(args.wav, dtype="float64", always_2d=True)
    stems = {p.stem: sf.read(p, dtype="float64", always_2d=True)[0] for p in sorted(args.stems.glob("*.wav"))}
    n = max(len(s) for s in stems.values())
    dry = np.zeros((n, 2))
    for s in stems.values():
        dry[: len(s)] += s

    def win(x, a, b):
        return x[int((a + args.lead_in) * sr) : int((b + args.lead_in) * sr)]

    res = {"segments": {}}
    print(f"{'segment':16s} {'RMS dBFS':>9s} {'centroid Hz':>12s} {'HF>2k dB':>9s}")
    for sg in segs:
        a, b = sg["start_s"], sg["end_s"] + 0.3
        r = {"rms_dbfs": round(rms_db(win(mix, a, b)), 2),
             "centroid_hz": round(centroid(win(dry, a, b), sr), 1),
             "hf_ratio_db": round(hf_ratio(win(dry, a, b), sr), 2)}
        res["segments"][sg["name"]] = r
        print(f"{sg['name']:16s} {r['rms_dbfs']:9.2f} {r['centroid_hz']:12.1f} {r['hf_ratio_db']:9.2f}")

    # --- phrases (pp / mf / ff): gain-matched spectra ------------------------------------------
    ph = {sg["name"]: sg for sg in segs if sg["kind"] == "phrase"}
    ref_name = "ff" if "ff" in ph else list(ph)[-1]
    ref = octave_bands(win(dry, ph[ref_name]["start_s"], ph[ref_name]["end_s"] + 0.3), sr)
    ref_rms = rms_db(win(dry, ph[ref_name]["start_s"], ph[ref_name]["end_s"] + 0.3))
    print(f"\ngain-matched to {ref_name} (dry, same RMS): octave-band level minus {ref_name} (dB); "
          "pure gain would be all 0")
    print("         " + " ".join(f"{b:>6d}" for b in BANDS))
    res["gain_matched_bands_db"] = {}
    for name in ph:
        x = win(dry, ph[name]["start_s"], ph[name]["end_s"] + 0.3)
        gain = ref_rms - rms_db(x)
        bands = octave_bands(x, sr) + gain - ref
        res["gain_matched_bands_db"][name] = {"gain_applied_db": round(gain, 2),
                                              "bands": {str(b): round(float(v), 2) for b, v in zip(BANDS, bands)}}
        print(f"{name:3s} +{gain:4.1f}  " + " ".join(f"{v:6.1f}" for v in bands))

    # --- crescendo ramps -----------------------------------------------------------------------
    for sg in (s for s in segs if s["kind"] == "ramp"):
        name = sg["name"]
        rows = []
        for nt in sg["notes"]:
            x = win(dry, nt["t_s"], nt["t_s"] + nt.get("win_s", 0.25))
            rows.append((nt, rms_db(x), centroid(x, sr), hf_ratio(x, sr)))
        lv = np.array([r[1] for r in rows])
        ce = np.array([r[2] for r in rows])
        hf = np.array([r[3] for r in rows])
        key = "cc11" if "cc11" in rows[0][0] else "level" if "level" in rows[0][0] else "velocity"
        ctl = np.array([r[0][key] for r in rows], dtype=float)
        imax = int(np.argmax(ctl))
        rise = np.diff(lv[: imax + 1])
        fall = np.diff(lv[imax:])
        label = {"cc11": "CC11 at velocity 120", "level": "plan level (2 = pp, 7 = ff) via perform.py",
                 "velocity": "velocity"}[key]
        print(f"\n{name}: per-{'window' if key == 'level' else 'note'} level (dB, dry) / HF ratio (dB); "
              f"control = {label}")
        print("  " + " ".join(f"{c:g}:{l:.0f}/{h:.0f}" for c, l, h in zip(ctl, lv, hf)))
        if key == "level":
            print("  velocity per window: " + " ".join(f"{r[0]['velocity']:g}" for r in rows))
            print("  centroid per window: " + " ".join(f"{c:.0f}" for c in ce))
        stat = {
            "level_range_db": round(float(lv.max() - lv.min()), 2),
            "hf_ratio_range_db": round(float(hf.max() - hf.min()), 2),
            "centroid_range_hz": [round(float(ce.min()), 1), round(float(ce.max()), 1)],
            "corr_level_vs_control": round(float(np.corrcoef(ctl, lv)[0, 1]), 3),
            "rising_steps_negative": int((rise < -0.5).sum()),
            "falling_steps_positive": int((fall > 0.5).sum()),
            "peak_note_level_db": round(float(lv[imax]), 2),
            "first_last_level_db": [round(float(lv[0]), 2), round(float(lv[-1]), 2)],
        }
        # Same chord throughout, so HF ratio and centroid track timbre only.
        lo = min(range(len(rows)), key=lambda k: ctl[k])
        stat["hf_ratio_loudest_minus_softest_db"] = round(float(hf[imax] - hf[lo]), 2)
        stat["corr_hf_ratio_vs_control"] = round(float(np.corrcoef(ctl, hf)[0, 1]), 3)
        res[name] = stat
        print("  " + json.dumps(stat))

    # --- voicing ---------------------------------------------------------------------------------
    names = [s["name"] for s in segs]
    if "voicing_flat" not in names or "voicing_tenor" not in names:
        if args.json:
            args.json.write_text(json.dumps(res, indent=1))
            print(f"\nwrote {args.json}")
        return
    res["voicing"] = {}
    print("\nvoicing: per-voice stem RMS (dBFS, dry, before normalisation)")
    for name in ["voicing_flat", "voicing_tenor"]:
        sg = next(s for s in segs if s["name"] == name)
        lv = {k: rms_db(win(v, sg["start_s"], sg["end_s"] + 0.3)) for k, v in stems.items()}
        ce = {k: centroid(win(v, sg["start_s"], sg["end_s"] + 0.3), sr) for k, v in stems.items()}
        others = np.mean([10 ** (lv[k] / 10) for k in lv if k != "Tenor"])
        diff = lv["Tenor"] - 10 * np.log10(others)
        res["voicing"][name] = {"stem_rms_dbfs": {k: round(v, 2) for k, v in lv.items()},
                                "stem_centroid_hz": {k: round(v, 1) for k, v in ce.items()},
                                "tenor_minus_mean_other_db": round(float(diff), 2)}
        print(f"  {name:14s} " + "  ".join(f"{k} {v:6.1f}" for k, v in lv.items()) + f"   tenor - others = {diff:+.1f} dB"
              f"   tenor centroid {ce['Tenor']:.0f} Hz")
    if args.json:
        args.json.write_text(json.dumps(res, indent=1))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
