#!/usr/bin/env python3
"""Render variants of the QA fugue.

  python3 qa_variants.py

 piano_target   perform.py --target piano (no CC1/CC11: dynamics from velocities,
                render_quartet's ensure_cc1 path): renders, level range pp -> ff,
                every note present (pitch at mid-note in the dry job WAVs)
 bass_double    --bass-double on and auto: the contrabass stem plays the cello's
                notes exactly an octave lower (pitch at mid-note), auto only where
                the cello is at or above ff
 voicing        the QA fugue plan with and without "role_level": in every "roles"
                window, the marked voice's K-weighted stem level re the power sum of
                the other three (dB), and the difference the marking makes
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import QA, ROOT, SR, TMP, db, k_weight, load, midi_notes, perform, pitch_spectral, render, save, state  # noqa


def piano_target(res):
    mid = TMP / "fugue_qa_piano.mid"
    perform(ROOT / "fugue.ly", QA / "fugue_qa.plan.json", mid, target="piano")
    rep = render(mid, TMP / "fugue_qa_piano", keep_temp=True)
    tmp = Path(rep["temp"])
    wrong, n = [], 0
    for i, j in enumerate(rep["jobs"]):
        x = load(tmp / f"j{i}_{j['inst']}.wav")
        for on, of, key, vel, art in j["note_list"]:
            d = of - on
            seg = x[int((on + d / 3) * SR): int((of - d / 3) * SR)] if d > 0.2 else x[int((on + d / 2 - 0.03) * SR): int((on + d / 2 + 0.03) * SR)]
            m, _ = pitch_spectral(seg, key, span=13)
            n += 1
            if abs(m - key) > 0.5:
                wrong.append((j["label"], round(on, 2), key, round(100 * (m - key))))
    mix = load(TMP / "fugue_qa_piano.wav")
    kx = k_weight(mix)
    w = int(10 * SR)
    lv = [db(kx[i:i + w]) for i in range(0, len(kx) - w, SR)]
    res["piano_target"] = dict(log=rep["notes"], notes=n, wrong_pitch=wrong[:20], n_wrong=len(wrong),
                               first_10s_k_db=round(lv[0], 1), loudest_10s_k_db=round(max(lv), 1),
                               range_db=round(max(lv) - lv[0], 1),
                               cc1_derived={k: (min(v for _, v in e), max(v for _, v in e)) for k, e in rep["cc1"].items()})
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("piano_target", {k: v for k, v in res["piano_target"].items() if k != "wrong_pitch"})


def bass_double(res):
    mid = TMP / "fugue_qa.mid"
    out = {}
    for mode in ("on", "auto"):
        rep = render(mid, TMP / f"fugue_qa_bass_{mode}", "--bass-double", mode, keep_temp=True)
        tmp = Path(rep["temp"])
        ji = next(i for i, j in enumerate(rep["jobs"]) if j["kind"] == "double")
        jb = rep["jobs"][ji]
        x = load(tmp / f"j{ji}_cb.wav")
        stem = load(TMP / f"fugue_qa_bass_{mode}_stem_cb.wav")
        vc_notes = sorted(n for j in rep["jobs"] if j["inst"] == "vc" for n in j["note_list"])
        errs = []
        for on, of, key, vel, art in jb["note_list"]:
            if of - on < 0.3:
                continue
            seg = x[int((on + (of - on) / 3) * SR): int((of - (of - on) / 3) * SR)]
            m, _ = pitch_spectral(seg, key - 12, span=13)
            errs.append(100 * (m - (key - 12)))
        errs = np.array(errs)
        # where does the doubling sound (auto)?  stem level per 5 s vs the cello's CC1 there
        hop = int(5 * SR)
        lv = [round(db(stem[i:i + hop]), 1) for i in range(0, len(stem) - hop, hop)]
        out[mode] = dict(double_notes=jb["notes"], cello_notes=len(vc_notes),
                         pitch_cents_median_abs=round(float(np.median(np.abs(errs))), 1),
                         wrong_octave_or_note=int(np.sum(np.abs(errs) > 50)), checked=len(errs),
                         lowest_key=min(n[2] for n in jb["note_list"]) - 12, cb_stem_db_per_5s=lv, log=rep["notes"])
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    rep = json.loads((TMP / "fugue_qa.json").read_text())
    cc = rep["cc1"].get("vc", [])
    out["cello_cc1_max"] = max(v for _, v in cc)
    out["cello_cc1_at_or_above_ff_114_s"] = [t for t, v in cc if v >= 114][:3] + ["..."] + [t for t, v in cc if v >= 114][-3:]
    res["bass_double"] = out
    print("bass_double", {m: {k: v for k, v in out[m].items() if k != "cb_stem_db_per_5s"} for m in ("on", "auto")})
    print("  auto cb level per 5 s:", out["auto"]["cb_stem_db_per_5s"])


def voicing(res):
    plan = json.loads((QA / "fugue_qa.plan.json").read_text())
    flat = dict(plan)
    flat.pop("role_level", None)
    fp = TMP / "fugue_qa_norole.plan.json"
    fp.write_text(json.dumps(flat))
    mid = TMP / "fugue_qa_norole.mid"
    perform(ROOT / "fugue.ly", fp, mid)
    render(mid, TMP / "fugue_qa_norole")
    measure = int(plan.get("measure", "1"))
    names = {"soprano": "vn1", "alto": "vn2", "tenor": "va", "pedal": "vc"}
    bar_t = {}
    # bar start times from the perform.py MIDI via the first notes' grid: use mido tempo map
    import mido
    mf = mido.MidiFile(str(TMP / "fugue_qa.mid"))
    tempos, t = [], 0
    for m in mf.tracks[0]:
        t += m.time
        if m.type == "set_tempo":
            tempos.append((t, m.tempo))

    def tick2s(tick):
        s, lt, tp = 0.0, 0, 500000
        for tt, tq in tempos:
            if tt > tick:
                break
            s += (tt - lt) * tp / 1e6 / mf.ticks_per_beat
            lt, tp = tt, tq
        return s + (tick - lt) * tp / 1e6 / mf.ticks_per_beat

    def pos(s_):
        b, beat = s_.split(":")
        return tick2s(int(((int(b) - 1) * 4 * measure + (float(beat) - 1)) * mf.ticks_per_beat))
    out = []
    for label, base in (("role_level", TMP / "fugue_qa"), ("no_role_level", TMP / "fugue_qa_norole")):
        rep = json.loads(Path(str(base) + ".json").read_text())
        off = rep["offset_s"]
        st = {i: k_weight(load(Path(f"{base}_stem_{i}.wav"))) for i in names.values()}
        for r in plan["roles"]:
            a, b = pos(r["at"]) - off, pos(r["until"]) - off
            i0, i1 = int(a * SR), int(b * SR)
            me = names[r["voice"]]
            lv = {i: db(x[i0:i1]) for i, x in st.items()}
            others = 10 * np.log10(sum(10 ** (lv[i] / 10) for i in lv if i != me and lv[i] > -150))
            out.append(dict(plan=label, voice=r["voice"], at=r["at"], role=r["role"],
                            re_others_db=round(lv[me] - others, 1)))
    diffs = []
    for r in out:
        if r["plan"] == "role_level":
            q = next(x for x in out if x["plan"] == "no_role_level" and x["voice"] == r["voice"] and x["at"] == r["at"])
            diffs.append(r["re_others_db"] - q["re_others_db"])
    res["voicing"] = dict(windows=out, lift_db_median=round(float(np.median(diffs)), 1),
                          lift_db_min=round(float(np.min(diffs)), 1), lift_db_max=round(float(np.max(diffs)), 1))
    print("voicing lift", res["voicing"]["lift_db_median"], res["voicing"]["lift_db_min"], res["voicing"]["lift_db_max"])
    for r in out:
        print("  ", r)


def main():
    res = json.loads((QA / "results" / "variants.json").read_text()) if (QA / "results" / "variants.json").exists() \
        else {}
    res["state"] = state()
    only = sys.argv[1:]
    for f in (piano_target, bass_double, voicing):
        if only and f.__name__ not in only:
            continue
        f(res)
    p = save("variants.json", res)
    print("->", p)


if __name__ == "__main__":
    main()
