#!/usr/bin/env python3
"""Closed-loop tuning of the built orchestra instruments (A4 = 440 Hz).

  python3 tune_orchestra.py [--only fl,hn] [--sets iowa] [--retune] [--rounds 2]

For every set: renders each sampled key of every layer and articulation
straight through sfizz_render (sustains 4 s at the layer's anchor, short
notes 0.3 s; timpani strokes and rolls), measures the pitch (YIN within +-1.2
semitones of the key, from harmonics 2-5 below 80 Hz: 1.0-3.8 s into a sustain, 40-250 ms into a short note;
timpani: the partial-template fit of orch_build.timp_pitch) and writes
built/tuning_verify.json.  --retune folds the errors into
built/tuning_corrections.json (only |error| < 150 c: anything larger is a
mislabelled sample and is reported, not bent), rewrites the SFZ files and
measures again (--rounds).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import orch_build as B  # noqa: E402
from orch_common import BUILT, PARTS, SFIZZ_RENDER, SR, midi_to_hz  # noqa: E402
import orch_measure as M  # noqa: E402

GAP = 4.4                      # s between notes (sustains are held 4 s)


def plan_for(part: str, s: str):
    lay = json.loads((BUILT / part / f"{s}.layers.json").read_text())
    meta = json.loads((BUILT / part / s / "meta.json").read_text())["notes"]
    drop = B.sparse_layers(meta)
    jobs = []
    for art, spec in lay.items():
        for name, anchor in zip(spec["names"], spec["anchors"]):
            keys = sorted({m["key"] for m in meta if m["art"] == art and m["layer"] == name
                           and (art, name) not in drop})
            if keys:
                jobs.append((art, name, anchor, spec["cc"], keys))
                if art == "sus" and "stac" not in lay:
                    jobs.append(("sus_short", name, anchor, spec["cc"], keys))   # short notes from the sustain
    return jobs


def render_job(part, s, art, name, anchor, cc, keys, tmp: Path):
    mid = mido.MidiFile(type=0, ticks_per_beat=480)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("set_tempo", tempo=500000))       # 960 ticks/s
    art_cc = {"sus": 0, "sus_short": 112, "stac": 112, "hit": 0, "roll": 100}[art]
    for c, v in ((1, 88), (3, 88), (2, anchor), (cc, anchor), (20, art_cc), (21, 20)):
        tr.append(mido.Message("control_change", control=c, value=int(v), time=0))
    dur = {"sus": 4.0, "sus_short": 0.3, "stac": 0.3, "hit": 1.2, "roll": 1.4}[art]
    last = 0
    for i, k in enumerate(keys):
        on = int((0.3 + i * GAP) * 960)
        off = int((0.3 + i * GAP + dur) * 960)
        tr.append(mido.Message("note_on", note=k, velocity=64, time=on - last))
        tr.append(mido.Message("note_off", note=k, velocity=0, time=off - on))
        last = off
    tr.append(mido.MetaMessage("end_of_track", time=960))
    mid.tracks.append(tr)
    tag = f"{part}_{s}_{art}_{name}"
    mp, wp = tmp / f"{tag}.mid", tmp / f"{tag}.wav"
    mid.save(str(mp))
    r = subprocess.run([str(SFIZZ_RENDER), "--sfz", str(BUILT / part / f"{s}.sfz"), "--midi", str(mp), "--wav",
                        str(wp), "-s", str(SR), "-q", "3"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    x, _ = sf.read(str(wp), dtype="float64", always_2d=True)
    rows = []
    for i, k in enumerate(keys):
        t0 = 0.3 + i * GAP
        if art == "sus":
            # the body of a held note (a low Iowa tuba note settles 20 cents away
            # from its first second, and a held note is heard by its body)
            seg = x[int((t0 + 1.0) * SR): int((t0 + 3.8) * SR)]
        elif art == "roll" and part != "timp":
            seg = x[int((t0 + 0.3) * SR): int((t0 + 1.2) * SR)]
        elif art in ("stac", "sus_short"):
            seg = x[int((t0 + 0.04) * SR): int((t0 + 0.25) * SR)]
        else:
            seg = x[int(t0 * SR): int((t0 + 1.2) * SR)]
        if part == "timp":
            f = B.timp_pitch(seg, 0, k)
            c = 100 * (f - k)
        elif midi_to_hz(k) < 80.0:
            c = M.pitch_cents_harmonic(seg, k)        # YIN is biased this low (orch_measure)
        else:
            c = M.pitch_cents(seg, k)
        rms = float(np.sqrt(np.mean(seg ** 2)) + 1e-12)
        # onset latency: note-on -> the note reaches 6 dB below its peak (first 0.6 s)
        e, hop = M.env_db(x[int((t0 - 0.05) * SR): int((t0 + 0.6) * SR)], 0.01, 0.0025)
        i6 = int(np.flatnonzero(e >= e.max() - 6.0)[0])
        rows.append(dict(key=k, cents=None if c is None else round(c, 1), level_db=round(20 * np.log10(rms), 1),
                         onset_ms=round(1000 * (i6 * hop - 0.05), 1)))
    return (part, s, art, name), rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--sets", default="")
    ap.add_argument("--retune", action="store_true")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args(argv)
    parts = [p for p in a.only.split(",") if p] or list(PARTS)
    sets = {s for s in a.sets.split(",") if s}
    targets = [(p, s) for p in parts for s in B.CANDIDATES[p]
               if (not sets or s in sets) and (BUILT / p / f"{s}.sfz").exists()]
    rep_p = BUILT / "tuning_verify.json"
    for rnd in range(a.rounds):
        tmp = Path(tempfile.mkdtemp(prefix="orch_tune_"))
        work = [(p, s, *j) for p, s in targets for j in plan_for(p, s)]
        with ThreadPoolExecutor(a.jobs) as ex:
            res = list(ex.map(lambda w: render_job(*w, tmp), work))
        rep = json.loads(rep_p.read_text()) if rep_p.exists() else {}
        corr = B.load_corrections()
        n_fix, bad = 0, []
        for (p, s, art, name), rows in res:
            rep.setdefault(f"{p}/{s}", {})[f"{art}/{name}"] = rows
            for r in rows:
                if art == "sus_short":
                    continue                      # same regions as 'sus': only the onset matters here
                if r["cents"] is None:
                    bad.append(f"{p}/{s}/{art}/{name}/{r['key']}: no pitch")
                    continue
                if abs(r["cents"]) >= 150:
                    bad.append(f"{p}/{s}/{art}/{name}/{r['key']}: {r['cents']:+.0f} c")
                    continue
                if a.retune and abs(r["cents"]) > 2.0:
                    kk = f"{p}/{s}/{art}/{name}/{r['key']}"
                    corr[kk] = round(corr.get(kk, 0.0) - r["cents"], 1)
                    n_fix += 1
        rep_p.write_text(json.dumps(rep, indent=0))
        lat_p = BUILT / "latency.json"
        lat = json.loads(lat_p.read_text()) if lat_p.exists() else {}
        for (p, s, art, name), rows in res:
            lat.setdefault(f"{p}/{s}", {}).setdefault(art, {})[name] = float(np.median([r["onset_ms"] for r in rows]))
        for k in lat:
            for art in lat[k]:
                lat[k][art]["_median"] = float(np.median([v for n, v in lat[k][art].items() if n != "_median"]))
        lat_p.write_text(json.dumps(lat, indent=1))
        allc = [abs(r["cents"]) for (k_, rows) in res for r in rows
                if k_[2] != "sus_short" and r["cents"] is not None and abs(r["cents"]) < 150]
        print(f"round {rnd + 1}: {len(allc)} notes, median |c| {np.median(allc):.1f}, p95 {np.percentile(allc, 95):.1f}, "
              f"over 10 c: {sum(c > 10 for c in allc)}; unmeasurable/outliers: {len(bad)}")
        for b in bad[:30]:
            print("  ", b)
        if not a.retune:
            break
        B.CORR_PATH.write_text(json.dumps(corr, indent=0, sort_keys=True))
        for p, s in targets:
            metas = json.loads((BUILT / p / s / "meta.json").read_text())["notes"]
            B.write_sfz(p, s, metas)
        print(f"  retuned {n_fix} regions")


if __name__ == "__main__":
    main()
