#!/usr/bin/env python3
"""Experiment (no renderer change): what would a shorter damper release buy?

Copies of the derived SFZ in /tmp with the damped keys' ampeg_release=1 replaced by 0.2 / 0.35 /
0.5 s (the undamped F6+ group keeps 5 s; samples RAM-loaded). The 16th runs of qa_clarity.py
are turned into stem MIDIs with render_piano's own load_midi/write_stem_midi and rendered with
sfizz_render directly; the overlap of the previous note (dB, first 100 ms of each note, K-weighted)
and the note-off click crest are compared with the shipped 1 s release.

    python3 qa/qa_release_experiment.py      # writes qa/results/release_experiment.json

Historical: this measured the stock 1 s release against shorter ones before the fix.
make_sfz.py now writes 0.35 s (0.5-0.375 s per region below F2), so the replace() below
no longer finds "ampeg_release=1" and its "1.0" row would silently be the new release.
The fix is re-measured by qa_clarity.py instead; do not re-run this script as is.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, PIANO, SR, TMP, kweight, rms_db, save  # noqa: E402

sys.path.insert(0, str(PIANO))
import render_piano as rp  # noqa: E402
from piano_paths import DERIVED_SFZ_NO_PEDAL_NOISE, SALAMANDER_DIR, SFIZZ_RENDER  # noqa: E402


def sfz_with_release(rel: float) -> Path:
    txt = DERIVED_SFZ_NO_PEDAL_NOISE.read_text()
    txt = txt.replace("ampeg_release=1 note_polyphony=2", f"ampeg_release={rel} note_polyphony=2", 1)
    p = TMP / "relexp" / f"rel_{rel}.sfz"
    p.parent.mkdir(exist_ok=True)
    p.write_text(f"<control> default_path={SALAMANDER_DIR}/ hint_ram_based=1\n" + txt)
    return p


def crest_at(x, times):
    m = x.mean(axis=1)
    d2 = np.abs(np.diff(m, 2))
    out = []
    for t in times:
        i = int(t * SR)
        a = d2[i: i + int(0.004 * SR)]
        bg = d2[max(0, i - int(0.06 * SR)): i - int(0.01 * SR)]
        out.append(20 * np.log10((a.max() + 1e-12) / (np.sqrt(np.mean(bg ** 2)) + 1e-12)))
    return float(np.median(out)), float(np.max(out))


def main() -> None:
    res = {}
    sfzs = {1.0: sfz_with_release(1), 0.5: sfz_with_release(0.5), 0.35: sfz_with_release(0.35), 0.2: sfz_with_release(0.2)}
    for reg in ("bass", "tenor"):
        for bpm in (66, 100):
            mid = TMP / f"run_{reg}_{bpm}.mid"
            voices = rp.load_midi(mid)
            names = [n for n in voices if voices[n].notes]
            for v in names:
                for n in voices[v].notes:
                    n.vel_eff = n.velocity
            stems = {}
            for v in names:
                p = TMP / "relexp" / f"{reg}_{bpm}_{v}.mid"
                rp.write_stem_midi(p, voices[v].notes, [], 0, LEAD_IN)
                stems[v] = p
            allnotes = sorted([n for v in names for n in voices[v].notes], key=lambda n: n.start)
            for rel, sfz in sfzs.items():
                wav = {}
                for v, p in stems.items():
                    w = TMP / "relexp" / f"{reg}_{bpm}_{v}_{rel}.wav"
                    subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(p), "--wav", str(w), "-s", str(SR),
                                    "-q", "10", "-p", "512", "-b", "256"], check=True, capture_output=True)
                    wav[v] = sf.read(w, dtype="float64", always_2d=True)[0]
                ov = []
                for i in range(1, len(allnotes)):
                    cur, prev = allnotes[i], allnotes[i - 1]
                    a = int((cur.start + LEAD_IN) * SR)
                    b = a + int(0.1 * SR)
                    ov.append(rms_db(kweight(wav[prev.voice][a:b])) - rms_db(kweight(wav[cur.voice][a:b])))
                offs = [n.end + LEAD_IN for n in allnotes]
                both = sum(np.pad(x, ((0, max(len(y) for y in wav.values()) - len(x)), (0, 0))) for x in wav.values())
                med, mx = crest_at(both, offs)
                res[f"{reg}_q{bpm}_release_{rel}"] = dict(overlap_prev_db_median=round(float(np.median(ov)), 1),
                                                          overlap_prev_db_worst=round(float(np.max(ov)), 1),
                                                          noteoff_crest_db_median=round(med, 1), noteoff_crest_db_max=round(mx, 1))
                print(reg, bpm, rel, res[f"{reg}_q{bpm}_release_{rel}"])
    save("release_experiment", res)


if __name__ == "__main__":
    main()
