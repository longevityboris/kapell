#!/usr/bin/env python3
"""Every note of the organ MIDI on its voice's rendered stem, and the final files, measured
independently of the renderer's report.

usage: python3 presence.py ORGAN.mid STEMS_DIR OUT.wav OUT.m4a [--lead 0.5] [-o RESULT.json]

Per note (read from the MIDI with mido): on the voice's dry stem, the strongest of partials 1-4
within +-60 cents of the key's equal-tempered frequency, 60 ms to 400 ms after the key-down
(orchestration/tests/qa_mix.py's pitch_cents: parabolic peak, prominence over the surrounding
semitone band). A note counts as present when a partial stands at least 6 dB over its
surroundings; its pitch error is reported. The organ's 16' stops put their octave below every
key; their partials 2 and 4 are the key's 1 and 2, so the measure holds on the pedal. The pedal's
pitch is read on a longer window (60 ms to 1 s after the key-down, or the key-up if sooner) and
from partials 2-4 only: its fundamentals lie at 33-87 Hz, where a 340 ms window resolves only a
few Hz, and the strongest-partial rule often picked the fundamental, which reported 20 c at p95
for pipes that measure within 1.5 c on their sustain (presence is still judged on 60-400 ms,
partials 1-4).
Files: ffmpeg ebur128 loudness and true peak of WAV and m4a, duration, sample rate.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / "orchestration" / "tests"))
sys.path.insert(0, str(R / "tools"))
from qa_mix import SR, notes_of, pitch_cents  # noqa: E402


def pitch_cents_partials(x: np.ndarray, key: int, partials=(2, 3, 4)):
    """qa_mix.pitch_cents restricted to the given partials: -> (cents, partial, prominence dB)."""
    f0 = 440.0 * 2 ** ((key - 69) / 12)
    n = len(x)
    if n < 1024:
        return None, None, 0.0
    nfft = 1 << int(np.ceil(np.log2(n * 8)))
    spec = np.abs(np.fft.rfft(x * np.hanning(n), nfft))
    freqs = np.fft.rfftfreq(nfft, 1 / SR)
    best = None
    for h in partials:
        fc = f0 * h
        band = (freqs >= fc * 2 ** (-60 / 1200)) & (freqs <= fc * 2 ** (60 / 1200))
        idx = np.nonzero(band)[0]
        if not len(idx):
            continue
        k = idx[np.argmax(spec[idx])]
        if k in (idx[0], idx[-1]):
            continue
        around = (freqs >= fc * 2 ** (-200 / 1200)) & (freqs <= fc * 2 ** (200 / 1200)) & ~band
        prom = 20 * np.log10(spec[k] / (np.median(spec[around]) + 1e-12))
        if best is None or spec[k] > best[0]:
            a, b, c = np.log(spec[k - 1] + 1e-20), np.log(spec[k] + 1e-20), np.log(spec[k + 1] + 1e-20)
            d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
            best = (spec[k], 1200 * np.log2((k + d) * SR / nfft / fc), h, prom)
    if best is None:
        return None, None, 0.0
    return float(best[1]), best[2], float(best[3])


def ebur(path: Path) -> dict:
    p = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-filter_complex",
                        "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    tail = p.stderr[p.stderr.rfind("Summary:"):]
    get = lambda k: float(re.search(k + r":\s+(-?[\d.]+)", tail).group(1))  # noqa: E731
    return {"integrated_lufs": get("I"), "lra_lu": get("LRA"), "true_peak_dbtp": get("Peak")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("midi")
    ap.add_argument("stems")
    ap.add_argument("wav")
    ap.add_argument("m4a")
    ap.add_argument("--lead", type=float, default=0.5)
    ap.add_argument("--long-pitch", default="bass", help="voices whose pitch is read on up to 1 s")
    ap.add_argument("-o")
    a = ap.parse_args()
    notes = notes_of(Path(a.midi))
    long_pitch = set(a.long_pitch.split(",")) if a.long_pitch else set()
    res = {"midi": a.midi, "voices": {}, "files": {}}
    total = present = 0
    for v, lst in sorted(notes.items()):
        if not lst:
            continue
        x, sr = sf.read(str(Path(a.stems) / f"{v}.wav"), dtype="float64")
        assert sr == SR
        mono = x.mean(axis=1)
        cents, drops, proms = [], [], []
        for on, off, key in lst:
            s0 = int((on + a.lead + 0.06) * SR)
            s1 = int((min(off, on + 0.4) + a.lead) * SR)
            if s1 - s0 < int(0.05 * SR):
                s0, s1 = int((on + a.lead + 0.02) * SR), int((off + a.lead) * SR)
            c, h, prom = pitch_cents(mono[s0:s1], key)
            proms.append(prom)
            if c is None or prom < 6:
                drops.append({"t_s": round(on, 2), "key": key, "prominence_db": round(prom, 1)})
                continue
            if v in long_pitch:
                cl, _, pl = pitch_cents_partials(
                    mono[int((on + a.lead + 0.06) * SR):int((max(min(off, on + 1.0), on + 0.2) + a.lead) * SR)], key)
                if cl is not None and pl >= 6:
                    c = cl
            cents.append(c)
        cents = np.array(cents)
        total += len(lst)
        present += len(lst) - len(drops)
        res["voices"][v] = {"notes": len(lst), "present": len(lst) - len(drops), "dropped": drops,
                            "prominence_db_p5": round(float(np.percentile(proms, 5)), 1),
                            "cents_median": round(float(np.median(cents)), 2),
                            "cents_abs_p95": round(float(np.percentile(np.abs(cents), 95)), 2),
                            "cents_abs_max": round(float(np.max(np.abs(cents))), 2),
                            "pitch_window_s": "0.06-1.0, partials 2-4" if v in long_pitch else "0.06-0.4, partials 1-4"}
        print(f"{v:8s} {len(lst):4d} notes, present {len(lst) - len(drops)}, prominence p5 "
              f"{res['voices'][v]['prominence_db_p5']} dB, cents median {res['voices'][v]['cents_median']} "
              f"p95 {res['voices'][v]['cents_abs_p95']}")
    res["notes"], res["present"] = total, present
    for key, p in (("wav", Path(a.wav)), ("m4a", Path(a.m4a))):
        info = sf.info(str(p)) if key == "wav" else None
        d = {"path": str(p), **ebur(p)}
        if info:
            d.update(duration_s=round(info.duration, 2), samplerate=info.samplerate, subtype=info.subtype)
        else:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                  "default=nw=1:nk=1", str(p)], capture_output=True, text=True).stdout
            d["duration_s"] = round(float(out.strip()), 2)
        res["files"][key] = d
        print(key, d)
    res["ok"] = present == total
    print(f"notes present: {present}/{total}")
    if a.o:
        Path(a.o).write_text(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
