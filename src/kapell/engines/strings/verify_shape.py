#!/usr/bin/env python3
"""Level shape of every built sustain region in its first second, as a note plays it from its offset.

A held note must not sit low and then dip and jump back (round-2 QA: 69 of 1094 regions did,
violin I Eb5 mf -6 dB at 0.5 s then +5.7 dB, heard as a 6-7.5 dB wobble on every long Eb5).
For every normal (CC20 0-63) and slurred (64-95) region of the five SFZ files: 50 ms RMS (25 ms hop)
from the region's offset for 3 s; steady = median over 1.2-3.0 s;
  early_db = mean level 0.15-0.7 s re steady (a late plateau),
  notch_db = lowest frame 0.15-1.2 s re steady,
  jump_db  = largest rise over 150 ms inside 0.15-1.2 s.
A region fails if early_db <= -3, or notch_db <= -5.5 with jump_db >= 4.5 (dip and recovery).
The criterion and windows are those of qa/round2/an_samples.py.

Usage:  python3 verify_shape.py [violin violin2 viola cello bass] [--json OUT]   (exit 1 on a failure)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from iowa_common import QUARTET_DIR  # noqa: E402

SR = 48000
INSTS = ("violin", "violin2", "viola", "cello", "bass")


def regions(path: Path) -> list[dict]:
    out, grp = [], None
    for line in path.read_text().splitlines():
        m = re.match(r"<group> // (\w+) art cc20 (\d+)-(\d+)", line)
        if m:
            grp = (m.group(1), int(m.group(2)))
            continue
        if line.startswith("<region>") and grp:
            kv = dict(re.findall(r"(\w+)=(\S+)", line.split("//")[0]))
            art = "normal" if grp[1] == 0 else "legato" if grp[1] == 64 else "short"
            out.append(dict(layer=grp[0], art=art, sample=kv["sample"], offset=int(kv.get("offset", 0)),
                            lokey=int(kv["lokey"]), hikey=int(kv["hikey"]), center=int(kv["pitch_keycenter"])))
    return out


def rms_env(x, win=0.05, hop=0.025):
    W, H = int(win * SR), int(hop * SR)
    n = max(1, (len(x) - W) // H + 1)
    idx = np.arange(n) * H
    c = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    e = (c[idx + W] - c[idx]) / W
    return idx / SR + win / 2, 10 * np.log10(np.maximum(e, 1e-20))


def shape(sample: str, offset: int) -> dict:
    x, sr = sf.read(str(QUARTET_DIR / sample), always_2d=True)
    assert sr == SR
    t, e = rms_env(x[offset: offset + 3 * SR].mean(axis=1))
    steady = float(np.median(e[(t >= 1.2) & (t <= 3.0)]))
    w = (t >= 0.15) & (t <= 1.2)
    ew, k = e[w], 6
    return dict(early_db=round(float(np.mean(e[(t >= 0.15) & (t <= 0.7)]) - steady), 1),
                notch_db=round(float(np.min(ew) - steady), 1),
                notch_at_s=round(float(t[w][np.argmin(ew)]), 2),
                jump_db=round(float(np.max(ew[k:] - ew[:-k])) if len(ew) > k else 0.0, 1))


def fails(s: dict) -> bool:
    return s["early_db"] <= -3 or (s["notch_db"] <= -5.5 and s["jump_db"] >= 4.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inst", nargs="*", default=list(INSTS))
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rep, cache, n_bad = {}, {}, 0
    for inst in a.inst:
        rows = []
        for r in regions(QUARTET_DIR / f"{inst}.sfz"):
            if r["art"] == "short":
                continue
            ck = (r["sample"], r["offset"])
            if ck not in cache:
                cache[ck] = shape(*ck)
            rows.append(dict(r, **cache[ck], fail=fails(cache[ck])))
        bad = [r for r in rows if r["fail"]]
        n_bad += len(bad)
        early = np.array([r["early_db"] for r in rows])
        notch = np.array([r["notch_db"] for r in rows])
        print(f"{inst:8s} {len(rows)} regions: early p5 {np.percentile(early, 5):+.1f} dB, notch p5 "
              f"{np.percentile(notch, 5):+.1f} dB, {len(bad)} fail"
              + ("" if not bad else ": " + ", ".join(f"{r['layer']} {r['art']} {r['center']} "
                                                     f"({r['early_db']:+.1f}/{r['notch_db']:+.1f}/{r['jump_db']:+.1f})"
                                                     for r in bad[:12])))
        rep[inst] = dict(regions=len(rows), failed=len(bad), early_db_p5=round(float(np.percentile(early, 5)), 1),
                         notch_db_p5=round(float(np.percentile(notch, 5)), 1), fails=bad)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=1))
    sys.exit(1 if n_bad else 0)


if __name__ == "__main__":
    main()
