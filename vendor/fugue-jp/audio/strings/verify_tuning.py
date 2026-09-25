#!/usr/bin/env python3
"""Independent tuning check of a built string instrument, through the real
playback chain (SFZ -> sfizz -> WAV).

For every key of the instrument's range and for every dynamic layer
(pp / mf / ff, selected with the CC1 value at which that layer plays alone)
a 2 s note is rendered with sfizz; the sounding pitch is measured in two
windows, 0.45-1.05 s (what a quarter or half note hears) and 1.05-1.9 s (the
spliced sustain), each by two estimators: YIN (median over frames, a wide lag
search that also catches wrong notes and octave slips) and the harmonic peaks
of partials 1-3 (40 ms / 6-period Hann frames, 10 % trimmed mean).  A key fails
if any of the four figures exceeds --tol cents (default 5) or the note is
unvoiced; 'cents' (their mean) is what iowa_build.py --retune folds into the
tuning corrections.  Both windows are needed: a note can be in tune over 2 s
and 10 c off over its first second (the players drift; iowa_build.py flattens
that drift, this check proves it).

--attack adds the pitch a short note hears: every key x layer x stroke (CC20
short 112 and normal 0, as render_quartet.py sets them) as a 0.25 s note, the
median YIN pitch 40-200 ms after the note-on (a 16th note at 64 bpm is nothing
but this attack).  A note fails if it is more than --attack-tol cents off
(default 30: the class of error this catches was 50-120 c; the report also
counts notes over 15 c).

Usage:
  python3 verify_tuning.py violin viola cello [--lib iowa|vpo3] [--tol 5] [--json OUT] [--attack]
  exit status 1 if any note fails.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from iowa_common import INSTRUMENTS, QUARTET_DIR, SFIZZ_RENDER, midi_name, midi_to_hz  # noqa: E402

SR = 48000
NOTE_S, STEP_S = 2.0, 2.6


def yin(x: np.ndarray, sr: int, fmin: float, fmax: float, W: int = 2048, hop: int = 512, thr: float = 0.12,
        global_min: bool = False):
    """YIN (de Cheveigne & Kawahara 2002) -> per-frame f0 (Hz, nan if unvoiced).
    global_min: take the deepest dip in [fmin, fmax] (for a narrow range around a
    known note) instead of the first dip under thr."""
    tmax = int(sr / fmin) + 2
    tmin = max(2, int(sr / fmax) - 1)
    out = []
    n = len(x)
    for s in range(0, n - W - tmax, hop):
        fr = x[s: s + W + tmax].astype(np.float64)
        # difference function via FFT autocorrelation
        L = 1 << int(np.ceil(np.log2(2 * (W + tmax))))
        F = np.fft.rfft(fr, L)
        a = np.fft.irfft(F * np.conj(np.fft.rfft(fr[:W], L)), L)[: tmax]
        c = np.concatenate([[0.0], np.cumsum(fr ** 2)])
        e0 = c[W] - c[0]
        et = c[np.arange(tmax) + W] - c[np.arange(tmax)]
        d = e0 + et - 2 * a
        d[0] = 0
        cm = np.ones_like(d)
        cs = np.cumsum(d[1:])
        cm[1:] = d[1:] * np.arange(1, tmax) / np.maximum(cs, 1e-20)
        if global_min:
            t = tmin + int(np.argmin(cm[tmin:tmax - 1]))
            if cm[t] >= thr:
                out.append(np.nan)
                continue
        else:
            cand = np.flatnonzero(cm[tmin:] < thr)
            if len(cand) == 0:
                out.append(np.nan)
                continue
            t = tmin + cand[0]
            while t + 1 < tmax and cm[t + 1] < cm[t]:
                t += 1
        if 1 <= t < tmax - 1:
            y0, y1, y2 = cm[t - 1], cm[t], cm[t + 1]
            den = y0 - 2 * y1 + y2
            tt = t + (0.5 * (y0 - y2) / den if abs(den) > 1e-12 else 0.0)
        else:
            tt = t
        out.append(sr / tt)
    return np.array(out)


def layer_cc1(lib: str) -> dict:
    if lib == "iowa":
        from iowa_build import LAYER_CC1
        return dict(LAYER_CC1)
    return {"single": 100}


def make_midi(keys, cc1: int, path: Path):
    mid = mido.MidiFile(type=0, ticks_per_beat=960)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("set_tempo", tempo=500000))       # 1920 ticks / s
    tps = 1920
    ev = [(0, mido.Message("control_change", control=1, value=cc1)),
          (0, mido.Message("control_change", control=11, value=127))]
    for i, k in enumerate(keys):
        t0 = int((0.2 + i * STEP_S) * tps)
        ev.append((t0, mido.Message("note_on", note=k, velocity=100)))
        ev.append((t0 + int(NOTE_S * tps), mido.Message("note_off", note=k, velocity=0)))
    ev.sort(key=lambda e: e[0])
    last = 0
    for t, m in ev:
        tr.append(m.copy(time=t - last))
        last = t
    tr.append(mido.MetaMessage("end_of_track", time=tps))
    mid.tracks.append(tr)
    mid.save(str(path))


WINDOWS = ((0.45, 1.05), (1.05, NOTE_S - 0.1))       # s after the note-on


def harmonic_f0(seg: np.ndarray, sr: int, f0: float, nh: int = 3, hop_s: float = 0.01, span_c: float = 80.0):
    """Time-mean f0 (Hz) from the peaks near k*f0 (k = 1..nh, +-span_c) of Hann frames of max(40 ms, 6 periods),
    zero-padded x8, log-parabolic interpolation, magnitude-weighted mean of f_k/k per frame, 10 % trimmed
    mean of the frames' cents.  None if fewer than 3 frames."""
    W = int(max(0.04, 6.0 / f0) * sr)
    H = int(hop_s * sr)
    nfft = 1 << int(np.ceil(np.log2(W * 8)))
    df = sr / nfft
    win = np.hanning(W)
    fr = []
    for s in range(0, len(seg) - W + 1, H):
        X = np.abs(np.fft.rfft(seg[s: s + W] * win, nfft))
        est, wt = [], []
        for k in range(1, nh + 1):
            fk = k * f0
            lo, hi = int(fk * 2 ** (-span_c / 1200) / df), int(fk * 2 ** (span_c / 1200) / df) + 1
            if hi >= len(X) - 1:
                break
            i = lo + int(np.argmax(X[lo:hi]))
            if lo < i < hi - 1:
                a, b, c = np.log(X[i - 1] + 1e-12), np.log(X[i] + 1e-12), np.log(X[i + 1] + 1e-12)
                den = a - 2 * b + c
                est.append((i + (0.5 * (a - c) / den if den != 0 else 0.0)) * df / k)
                wt.append(X[i])
        if est:
            fr.append(float(np.average(est, weights=wt)))
    if len(fr) < 3:
        return None
    c = np.sort(1200 * np.log2(np.array(fr) / f0))
    k = len(c) // 10
    c = c[k: len(c) - k] if len(c) > 10 else c
    return float(f0 * 2 ** (np.mean(c) / 1200))


