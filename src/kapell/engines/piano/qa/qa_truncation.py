#!/usr/bin/env python3
"""Truncated notes: sfizz_render streaming underruns.

A sounding note that stops within 1 ms (1 ms frame RMS falls > 25 dB from one frame to
the next, from a level within 50 dB of the stem's loudest frame) while its key is held is
a truncation: it clicks and the rest of the note is missing. The detector runs on dry stems.

1. existing renders from qa_chain.py (demo and QA plan): list every truncation with the
   note that was cut and how long after its note-on;
2. nondeterminism: the kept stem MIDIs of the demo rendered again with sfizz_render as
   render_piano.py calls it (4 stems in parallel), 3 times;
3. the same with a copy of the derived SFZ that adds <control> hint_ram_based=1 (samples
   loaded in RAM instead of streamed; what the strings renderer does), 3 times.

    python3 qa/qa_truncation.py      # writes qa/results/truncation.json

Historical: written before the fix. The derived SFZ now starts with <control>
hint_ram_based=1, so the "stream" arm loads samples into RAM as well and the
stream-vs-RAM comparison no longer applies. render_piano.py runs the same detector on
every stem (truncation_check in the render report); see results/truncation_after_fix.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, PIANO, SR, TMP, read, save  # noqa: E402

sys.path.insert(0, str(PIANO))
from piano_paths import DERIVED_SFZ, DERIVED_SFZ_NO_PEDAL_NOISE, SALAMANDER_DIR, SFIZZ_RENDER  # noqa: E402


def detect(x: np.ndarray) -> list[tuple[float, float, float]]:
    """1 ms frames; a truncation is a drop of > 25 dB from the mean of the 10 frames before to the
    mean of the 10 frames after (so a single low frame at a zero crossing of a bass note does not
    count), with the sharpest single-frame fall at that point, from within 50 dB of the stem max."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    fr = SR // 1000
    nf = len(m) // fr
    p = (m[: nf * fr].reshape(nf, fr) ** 2).mean(axis=1) + 1e-30
    e = 10 * np.log10(p)
    top = e.max()
    k = np.ones(10) / 10
    before = 10 * np.log10(np.convolve(p, k, mode="full")[:nf])            # frames i-9..i
    after = 10 * np.log10(np.convolve(p[::-1], k, mode="full")[:nf][::-1])  # frames i..i+9
    d = after[1:] - before[:-1]  # drop across the boundary between frame i and i+1
    cand = np.nonzero((d < -25) & (before[:-1] > top - 50))[0]
    out, last = [], -100
    for i in cand:
        if i - last > 20:
            out.append((round((i + 1) / 1000, 3), round(float(d[i]), 1), round(float(before[i] - top), 1)))
        last = i
    return out


def stem_notes(mid: Path) -> list[dict]:
    t, pend, out = 0.0, {}, []
    for m in mido.MidiFile(mid):
        t += m.time
        if m.type == "note_on" and m.velocity > 0:
            pend.setdefault(m.note, []).append(t)
        elif m.type in ("note_on", "note_off") and pend.get(m.note):
            out.append(dict(key=m.note, on=pend[m.note].pop(0), off=t))
    return out


def explain(trunc, notes):
    rows = []
    for t, drop, lvl in trunc:
        held = [n for n in notes if n["on"] < t < n["off"] + 0.002]
        n = max(held, key=lambda n: n["on"]) if held else None
        rows.append(dict(t_stem=t, drop_db=drop, level_re_stem_max_db=lvl,
                         cut_note=None if n is None else dict(key=n["key"], after_on_ms=round((t - n["on"]) * 1000, 1),
                                                                  before_off_ms=round((n["off"] - t) * 1000, 1))))
    return rows


def run_parallel(sfzs, mids, tag):
    def one(i):
        wav = TMP / f"trunc_{tag}_{i}.wav"
        r = subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfzs[i]), "--midi", str(mids[i]), "--wav", str(wav), "-s", str(SR),
                            "-q", "10", "-p", "512", "-b", "256"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return wav
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(mids)) as ex:
        wavs = list(ex.map(one, range(len(mids))))
    return wavs, time.time() - t0


def main() -> None:
    res = {}
    for plan in ("demo", "qa"):
        rep = json.loads((TMP / f"fugue_{plan}.render.json").read_text())
        temp = Path(rep["temp"])
        voices = list(rep["voices"])
        res[plan] = {}
        for i, v in enumerate(voices):
            x = read(TMP / f"fugue_{plan}_stems" / f"{v}.wav")
            res[plan][v] = explain(detect(x), stem_notes(temp / f"stem{i:02d}.mid"))
        print(plan, {v: len(r) for v, r in res[plan].items()})
    # reruns of the demo stems
    rep = json.loads((TMP / "fugue_demo.render.json").read_text())
    temp = Path(rep["temp"])
    voices = list(rep["voices"])
    mids = [temp / f"stem{i:02d}.mid" for i in range(len(voices))]
    ram_dir = TMP / "ramsfz"
    ram_dir.mkdir(exist_ok=True)
    ram = []
    for src in (DERIVED_SFZ, DERIVED_SFZ_NO_PEDAL_NOISE):
        dst = ram_dir / src.name
        dst.write_text(f"<control> default_path={SALAMANDER_DIR}/ hint_ram_based=1\n" + src.read_text())
        ram.append(dst)
    stream_sfz = [DERIVED_SFZ] + [DERIVED_SFZ_NO_PEDAL_NOISE] * (len(mids) - 1)
    ram_sfz = [ram[0]] + [ram[1]] * (len(mids) - 1)
    for tag, sfzs in (("stream", stream_sfz), ("ram", ram_sfz)):
        runs = []
        for rep_i in range(3):
            wavs, secs = run_parallel(sfzs, mids, f"{tag}{rep_i}")
            counts, cut = {}, []
            for i, (v, w) in enumerate(zip(voices, wavs)):
                x, _ = sf.read(w, dtype="float64", always_2d=True)
                tr = explain(detect(x), stem_notes(mids[i]))
                counts[v] = len(tr)
                cut += [(v, r["t_stem"], r["cut_note"]["key"] if r["cut_note"] else None) for r in tr]
            runs.append(dict(seconds=round(secs, 1), truncations=counts, cut=cut))
            print(tag, rep_i, counts, round(secs, 1), "s")
        res[f"rerun_{tag}"] = runs
    save("truncation", res)


if __name__ == "__main__":
    main()
