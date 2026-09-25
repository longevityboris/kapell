#!/usr/bin/env python3
"""Stage 2 of the Iowa quartet build: segment every raw Iowa arco file into
single notes and measure each note (pitch, tuning offset, level, attack time,
sustain window).  Writes IowaMIS/quartet/analysis.json.

Usage:  python3 iowa_analyze.py [--jobs 10] [--only violin,cello]
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scipy.signal import butter, sosfiltfilt  # noqa: E402

from iowa_common import (INSTRUMENTS, QUARTET_DIR, RAW_DIR, env_db, estimate_f0,  # noqa: E402
                         load_audio, load_iowa, midi_name, midi_to_hz, parse_iowa_name)


def highpass(x: np.ndarray, sr: int, fc: float, order: int = 6) -> np.ndarray:
    """Zero-phase Butterworth high-pass (removes the sub-60 Hz building rumble
    that sits at about -55 dBFS under every Iowa recording)."""
    sos = butter(order, fc, btype="highpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x, axis=0).astype(np.float32)


def file_hpf(inst: str, info: dict) -> float:
    return 0.7 * midi_to_hz(min(info["lo"], INSTRUMENTS[inst]["lo"]) - 1)


def segment(mono: np.ndarray, sr: int):
    """Split a chromatic-run recording on the silences between notes."""
    db, hop = env_db(mono, sr, 0.01)
    peak = db.max()
    floor = np.percentile(db, 10)
    thr = max(floor + 12.0, peak - 55.0, -95.0)
    on = db > thr
    # close gaps shorter than 0.25 s
    idx = np.flatnonzero(on)
    segs = []
    if len(idx) == 0:
        return segs, thr
    start = prev = idx[0]
    for i in idx[1:]:
        if i - prev > 25:
            segs.append((start, prev + 1))
            start = i
        prev = i
    segs.append((start, prev + 1))
    segs = [(a * hop, b * hop) for a, b in segs if (b - a) * hop / sr > 0.45]
    return segs, thr


def analyze_note(x: np.ndarray, sr: int, a: int, b: int, lo: float, hi: float):
    seg = x[a:b]
    mono = seg.mean(axis=1)
    db, hop = env_db(mono, sr, 0.005)
    pk = float(db.max())
    ipk = int(np.argmax(db))
    # onset: first sample above peak-45 dB, then back off 8 ms
    above = np.flatnonzero(np.abs(mono) > 10 ** ((pk - 45) / 20) * np.sqrt(2))
    onset = max(0, int(above[0]) - int(0.008 * sr)) if len(above) else 0
    # end of the sounding note: last frame above peak-50 dB (+30 ms)
    last = np.flatnonzero(db > pk - 50)
    end = min(len(mono), (int(last[-1]) + 1) * hop + int(0.03 * sr))
    # body = frames within 12 dB of the peak, contiguous from the onset region
    body = np.flatnonzero(db > pk - 12)
    body_end = int(body[-1])
    on_f = onset // hop
    core = db[on_f:body_end + 1]
    steady = float(np.median(core[len(core) // 4:])) if len(core) > 8 else pk
    reach = np.flatnonzero(db[on_f:] > steady - 3.0)
    attack = float(reach[0] * hop / sr) if len(reach) else 0.1
    # sustain end: last frame where env > steady-6 dB (the bow is still moving)
    sus = np.flatnonzero(db[: body_end + 1] > steady - 6.0)
    sus_end = float(sus[-1] * hop / sr) if len(sus) else body_end * hop / sr
    # pitch on the body after the attack
    p0 = onset + int(max(attack, 0.15) * sr)
    p1 = min(int(sus_end * sr), p0 + int(1.2 * sr))
    if p1 - p0 < int(0.25 * sr):
        p0, p1 = onset, max(onset + int(0.3 * sr), int(sus_end * sr))
    mid = mono[p0:p1]
    f0, conf = estimate_f0(mid, sr, lo, hi)
    spec = np.abs(np.fft.rfft(mid * np.hanning(len(mid))))
    fr = np.fft.rfftfreq(len(mid), 1 / sr)
    centroid = float((spec * fr).sum() / (spec.sum() + 1e-12))
    return dict(a=int(a), b=int(b), onset=int(onset), end=int(end), peak_db=pk,
                steady_db=steady, attack_s=attack, sus_end_s=sus_end, f0_midi=f0,
                conf=conf, centroid=centroid, dur_s=(end - onset) / sr,
                body_s=(body_end * hop - onset) / sr)


def analyze_file(args):
    inst, path = args
    info = parse_iowa_name(path.name)
    x, sr = load_iowa(inst, path)
    hpf = file_hpf(inst, info)
    x = highpass(x, sr, hpf)
    mono = x.mean(axis=1)
    segs, thr = segment(mono, sr)
    lo = min(info["lo"], INSTRUMENTS[inst]["lo"]) - 1.5
    hi = max(info["hi"], INSTRUMENTS[inst]["lo"]) + 1.5
    # search window: the file's nominal range +- 1.5 semitones (filenames can be wrong,
    # so fall back to the whole instrument range if the pitch lands on an edge)
    notes = []
    for a, b in segs:
        r = analyze_note(x, sr, a, b, info["lo"] - 1.5, info["hi"] + 1.5)
        if abs(r["f0_midi"] - (info["lo"] - 1.5)) < 0.2 or abs(r["f0_midi"] - (info["hi"] + 1.5)) < 0.3:
            r = analyze_note(x, sr, a, b, INSTRUMENTS[inst]["lo"] - 1, INSTRUMENTS[inst]["hi"] + 1)
        if r["body_s"] < 0.35 or r["conf"] < 4.0:
            r["junk"] = True
        notes.append(r)
    notes = [n for n in notes if not n.get("junk")]
    # assign MIDI keys: remove a per-file tuning offset, then round
    f0s = np.array([n["f0_midi"] for n in notes])
    if len(f0s):
        off = float(np.median(f0s - np.round(f0s)))
        for n in notes:
            n["midi"] = int(round(n["f0_midi"] - off))
            n["cents"] = round(100.0 * (n["f0_midi"] - n["midi"]), 1)
    expected = info["hi"] - info["lo"] + 1
    return dict(inst=inst, file=path.name, sr=sr, thr=thr, hpf=hpf, expected=expected, found=len(notes), **info,
                notes=notes)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = set(a.only.split(",")) - {""}
    jobs = []
    for inst in INSTRUMENTS:
        if (only and inst not in only) or "variant_of" in INSTRUMENTS[inst]:
            continue
        for p in sorted((RAW_DIR / inst).glob("*.aif")):
            if ".stereo." in p.name and ".arco." in p.name:
                jobs.append((inst, p))
    QUARTET_DIR.mkdir(parents=True, exist_ok=True)
    out = QUARTET_DIR / "analysis.json"
    old = json.loads(out.read_text()) if out.exists() else []
    keep = [r for r in old if only and r["inst"] not in only]
    with ProcessPoolExecutor(a.jobs) as ex:
        res = list(ex.map(analyze_file, jobs))
    for r in res:
        seq = [n["midi"] for n in r["notes"]]
        flag = "" if r["found"] == r["expected"] and seq == list(range(r["lo"], r["hi"] + 1)) else "  <-- CHECK"
        print(f"{r['file']:45s} exp {r['expected']:2d} found {r['found']:2d} "
              f"{midi_name(seq[0]) if seq else '-'}..{midi_name(seq[-1]) if seq else '-'}{flag}")
    out.write_text(json.dumps(keep + res, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
