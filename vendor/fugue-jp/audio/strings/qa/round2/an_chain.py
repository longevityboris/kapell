#!/usr/bin/env python3
"""Round-2 chain check: perform.py -> render_quartet.py, every note of the MIDI.

  python3 an_chain.py [--plan demo/fugue_plan.json] [--score fugue.ly] [--reuse REPORT.json --mid X.mid]

For every note of the perform.py MIDI (mido timing, not the renderer's):
  * accounting: exactly one render job plays it, same key (borrowed / transposed flagged);
  * onset (dry job WAV, MIDI time): the note's own partials (those not shared with the
    neighbouring note) rise to -6 dB (and -20 dB after a rest) of their level in the
    note; detector validated on planted notes with a known start;
  * the previous note's partials fall to -6 dB (slur hand-over);
  * repeated key: depth of the dip between the strokes;
  * pitch (notes >= 0.25 s, middle of the note): frame-harmonic and YIN estimators,
    octave check;
  * release: notes before a rest >= 0.5 s: -3 / -20 / -40 dB times after the key lift;
  * stuck: level in every rest >= 1.2 s from 1.5 s after the lift, and after the last note;
  * final file: the default (lead-in) render against the keep-start render (offset and
    identity), m4a alignment.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import (ROOT, SR, STRINGS, TMP, Spec, cents, db, hz, job_wavs, midi_voices, octave_check,  # noqa: E402
                    pct, perform, pitch_fft, pitch_switch, pitch_yin, render, rms_env, save)


def onset_times(B, T, on, off, ref_win=0.3, thr=(6.0, 20.0), search=(-0.10, 0.20)):
    """First frame time (re on) where band level B reaches ref - thr, ref = 75th pct inside the note."""
    dur = off - on
    m = (T >= on + 0.015) & (T <= on + max(0.03, min(dur, ref_win)))
    if not m.any():
        return None, {}
    ref = float(np.percentile(B[m], 75))
    s = (T >= on + search[0]) & (T <= on + search[1])
    idx = np.flatnonzero(s)
    out = {}
    pre = float(B[idx[0]] - ref) if len(idx) else None
    for th in thr:
        hit = idx[B[idx] >= ref - th]
        out[th] = None if (len(hit) == 0 or hit[0] == idx[0]) else float(T[hit[0]] - on)
    return ref, dict(out, pre=pre)


def fall_time(B, T, t_from, ref, th=6.0, span=0.4):
    s = (T >= t_from - 0.1) & (T <= t_from + span)
    idx = np.flatnonzero(s)
    hit = idx[B[idx] <= ref - th]
    return None if len(hit) == 0 else float(T[hit[0]] - t_from)


def validate_detector():
    """Planted notes: harmonic tones with 5-30 ms fades at known times -> detector error (ms)."""
    rng = np.random.default_rng(1)
    x = np.zeros(int(6 * SR))
    plan = []
    t0 = 0.5
    keys = [60, 64, 62, 67, 36, 43, 88, 84]
    for i, k in enumerate(keys):
        dur = [0.4, 0.12, 0.25, 0.6][i % 4]
        fade = [0.005, 0.03, 0.015, 0.03][i % 4]
        n = int(dur * SR)
        t = np.arange(n) / SR
        y = sum(np.sin(2 * np.pi * h * hz(k) * t + rng.uniform(0, 6)) / h for h in range(1, 7))
        y *= np.minimum(1, t / fade) * np.exp(-np.maximum(0, t - dur + 0.05) / 0.02)
        a = int(t0 * SR)
        x[a: a + n] += 0.1 * y
        plan.append((t0, t0 + dur, k))
        t0 += dur if i % 2 == 0 else dur + 0.3
    res = []
    for win in (0.05, 0.08):
        sp = Spec(x, win=win)
        for i, (on, off, k) in enumerate(plan):
            prev = plan[i - 1][2] if i else None
            B = sp.band_energy(k, exclude_keys=[prev] if prev else [])
            ref, o = onset_times(B, sp.t, on, off)
            res.append(dict(win=win, key=k, err6_ms=None if o.get(6.0) is None else 1000 * o[6.0],
                            err20_ms=None if o.get(20.0) is None else 1000 * o[20.0]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", default=str(ROOT / "fugue.ly"))
    ap.add_argument("--plan", default=str(STRINGS / "demo" / "fugue_plan.json"))
    ap.add_argument("--reuse", help="existing --keep-start --keep-temp report (with 'temp' key added)")
    ap.add_argument("--mid")
    ap.add_argument("--tag", default="fugue")
    ap.add_argument("--target", default="strings", help="perform.py --target (piano: no CC1, dynamics from velocity)")
    ap.add_argument("--extra", nargs="*", default=[], help="extra render_quartet.py options")
    a = ap.parse_args()
    TMP.mkdir(exist_ok=True)
    out = TMP / f"chain_{a.tag}"
    mid = Path(a.mid) if a.mid else TMP / f"chain_{a.tag}.mid"
    if a.reuse:
        rep = json.loads(Path(a.reuse).read_text())
    else:
        perform(a.score, a.plan, mid, target=a.target)
        rep = render(mid, out, "--keep-start", *a.extra)
    val = validate_detector()
    midi = midi_voices(mid)
    jobs = job_wavs(rep)

    # ---- accounting: every MIDI note -> exactly one job note (on within 1 ms, key equal or octave-shifted)
    job_notes = []
    for ji, (j, _) in enumerate(jobs):
        for k, (on, off, key, vel, art) in enumerate(j["note_list"]):
            job_notes.append(dict(ji=ji, idx=k, on=on, off=off, key=key, art=art, pre=j["pre_ms"][k] / 1000))
    by_on = defaultdict(list)
    for jn in job_notes:
        by_on[round(jn["on"], 2)].append(jn)
    acct = dict(midi_notes=0, matched=0, missing=[], multiple=[], transposed=[], hanging=[], borrowed=0)
    note_rows = []
    used = set()
    for ch, v in sorted(midi.items()):
        for n in v["notes"]:
            acct["midi_notes"] += 1
            if n.get("hanging"):
                acct["hanging"].append((v["name"], n["key"], n["on"]))
                continue
            cands = [jn for d in (-0.01, 0.0, 0.01) for jn in by_on.get(round(n["on"] + d, 2), [])
                     if abs(jn["on"] - n["on"]) < 1e-3 and (jn["key"] - n["key"]) % 12 == 0
                     and (jn["ji"], jn["idx"]) not in used]
            cands = list({(c["ji"], c["idx"]): c for c in cands}.values())
            exact = [c for c in cands if c["key"] == n["key"]]
            pick = (exact or cands)
            if not pick:
                acct["missing"].append((v["name"], n["key"], round(n["on"], 3)))
                continue
            c = pick[0]
            used.add((c["ji"], c["idx"]))
            acct["matched"] += 1
            if c["key"] != n["key"]:
                acct["transposed"].append((v["name"], n["key"], c["key"], round(n["on"], 3)))
            if jobs[c["ji"]][0]["kind"] == "borrowed":
                acct["borrowed"] += 1
            note_rows.append(dict(voice=v["name"], ji=c["ji"], on=n["on"], off=n["off"], key=n["key"], rkey=c["key"],
                                  vel=n["vel"], art=c["art"], pre=c["pre"]))
    acct["job_notes_unmatched"] = len(job_notes) - len(used)

    # ---- per job analysis
    rows_by_job = defaultdict(list)
    for r in note_rows:
        rows_by_job[r["ji"]].append(r)
    notes_out = []
    stuck = []
    releases = []
    for ji, (j, x) in enumerate(jobs):
        rows = sorted(rows_by_job[ji], key=lambda r: r["on"])
        if not rows:            # e.g. the --bass-double job: its notes are the cello's, accounted to the cello job
            continue
        win = 0.08 if j["inst"] in ("vc", "cb") else 0.05
        sp = Spec(x, win=win)
        Te, E = rms_env(x, 0.01, 0.002)
        act = np.concatenate([E[(Te >= r["on"] + 0.05) & (Te <= r["off"])] for r in rows if r["off"] - r["on"] > 0.06])
        act_med = float(np.median(act))
        for i, r in enumerate(rows):
            prev = rows[i - 1] if i else None
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            gap = r["on"] - prev["off"] if prev else 99.0
            cls = "after_rest" if gap >= 0.1 else ("repeat" if prev["rkey"] == r["rkey"] else "change")
            excl = [prev["rkey"]] if (prev and gap < 1.2 and prev["rkey"] != r["rkey"]) else []
            if nxt is not None and nxt["on"] - r["on"] < 0.35 and nxt["rkey"] != r["rkey"]:
                excl.append(nxt["rkey"])
            B = sp.band_energy(r["rkey"], exclude_keys=excl)
            row = dict(voice=r["voice"], job=j["label"], key=r["key"], on=round(r["on"], 3), dur=round(r["off"] - r["on"], 3),
                       cls=cls, art=r["art"], vel=r["vel"])
            if B is not None:
                ref, o = onset_times(B, sp.t, r["on"], r["off"], ref_win=0.3 if cls == "after_rest" else 0.12)
                if cls == "change" and o.get("pre") is not None and o["pre"] > -10:
                    o[6.0] = None                        # the new partials leak from the neighbour: no clean onset
                    row["ambiguous"] = True
                row.update(on6_ms=None if o.get(6.0) is None else round(1000 * o[6.0], 1),
                           on20_ms=None if o.get(20.0) is None else round(1000 * o[20.0], 1),
                           pre_db=None if o.get("pre") is None else round(o["pre"], 1),
                           level_db=round(ref, 1))
                # the note's level re the job's active median (dropped notes)
                m = (Te >= r["on"] + 0.03) & (Te <= max(r["on"] + 0.05, r["off"]))
                row["rms_re_job_db"] = round(float(np.max(E[m]) - act_med), 1) if m.any() else None
            if cls == "change" and prev is not None:
                sw = pitch_switch(x, r["on"], prev["rkey"], r["rkey"])
                row["switch_ms"] = None if sw is None else round(1000 * sw, 1)
                Bo = sp.band_energy(prev["rkey"], exclude_keys=[r["rkey"]])
                if Bo is not None:
                    mo = (sp.t >= prev["on"] + 0.015) & (sp.t <= max(prev["on"] + 0.03, min(prev["off"], r["on"] - 0.03)))
                    if mo.any():
                        refo = float(np.percentile(Bo[mo], 75))
                        ft = fall_time(Bo, sp.t, r["on"], refo)
                        row["old_fall6_ms"] = None if ft is None else round(1000 * ft, 1)
            if cls == "repeat":
                m = (Te >= r["on"] - 0.1) & (Te <= r["on"] + 0.06)
                m_in = (Te >= prev["on"] + 0.05) & (Te <= prev["off"] - 0.02)
                if m.any() and m_in.any():
                    Lin = float(np.median(E[m_in]))
                    row["dip_db"] = round(Lin - float(E[m].min()), 1)
                    k = np.flatnonzero(m)[int(np.argmin(E[m]))]
                    back = np.flatnonzero((Te > Te[k]) & (Te <= r["on"] + 0.3) & (E >= Lin - 3))
                    row["dip_at_ms"] = round(1000 * (Te[k] - r["on"]), 1)
                    row["recover3_ms"] = None if len(back) == 0 else round(1000 * (Te[back[0]] - r["on"]), 1)
            dur = r["off"] - r["on"]
            if dur >= 0.25:
                a0, b0 = r["on"] + max(0.08, 0.25 * dur), r["off"] - 0.2 * dur
                if b0 - a0 >= 0.12:
                    seg = x[int(a0 * SR): int(b0 * SR)]
                    row["c_fft"] = cents(pitch_fft(seg, r["rkey"]), r["rkey"])
                    row["c_yin"] = cents(pitch_yin(seg, r["rkey"]), r["rkey"])
                    oc = octave_check(seg, r["rkey"])
                    row["sub_db"], row["odd_db"] = round(oc["sub_db"], 1), round(oc["odd_db"], 1)
            # release before a rest (or the last note)
            if nxt is None or nxt["on"] - r["off"] >= 0.5:
                lim = nxt["on"] if nxt else len(x) / SR
                m0 = (Te >= r["off"] - 0.12) & (Te <= r["off"] - 0.02)
                if m0.any():
                    L0 = float(np.median(E[m0]))
                    rel = {}
                    for th in (3, 20, 40):
                        s = np.flatnonzero((Te >= r["off"] - 0.2) & (Te <= lim) & (E <= L0 - th))
                        rel[th] = None if len(s) == 0 else round(1000 * (Te[s[0]] - r["off"]), 1)
                    mm = (Te >= r["off"] + 0.9) & (Te <= r["off"] + 1.1)
                    releases.append(dict(voice=r["voice"], job=j["label"], key=r["key"], off=round(r["off"], 3),
                                         dur=round(dur, 3), t3_ms=rel[3], t20_ms=rel[20], t40_ms=rel[40],
                                         at1s_db=round(float(np.median(E[mm]) - L0), 1) if mm.any() and r["off"] + 1.1 < lim else None))
                # stuck: level from 1.5 s after the lift
                if lim - r["off"] >= 1.2 + (0.3 if nxt else 0):
                    m = (Te >= r["off"] + 1.5) & (Te <= lim - 0.1)
                    if m.any():
                        stuck.append(dict(job=j["label"], after_key=r["key"], t=round(r["off"], 2), rest_s=round(lim - r["off"], 2),
                                          max_db_re_active=round(float(E[m].max() - act_med), 1)))
            notes_out.append(row)

    # ---- summaries
    def summ(sel, key):
        v = [r[key] for r in notes_out if sel(r) and r.get(key) is not None]
        if not v:
            return None
        v = np.array(v)
        return dict(n=len(v), median=round(float(np.median(v)), 1), p10=round(float(np.percentile(v, 10)), 1),
                    p90=round(float(np.percentile(v, 90)), 1), min=round(float(v.min()), 1), max=round(float(v.max()), 1),
                    within20=round(float(np.mean(np.abs(v) <= 20)), 3))
    onsets = {}
    for cls in ("after_rest", "change", "repeat"):
        for art in ("short", "legato", "normal"):
            def sel(r, cls=cls, art=art):
                a_ = r["art"] or 0
                return r["cls"] == cls and (art == ("short" if a_ >= 96 else "legato" if a_ >= 64 else "normal"))
            s6 = summ(sel, "on6_ms")
            if s6:
                onsets[f"{cls}/{art}"] = dict(switch=summ(sel, "switch_ms") if cls == "change" else None,
                                              switch_missing=sum(1 for r in notes_out if sel(r) and r.get("switch_ms") is None)
                                              if cls == "change" else None,on6=s6, on20=summ(sel, "on20_ms") if cls == "after_rest" else None,
                                              old_fall6=summ(sel, "old_fall6_ms") if cls == "change" else None)
    undetected = [r for r in notes_out if r.get("on6_ms") is None and r["cls"] != "repeat" and not r.get("ambiguous")]
    reps = [r for r in notes_out if r["cls"] == "repeat" and r.get("dip_db") is not None]
    repeat = dict(n=len(reps), dip_db_median=pct([r["dip_db"] for r in reps], 50), dip_db_min=pct([r["dip_db"] for r in reps], 0),
                  dip_db_max=pct([r["dip_db"] for r in reps], 100), dip_at_ms_median=pct([r["dip_at_ms"] for r in reps], 50),
                  recover3_ms_median=pct([r["recover3_ms"] for r in reps], 50), recover3_ms_p90=pct([r["recover3_ms"] for r in reps], 90),
                  not_recovered=sum(1 for r in reps if r["recover3_ms"] is None))
    n_ambiguous = sum(1 for r in notes_out if r.get("ambiguous"))
    late = sorted([r for r in notes_out if r.get("on6_ms") is not None and abs(r["on6_ms"]) > 20],
                  key=lambda r: -abs(r["on6_ms"]))
    pitch = {}
    for inst in sorted({r["job"] for r in notes_out}):
        c1 = [r["c_fft"] for r in notes_out if r["job"] == inst and r.get("c_fft") is not None]
        c2 = [r["c_yin"] for r in notes_out if r["job"] == inst and r.get("c_yin") is not None]
        both = [0.5 * (r["c_fft"] + r["c_yin"]) for r in notes_out if r["job"] == inst and r.get("c_fft") is not None
                and r.get("c_yin") is not None]
        if not c1:
            continue
        pitch[inst] = dict(n=len(c1), fft_median_abs=round(float(np.median(np.abs(c1))), 2),
                           fft_p95_abs=round(float(np.percentile(np.abs(c1), 95)), 2),
                           yin_median_abs=round(float(np.median(np.abs(c2))), 2) if c2 else None,
                           yin_p95_abs=round(float(np.percentile(np.abs(c2), 95)), 2) if c2 else None,
                           mean_signed=round(float(np.mean(both)), 2) if both else None,
                           over5=int(np.sum(np.abs(both) > 5)), over10=int(np.sum(np.abs(both) > 10)),
                           over25=int(np.sum(np.abs(both) > 25)),
                           estimator_disagree_gt5=int(sum(1 for r in notes_out if r["job"] == inst and r.get("c_fft") is not None
                                                          and r.get("c_yin") is not None and abs(r["c_fft"] - r["c_yin"]) > 5)))
    worst_pitch = sorted([r for r in notes_out if r.get("c_fft") is not None and r.get("c_yin") is not None],
                         key=lambda r: -abs(r["c_fft"] + r["c_yin"]))[:15]
    octave_flags = [r for r in notes_out if r.get("sub_db") is not None and (r["sub_db"] > -12 or r["odd_db"] < -15)]
    dropped = [r for r in notes_out if r.get("rms_re_job_db") is not None and r["rms_re_job_db"] < -30]
    lev = {}
    for ji, (j, x) in enumerate(jobs):
        te, e = rms_env(x, 0.4, 0.2)
        e = e[e > -90]
        if len(e):
            lev[j["label"]] = dict(p5_db=round(float(np.percentile(e, 5)), 1), p95_db=round(float(np.percentile(e, 95)), 1),
                                   range_db=round(float(np.percentile(e, 95) - np.percentile(e, 5)), 1))
    res = dict(target=a.target, extra=a.extra, log=rep.get("notes"), level_range_400ms=lev, validation=val, accounting=acct, onsets=onsets, repeat=repeat, n_ambiguous_change=n_ambiguous,
               n_notes=len(notes_out),
               undetected=[{k: r.get(k) for k in ("voice", "key", "on", "dur", "cls", "pre_db")} for r in undetected],
               late_gt20=[{k: r.get(k) for k in ("voice", "key", "on", "dur", "cls", "art", "vel", "on6_ms", "pre_db")}
                          for r in late[:40]], n_late_gt20=len(late),
               pitch=pitch, worst_pitch=[{k: r.get(k) for k in ("voice", "job", "key", "on", "dur", "c_fft", "c_yin")}
                                         for r in worst_pitch],
               octave_flags=[{k: r.get(k) for k in ("voice", "key", "on", "sub_db", "odd_db")} for r in octave_flags],
               dropped=dropped,
               releases=dict(n=len(releases), t3_ms=pct([r["t3_ms"] for r in releases], 50),
                             t3_min_ms=min([r["t3_ms"] for r in releases if r["t3_ms"] is not None], default=None),
                             t20_ms_median=pct([r["t20_ms"] for r in releases], 50),
                             t20_ms_max=max([r["t20_ms"] for r in releases if r["t20_ms"] is not None], default=None),
                             t40_ms_median=pct([r["t40_ms"] for r in releases], 50),
                             t40_ms_max=max([r["t40_ms"] for r in releases if r["t40_ms"] is not None], default=None),
                             at1s_db_max=max([r["at1s_db"] for r in releases if r["at1s_db"] is not None], default=None),
                             early=[r for r in releases if r["t3_ms"] is not None and r["t3_ms"] < -30],
                             rows=releases),
               stuck=dict(n=len(stuck), worst_db=max([s["max_db_re_active"] for s in stuck], default=None), rows=stuck),
               notes=notes_out)
    save(f"chain_{a.tag}.json", res)
    print(json.dumps({k: res[k] for k in ("accounting", "onsets", "repeat", "n_ambiguous_change", "n_late_gt20", "pitch")},
                     default=float))
    print("undetected", len(undetected), "octave flags", len(octave_flags), "dropped", len(dropped))
    print("releases", {k: v for k, v in res["releases"].items() if k not in ("rows",)})
    print("stuck", res["stuck"]["n"], res["stuck"]["worst_db"])
    print("validation", [(v["win"], v["key"], v["err6_ms"], v["err20_ms"]) for v in val])


if __name__ == "__main__":
    main()