def check(sfz: Path, keys: list[int], cc1: int, tmp: Path, tag: str):
    mp, wp = tmp / f"{tag}.mid", tmp / f"{tag}.wav"
    make_midi(keys, cc1, mp)
    r = subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(mp), "--wav", str(wp),
                        "-s", str(SR), "-q", "3"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    x, _ = sf.read(str(wp), dtype="float64", always_2d=True)
    m = x.mean(axis=1)
    rows = []
    for i, k in enumerate(keys):
        t0 = 0.2 + i * STEP_S
        a, b = int((t0 + WINDOWS[0][0]) * SR), int((t0 + WINDOWS[-1][1]) * SR)
        lvl = 20 * np.log10(np.sqrt(np.mean(m[a:b] ** 2)) + 1e-12)
        f = midi_to_hz(k)
        est, spread, voiced = {}, None, 0
        for wi, (w0, w1) in enumerate(WINDOWS):
            seg = m[int((t0 + w0) * SR): int((t0 + w1) * SR)]
            # wide search: one octave down to a fifth up, catches wrong notes / octave slips
            f0 = yin(seg, SR, f / 2.05, f * 1.55)
            f0 = f0[np.isfinite(f0)]
            voiced += len(f0)
            if len(f0) >= 3:
                cy = 1200 * np.log2(f0 / f)
                est[f"yin{wi}"] = float(np.median(cy))
                if wi == len(WINDOWS) - 1:
                    spread = round(float(np.percentile(cy, 75) - np.percentile(cy, 25)), 1)
                # the harmonic estimator only near the right note (a wrong note shows in YIN)
                if abs(est[f"yin{wi}"]) < 60:
                    fh = harmonic_f0(seg, SR, f)
                    if fh is not None:
                        est[f"fft{wi}"] = float(1200 * np.log2(fh / f))
        if len(est) < 2 or not any(k_.startswith("yin") for k_ in est):
            rows.append(dict(key=k, name=midi_name(k), cents=None, level_db=round(lvl, 1), voiced=voiced))
            continue
        rows.append(dict(key=k, name=midi_name(k), cents=round(float(np.mean(list(est.values()))), 1),
                         worst=round(max(est.values(), key=abs), 1),
                         **{k_: round(v, 1) for k_, v in est.items()},
                         spread=spread, level_db=round(lvl, 1), voiced=int(voiced)))
    return rows


STROKES = (("short", 112, 6), ("normal", 0, 18))       # CC20, CC21 as render_quartet.py sets them
ATT_NOTE_S, ATT_STEP_S = 0.25, 1.0


