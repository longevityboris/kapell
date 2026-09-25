#!/usr/bin/env python3
"""Objective listening checks on a quartet render (needs --stems --report).

  python3 qa_render.py OUT_BASENAME [--json QA.json]

OUT_BASENAME is what render_quartet.py was given with -o; the script reads
OUT_BASENAME.json (--report), OUT_BASENAME_stem_<inst>.wav (--stems) and
OUT_BASENAME.wav.  Levels are K-weighted (BS.1770).

  balance     where all four instruments sound at once, each dry stem's level
              re the loudest (median over 0.4 s windows); the inner voices
              should sit within a few dB of the outer ones
  clicks      isolated broadband impulses: 0.5 ms frames of the >5 kHz band
              more than 15 dB above both the median of the surrounding 40 ms
              and the frames 2 ms either side (a bow attack rises over several
              ms and is not counted); reported per stem with the nearest note
              boundary and the spike level re the instrument's own level (100 ms
              RMS); spikes within 20 dB of it are counted as audible candidates
  short notes onset rise (20 ms RMS, level 20-40 ms after the note-on minus 10 ms before) and
              time to reach the note's peak - 3 dB, for notes played with the
              short stroke
  legato      level dip at slurred note changes: minimum in [-20, +100] ms
              around the new note below the quieter of the two notes (0 = no dip;
              a step between a loud and a soft note is not a dip)
  dynamics    K-weighted level of the first 10 s (pp exposition) vs the loudest 10 s
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter
from scipy.signal import butter, lfilter, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_dynamics import a_weight, k_weight  # noqa: E402

NAMES = {"vn1": "Violin I", "vn2": "Violin II", "va": "Viola", "vc": "Cello", "cb": "Contrabass"}


def env_db(x, sr, hop_s, win_s=None):
    """RMS envelope in dB, one value per hop; win_s (> hop) = sliding window
    centred on each hop (use >= 20 ms for the cello: its periods are 7-15 ms)."""
    hop = max(1, int(hop_s * sr))
    if win_s is None:
        n = len(x) // hop
        return 10 * np.log10(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20), hop
    w = int(win_s * sr)
    p = np.convolve(x.astype(np.float64) ** 2, np.ones(w) / w, mode="same")
    return 10 * np.log10(p[::hop] + 1e-20), hop


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rep = json.loads(a.base.with_suffix(".json").read_text())
    off = rep["offset_s"]
    stems = {}
    for inst in NAMES:
        p = a.base.parent / f"{a.base.name}_stem_{inst}.wav"
        if p.exists():
            x, sr = sf.read(str(p), dtype="float64", always_2d=True)
            stems[inst] = x.mean(axis=1)
    aw = a_weight(sr)
    A = {k: lfilter(*aw, v) for k, v in stems.items()}
    K = {k: k_weight(v, sr) for k, v in stems.items()}
    notes = {}
    for j in rep["jobs"]:
        notes.setdefault(j["inst"], []).extend(j["note_list"])
    out = {}

    # ---------------------------------------------------------------- balance
    win, hop = 0.4, 0.2
    n_win = int((len(next(iter(A.values()))) / sr - win) / hop)
    quartet = [i for i in ("vn1", "vn2", "va", "vc") if i in A]
    rows = []
    for w in range(n_win):
        t0 = off + w * hop
        t1 = t0 + win

        def active(inst):
            cov = 0.0
            for on, of, *_ in notes.get(inst, []):
                cov += max(0.0, min(t1, of) - max(t0, on))
            return cov >= 0.7 * win
        if all(active(i) for i in quartet):
            i0, i1 = int(w * hop * sr), int((w * hop + win) * sr)
            rows.append([10 * np.log10(np.mean(K[i][i0:i1] ** 2) + 1e-20) for i in quartet])
    if rows:
        L = np.array(rows)
        rel = L - L.max(axis=1, keepdims=True)
        out["balance"] = dict(windows=len(rows), median_db_re_loudest={NAMES[i]: round(float(np.median(rel[:, k])), 1)
                                                                       for k, i in enumerate(quartet)},
                              p10_db_re_loudest={NAMES[i]: round(float(np.percentile(rel[:, k], 10)), 1)
                                                 for k, i in enumerate(quartet)},
                              share_of_windows_loudest={NAMES[i]: round(float(np.mean(rel[:, k] == 0)), 2)
                                                        for k, i in enumerate(quartet)})

    # ----------------------------------------------------------------- clicks
    sos = butter(4, 5000, "highpass", fs=sr, output="sos")
    clicks = {}
    for inst, x in stems.items():
        h = sosfilt(sos, x)
        e, hp = env_db(h, sr, 0.0005)
        full, fhp = env_db(x, sr, 0.0005, 0.1)          # the instrument's own level around each frame
        k = int(0.02 / 0.0005)
        med = median_filter(e, size=2 * k + 1, mode="nearest")
        side = np.maximum(np.roll(e, 4), np.roll(e, -4))
        floor = e.max() - 70
        idx = np.flatnonzero((e > med + 15) & (e > side + 8) & (e > floor))
        events = []
        last = -1e9
        bounds = np.array(sorted([b for on, of, *_ in notes.get(inst, []) for b in (on, of)])) - off
        for i in idx:
            t = i * hp / sr
            if t - last < 0.01:
                continue
            last = t
            near = float(bounds[np.argmin(np.abs(bounds - t))] - t) if len(bounds) else None
            rel = float(e[i] - full[min(i, len(full) - 1)])
            events.append(dict(t=round(t + off, 3), db_over_local=round(float(e[i] - med[i]), 1),
                               db_re_instrument_level=round(rel, 1),
                               nearest_note_boundary_ms=None if near is None else round(near * 1000, 1)))
        # a spike more than 20 dB below the instrument's own sound is masked by it
        clicks[NAMES[inst]] = dict(count=len(events), audible_candidates=sum(ev["db_re_instrument_level"] > -20
                                                                             for ev in events), events=events[:20])
    out["clicks"] = clicks

    # ------------------------------------------------------- short / legato
    short, legato = {}, {}
    for inst, x in stems.items():
        e, hp = env_db(K[inst], sr, 0.005, 0.02)
        fr = sr / hp

        def at(t):
            return e[int(np.clip((t - off) * fr, 0, len(e) - 1))]
        rises, t3s, dips = [], [], []
        nl = sorted(notes.get(inst, []))
        for on, of, key, vel, art in nl:
            if art is not None and art >= 96:
                rises.append(max(e[int((on - off + 0.02) * fr): int((on - off + 0.04) * fr) + 1].max(), -200)
                             - at(on - 0.01))
                seg = e[int((on - off) * fr): int((min(of, on + 0.25) - off) * fr)]
                if len(seg):
                    pk = seg.max()
                    t3s.append(float(np.flatnonzero(seg >= pk - 3)[0] / fr))
            elif art is not None and 64 <= art < 96:
                before = np.mean(10 ** (e[int((on - off - 0.12) * fr): int((on - off - 0.02) * fr)] / 10))
                after = np.mean(10 ** (e[int((on - off + 0.10) * fr): int((on - off + 0.20) * fr)] / 10))
                lo = e[int((on - off - 0.02) * fr): int((on - off + 0.10) * fr)].min()
                ref = 10 * np.log10(min(before, after) + 1e-20)
                dips.append(max(0.0, ref - lo))
        if rises:
            short[NAMES[inst]] = dict(n=len(rises), median_onset_rise_db=round(float(np.median(rises)), 1),
                                      p10_onset_rise_db=round(float(np.percentile(rises, 10)), 1),
                                      median_time_to_peak_ms=round(1000 * float(np.median(t3s)), 1))
        if dips:
            legato[NAMES[inst]] = dict(n=len(dips), median_dip_db=round(float(np.median(dips)), 1),
                                       p90_dip_db=round(float(np.percentile(dips, 90)), 1))
    out["short_notes"] = short
    out["legato"] = legato

    # --------------------------------------------------------------- dynamics
    mix, sr2 = sf.read(str(a.base.with_suffix(".wav")), dtype="float64", always_2d=True)
    ma = k_weight(mix.mean(axis=1), sr2)
    w10 = int(10 * sr2)
    lv = [10 * np.log10(np.mean(ma[i:i + w10] ** 2) + 1e-20) for i in range(0, len(ma) - w10, int(sr2))]
    out["dynamics"] = dict(first_10s_db=round(lv[0], 1), loudest_10s_db=round(max(lv), 1),
                           range_db=round(max(lv) - lv[0], 1))
    print(json.dumps(out, indent=1) if not a.json else "")
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))
        s = out
        print(f"== {a.base.name}")
        if "balance" in s:
            print("balance (dB re loudest, median / p10):",
                  ", ".join(f"{k} {v} / {s['balance']['p10_db_re_loudest'][k]}"
                            for k, v in s["balance"]["median_db_re_loudest"].items()),
                  f"[{s['balance']['windows']} windows]")
        print("clicks (flagged / within 20 dB of the instrument's level):",
              ", ".join(f"{k} {v['count']}/{v['audible_candidates']}" for k, v in s["clicks"].items()))
        print("short notes:", "; ".join(f"{k}: rise {v['median_onset_rise_db']} dB (p10 {v['p10_onset_rise_db']}), "
                                        f"peak-3dB after {v['median_time_to_peak_ms']} ms"
                                        for k, v in s["short_notes"].items()))
        print("legato dips:", "; ".join(f"{k}: {v['median_dip_db']} dB (p90 {v['p90_dip_db']})"
                                        for k, v in s["legato"].items()))
        print("dynamics:", s["dynamics"])


if __name__ == "__main__":
    main()
