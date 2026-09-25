#!/usr/bin/env python3
"""Clarity of fast 16th passages, low-bass definition, releases in rests, noise floor.

1. Runs: a diatonic 16th run (up and down two octaves) in three registers (bass C1-C3,
   tenor C3-C5, treble C5-C7) at quarter = 66, 100, 132, articulated as perform.py does
   (note-off 40 ms before the next 16th). Odd and even notes go to two voices, so each
   lands in its own dry stem: for every note, the level of the *previous* note (other
   stem) during this note's first 100 ms, relative to this note = overlap (dB). Lower is
   clearer. Also the same with the hall (render mix) as C50 of the whole run.
2. Releases in rests: bass (C1..C3) and mid notes held 0.5 s then silence; broadband level
   of the stem 0.1/0.2/0.4 s after the note-off relative to the 50 ms before it.
3. Noise floor: dry-stem level 1.3-1.5 s after the note-off of isolated pp notes,
   relative to the note's peak (from the qa_notes renders).

    python3 qa/qa_clarity.py      # writes qa/results/clarity.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, SR, TMP, kweight, read, render, rms_db, save, write_midi  # noqa: E402

N = mido.Message
SCALE = [0, 2, 4, 5, 7, 9, 11]


def run_keys(base: int) -> list[int]:
    up = [base + 12 * (i // 7) + SCALE[i % 7] for i in range(15)]
    return up + up[-2::-1]


def runs() -> dict:
    res = {}
    for reg, base in (("bass", 24), ("tenor", 48), ("treble", 72)):
        for bpm in (66, 100, 132):
            six = 60 / bpm / 4
            keys = run_keys(base)
            evs = {"odd": [], "even": []}
            times = []
            for i, k in enumerate(keys):
                t = 0.5 + i * six
                v = "odd" if i % 2 else "even"
                evs[v] += [(t, N("note_on", note=k, velocity=70)), (t + six - 0.04, N("note_off", note=k, velocity=0))]
                times.append(t)
            mid = TMP / f"run_{reg}_{bpm}.mid"
            write_midi(mid, evs)
            out = TMP / f"run_{reg}_{bpm}"
            render(mid, out, "--no-m4a")
            st = {v: read(Path(str(out) + "_stems") / f"{v}.wav") for v in ("odd", "even")}
            ov = []
            for i in range(1, len(keys)):
                cur = "odd" if i % 2 else "even"
                prev = "even" if i % 2 else "odd"
                a = int((times[i] + LEAD_IN) * SR)
                b = a + int(0.1 * SR)
                ov.append(rms_db(kweight(st[prev][a:b])) - rms_db(kweight(st[cur][a:b])))
            mix = read(Path(str(out) + ".wav"))
            e = np.sum(mix ** 2, axis=1)
            a0 = int((times[0] + LEAD_IN) * SR)
            # run-level C50 proxy: energy within 50 ms of each onset vs the rest of each 16th slot
            early = sum(e[int((t + LEAD_IN) * SR): int((t + LEAD_IN + 0.05) * SR)].sum() for t in times)
            total = e[a0: int((times[-1] + LEAD_IN + six) * SR)].sum()
            res[f"{reg}_q{bpm}"] = dict(sixteenth_ms=round(six * 1000), overlap_prev_note_db_median=round(float(np.median(ov)), 1),
                                        overlap_worst_db=round(float(np.max(ov)), 1),
                                        early50_share_db=round(10 * np.log10(early / total), 1))
            print(reg, bpm, res[f"{reg}_q{bpm}"])
    return res


def releases() -> dict:
    res = {}
    evs, keys = [], [24, 28, 31, 36, 40, 43, 48, 55, 60, 67, 72, 79, 84]
    for i, k in enumerate(keys):
        t = 0.5 + i * 2.0
        evs += [(t, N("note_on", note=k, velocity=80)), (t + 0.5, N("note_off", note=k, velocity=0))]
    mid = TMP / "rel_rest.mid"
    write_midi(mid, {"solo": evs})
    render(mid, TMP / "rel_rest", "--no-reverb", "--no-m4a")
    x = read(TMP / "rel_rest_stems" / "solo.wav")
    for i, k in enumerate(keys):
        off = int((0.5 + i * 2.0 + 0.5 + LEAD_IN) * SR)
        ref = rms_db(x[off - int(0.05 * SR): off])
        res[k] = {f"after_{int(d * 1000)}ms_db": round(rms_db(x[off + int(d * SR): off + int((d + 0.05) * SR)]) - ref, 1)
                  for d in (0.1, 0.2, 0.4, 0.8)}
    return res


def noise_floor() -> dict:
    x = read(TMP / "iso_v30_stems" / "solo.wav")
    out = {}
    for k in (24, 36, 48, 60, 72, 84, 96):
        i = k - 21
        t_on = 0.2 + i * 2.2 + LEAD_IN
        pk = 20 * np.log10(np.abs(x[int(t_on * SR): int((t_on + 0.2) * SR)]).max())
        lv = rms_db(x[int((t_on + 0.8 + 1.1) * SR): int((t_on + 0.8 + 1.3) * SR)])
        out[k] = round(lv - pk, 1)
    return out


def main() -> None:
    res = {"runs": runs(), "releases_in_rest": releases(), "noise_floor_after_release_db_re_peak": noise_floor()}
    save("clarity", res)
    print(json.dumps(res["releases_in_rest"]))
    print(json.dumps(res["noise_floor_after_release_db_re_peak"]))


if __name__ == "__main__":
    main()