def check_attack(sfz: Path, keys: list[int], cc1: int, tmp: Path, tag: str):
    rows = {}
    for stroke, cc20, cc21 in STROKES:
        mp, wp = tmp / f"{tag}_{stroke}.mid", tmp / f"{tag}_{stroke}.wav"
        mid = mido.MidiFile(type=0, ticks_per_beat=960)
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("set_tempo", tempo=500000))
        tps = 1920
        ev = [(0, 0, mido.Message("control_change", control=1, value=cc1)),
              (0, 0, mido.Message("control_change", control=20, value=cc20)),
              (0, 0, mido.Message("control_change", control=21, value=cc21))]
        for i, k in enumerate(keys):
            t0 = int((0.2 + i * ATT_STEP_S) * tps)
            ev.append((t0, 2, mido.Message("note_on", note=k, velocity=64)))
            ev.append((t0 + int(ATT_NOTE_S * tps), 1, mido.Message("note_off", note=k, velocity=0)))
        ev.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for t, _, m in ev:
            tr.append(m.copy(time=t - last))
            last = t
        tr.append(mido.MetaMessage("end_of_track", time=tps))
        mid.tracks.append(tr)
        mid.save(str(mp))
        r = subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(mp), "--wav", str(wp),
                            "-s", str(SR), "-q", "3"], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr)
        x, _ = sf.read(str(wp), dtype="float64", always_2d=True)
        m = x.mean(axis=1)
        out = []
        for i, k in enumerate(keys):
            f = midi_to_hz(k)
            t0 = 0.2 + i * ATT_STEP_S
            W = int(max(0.03, 4.0 / f) * SR)
            seg = m[int((t0 + 0.04) * SR) - W // 2: int((t0 + 0.2) * SR) + W // 2]
            f0 = yin(seg, SR, f / 1.41, f * 1.41, W=W, hop=int(0.01 * SR), thr=0.4, global_min=True)
            f0 = f0[np.isfinite(f0)]
            if len(f0) < 3:
                out.append(dict(key=k, name=midi_name(k), cents=None, voiced=int(len(f0))))
                continue
            out.append(dict(key=k, name=midi_name(k), cents=round(float(np.median(1200 * np.log2(f0 / f))), 1),
                            voiced=int(len(f0))))
        rows[stroke] = out
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inst", nargs="+")
    ap.add_argument("--lib", default="iowa", choices=["iowa", "vpo3"])
    ap.add_argument("--tol", type=float, default=5.0,
                    help="steady pitch tolerance in cents, every window and estimator (default 5)")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--attack", action="store_true", help="also check the pitch of short notes (see above)")
    ap.add_argument("--attack-tol", type=float, default=30.0)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="tune_"))
    report, fails = {}, 0
    for inst in a.inst:
        if a.lib == "iowa":
            sfz = QUARTET_DIR / f"{inst}.sfz"
            lo, hi = INSTRUMENTS[inst]["lo"], INSTRUMENTS[inst]["hi"]
        else:
            from vpo3 import VPO3_SFZ, VPO3_RANGE
            sfz = VPO3_SFZ[inst]
            lo, hi = VPO3_RANGE[inst]
        keys = list(range(lo, hi + 1))
        report[inst] = {}
        for layer, cc in layer_cc1(a.lib).items():
            rows = check(sfz, keys, cc, tmp, f"{inst}_{layer}")
            report[inst][layer] = rows
            bad = [r for r in rows if r["cents"] is None or abs(r["worst"]) > a.tol]
            fails += len(bad)
            c = np.array([r["worst"] for r in rows if r["cents"] is not None])
            print(f"{inst:7s} {layer:6s} keys {midi_name(lo)}-{midi_name(hi)}: worst window/estimator median |err| "
                  f"{np.median(np.abs(c)):.1f} c, max |err| {np.max(np.abs(c)):.1f} c, "
                  f"{len(bad)} over {a.tol:g} c" + ("" if not bad else ": " + ", ".join(
                      f"{r['name']}({r['cents'] if r['cents'] is None else r['worst']})" for r in bad)))
    if a.attack:
        attack = {}
        for inst in a.inst:
            if a.lib != "iowa":
                break
            sfz = QUARTET_DIR / f"{inst}.sfz"
            lo, hi = INSTRUMENTS[inst]["lo"], INSTRUMENTS[inst]["hi"]
            keys = list(range(lo, hi + 1))
            attack[inst] = {}
            for layer, cc in layer_cc1(a.lib).items():
                rows = check_attack(sfz, keys, cc, tmp, f"att_{inst}_{layer}")
                attack[inst][layer] = rows
                for stroke, rr in rows.items():
                    c = np.array([abs(r["cents"]) for r in rr if r["cents"] is not None])
                    bad = [r for r in rr if r["cents"] is not None and abs(r["cents"]) > a.attack_tol]
                    fails += len(bad)
                    print(f"{inst:7s} {layer:3s} {stroke:6s} attack 40-200 ms: median |err| {np.median(c):.1f} c, "
                          f"max {c.max():.1f} c, {int((c > 15).sum())} over 15 c, {len(bad)} over {a.attack_tol:g} c"
                          + ("" if not bad else ": " + ", ".join(f"{r['name']}({r['cents']})" for r in bad)))
        report = dict(steady=report, attack=attack) if a.json else report
    if a.json:
        a.json.write_text(json.dumps(report, indent=1))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
