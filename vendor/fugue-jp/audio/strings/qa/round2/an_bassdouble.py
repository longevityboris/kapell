#!/usr/bin/env python3
"""Round-2 --bass-double auto on the test music: where the contrabass sounds (cb dry stem) against the
cello's CC1 (auto threshold ff = CC1 114), pitch of the doubled notes (an octave below the cello key) and
their level re the cello stem.  Input: an_chain.py --tag sk_final_bd (--extra=--bass-double=auto).

  python3 an_bassdouble.py [--tag sk_final_bd]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import SR, TMP, cents, db, pitch_fft, pitch_yin, save  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="sk_final_bd")
a = ap.parse_args()
rep = json.loads((TMP / f"chain_{a.tag}.json").read_text())
cb = sf.read(str(TMP / f"chain_{a.tag}_stem_cb.wav"), always_2d=True)[0].mean(axis=1)
vc = sf.read(str(TMP / f"chain_{a.tag}_stem_vc.wav"), always_2d=True)[0].mean(axis=1)
cc = rep["cc1"]["vc"]
job = next(j for j in rep["jobs"] if j["inst"] == "cb")
rows = []
for on, off, key, vel, art in job["note_list"]:
    if off - on < 0.3:
        continue
    s0, s1 = int((on + 0.1) * SR), int((off - 0.05) * SR)
    lcb, lvc = float(db(np.mean(cb[s0:s1] ** 2))), float(db(np.mean(vc[s0:s1] ** 2)))
    c1 = max([v for t, v in cc if t <= on + 0.1] or [0])
    r = dict(on=on, dur=round(off - on, 3), cello_key=key, cc1=c1, cb_re_cello_db=round(lcb - lvc, 1))
    if lcb > -70:
        r["cents"] = round(cents(pitch_yin(cb[s0:s1], key - 12), key - 12), 1)
        r["cents_fft"] = round(cents(pitch_fft(cb[s0:s1], key - 12), key - 12), 1)
    rows.append(r)
on_rows = [r for r in rows if r["cb_re_cello_db"] > -30]
res = dict(n_notes=len(rows), n_sounding=len(on_rows),
           cc1_when_sounding=sorted({r["cc1"] for r in on_rows}),
           max_cc1_when_silent=max([r["cc1"] for r in rows if r["cb_re_cello_db"] <= -30], default=None),
           cb_re_cello_db=dict(median=float(np.median([r["cb_re_cello_db"] for r in on_rows])) if on_rows else None),
           worst_cents=sorted(on_rows, key=lambda r: -abs(r.get("cents", 0)))[:5], rows=rows)
save(f"bassdouble_{a.tag}.json", res)
print(json.dumps({k: v for k, v in res.items() if k != "rows"}, default=float))
