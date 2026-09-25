#!/usr/bin/env python3
"""End-to-end chain check: perform.py -> render_quartet.py -> every note.

  python3 qa_chain.py [--plan qa/fugue_qa.plan.json] [--score fugue.ly]

1. perform.py SCORE PLAN OUT.mid --target strings; the MIDI contract
   (tracks, names, channels, programs, CC ranges, hanging notes).
2. render_quartet.py OUT.mid --stems --report --keep-temp.
3. For every note of the INPUT MIDI (mido timing, not the renderer's):
   - which render job plays it (the report's note lists; transpositions flagged),
   - pitch at the middle third of the note in the dry job WAV (untrimmed, t=0 =
     MIDI 0), spectral harmonic-peak estimator -> right note (+-50 c) and cents,
   - level at the midpoint (dropped if >30 dB under the job's median),
   - onset: after a rest, the time the level first reaches steady-20 dB and
     steady-6 dB; after another pitch, the time the new pitch overtakes the old
     one (two-hypothesis harmonic score, 50 ms frames, 5 ms hop),
   - release: for notes followed by >= 0.6 s of rest, the time from the key lift
     (input note-off) to -20 / -40 dB, and the level 1.5 s after the lift,
   - stuck: level in every rest >= 1.2 s, from 1.5 s after the lift to the next note.
4. The same notes in the final mix: offset_s from the report applied, mix level
   at each note midpoint with the note's own pitch dominant (spot check).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import (QA, ROOT, SR, TMP, db, env_db, hz, load, midi_cc, midi_notes, perform,  # noqa: E402
                    pitch_spectral, render, save, state)


def harm_score(seg, key, nh=8):
    n = len(seg)
    nfft = max(8192, 1 << int(np.ceil(np.log2(n * 2))))
    X = np.abs(np.fft.rfft(seg * np.hanning(n), nfft))
    L = np.log(X + 1e-12)
    df = SR / nfft
    f0 = hz(key)
    s, c = 0.0, 0
    for k in range(1, nh + 1):
        if k * f0 > SR * 0.45:
            break
        i = int(round(k * f0 / df))
        w = max(1, int(round(k * f0 * 0.02 / df)))            # +-35 cents
        s += L[max(i - w, 0): i + w + 1].max()
        c += 1
    return s / c


def switch_time(x, t_from, t_to, k_old, k_new):
    """First frame centre (s) from which the new pitch's harmonic score beats the old one for 3 frames."""
    per = SR / hz(min(k_old, k_new))
    W = int(max(0.05 * SR, 4 * per))
    hop = int(0.005 * SR)
    run = 0
    first = None
    for c in range(int(t_from * SR), int(t_to * SR), hop):
        a = c - W // 2
        if a < 0 or a + W > len(x):
            continue
        seg = x[a: a + W]
        if harm_score(seg, k_new) > harm_score(seg, k_old):
            run += 1
            if run == 1:
                first = c / SR
            if run >= 3:
                return first
        else:
            run = 0
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, default=QA / "fugue_qa.plan.json")
    ap.add_argument("--score", type=Path, default=ROOT / "fugue.ly")
    ap.add_argument("--name", default="fugue_qa")
    ap.add_argument("--reuse", action="store_true", help="reuse /tmp/sqa renders if present")
    a = ap.parse_args()
    TMP.mkdir(exist_ok=True)
    mid = TMP / f"{a.name}.mid"
    out = TMP / a.name
    res = dict(state=state(), plan=str(a.plan), score=str(a.score))
    res["perform_stdout"] = perform(a.score, a.plan, mid)

    # ---------------------------------------------------------------- contract
    mf = mido.MidiFile(str(mid))
    tracks = []
    for i, tr in enumerate(mf.tracks):
        info = dict(index=i, name=None, channels=set(), program=None, notes=0, cc={})
        for m in tr:
            if m.type == "track_name":
                info["name"] = m.name
            if m.type == "text":
                info["text"] = m.text
            if hasattr(m, "channel"):
                info["channels"].add(m.channel)
            if m.type == "program_change":
                info["program"] = m.program
            if m.type == "note_on" and m.velocity:
                info["notes"] += 1
            if m.type == "control_change":
                c = info["cc"].setdefault(m.control, [127, 0, 0])
                c[0], c[1], c[2] = min(c[0], m.value), max(c[1], m.value), c[2] + 1
        info["channels"] = sorted(info["channels"])
        tracks.append(info)
    mn = midi_notes(mid)
    ccs = midi_cc(mid)
    res["midi"] = dict(type=mf.type, tpb=mf.ticks_per_beat, length_s=mf.length, tracks=tracks,
                       hanging_note_ons=mn["hanging"])
    names = {t["channels"][0]: t["name"] for t in tracks if t["channels"]}
    # CC1 == CC11 everywhere (perform.py sends the same value)?
    same = all([v for _, v in ccs[ch].get(1, [])] == [v for _, v in ccs[ch].get(11, [])] for ch in ccs)
    res["midi"]["cc1_equals_cc11"] = same

    # ------------------------------------------------------------------ render
    rep = render(mid, out, keep_temp=True)
    tmp = Path(rep["temp"])
    res["render_stdout"] = rep["stdout"]
    off = rep["offset_s"]
    jobs = rep["jobs"]
    jw = {}
    for i, j in enumerate(jobs):
        jw[i] = load(tmp / f"j{i}_{j['inst']}.wav")

    # renderer timing vs mido timing: match every input note to a job note
    by_label = {j["label"]: i for i, j in enumerate(jobs)}
    rows = []
    tdiff = []
    for ch, notes in mn["notes"].items():
        vname = names[ch]
        for n in notes:
            hit = None
            for i, j in enumerate(jobs):
                if not (j["label"] == vname or j["label"].startswith(vname + " on ")):
                    continue
                for on, of, key, vel, art in j["note_list"]:
                    if abs(on - n["on"]) < 0.004 and (key - n["key"]) % 12 == 0:
                        hit = (i, on, of, key, vel, art)
                        break
                if hit:
                    break
            r = dict(voice=vname, on=n["on"], off=n["off"], key=n["key"], vel=n["vel"])
            if hit is None:
                r["job"] = None
            else:
                i, on, of, key, vel, art = hit
                tdiff.append(on - n["on"])
                r.update(job=i, inst=jobs[i]["inst"], rkey=key, roff=of, art=art)
            rows.append(r)
    res["timing_renderer_vs_mido_ms"] = dict(max_abs=round(1000 * float(np.max(np.abs(tdiff))), 3),
                                             n=len(tdiff))
    res["notes_in_midi"] = len(rows)
    res["notes_without_job"] = [r for r in rows if r.get("job") is None]
    res["transposed"] = [dict(voice=r["voice"], on=round(r["on"], 3), key=r["key"], rendered=r["rkey"])
                         for r in rows if r.get("job") is not None and r["rkey"] != r["key"]]

    # ------------------------------------------------------------ per note
    envs = {i: env_db(x, 0.01, 0.002) for i, x in jw.items()}
    per_job = defaultdict(list)
    for r in rows:
        if r.get("job") is not None:
            per_job[r["job"]].append(r)
    for i, lst in per_job.items():
        lst.sort(key=lambda r: r["on"])
        e, hop = envs[i]
        fr = SR / hop
        act = e[e > e.max() - 60]
        med = float(np.median(act))
        x = jw[i]
        for k, r in enumerate(lst):
            prev = lst[k - 1] if k else None
            on, of = r["on"], r["off"]
            dur = of - on
            m0, m1 = on + dur / 3, of - dur / 3
            if m1 - m0 < 0.06:
                c = (on + of) / 2
                m0, m1 = c - 0.03, c + 0.03
            seg = x[int(m0 * SR): int(m1 * SR)]
            est, hnr = pitch_spectral(seg, r["rkey"])
            r["cents"] = round(100 * (est - r["rkey"]), 1)
            r["mid_level_db_re_job"] = round(db(seg) - med, 1)
            r["mid_seg_s"] = round(m1 - m0, 3)
            # onset
            after_rest = prev is None or on - prev["off"] > 0.25
            if after_rest:
                steady = float(np.median(e[int((on + 0.3 * dur) * fr): max(int((on + 0.3 * dur) * fr) + 1,
                                                                            int((of - 0.1 * dur) * fr))]))
                seg_e = e[int((on - 0.1) * fr): int((on + min(dur, 0.4)) * fr)]
                t0 = on - 0.1
                i20 = np.flatnonzero(seg_e >= steady - 20)
                i6 = np.flatnonzero(seg_e >= steady - 6)
                r["onset_kind"] = "after_rest"
                r["t20_ms"] = round(1000 * (t0 + i20[0] / fr - on), 1) if len(i20) else None
                r["t6_ms"] = round(1000 * (t0 + i6[0] / fr - on), 1) if len(i6) else None
            elif prev["key"] != r["key"]:
                ts = switch_time(x, on - 0.08, min(of, on + 0.25), prev["rkey"], r["rkey"])
                r["onset_kind"] = "pitch_change"
                r["switch_ms"] = None if ts is None else round(1000 * (ts - on), 1)
            else:
                # repeated pitch: dip then re-attack
                lo = int((prev["off"] - 0.03) * fr)
                hi = int((on + 0.06) * fr)
                dmin = int(np.argmin(e[lo:hi])) + lo
                steady = float(np.median(e[int((on + 0.3 * dur) * fr): max(int((on + 0.3 * dur) * fr) + 1,
                                                                            int((of - 0.1 * dur) * fr))]))
                r["onset_kind"] = "repeat"
                r["dip_db"] = round(steady - float(e[dmin]), 1)
                i6 = np.flatnonzero(e[dmin: dmin + int(0.3 * fr)] >= steady - 6)
                r["t6_ms"] = round(1000 * ((dmin + i6[0]) / fr - on), 1) if len(i6) else None
            # release into a rest
            nxt = lst[k + 1] if k + 1 < len(lst) else None
            gap = (nxt["on"] - of) if nxt else 99.0
            if gap >= 0.6:
                lvl = float(np.max(e[int((of - 0.06) * fr): int((of - 0.01) * fr)]))
                tail = e[int(of * fr): int((of + min(gap, 3.0)) * fr)]
                i20 = np.flatnonzero(tail <= lvl - 20)
                i40 = np.flatnonzero(tail <= lvl - 40)
                r["release"] = dict(gap_s=round(min(gap, 99), 2), key_lift_to_minus20_ms=
                                    round(1000 * i20[0] / fr, 1) if len(i20) else None,
                                    key_lift_to_minus40_ms=round(1000 * i40[0] / fr, 1) if len(i40) else None,
                                    renderer_off_minus_key_lift_ms=round(1000 * (r["roff"] - of), 1))
                if gap >= 1.2:
                    st = e[int((of + 1.5) * fr): int((min(of + gap, len(x) / SR) - 0.05) * fr)]
                    if len(st):
                        r["release"]["rest_level_db_re_job"] = round(float(st.max()) - med, 1)

    # ------------------------------------------------------------ summaries
    ok = [r for r in rows if r.get("job") is not None]
    wrong = [r for r in ok if abs(r["cents"]) > 50]
    quiet = [r for r in ok if r["mid_level_db_re_job"] < -30]
    long_ = [r for r in ok if r["mid_seg_s"] >= 0.25 and r["mid_level_db_re_job"] > -30]
    cents_by_inst = defaultdict(list)
    for r in long_:
        cents_by_inst[r["inst"]].append(r["cents"])
    res["pitch"] = dict(
        notes=len(ok), wrong_note_over_50c=[{k: r[k] for k in ("voice", "on", "key", "rkey", "cents")} for r in wrong],
        long_notes_cents={i: dict(n=len(v), median=round(float(np.median(v)), 1),
                                  median_abs=round(float(np.median(np.abs(v))), 1),
                                  p95_abs=round(float(np.percentile(np.abs(v), 95)), 1),
                                  max_abs=round(float(np.max(np.abs(v))), 1)) for i, v in cents_by_inst.items()},
        worst_long=sorted(({k: r[k] for k in ("voice", "on", "key", "cents", "mid_seg_s")} for r in long_),
                          key=lambda d: -abs(d["cents"]))[:8])
    res["dropped_or_inaudible"] = [{k: r[k] for k in ("voice", "on", "key", "mid_level_db_re_job")} for r in quiet]

    def dist(v):
        v = [x for x in v if x is not None]
        if not v:
            return None
        v = np.array(v)
        return dict(n=len(v), median=round(float(np.median(v)), 1), p10=round(float(np.percentile(v, 10)), 1),
                    p90=round(float(np.percentile(v, 90)), 1), min=round(float(v.min()), 1),
                    max=round(float(v.max()), 1), share_within_20ms=round(float(np.mean(np.abs(v) <= 20)), 3))
    ons = {}
    for kind in ("after_rest", "pitch_change", "repeat"):
        for art_name, rng in (("normal", (0, 63)), ("legato", (64, 95)), ("short", (96, 127))):
            sel = [r for r in ok if r.get("onset_kind") == kind and r["art"] is not None
                   and rng[0] <= r["art"] <= rng[1]]
            if not sel:
                continue
            d = {}
            if kind == "after_rest":
                d["t20_ms"] = dist([r["t20_ms"] for r in sel])
                d["t6_ms"] = dist([r["t6_ms"] for r in sel])
                d["vel_median"] = float(np.median([r["vel"] for r in sel]))
            elif kind == "pitch_change":
                d["switch_ms"] = dist([r["switch_ms"] for r in sel])
                d["no_switch_found"] = sum(r["switch_ms"] is None for r in sel)
            else:
                d["t6_ms"] = dist([r["t6_ms"] for r in sel])
                d["dip_db"] = dist([r["dip_db"] for r in sel])
            ons[f"{kind}/{art_name}"] = d
    res["onsets"] = ons
    res["onset_late_examples"] = sorted(
        ({k: r.get(k) for k in ("voice", "on", "key", "vel", "art", "onset_kind", "t20_ms", "t6_ms", "switch_ms")}
         for r in ok if (r.get("t20_ms") or 0) > 40 or (r.get("switch_ms") or 0) > 60),
        key=lambda d: -max(d.get("t20_ms") or 0, d.get("switch_ms") or 0))[:12]
    rel = [r["release"] for r in ok if "release" in r]
    res["releases"] = dict(
        n=len(rel), key_lift_to_minus20_ms=dist([x["key_lift_to_minus20_ms"] for x in rel]),
        key_lift_to_minus40_ms=dist([x["key_lift_to_minus40_ms"] for x in rel]),
        never_reached_minus40=sum(x["key_lift_to_minus40_ms"] is None for x in rel),
        renderer_off_minus_key_lift_ms=dist([x["renderer_off_minus_key_lift_ms"] for x in rel]),
        rest_level_db_re_job=dist([x.get("rest_level_db_re_job") for x in rel]))
    res["stuck_suspects"] = [dict(voice=r["voice"], off=round(r["off"], 2), **r["release"]) for r in ok
                             if "release" in r and (r["release"].get("rest_level_db_re_job") or -99) > -45]

    # ------------------------------------------------------------ final mix
    mix = load(Path(str(out) + ".wav"))
    mix_st = load(Path(str(out) + ".wav"), mono=False)
    mix_rows = []
    for r in ok:
        if r["mid_seg_s"] < 0.2:
            continue
        on, of = r["on"] - off, r["off"] - off
        seg = mix[int((on + (of - on) / 3) * SR): int((of - (of - on) / 3) * SR)]
        mix_rows.append(harm_score(seg, r["rkey"]) - max(harm_score(seg, r["rkey"] + 1),
                                                          harm_score(seg, r["rkey"] - 1)))
    res["mix"] = dict(duration_s=len(mix) / SR, offset_s=off, channels=mix_st.shape[1],
                      notes_checked=len(mix_rows),
                      own_pitch_beats_semitone_neighbours=round(float(np.mean(np.array(mix_rows) > 0)), 3))
    res["rows"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]
    p = save(f"chain_{a.name}.json", res)
    short = {k: v for k, v in res.items() if k not in ("rows", "perform_stdout", "render_stdout")}
    print(json.dumps(short, indent=1, default=str)[:12000])
    print("->", p)


if __name__ == "__main__":
    main()
