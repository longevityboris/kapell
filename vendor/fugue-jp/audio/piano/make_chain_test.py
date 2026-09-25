#!/usr/bin/env python3
"""Dynamics test through the whole chain: LilyPond + plan -> perform.py -> MIDI.

Usage::

    python3 make_chain_test.py [-o out/chain_test.mid]
    python3 render_piano.py out/chain_test.mid -o out/chain_test --stems out/chain_test_stems
    python3 analyse_dynamics.py --wav out/chain_test.wav --stems out/chain_test_stems \\
        --segments out/chain_test.segments.json --json out/chain_test.analysis.json

(``run_tests.sh`` runs this and the direct test, make_test_midi.py, end to end.)

``make_test_midi.py`` writes calibrated velocities directly, to show what the
instrument can do. This test writes nothing but a score (``tests/chain_test.ly``)
and a performance plan (``tests/chain_test.plan.json``) and lets
``tools/perform.py --target piano`` produce the MIDI, exactly as the ricercar
will be produced. It shows that a dynamic marking in a plan arrives at the
piano as loudness *and* timbre:

* ``pp``, ``mf``, ``ff``: the same phrase (theme bars 1-4 over a bass) at
  three plan levels. No roles, no humanising, so only the level differs.
* ``hairpin``: one repeated bar of eighths over a repeated bass (constant
  pitch), the plan crescendos pp -> ff over four bars and back over four.
  Analysed per half bar; the control column is the plan level (2 = pp, 7 = ff).

Besides the MIDI this writes ``chain_test.segments.json`` (segment times from
the MIDI's own tempo map), which ``analyse_dynamics.py`` reads.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import mido

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from render_piano import TempoMap  # noqa: E402

PERFORM = HERE.parent.parent / "tools" / "perform.py"
SCORE = HERE / "tests" / "chain_test.ly"
PLAN = HERE / "tests" / "chain_test.plan.json"
LEVELS = {"ppp": 1, "pp": 2, "p": 3, "mp": 4, "mf": 5, "f": 6, "ff": 7, "fff": 8}


def main() -> None:
    ap = argparse.ArgumentParser(description="perform.py chain dynamics test")
    ap.add_argument("-o", "--out", type=Path, default=HERE / "out" / "chain_test.mid")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(PERFORM), str(SCORE), str(PLAN), str(args.out), "--target", "piano"], check=True)

    mf = mido.MidiFile(args.out)
    tpb = mf.ticks_per_beat
    tempos, notes = [], []
    for tr in mf.tracks:
        tick = 0
        for msg in tr:
            tick += msg.time
            if msg.type == "set_tempo":
                tempos.append((tick, msg.tempo))
            elif msg.type == "note_on" and msg.velocity > 0:
                notes.append((tick, tr.name, msg.note, msg.velocity))
    tmap = TempoMap(tpb, tempos)
    bar_tick = lambda b: int(round((b - 1) * 4 * tpb))  # noqa: E731  (4/4)
    bar_s = lambda b: tmap.seconds(bar_tick(b))  # noqa: E731

    segs = []
    for name, b0 in (("pp", 1), ("mf", 6), ("ff", 11)):
        segs.append({"name": name, "kind": "phrase", "plan_level": LEVELS[name],
                     "start_s": bar_s(b0), "end_s": bar_s(b0 + 4),
                     "velocities": sorted({v for t, _, _, v in notes if bar_tick(b0) - tpb // 4 <= t < bar_tick(b0 + 4)})})
    rows = []
    for k in range(16):  # half bars 16.0 .. 23.5
        b = 16 + k / 2
        level = 2 + 5 * (k / 8) if k <= 8 else 7 - 5 * ((k - 8) / 8)
        t0, t1 = bar_tick(b), bar_tick(b + 0.5)
        vels = [v for t, name, _, v in notes if name == "soprano" and t0 - tpb // 4 <= t < t1 - tpb // 4]
        rows.append({"t_s": tmap.seconds(t0), "win_s": tmap.seconds(t1) - tmap.seconds(t0), "level": round(level, 3),
                     "velocity": round(sum(vels) / len(vels), 1)})
    segs.append({"name": "hairpin", "kind": "ramp", "start_s": bar_s(16), "end_s": bar_s(24), "notes": rows})

    seg_path = args.out.with_suffix(".segments.json")
    seg_path.write_text(json.dumps({"source": [str(SCORE.name), str(PLAN.name)], "segments": segs}, indent=1))
    print(f"wrote {args.out} and {seg_path}")


if __name__ == "__main__":
    main()
