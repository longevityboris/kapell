#!/usr/bin/env python3
"""Round-2 check that the round-1 layer-interference fix holds (0fd6801: "two takes of the same note
interfered wherever CC1 sat between the recorded layers, 5-8 dB swells at p/mp/f").

  python3 an_held.py --temp QUARTET_TEMP_DIR [--tag sk_final] [--reuse]

A. On the test music (the --keep-start --keep-temp chain render of an_chain.py, tag sk_final):
   * zone occupancy: the CC1 each job MIDI sends to sfizz (MIDI time) inside the SFZ crossfade zones
     (66-70 and 105-109; iowa_build.XF 65-72 / 104-111, sfizz reaching full gain one step before the end) while a note sounds: every contiguous stay, its
     length (the renderer's plan allows 0.05 s at a note-on, 0.3 s inside a held note);
   * every note >= 1.0 s in the dry stem (all gains applied): 50 ms RMS over [on+0.3, off-0.1],
     the level the MIDI asks for (cc1_target_db of the true CC1 + CC11 at --cc11-depth 0.5) removed,
     p98-p2 of the residual, its largest deviation from a 1 s smooth, and whether a zone stay (layer
     switch) falls inside the note.
B. Controlled held notes, 6 s at fixed CC1 = CC11 in {49 62 69 75 88 101 108 114}, three keys per
   instrument from the test music's register, through render_quartet.py (--hall none, stems):
   wander (p98-p2 of 50 ms RMS over [on+1.0, off-0.3]) and 1 s-smooth deviation.
C. Positive control: the same notes played by sfizz directly from the SFZ with CC1 parked INSIDE a
   zone (68, 108) vs at the layer anchors (49, 88, 114): the interference the renderer avoids
   must show up here, otherwise the measure could not have seen it.  Also CC1 71 / 104 / 110, the
   edges of the renderer's home ranges (LAYER_HOME mf 71-104, ff 110-127): are they one layer?
D. A/B on the test music: its kept job MIDIs played by sfizz as they are and with CC1 71 -> 72 and
   110 -> 111 (the first values where the lower layer is fully out); per-note wander of every note
   >= 1 s that spends >= half its window at 71 / 110, same notes, same random seed sequence.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import SR, STRINGS, TMP, db, midi_voices, render, rms_env, save  # noqa: E402

sys.path.insert(0, str(STRINGS))
import render_quartet as rq  # noqa: E402
from iowa_common import QUARTET_DIR, SFIZZ_RENDER  # noqa: E402

ZONES = ((65, 71), (104, 110))   # layers mix only at 66-70 / 105-109 (sfizz: gain 1 one step before the zone end; control C checks 71/104/110)
H = TMP / "held"
KEYS = {"vn1": ("soprano", 0, 40, [70, 77, 82]), "vn2": ("alto", 1, 40, [63, 68, 72]),
        "va": ("tenor", 2, 41, [53, 58, 62]), "vc": ("bass", 3, 42, [39, 46, 53])}
CCS = [49, 62, 69, 75, 88, 101, 108, 114]
ANCHOR_OF = {49: 49, 62: 49, 69: 49, 75: 88, 88: 88, 101: 88, 108: 88, 114: 114}   # layer the renderer plays (69: pp, hysteresis up at 70; 108: mf, up at 109)
DUR, GAP = 6.0, 1.2


def in_zone(c):
    return any(lo < c < hi for lo, hi in ZONES)


def job_cc1(mid_path):
    """[(t, value)] of CC1 in a kept job MIDI (MIDI time)."""
    t, out = 0.0, []
    for msg in mido.MidiFile(str(mid_path)):
        t += msg.time
        if msg.type == "control_change" and msg.control == 1:
            out.append((t, msg.value))
    return out


def step_on_grid(ev, T, default):
    if not ev:
        return np.full(len(T), float(default))
    et = np.array([e[0] for e in ev])
    ev_ = np.array([e[1] for e in ev], dtype=float)
    idx = np.searchsorted(et, T + 1e-9, side="right") - 1
    out = np.where(idx >= 0, ev_[np.clip(idx, 0, None)], default)
    return out.astype(float)


def wander(e, t, a, b):
    m = (t >= a) & (t <= b)
    if m.sum() < 10:
        return None
    x = e[m]
    k = max(3, int(round(1.0 / (t[1] - t[0]))) | 1)
    pad = np.concatenate([np.full(k // 2, x[0]), x, np.full(k // 2, x[-1])])
    sm = np.convolve(pad, np.ones(k) / k, mode="valid")[: len(x)]
    return dict(p2_p98_db=round(float(np.percentile(x, 98) - np.percentile(x, 2)), 2),
                max_dev_1s_db=round(float(np.max(np.abs(x - sm))), 2))


# ---------------------------------------------------------------- A: the test music
def part_a(tag, temp):
    rep = json.loads((TMP / f"chain_{tag}.json").read_text())
    midi = midi_voices(TMP / f"chain_{tag}.mid")
    by_name = {v["name"]: v for v in midi.values()}
    out = {}
    for i, j in enumerate(rep["jobs"]):
        inst, label = j["inst"], j["label"]
        ev = job_cc1(Path(temp) / f"j{i}_{inst}.mid")
        notes = j["note_list"]
        pre = [p / 1000 for p in j["pre_ms"]]
        t_end = max(n[1] for n in notes) + 1.0
        T = np.arange(0, t_end, 0.005)
        c_sfz = step_on_grid(ev, T, 88)
        sounding = np.zeros(len(T), bool)
        for (on, off, *_), p in zip(notes, pre):
            sounding[(T >= on - p) & (T <= off)] = True
        zmask = np.array([in_zone(c) for c in c_sfz]) & sounding
        # contiguous zone stays
        stays = []
        d = np.diff(np.concatenate([[0], zmask.astype(int), [0]]))
        for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            stays.append((round(float(T[a]), 3), round(float((b - a) * 0.005), 3)))
        # true dynamic curve the MIDI asks for
        v = by_name[label]
        cc1 = rq.cc1_curve(sorted(v["cc"].get(1, [])), t_end)
        cc11 = rq.cc1_curve(sorted(v["cc"].get(11, [])), t_end)
        exp_db = rq.cc1_target_db(step_on_grid(cc1, T, 88)) + 0.5 * 20 * np.log10(np.maximum(step_on_grid(cc11, T, 127), 1) / 127)
        st, _ = sf.read(str(TMP / f"chain_{tag}_stem_{inst}.wav"), always_2d=True)
        te, e = rms_env(st.mean(axis=1), 0.05, 0.01)
        ex = np.interp(te, T, exp_db)
        resid = e - ex
        rows = []
        for (on, off, key, vel, art) in notes:
            if off - on < 1.0:
                continue
            w_raw = wander(e, te, on + 0.3, off - 0.1)
            w_res = wander(resid, te, on + 0.3, off - 0.1)
            if w_raw is None:
                continue
            sw = [s for s in stays if s[0] < off - 0.1 and s[0] + s[1] > on + 0.3]
            rows.append(dict(on=round(on, 3), dur=round(off - on, 3), key=key,
                             asked_range_db=round(float(np.ptp(ex[(te >= on + 0.3) & (te <= off - 0.1)])), 2),
                             raw=w_raw, residual=w_res, switch_inside=bool(sw)))
        res_p = [r["residual"]["p2_p98_db"] for r in rows]
        dev = [r["residual"]["max_dev_1s_db"] for r in rows]
        sw_rows = [r for r in rows if r["switch_inside"]]
        out[inst] = dict(
            label=label, zone_stays=len(stays), zone_time_s=round(sum(s[1] for s in stays), 3),
            zone_stay_max_s=max([s[1] for s in stays], default=0.0),
            zone_stays_over_0p31s=[s for s in stays if s[1] > 0.31],
            notes_ge_1s=len(rows),
            # every long note's residual per key, no switch inside (round-2 defect: vn1 Eb5 6.65-7.5 dB)
            residual_by_key_no_switch={str(k): sorted(r["residual"]["p2_p98_db"] for r in rows
                                                      if r["key"] == k and not r["switch_inside"])
                                       for k in sorted({r["key"] for r in rows})},
            residual_p2_p98_db=dict(median=round(float(np.median(res_p)), 2), p90=round(float(np.percentile(res_p, 90)), 2),
                                    max=round(float(np.max(res_p)), 2)),
            residual_max_dev_1s_db=dict(median=round(float(np.median(dev)), 2), p90=round(float(np.percentile(dev, 90)), 2),
                                        max=round(float(np.max(dev)), 2)),
            notes_with_switch_inside=len(sw_rows),
            switch_notes_residual_p2_p98_max_db=max([r["residual"]["p2_p98_db"] for r in sw_rows], default=None),
            worst=sorted(rows, key=lambda r: -r["residual"]["p2_p98_db"])[:6])
    return out


# ---------------------------------------------------------------- B / C: controlled held notes
def build_render_midi(path):
    mf = mido.MidiFile(type=1, ticks_per_beat=960)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    mf.tracks.append(t0)
    tps = 1920
    sched = []
    for inst, (name, ch, prog, keys) in KEYS.items():
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
        ev, t = [], 0.5
        for k in keys:
            for c in CCS:
                ev += [(t - 0.2, 0, mido.Message("control_change", channel=ch, control=1, value=c)),
                       (t - 0.2, 0, mido.Message("control_change", channel=ch, control=11, value=c)),
                       (t, 2, mido.Message("note_on", channel=ch, note=k, velocity=70)),
                       (t + DUR, 1, mido.Message("note_off", channel=ch, note=k, velocity=0))]
                sched.append((inst, k, c, t, t + DUR))
                t += DUR + GAP
        last = 0
        for tt, _, m in sorted(ev, key=lambda e: (e[0], e[1])):
            tk = int(round(tt * tps))
            tr.append(m.copy(time=tk - last))
            last = tk
        mf.tracks.append(tr)
    mf.save(str(path))
    return sched


def direct_sfizz(inst, keys, ccs, wav):
    """sfizz straight from the SFZ, CC1 fixed per note (no renderer layer plan)."""
    mf = mido.MidiFile(type=0, ticks_per_beat=960)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    tps, ev, sched, t = 1920, [], [], 0.5
    for k in keys:
        for c in ccs:
            ev += [(t - 0.2, 0, mido.Message("control_change", control=1, value=c)),
                   (t, 2, mido.Message("note_on", note=k, velocity=70)),
                   (t + DUR, 1, mido.Message("note_off", note=k, velocity=0))]
            sched.append((k, c, t, t + DUR))
            t += DUR + GAP
    last = 0
    for tt, _, m in sorted(ev, key=lambda e: (e[0], e[1])):
        tk = int(round(tt * tps))
        tr.append(m.copy(time=tk - last))
        last = tk
    mf.tracks.append(tr)
    mp = wav.with_suffix(".mid")
    mf.save(str(mp))
    sfz = QUARTET_DIR / rq.INSTR[inst]["sfz"]
    subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(mp), "--wav", str(wav), "-s", str(SR),
                    "-p", "256", "-q", "3"], check=True, capture_output=True)
    return sched


def part_bc(reuse):
    H.mkdir(parents=True, exist_ok=True)
    mid = H / "held.mid"
    sched = build_render_midi(mid)
    if not (reuse and (H / "held_stem_vn1.wav").exists()):
        render(mid, H / "held", "--keep-start", "--hall", "none", keep_temp=False)
    B = {}
    for inst in KEYS:
        st, _ = sf.read(str(H / f"held_stem_{inst}.wav"), always_2d=True)
        te, e = rms_env(st.mean(axis=1), 0.05, 0.01)
        rows = {}
        for (i_, k, c, on, off) in sched:
            if i_ != inst:
                continue
            rows.setdefault(k, {})[c] = wander(e, te, on + 1.0, off - 0.3)
        B[inst] = rows
    # excess over the anchor of the layer the renderer plays
    summ = {}
    for inst, rows in B.items():
        ex = []
        for k, r in rows.items():
            for c, w in r.items():
                a = r[ANCHOR_OF[c]]
                ex.append(dict(key=k, cc1=c, p2_p98_db=w["p2_p98_db"], anchor_db=a["p2_p98_db"],
                               excess_db=round(w["p2_p98_db"] - a["p2_p98_db"], 2)))
        summ[inst] = dict(max_p2_p98_db=max(x["p2_p98_db"] for x in ex), max_excess_over_anchor_db=max(x["excess_db"] for x in ex),
                          worst=sorted(ex, key=lambda x: -x["excess_db"])[:4])
    # C: positive control
    C = {}
    for inst, (_, _, _, keys) in KEYS.items():
        wav = H / f"direct_{inst}.wav"
        sch = direct_sfizz(inst, keys, [49, 68, 71, 72, 88, 104, 108, 110, 111, 114], wav)
        x, _ = sf.read(str(wav), always_2d=True)
        te, e = rms_env(x.mean(axis=1), 0.05, 0.01)
        rows = {}
        for k, c, on, off in sch:
            rows.setdefault(k, {})[c] = wander(e, te, on + 1.0, off - 0.3)["p2_p98_db"]
        zone = [rows[k][c] for k in rows for c in (68, 108)]
        anch = [rows[k][c] for k in rows for c in (49, 88, 114)]
        home = [rows[k][c] for k in rows for c in (71, 104, 110)]
        C[inst] = dict(per_key=rows, zone_median_db=round(float(np.median(zone)), 2), zone_max_db=max(zone),
                       anchor_median_db=round(float(np.median(anch)), 2), anchor_max_db=max(anch),
                       home_edges_71_104_110_median_db=round(float(np.median(home)), 2), home_edges_max_db=max(home),
                       # round-2 fix: LAYER_HOME is now mf 72-104, ff 111-127 (the first values with one take only)
                       new_home_edges_72_111_excess_db={f"{k}/{c}": round(rows[k][c] - rows[k][a], 2)
                                                        for k in rows for c, a in ((72, 88), (111, 114))})
    return dict(renderer=B, renderer_summary=summ, direct_sfizz_control=C)


def sfizz_job(mid_in, mid_out, wav, inst, remap):
    mf = mido.MidiFile(str(mid_in))
    for tr in mf.tracks:
        for m in tr:
            if m.type == "control_change" and m.control == 1 and m.value in remap:
                m.value = remap[m.value]
    mf.save(str(mid_out))
    subprocess.run([str(SFIZZ_RENDER), "--sfz", str(QUARTET_DIR / rq.INSTR[inst]["sfz"]), "--midi", str(mid_out),
                    "--wav", str(wav), "-s", str(SR), "-p", "256", "-q", "3"], check=True, capture_output=True)
    x, _ = sf.read(str(wav), always_2d=True)
    return x.mean(axis=1)


def part_d(tag, temp):
    rep = json.loads((TMP / f"chain_{tag}.json").read_text())
    H.mkdir(parents=True, exist_ok=True)
    out = {}
    for i, j in enumerate(rep["jobs"]):
        inst = j["inst"]
        src = Path(temp) / f"j{i}_{inst}.mid"
        ev = job_cc1(src)
        notes = j["note_list"]
        G = np.arange(0, max(n[1] for n in notes) + 1.0, 0.005)
        c = step_on_grid(ev, G, 88)
        sounding = np.zeros(len(G), bool)
        for (on_, off_, *_r) in notes:
            sounding |= (G >= on_) & (G < off_)
        at_old_edges_s = round(float(np.sum(sounding & ((c == 71) | (c == 110)))) * 0.005, 3)
        xa = sfizz_job(src, H / f"d_{inst}_a.mid", H / f"d_{inst}_a.wav", inst, {})
        xb = sfizz_job(src, H / f"d_{inst}_b.mid", H / f"d_{inst}_b.wav", inst, {71: 72, 110: 111})
        ta, ea = rms_env(xa, 0.05, 0.01)
        tb, eb = rms_env(xb, 0.05, 0.01)
        rows = []
        for (on, off, key, vel, art) in notes:
            if off - on < 1.0:
                continue
            m = (G >= on + 0.3) & (G <= off - 0.1)
            frac = float(np.mean((c[m] == 71) | (c[m] == 110)))
            if frac < 0.5:
                continue
            wa, wb = wander(ea, ta, on + 0.3, off - 0.1), wander(eb, tb, on + 0.3, off - 0.1)
            rows.append(dict(on=round(on, 3), dur=round(off - on, 3), key=key, frac_at_edge=round(frac, 2),
                             as_rendered=wa, edge_moved=wb, excess_db=round(wa["p2_p98_db"] - wb["p2_p98_db"], 2)))
        exs = [r["excess_db"] for r in rows]
        out[inst] = dict(sounding_s_at_cc1_71_or_110=at_old_edges_s, n=len(rows), excess_median_db=round(float(np.median(exs)), 2) if exs else None,
                         excess_max_db=max(exs, default=None),
                         as_rendered_max_db=max([r["as_rendered"]["p2_p98_db"] for r in rows], default=None),
                         edge_moved_max_db=max([r["edge_moved"]["p2_p98_db"] for r in rows], default=None),
                         rows=sorted(rows, key=lambda r: -r["excess_db"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temp", required=True, help="--keep-temp directory of the chain render")
    ap.add_argument("--tag", default="sk_final")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    res = dict(test_music=part_a(a.tag, a.temp))
    res.update(part_bc(a.reuse))
    res["edge_ab_test_music"] = part_d(a.tag, a.temp)
    save(f"held_{a.tag}.json", res)
    print(json.dumps({k: v for k, v in res["test_music"].items()}, default=float)[:4000])
    print(json.dumps(res["renderer_summary"], default=float))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "per_key"} for k, v in res["direct_sfizz_control"].items()}))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in res["edge_ab_test_music"].items()}))


if __name__ == "__main__":
    main()
