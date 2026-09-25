#!/usr/bin/env python3
"""Reproduce the nondeterministic truncations under the machine's real load: render the demo
MIDI N times through render_piano.py (streaming, as shipped) interleaved with N direct
sfizz_render runs of the same stem MIDIs using a copy of the derived SFZ with
<control> hint_ram_based=1. Counts truncations (qa_truncation.detect) per run.

    python3 qa/qa_truncation_repro.py [N]      # writes qa/results/truncation_repro.json

Historical: written before the fix. The derived SFZ now starts with <control>
hint_ram_based=1, so the "stream" arm loads samples into RAM as well and the
stream-vs-RAM comparison no longer applies. render_piano.py runs the same detector on
every stem (truncation_check in the render report); see results/truncation_after_fix.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_truncation as qt  # noqa: E402
from qa_lib import PIANO, TMP, read, render, save  # noqa: E402


def load_avg() -> float:
    return round(os.getloadavg()[0], 1)


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    rep = json.loads((TMP / "fugue_demo.render.json").read_text())
    temp = Path(rep["temp"])
    voices = list(rep["voices"])
    mids = [temp / f"stem{i:02d}.mid" for i in range(len(voices))]
    notes = [qt.stem_notes(m) for m in mids]
    ram = [TMP / "ramsfz" / p.name for p in (qt.DERIVED_SFZ, qt.DERIVED_SFZ_NO_PEDAL_NOISE)]
    ram_sfz = [ram[0]] + [ram[1]] * (len(mids) - 1)
    runs = []
    for r in range(n):
        la = load_avg()
        out = TMP / f"repro_{r}"
        render(TMP / "fugue_demo.mid", out, "--transpose", "pedal=-12", "--no-m4a")
        cut = []
        for i, v in enumerate(voices):
            x = read(Path(str(out) + "_stems") / f"{v}.wav")
            cut += [(v, z["t_stem"], z["cut_note"]) for z in qt.explain(qt.detect(x), notes[i])]
        runs.append(dict(kind="render_piano.py (streaming)", load_avg=la, truncations=len(cut), cut=cut))
        print(runs[-1]["kind"], r, "load", la, "truncations", len(cut), cut[:4])
        la = load_avg()
        wavs, secs = qt.run_parallel(ram_sfz, mids, f"reproram{r}")
        cut = []
        for i, (v, w) in enumerate(zip(voices, wavs)):
            x, _ = sf.read(w, dtype="float64", always_2d=True)
            cut += [(v, z["t_stem"], z["cut_note"]) for z in qt.explain(qt.detect(x), notes[i])]
        runs.append(dict(kind="sfizz_render + hint_ram_based=1", load_avg=la, seconds=round(secs, 1), truncations=len(cut), cut=cut))
        print(runs[-1]["kind"], r, "load", la, "truncations", len(cut), cut[:4])
    save("truncation_repro", {"runs": runs})


if __name__ == "__main__":
    main()
