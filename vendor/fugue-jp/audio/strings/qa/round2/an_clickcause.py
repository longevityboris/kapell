#!/usr/bin/env python3
"""Round-2: what are the HF spikes an_mix.py flags at note starts in the dry stems?

  python3 an_clickcause.py --temp QUARTET_TEMP_DIR [--tag sk_final]

an_mix.py flags 1 ms peaks of the >6 kHz residual more than 15 dB above its local RMS within 30 ms of a
note boundary (SK_final: vn2 13, va 8, vc 4, mix 0).  For every flag, in the raw sfizz output of the job
(the --keep-temp WAV of the chain render, rendered with the renderer's 0.5 s shift):
  * the waveform's largest second difference within 3 ms re its local median (a one-sample slip or step
    shows as an isolated outlier; bow noise does not);
  * the same job MIDI rendered again by sfizz with a different block alignment (no shift: every note
    moves by 192 samples re the 256-sample blocks): is the outlier still there?  Same notes, same random
    seed sequence, so the two renders agree to about -30 dB except where the engine differs;
  * the position of the outlier re the 256-sample block grid of the original render.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import SR, STRINGS, TMP, db, save  # noqa: E402
from an_mix import click_scan  # noqa: E402

sys.path.insert(0, str(STRINGS))
import render_quartet as rq  # noqa: E402
from iowa_common import QUARTET_DIR, SFIZZ_RENDER  # noqa: E402

SHIFT = 0.5          # render_quartet: shift_s = max(0.5, lead_in + 0.05)


def d2_outlier(x, i, half=int(0.003 * SR)):
    d2 = np.abs(np.diff(x[i - 2000: i + 2000], 2, axis=0)).max(axis=1)
    c = 2000 - 1
    w = d2[c - half: c + half]
    k = int(np.argmax(w))
    return float(w[k] / max(np.median(d2), 1e-12)), c - half + k + 1 - 2000   # ratio, sample offset re i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temp", required=True)
    ap.add_argument("--tag", default="sk_final")
    a = ap.parse_args()
    rep = json.loads((TMP / f"chain_{a.tag}.json").read_text())      # keep-start: stems and jobs in MIDI time
    out_dir = TMP / "clickcause"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, j in enumerate(rep["jobs"]):
        inst = j["inst"]
        st = sf.read(str(TMP / f"chain_{a.tag}_stem_{inst}.wav"), always_2d=True)[0].mean(axis=1)
        times = sorted(t for (on, off, *_), pre in zip(j["note_list"], j["pre_ms"]) for t in (on - pre / 1000, off))
        hits = click_scan(st, times)
        if not hits:
            continue
        ja = sf.read(str(Path(a.temp) / f"j{i}_{inst}.wav"), always_2d=True)[0]
        wb = out_dir / f"j{i}_{inst}_noshift.wav"
        if not wb.exists():
            subprocess.run([str(SFIZZ_RENDER), "--sfz", str(QUARTET_DIR / rq.INSTR[inst]["sfz"]), "--midi",
                            str(Path(a.temp) / f"j{i}_{inst}.mid"), "--wav", str(wb), "-s", str(SR), "-p", "256", "-q", "3"],
                           check=True, capture_output=True)
        jb = sf.read(str(wb), always_2d=True)[0]
        for h in hits:
            n = int(round(h["t"] * SR))
            ra, ka = d2_outlier(ja, n)
            rb, kb = d2_outlier(jb, n)
            seg_a, seg_b = ja[n - 2400: n + 2400], jb[n - 2400: n + 2400]
            agree = float(db(np.mean((seg_a - seg_b) ** 2) / np.mean(seg_a ** 2)))
            blk = (n + ka + int(round(SHIFT * SR))) % 256
            rows.append(dict(inst=inst, t=h["t"], hf_re_local_db=h["hf_re_local_db"], re_fullband_db=h["re_fullband_db"],
                             d2_ratio_render=round(ra, 1), d2_ratio_other_alignment=round(rb, 1),
                             renders_agree_db=round(agree, 1), pos_in_256_block=int(blk)))
    rows = list({(r["inst"], r["t"]): r for r in rows}.values())          # a flag near both a note-off and a note-on
    slips = [r for r in rows if r["pos_in_256_block"] in (0, 1, 255)
             and r["d2_ratio_other_alignment"] < 0.8 * r["d2_ratio_render"]]
    res = dict(n_flags=len(rows), n_block_boundary_slips=len(slips),
               slips_per_inst={i: sum(1 for r in slips if r["inst"] == i) for i in ("vn1", "vn2", "va", "vc")},
               same_in_both_alignments=[(r["inst"], r["t"]) for r in rows if r not in slips],
               re_fullband_db_range=[min((r["re_fullband_db"] for r in slips), default=None),
                                     max((r["re_fullband_db"] for r in slips), default=None)],
               rows=rows)
    save(f"clickcause_{a.tag}.json", res)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}))
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
