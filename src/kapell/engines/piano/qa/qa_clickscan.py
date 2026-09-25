#!/usr/bin/env python3
"""Global click scan of the demo fugue render (run qa_chain.py first).

|2nd difference| of the mono sum in 1 ms frames, crest = frame max / RMS of the preceding
50 ms of |d2|. Top candidates are listed with the nearest MIDI note-on / note-off; candidates
within 5 ms of a note-on are hammer attacks. Also scans each dry stem the same way and
inspects the one key-sharing restrike (alto stub at 61.45 s).

    python3 qa/qa_clickscan.py      # writes qa/results/clickscan.json
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, SR, TMP, midi_notes, read, save  # noqa: E402


def scan(m: np.ndarray, top: int = 25):
    d2 = np.abs(np.diff(m, 2))
    fr = SR // 1000
    nf = len(d2) // fr
    fmax = d2[: nf * fr].reshape(nf, fr).max(axis=1)
    fms = (d2[: nf * fr].reshape(nf, fr) ** 2).mean(axis=1)
    bg = np.sqrt(np.convolve(fms, np.ones(50) / 50, mode="full")[:nf])  # trailing 50 ms incl. this frame
    bg = np.concatenate([[bg[0]], bg[:-1]])  # strictly preceding
    crest = 20 * np.log10((fmax + 1e-15) / (bg + 1e-15))
    level = 20 * np.log10(fmax + 1e-15)
    # ignore frames whose d2 peak is far below the loudest (inaudible)
    ok = level > level.max() - 50
    idx = np.argsort(-np.where(ok, crest, -np.inf))
    picked = []
    for i in idx:
        if len(picked) >= top:
            break
        if all(abs(i - j) > 20 for j, _ in picked):
            picked.append((i, crest[i]))
    return [(i / 1000, c, level[i] - level.max()) for i, c in picked]


def nearest(t, evs):
    d = [(abs(t - e), e, what) for e, what in evs]
    return min(d)


def main() -> None:
    notes = midi_notes(TMP / "fugue_demo.mid")
    ons = [(n["start"] + LEAD_IN, f"on {n['voice']} {n['key']}") for n in notes]
    offs = [(n["end"] + LEAD_IN, f"off {n['voice']} {n['key']}") for n in notes]
    res = {}
    x = read(TMP / "fugue_demo.wav").mean(axis=1)
    rows = []
    for t, c, lv in scan(x):
        d_on, e_on, w_on = nearest(t, ons)
        d_off, e_off, w_off = nearest(t, offs)
        rows.append(dict(t=round(t, 3), crest_db=round(float(c), 1), d2_level_re_max_db=round(float(lv), 1),
                         nearest_on=[round(e_on - t, 4), w_on], nearest_off=[round(e_off - t, 4), w_off],
                         attack=bool(d_on < 0.006)))
    res["mix_top"] = rows
    res["mix_non_attack"] = [r for r in rows if not r["attack"]]
    for v in ("soprano", "alto", "tenor", "pedal"):
        s = read(TMP / "fugue_demo_stems" / f"{v}.wav").mean(axis=1)
        vr = []
        for t, c, lv in scan(s, top=15):
            d_on, e_on, w_on = nearest(t, ons)
            d_off, e_off, w_off = nearest(t, offs)
            if d_on >= 0.006:
                vr.append(dict(t=round(t, 3), crest_db=round(float(c), 1), d2_level_re_max_db=round(float(lv), 1),
                               nearest_on=[round(e_on - t, 4), w_on], nearest_off=[round(e_off - t, 4), w_off]))
        res[f"stem_{v}_non_attack"] = vr
    # crest distribution of attacks for reference
    res["attack_crest_median_db"] = float(np.median([r["crest_db"] for r in rows if r["attack"]])) if any(r["attack"] for r in rows) else None
    save("clickscan", res)
    for k, v in res.items():
        print(k, v if not isinstance(v, list) else "\n  " + "\n  ".join(map(str, v[:12])))


if __name__ == "__main__":
    main()
