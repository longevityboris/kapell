#!/usr/bin/env python3
"""Subject/answer entries of the demo: entry voice's dry stem RMS during the entry's first bar
against the other stems (loudest and energy mean), and the stems' overall balance."""
import json
import math
import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from lib2 import SR, read, tempo_map, write_json  # noqa: E402

P = Path("/tmp/pianoqa2")
PLAN = Path(__file__).resolve().parents[2] / "plans/fugue_jp.plan.json"
LEAD = 0.3


def main():
    plan = json.loads(PLAN.read_text())
    mf = mido.MidiFile(P / "demo.mid")
    sec = tempo_map(mf)
    names = ["alto", "soprano", "tenor", "pedal"]
    st = {n: read(P / f"demo_j4_stems/{n}.wav") for n in names}
    L = max(len(s) for s in st.values())
    st = {n: np.pad(s, ((0, L - len(s)), (0, 0))) for n, s in st.items()}

    def t_of(pos):
        bar, beat = pos.split(":")
        return sec(int(((int(bar) - 1) * 4 + (float(beat) - 1)) * 960))

    rows = []
    seen = set()
    for r in plan["roles"]:
        if r["role"] not in ("subject", "answer") or (r["voice"], r["at"]) in seen:
            continue
        seen.add((r["voice"], r["at"]))
        bar = int(r["at"].split(":")[0])
        t0, t1 = t_of(f"{bar}:1") + LEAD, t_of(f"{bar + 1}:1") + LEAD
        e = {n: float(np.mean(st[n][int(t0 * SR):int(t1 * SR)] ** 2)) + 1e-30 for n in names}
        others = [e[n] for n in names if n != r["voice"] and e[n] > 1e-12]
        rows.append(dict(voice=r["voice"], at=r["at"], role=r["role"],
                         re_loudest_other_db=round(10 * math.log10(e[r["voice"]] / max(others)), 1) if others else None,
                         re_mean_other_db=round(10 * math.log10(e[r["voice"]] / np.mean(others)), 1) if others else None))
    tot = {n: round(float(10 * np.log10(np.mean(st[n] ** 2))), 2) for n in names}
    res = dict(entries=rows, stem_rms_dbfs=tot, stem_spread_db=round(max(tot.values()) - min(tot.values()), 2),
               min_entry_margin_db=min(r["re_loudest_other_db"] for r in rows if r["re_loudest_other_db"] is not None))
    write_json(Path(__file__).parent / "results/entries.json", res)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
