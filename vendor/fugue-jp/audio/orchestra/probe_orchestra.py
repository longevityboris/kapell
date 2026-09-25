#!/usr/bin/env python3
"""Per-part behaviour probe for the orchestra renderer (evidence/probe.json).

  python3 probe_orchestra.py [--skip-render] [--parts fl,ob,...]

Writes out/test/probe.mid: every part in turn (sounding pitch, 60 bpm), alone:
  held    three 4 s notes at mf (CC1 88), low / middle / high of the compass
  hairpin one 6 s note, CC1 49 (pp) -> 114 (ff) -> 49 inside the note
  short   six 0.2 s notes, CC20 short, 0.45 s apart, at mf
  slur    five 0.5 s notes, CC20 legato
  timpani three strokes pp / mf / ff, then a 4 s crescendo roll
renders it dry with stems (--stems --keep-start --no-reverb) and measures per part:
  pitch      YIN cents vs A4 = 440 Hz equal temperament of every held / slurred note
  steadiness largest 50 ms level step and level range inside the held notes
             (constant CC1: a loop seam, a splice or a layer swap shows as a step)
  timbre     over the hairpin: correlation of CC1 with level and with the
             spectral centroid (0.25 s frames), level and centroid pp -> ff
  short      level of each short note re the held mf notes, and the time from its
             onset until it has fallen 20 dB (a short note must stop short)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from orch_common import PARTS, SR, midi_name  # noqa: E402
import orch_measure as M  # noqa: E402

OUT = HERE / "out" / "test"
EV = HERE / "evidence"
TPQ = 480
ORDER = ["fl", "ob", "cl", "bn", "hn", "tpt", "tbn", "btbn", "tba", "timp", "vn1", "vn2", "va", "vc", "cb"]


def pitches(p: str) -> tuple[list[int], int]:
    lo, hi = PARTS[p]["lo"], PARTS[p]["hi"]
    mid = (lo + hi) // 2
    return [lo + 3, mid, hi - 4], mid


def build(parts: list[str]) -> tuple[Path, dict]:
    plan: dict = {}
    mid = mido.MidiFile(type=1, ticks_per_beat=TPQ)
    tt = mido.MidiTrack()
    tt.append(mido.MetaMessage("track_name", name="tempo"))
    tt.append(mido.MetaMessage("set_tempo", tempo=1_000_000))
    mid.tracks.append(tt)
    t = 0.5
    for p in parts:
        ev = []
        segs = plan.setdefault(p, {"held": [], "hairpin": None, "short": [], "slur": [], "strokes": [], "roll": None})

        def cc(tt_, c, v):
            ev.append((tt_, 0, mido.Message("control_change", control=c, value=int(v))))

        def nt(on, off, k, vel=64):
            ev.append((on, 2, mido.Message("note_on", note=k, velocity=vel)))
            ev.append((off, 1, mido.Message("note_off", note=k, velocity=0)))

        cc(max(0.0, t - 0.3), 11, 127)
        if p == "timp":
            for c in (49, 88, 114):
                cc(t - 0.05, 1, c)
                cc(t - 0.05, 20, 0)
                nt(t, t + 1.2, 46)
                segs["strokes"].append((t, t + 1.2, 46, c))
                t += 1.8
            cc(t - 0.05, 20, 100)
            for i in range(41):
                cc(t + i * 0.1, 1, 49 + round(65 * i / 40))
            nt(t, t + 4.0, 41)
            segs["roll"] = (t, t + 4.0, 41)
            t += 5.5
        else:
            held, m = pitches(p)
            cc(t - 0.3, 1, 88)
            cc(t - 0.3, 20, 0)
            for k in held:
                nt(t, t + 4.0, k)
                segs["held"].append((t, t + 4.0, k))
                t += 4.8
            cc(t - 0.3, 1, 49)
            for i in range(61):
                x = i / 60
                cc(t + 6.0 * x, 1, 49 + round(65 * (1 - abs(2 * x - 1))))
            nt(t, t + 6.0, m)
            segs["hairpin"] = (t, t + 6.0, m)
            t += 7.0
            cc(t - 0.3, 1, 88)
            cc(t - 0.3, 20, 110)
            for i in range(6):
                nt(t + 0.45 * i, t + 0.45 * i + 0.2, m + (0, 2, 3, 5, 3, 2)[i], vel=80)
                segs["short"].append((t + 0.45 * i, t + 0.45 * i + 0.2, m + (0, 2, 3, 5, 3, 2)[i]))
            t += 3.2
            cc(t - 0.3, 20, 80)
            for i in range(5):
                k = m + (0, 2, 4, 5, 7)[i]
                nt(t + 0.5 * i, t + 0.5 * i + 0.5, k)
                segs["slur"].append((t + 0.5 * i, t + 0.5 * i + 0.5, k))
            cc(t + 2.6, 20, 0)
            t += 3.8
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=p))
        last = 0
        for tt_, _, msg in sorted(ev, key=lambda e: (e[0], e[1])):
            tk = int(round(tt_ * TPQ))
            tr.append(msg.copy(time=max(0, tk - last)))
            last = max(last, tk)
        mid.tracks.append(tr)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "probe.mid"
    mid.save(str(path))
    return path, plan


def measure(rep: dict, plan: dict) -> dict:
    depth = {}
    for j in rep["jobs"]:
        depth.setdefault(j["label"].split("/")[0], j["seat_depth_m"])
    res = {}
    stems = OUT / "probe.stems"
    for p, segs in plan.items():
        x, _ = sf.read(str(stems / f"{p}.wav"), dtype="float64", always_2d=True)
        m = x.mean(axis=1)
        d = depth.get(p, 0.0) / 343.0

        def sl(a, b):
            return m[max(0, int((a + d) * SR)): max(0, int((b + d) * SR))]

        r: dict = {}
        if p == "timp":
            lv = [M.k_level_db(sl(on + 0.01, on + 0.4)) for on, _, _, _ in segs["strokes"]]
            ce = [M.centroid(sl(on + 0.01, on + 0.4)) for on, _, _, _ in segs["strokes"]]
            r["stroke_klevel_pp_mf_ff"] = [round(v, 1) for v in lv]
            r["stroke_centroid_pp_mf_ff"] = [round(v) for v in ce]
            ring = []
            for on, off, k, _ in segs["strokes"]:
                e, hop = M.env_db(sl(on, off + 0.6), 0.02, 0.005)
                pk = float(e.max())
                i_off = int((off - on) / hop)
                ring.append(round(float(e[min(len(e) - 1, i_off - 4)] - pk), 1))
                ring.append(round(float(e[min(len(e) - 1, i_off + 60)] - pk), 1))
            r["stroke_level_at_off_and_0p3s_after_db"] = ring
            on, off, k = segs["roll"]
            fr = np.arange(on + 0.25, off - 0.25, 0.25)
            lv = [M.k_level_db(sl(a, a + 0.25)) for a in fr]
            cc1 = 49 + 65 * (fr + 0.125 - on) / 4.0
            r["roll_level_span_db"] = round(lv[-1] - lv[0], 1)
            r["roll_corr_level_cc1"] = round(float(np.corrcoef(lv, cc1)[0, 1]), 3)
            e, _ = M.env_db(sl(on + 0.3, off - 0.1), 0.05, 0.05)
            r["roll_max_step_db"] = round(float(np.max(np.abs(np.diff(e)))), 1)
            c = M.pitch_cents(sl(on + 0.4, off - 0.2), k)
            r["roll_pitch_c"] = None if c is None else round(c, 1)
            res[p] = r
            continue
        cents, steps, ranges = [], [], []
        for on, off, k in segs["held"]:
            c = M.pitch_cents(sl(on + 0.8, off - 0.3), k)
            cents.append((midi_name(k), None if c is None else round(c, 1)))
            e, _ = M.env_db(sl(on + 0.4, off - 0.15), 0.05, 0.05)
            steps.append(round(float(np.max(np.abs(np.diff(e)))), 1))
            ranges.append(round(float(e.max() - e.min()), 1))
        for on, off, k in segs["slur"]:
            c = M.pitch_cents(sl(on + 0.15, off - 0.05), k)
            cents.append((midi_name(k), None if c is None else round(c, 1)))
        r["pitch_c"] = cents
        r["held_max_step_db"] = steps
        r["held_level_range_db"] = ranges
        on, off, k = segs["hairpin"]
        fr = np.arange(on + 0.25, off - 0.25, 0.25)
        lv = np.array([M.k_level_db(sl(a, a + 0.25)) for a in fr])
        ce = np.array([M.centroid(sl(a, a + 0.25)) for a in fr])
        rich = np.array([M.harmonic_richness(sl(a, a + 0.25), k) or np.nan for a in fr])
        xm = (fr + 0.125 - on) / 6.0
        cc1 = 49 + 65 * (1 - np.abs(2 * xm - 1))
        r["hairpin_corr_level_cc1"] = round(float(np.corrcoef(lv, cc1)[0, 1]), 3)
        r["hairpin_corr_centroid_cc1"] = round(float(np.corrcoef(ce, cc1)[0, 1]), 3)
        ok = np.isfinite(rich)
        r["hairpin_corr_richness_cc1"] = round(float(np.corrcoef(rich[ok], cc1[ok])[0, 1]), 3) if ok.sum() > 4 else None
        ipk = int(np.argmax(cc1))
        r["hairpin_level_pp_ff_pp_db"] = [round(float(lv[0]), 1), round(float(lv[ipk]), 1), round(float(lv[-1]), 1)]
        r["hairpin_centroid_pp_ff_pp_hz"] = [round(float(ce[0])), round(float(ce[ipk])), round(float(ce[-1]))]
        e, _ = M.env_db(sl(on + 0.3, off - 0.15), 0.05, 0.05)
        r["hairpin_max_step_db"] = round(float(np.max(np.abs(np.diff(e)))), 1)
        ref = np.median([M.k_level_db(sl(a + 1.0, b - 0.5)) for a, b, _ in segs["held"][1:2]])
        sh_lv, sh_len = [], []
        for on, off, k in segs["short"]:
            sh_lv.append(round(M.k_level_db(sl(on, on + 0.25)) - float(ref), 1))
            eb = M.band_env_db(sl(on - 0.05, on + 0.45), k)
            pk = int(np.argmax(eb))
            after = np.flatnonzero(eb[pk:] < eb[pk] - 20)
            sh_len.append(round((pk + (after[0] if len(after) else len(eb) - pk)) * 0.005 - 0.05, 3))
        r["short_level_re_held_db"] = sh_lv
        r["short_time_to_minus20db_s"] = sh_len
        r["clicks"] = [round(t, 3) for t in M.clicks(x)][:10]
        res[p] = r
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--parts", default=",".join(ORDER))
    a = ap.parse_args(argv)
    parts = [p for p in a.parts.split(",") if p]
    path, plan = build(parts)
    base = OUT / "probe"
    if not a.skip_render:
        subprocess.run([sys.executable, str(HERE / "render_orchestra.py"), str(path), "-o", str(base),
                        "--stems", "--keep-start", "--no-reverb"], check=True)
    rep = json.loads(base.with_suffix(".json").read_text())
    res = measure(rep, plan)
    flat = [c for r in res.values() for _, c in r.get("pitch_c", []) if c is not None]
    summary = dict(notes_pitched=len(flat), pitch_med_abs_c=round(float(np.median(np.abs(flat))), 1),
                   pitch_max_abs_c=round(float(np.max(np.abs(flat))), 1),
                   pitch_over_10c=[f"{p} {n} {c:+.1f}" for p, r in res.items() for n, c in r.get("pitch_c", [])
                                   if c is not None and abs(c) > 10],
                   pitch_unmeasured=[f"{p} {n}" for p, r in res.items() for n, c in r.get("pitch_c", []) if c is None],
                   held_steps_over_3db=[f"{p} {s}" for p, r in res.items() for s in r.get("held_max_step_db", []) if s > 3],
                   hairpin_centroid_corr_below_0p5=[p for p, r in res.items()
                                                    if r.get("hairpin_corr_centroid_cc1", 1) < 0.5],
                   short_longer_than_0p4s=[f"{p} {s}" for p, r in res.items()
                                           for s in r.get("short_time_to_minus20db_s", []) if s > 0.4],
                   warnings=rep.get("warnings", []))
    out = dict(summary=summary, parts=res)
    EV.mkdir(exist_ok=True)
    (EV / "probe.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
