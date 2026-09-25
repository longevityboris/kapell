#!/usr/bin/env python3
"""Choose each part's recordings by measurement: render the SAME test phrase
with every candidate set (dry, through render_orchestra.py --force-set) and
measure it.

  python3 compare_sets.py [--only fl,hn] [--out out/compare]

The phrase (60 bpm, one beat = 1 s), in the part's working register:
  A  one note held 3 s at pp, then mf, then ff (CC1 49 / 88 / 114)
  B  a 4 s note, hairpin pp -> ff (CC1 40 -> 120)
  C  eight legato eighths (0.4 s, scale), mf
  D  eight short sixteenths (0.18 s every 0.2 s), mf
  E  four detached quarters (0.6 s, 0.1 s gaps), mf
Timpani: strokes on F2 and B-flat 2 at pp / mf / ff, a crescendo roll on B-flat,
a roll on F at mf.

Metrics per set (dry stem, the renderer's own gains):
  pitch        median |cents| and worst note (YIN near the written key)
  timbre       harmonic richness ff - pp of the held note (harmonics 3-10 re 1-2,
               dB, noise between harmonics ignored), plus centroid ff / pp and the
               change in the share of energy above 2 kHz
  steady       std (dB) of the 50 ms level over the held notes after the attack
               (loop / splice artefacts, recorded wobble)
  hairpin      correlation of the level with CC1, and the largest 0.25 s drop
  onset        median ms from the note-on to -6 dB of the note's peak (short notes)
  clarity      mean dB the short notes rise above the gap before them
  clicks       discontinuity count (>6 kHz jumps 30 dB above the local level)
The chosen set per part is the one with the best combined score (weights in
score()); the table goes to README.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from orch_common import PARTS, SR, midi_name  # noqa: E402
import orch_measure as M  # noqa: E402
import render_orchestra as R  # noqa: E402
from orch_build import CANDIDATES  # noqa: E402

REGISTER = {"fl": 72, "ob": 67, "cl": 58, "bn": 45, "hn": 53, "tpt": 62, "tbn": 50, "btbn": 40, "tba": 34,
            "vn1": 67, "vn2": 62, "va": 55, "vc": 43, "cb": 33, "timp": 41}
SCALE = [0, 2, 3, 5, 7, 8, 10, 12]


def phrase(part: str, path: Path) -> list:
    """Write the test MIDI; return [(section, on, off, key)]."""
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    tt = mido.MidiTrack()
    tt.append(mido.MetaMessage("set_tempo", tempo=1_000_000))
    mid.tracks.append(tt)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name=part))
    ev = []                                    # (t, prio, msg)
    notes = []
    b = REGISTER[part]

    def note(sec, on, off, key, vel=64, cc1=None, art=None):
        if cc1 is not None:
            ev.append((on - 0.02, 0, mido.Message("control_change", control=1, value=cc1)))
        if art is not None:
            ev.append((on - 0.01, 0, mido.Message("control_change", control=20, value=art)))
        ev.append((on, 2, mido.Message("note_on", note=key, velocity=vel)))
        ev.append((off, 1, mido.Message("note_off", note=key, velocity=0)))
        notes.append((sec, on, off, key))
    if part == "timp":
        t = 0.5
        for key in (41, 46):
            for c in (49, 88, 114):
                note(f"A{c}", t, t + 0.9, key, cc1=c, art=0)
                t += 1.5
        note("B", 10.0, 14.0, 46, art=100)
        for i in range(81):
            ev.append((10.0 + i * 0.05, 0, mido.Message("control_change", control=1, value=int(40 + i))))
        note("C", 15.5, 18.5, 41, cc1=88, art=100)
        end = 20.0
    else:
        k = b + 5
        for i, c in enumerate((49, 88, 114)):
            note(f"A{c}", 0.5 + 3.5 * i, 3.5 + 3.5 * i, k, cc1=c)
        t0 = 11.5
        note("B", t0, t0 + 4.0, b + 7, cc1=40)
        for i in range(81):
            ev.append((t0 + i * 0.05, 0, mido.Message("control_change", control=1, value=int(40 + i))))
        t = 16.5
        for i, s in enumerate(SCALE):
            note("C", t + 0.4 * i, t + 0.4 * (i + 1), b + s, cc1=88 if i == 0 else None)
        t = 20.5
        for i, s in enumerate(SCALE):
            note("D", t + 0.2 * i, t + 0.2 * i + 0.18, b + s)
        t = 23.0
        for i, s in enumerate((0, 3, 7, 12)):
            note("E", t + 0.7 * i, t + 0.7 * i + 0.6, b + s)
        end = 26.5
    ev.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for t, _, msg in ev:
        tk = int(round(max(0.0, t) * 480))
        tr.append(msg.copy(time=tk - last))
        last = tk
    tr.append(mido.MetaMessage("end_of_track", time=int((end - last / 480) * 480)))
    mid.tracks.append(tr)
    mid.save(str(path))
    return notes


def measure(part: str, wav: Path, notes: list, delay: float) -> dict:
    x, _ = sf.read(str(wav), dtype="float64", always_2d=True)
    m = x.mean(axis=1)

    def seg(a, b):
        return m[int((a + delay) * SR): int((b + delay) * SR)]
    out = {}
    cents = []
    for sec, on, off, key in notes:
        if part == "timp":
            s = seg(on + 0.12, min(off, on + 0.8))
        else:
            s = seg(on + (0.12 if off - on > 0.3 else 0.04), off - 0.03)
        c = M.pitch_cents(s, key) if part != "timp" else None
        if c is not None:
            cents.append((c, sec, key))
    if part == "timp":
        import orch_build as B
        for sec, on, off, key in notes:
            f = B.timp_pitch(np.stack([seg(on, on + 1.2)] * 2, axis=1), 0, key)
            cents.append((100 * (f - key), sec, key))
    ac = np.array([abs(c) for c, _, _ in cents]) if cents else np.array([np.nan])
    out["pitch_med_c"] = round(float(np.median(ac)), 1)
    worst = max(cents, key=lambda z: abs(z[0])) if cents else (np.nan, "", 0)
    out["pitch_worst"] = f"{worst[0]:+.0f} c ({midi_name(worst[2])} {worst[1]})"
    held = {sec: (on, off) for sec, on, off, key in notes if sec.startswith("A")}
    if part == "timp":
        cs = {c: seg(held[f"A{c}"][0] + 0.02, held[f"A{c}"][0] + 0.4) for c in (49, 88, 114) if f"A{c}" in held}
    else:
        cs = {c: seg(held[f"A{c}"][0] + 0.8, held[f"A{c}"][1] - 0.2) for c in (49, 88, 114)}
    out["centroid_pp_mf_ff"] = [round(M.centroid(cs[c])) for c in (49, 88, 114)]
    out["timbre_ratio"] = round(out["centroid_pp_mf_ff"][2] / max(1, out["centroid_pp_mf_ff"][0]), 2)
    out["hf_change_db"] = round(M.band_share(cs[114]) - M.band_share(cs[49]), 1)
    out["level_pp_mf_ff"] = [round(M.level_db(cs[c]), 1) for c in (49, 88, 114)]
    hk = [k for s_, o, f, k in notes if s_ == "A49"][0]
    hr = [M.harmonic_richness(cs[c], hk) for c in (49, 114)]
    out["richness_change_db"] = round(hr[1] - hr[0], 1) if None not in hr else None
    if part != "timp":
        st = []
        for c in (49, 88, 114):
            e, h = M.env_db(cs[c], 0.05, 0.05)
            st.append(float(np.std(e)))
        out["steady_std_db"] = round(float(np.mean(st)), 2)
        on, off = [(o, f) for s_, o, f, k in notes if s_ == "B"][0]
        e, h = M.env_db(seg(on + 0.3, off - 0.2), 0.1, 0.25)
        target = np.linspace(0, 1, len(e))
        out["hairpin_corr"] = round(float(np.corrcoef(e, target)[0, 1]), 3)
        out["hairpin_worst_drop_db"] = round(float(min(0.0, np.min(np.diff(e)))), 1)
        ons, rises = [], []
        dn = [(o, f, k) for s_, o, f, k in notes if s_ == "D"]
        for i, (o, f, k) in enumerate(dn):
            e = M.band_env_db(seg(o - 0.1, o + 0.2), k)
            pk = e.max()
            i6 = int(np.flatnonzero(e >= pk - 6)[0])
            ons.append(1000 * (i6 * 0.005 - 0.1))
            pre = e[max(0, int(0.07 / 0.005)): int(0.095 / 0.005)].mean()
            rises.append(pk - pre)
        out["onset_ms"] = round(float(np.median(ons)), 1)
        out["short_clarity_db"] = round(float(np.mean(rises)), 1)
    else:
        on, off = [(o, f) for s_, o, f, k in notes if s_ == "B"][0]
        e, h = M.env_db(seg(on + 0.3, off - 0.2), 0.1, 0.25)
        out["hairpin_corr"] = round(float(np.corrcoef(e, np.linspace(0, 1, len(e)))[0, 1]), 3)
        out["hairpin_worst_drop_db"] = round(float(min(0.0, np.min(np.diff(e)))), 1)
    out["clicks"] = len(M.clicks(x))
    return out


def score(r: dict) -> float:
    """Higher is better.  Pitch and steadiness are hard requirements, timbre
    change with dynamics the main musical one, then short-note clarity."""
    s = 0.0
    s -= 0.25 * min(40.0, r["pitch_med_c"])
    rc = r.get("richness_change_db")
    s += 0.5 * min(12.0, max(-6.0, rc if rc is not None else 8.0 * (r["timbre_ratio"] - 1.0)))
    if "steady_std_db" in r:
        s -= 2.0 * r["steady_std_db"]
        s += 0.3 * min(12.0, r["short_clarity_db"])
        s -= 0.05 * abs(r["onset_ms"])
    s += 3.0 * r["hairpin_corr"]
    s -= 1.0 * min(5, r["clicks"])
    return round(s, 2)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", type=Path, default=HERE / "out" / "compare")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    parts = [p for p in a.only.split(",") if p] or list(PARTS)
    res_p = a.out / "compare.json"
    res = json.loads(res_p.read_text()) if res_p.exists() else {}
    for part in parts:
        mp = a.out / f"{part}.mid"
        notes = phrase(part, mp)
        res[part] = {}
        stack0 = list(R.STACK.get(part, []))
        for s in CANDIDATES[part] + (["stack"] if part in R.STACK else []):
            if s != "stack" and not R.set_available(part, s):
                continue
            o = a.out / f"{part}_{s}"
            if s == "stack":
                R.STACK[part] = stack0
            force = [] if s == "stack" else ["--force-set", f"{part}={s}"]
            rep = R.main([str(mp), "-o", str(o), "--no-reverb", "--keep-start", "--stems", "--no-normalize",
                          "--jobs", "4"] + force)
            depth = rep["jobs"][0]["seat_depth_m"]
            stem = next((o.parent / (o.name + ".stems")).glob("*.wav"))
            r = measure(part, stem, notes, depth / 343.0)
            r["score"] = score(r)
            res[part][s] = r
            print(part, s, json.dumps(r))
        best = max(res[part], key=lambda k: res[part][k]["score"]) if res[part] else None
        res[part]["_best"] = best
        res_p.write_text(json.dumps(res, indent=1))
    print(json.dumps({p: res[p].get("_best") for p in res}, indent=0))


if __name__ == "__main__":
    main()
