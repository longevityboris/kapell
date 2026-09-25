#!/usr/bin/env python3
"""Round-2 final-file checks on the demo render (default options: lead-in, hall, -1 dBTP).

  python3 an_mix.py [--base /tmp/sqa2/fugue_def] [--ks /tmp/sqa2/fugue_ks] [--mid /tmp/sqa2/fugue.mid]

  * format (sf.info / ffprobe), sample peak, clipped samples, true peak (x4 polyphase and
    ffmpeg ebur128), DC per channel, integrated loudness / LRA;
  * lead-in: digital silence before the first note; quietest 100 ms inside the piece;
  * tail: level when the renderer's 0.3 s fade starts, re the final chord and re the peak;
    time from the last key lift to -60 dB; the file does not end on sound;
  * stereo: L/R balance, correlation, side/mid, mono fold-down loss, the dry stems' own L/R;
  * timeline: the default render against the --keep-start render at the reported offsets
    (same music at the same MIDI time), m4a decoded against the WAV (lag, peak, length);
  * balance: K-weighted level of each dry stem re the loudest in 2 s windows where all four play;
  * clarity: for every short note (< 0.26 s) and every cello note <= A2, the note's own
    partials vs the previous note's partials at the note's middle: dry stem, dry sum of the
    four stems, final mix, and the same MIDI rendered --hall none / --wet -8 if present
    (partials shared with any other note sounding within 0.3 s excluded);
  * hall: octave-band decay of the IR the renderer uses (hall.Hall), Schroeder EDT/T20/T30,
    the splice at 1.0-1.44 s, octave-band C80 and early/late energy at -4 dB wet;
  * clicks: 1 ms peaks of the >6 kHz residual re the local 50 ms RMS at every note-on /
    note-off (+-30 ms) in the dry stems, validated on planted clicks.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import lfilter, resample_poly, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import (SR, STRINGS, TMP, Spec, db, hp, hz, midi_voices, rms_env, save)  # noqa: E402

sys.path.insert(0, str(STRINGS))


def kweight(x):
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1, -1.99004745483398, 0.99007225036621]
    return lfilter(b2, a2, lfilter(b1, a1, x, axis=0), axis=0)


def ebur128(path):
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-filter_complex", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    s = r.stderr[r.stderr.rfind("Summary:"):]
    g = lambda k: float(re.search(k + r":\s+(-?[\d.]+)", s).group(1))
    return dict(I_lufs=g("I"), LRA_lu=g("LRA"), true_peak_dbfs=g("Peak"))


def click_scan(x, times, thr=15.0):
    """1 ms peaks of the >6 kHz residual re the local 50 ms RMS of that residual, within +-30 ms of `times`."""
    y = hp(x, 6000)
    W = int(0.001 * SR)
    n = len(y) // W * W
    pk = np.abs(y[:n]).reshape(-1, W).max(axis=1)
    loc = np.sqrt(np.convolve(y[:n] ** 2, np.ones(int(0.05 * SR)) / int(0.05 * SR), "same"))[::W]
    tot = np.sqrt(np.convolve(x[:n] ** 2, np.ones(int(0.05 * SR)) / int(0.05 * SR), "same"))[::W]
    r = db(pk ** 2 / np.maximum(loc ** 2, 1e-24))
    rel_full = db(pk ** 2 / np.maximum(tot ** 2, 1e-24))          # click peak re the full-band local RMS
    hits = []
    for t in times:
        i0, i1 = max(0, int((t - 0.03) * 1000)), min(len(r), int((t + 0.03) * 1000))
        if i1 <= i0:
            continue
        j = i0 + int(np.argmax(r[i0:i1]))
        if r[j] > thr and rel_full[j] > -30:
            hits.append(dict(t=round(j / 1000, 3), hf_re_local_db=round(float(r[j]), 1), re_fullband_db=round(float(rel_full[j]), 1)))
    return hits


def validate_clicks():
    rng = np.random.default_rng(3)
    t = np.arange(int(4 * SR)) / SR
    x = 0.1 * sum(np.sin(2 * np.pi * k * 220 * t) / k for k in range(1, 12)) * (1 + 0.1 * np.sin(2 * np.pi * 5 * t))
    x += 1e-4 * rng.standard_normal(len(t))
    planted = [0.7, 1.5, 2.3, 3.1]
    amps = [0.02, 0.01, 0.005, 0.0025]
    for p, a in zip(planted, amps):
        i = int(p * SR)
        x[i] += a                                   # a single-sample step-like click
        x[i + 1:] += 0.0                            # (no DC step)
    cand = planted + [0.3, 1.1, 1.9, 2.7]
    hits = click_scan(x, cand)
    return dict(planted=planted, amps_re_signal_rms_db=[round(float(db(a ** 2 / np.mean(x ** 2))), 1) for a in amps],
                found=[h["t"] for h in hits], false=[h for h in hits if min(abs(h["t"] - p) for p in planted) > 0.005])


def clarity(midi, off, stem_raw, sigs):
    """Short notes (< 0.26 s) and cello notes <= A2 (< 1 s) that follow another pitch within 0.1 s: the new
    note's own partials vs the previous note's own partials (partials shared with each other or with any
    other note sounding within 0.3 s excluded) at the middle of the note; > 0 dB = the new pitch dominates."""
    names = {"soprano": "vn1", "alto": "vn2", "tenor": "va", "pedal": "vc", "bass": "vc"}
    allnotes = [n for v in midi.values() for n in v["notes"]]
    specs = {}

    def spec(name, sig, w):
        if (name, w) not in specs:
            specs[(name, w)] = Spec(sig, win=w)
        return specs[(name, w)]
    out = {}
    for v in midi.values():
        notes = v["notes"]
        inst = names.get(v["name"])
        for i, nt in enumerate(notes[1:], 1):
            p = notes[i - 1]
            dur = nt["off"] - nt["on"]
            kind = "short" if dur < 0.26 else ("low_cello" if inst == "vc" and nt["key"] <= 45 and dur < 1.0 else None)
            if kind is None or p["key"] == nt["key"] or nt["on"] - p["off"] > 0.1:
                continue
            tm = nt["on"] + 0.5 * dur - off
            others = [o["key"] for o in allnotes if o is not nt and o is not p and o["on"] - off < tm + 0.02
                      and o["off"] - off + 0.3 > tm]
            w = 0.08 if nt["key"] < 50 else 0.05
            srcs = dict(dry_stem=stem_raw[inst], **sigs)
            for nm, sig in srcs.items():
                sp = spec(nm if nm != "dry_stem" else "stem_" + inst, sig, w)
                bn = sp.band_energy(nt["key"], exclude_keys=[p["key"]] + others)
                bo = sp.band_energy(p["key"], exclude_keys=[nt["key"]] + others)
                if bn is None or bo is None:
                    continue
                j = int(np.argmin(np.abs(sp.t - tm)))
                out.setdefault(kind, {}).setdefault(nm, []).append(float(bn[j] - bo[j]))
    return {k: {nm: dict(n=len(v), new_dominates=round(float(np.mean(np.array(v) > 0)), 3),
                         median_db=round(float(np.median(v)), 1), p10_db=round(float(np.percentile(v, 10)), 1))
                for nm, v in d.items()} for k, d in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(TMP / "fugue_def"))
    ap.add_argument("--ks", default=str(TMP / "fugue_ks"))
    ap.add_argument("--mid", default=str(TMP / "fugue.mid"))
    ap.add_argument("--tag", default="fugue")
    a = ap.parse_args()
    base, ks = Path(a.base), Path(a.ks)
    rep = json.loads(Path(str(base) + ".json").read_text())
    rks = json.loads(Path(str(ks) + ".json").read_text())
    info = sf.info(str(base) + ".wav")
    x, sr = sf.read(str(base) + ".wav", always_2d=True)
    res = dict(format=dict(samplerate=info.samplerate, channels=info.channels, subtype=info.subtype,
                           duration_s=round(info.duration, 3)))
    # ---- levels
    up = resample_poly(x, 4, 1, axis=0)
    res["levels"] = dict(sample_peak_dbfs=round(float(db(np.max(np.abs(x)) ** 2)), 3),
                         true_peak_x4_dbtp=round(float(db(np.max(np.abs(up)) ** 2)), 3),
                         clipped_samples=int(np.sum(np.abs(x) >= 0.99999)),
                         dc=[float(np.mean(x[:, c])) for c in range(2)],
                         dc_db=[round(float(db(np.mean(x[:, c]) ** 2)), 1) for c in range(2)],
                         ebur128=ebur128(str(base) + ".wav"))
    # ---- lead-in, noise floor
    midi = midi_voices(a.mid)
    first_on = min(n["on"] for v in midi.values() for n in v["notes"])
    last_off = max(n["off"] for v in midi.values() for n in v["notes"])
    off = rep["offset_s"]
    i_first = int((first_on - off) * SR)
    lead = x[: max(0, i_first - int(0.03 * SR))]
    t, e = rms_env(x.mean(axis=1), 0.1, 0.05)
    inside = (t > first_on - off + 0.5) & (t < last_off - off - 0.5)
    res["noise"] = dict(first_note_at_s=round(first_on - off, 3), lead_in_max_abs=float(np.max(np.abs(lead))) if len(lead) else None,
                        lead_in_rms_dbfs=round(float(db(np.mean(lead ** 2))), 1) if len(lead) else None,
                        quietest_100ms_inside_dbfs=round(float(e[inside].min()), 1),
                        quietest_at_s=round(float(t[inside][np.argmin(e[inside])]), 2),
                        loudest_100ms_dbfs=round(float(e.max()), 1))
    # ---- tail
    L = len(x)
    fade0 = L - int(0.3 * SR)
    t_last = last_off - off
    fin = x[int((t_last - 1.0) * SR): int((t_last - 0.1) * SR)].mean(axis=1)
    fin_db = float(db(np.mean(fin ** 2)))
    pre_fade = x[fade0 - int(0.1 * SR): fade0].mean(axis=1)
    te, ee = rms_env(x.mean(axis=1), 0.05, 0.01)
    after = (te > t_last)
    below60 = te[after & (ee < fin_db - 60)]
    res["tail"] = dict(last_key_lift_s=round(t_last, 3), file_end_s=round(L / SR, 3),
                       seconds_after_lift=round(L / SR - t_last, 3),
                       final_chord_dbfs=round(fin_db, 1),
                       level_when_fade_starts_re_final_chord_db=round(float(db(np.mean(pre_fade ** 2))) - fin_db, 1),
                       level_when_fade_starts_re_peak_db=round(float(db(np.mean(pre_fade ** 2))) - res["noise"]["loudest_100ms_dbfs"], 1),
                       t_to_minus60_re_final_chord_s=round(float(below60[0] - t_last), 2) if len(below60) else None,
                       last_10ms_dbfs=round(float(db(np.mean(x[-480:] ** 2))), 1))
    # ---- stereo
    l, r = x[:, 0], x[:, 1]
    m, s = 0.5 * (l + r), 0.5 * (l - r)
    res["stereo"] = dict(lr_balance_db=round(float(db(np.mean(l ** 2) / np.mean(r ** 2))), 2),
                         correlation=round(float(np.corrcoef(l, r)[0, 1]), 3),
                         side_re_mid_db=round(float(db(np.mean(s ** 2) / np.mean(m ** 2))), 1),
                         mono_foldown_loss_db=round(float(db(np.mean(m ** 2) / (0.5 * (np.mean(l ** 2) + np.mean(r ** 2))))), 2))
    pans = {}
    for inst in ("vn1", "vn2", "va", "vc"):
        st, _ = sf.read(f"{base}_stem_{inst}.wav", always_2d=True)
        # the stems are dry and unpanned: the pan is applied in the mix; report the stem's own L/R for sanity
        pans[inst] = round(float(db(np.mean(st[:, 0] ** 2) / np.mean(st[:, 1] ** 2))), 2)
    res["stereo"]["dry_stem_lr_db"] = pans
    # ---- timeline: default vs keep-start
    xk, _ = sf.read(str(ks) + ".wav", always_2d=True)
    sh = int(round((rep["offset_s"] - rks["offset_s"]) * SR))
    a_ = x.mean(axis=1)
    b_ = xk.mean(axis=1)[sh: sh + len(a_)] if sh >= 0 else np.concatenate([np.zeros(-sh), xk.mean(axis=1)])[: len(a_)]
    n = min(len(a_), len(b_)) - int(0.5 * SR)
    g = np.dot(a_[:n], b_[:n]) / np.dot(b_[:n], b_[:n])
    resid = a_[:n] - g * b_[:n]
    # lag check by cross-correlation of 10 ms envelopes
    _, ea = rms_env(a_[:n], 0.01, 0.001)
    _, eb = rms_env(b_[:n], 0.01, 0.001)
    ea, eb = ea - ea.mean(), eb - eb.mean()
    lags = range(-50, 51)
    cc = [np.dot(ea[max(0, k): len(ea) + min(0, k)], eb[max(0, -k): len(eb) - max(0, k)]) for k in lags]
    res["timeline"] = dict(offset_default_s=rep["offset_s"], offset_keep_start_s=rks["offset_s"],
                           residual_re_signal_db=round(float(db(np.mean(resid ** 2) / np.mean(a_[:n] ** 2))), 1),
                           best_env_lag_ms=int(list(lags)[int(np.argmax(cc))]))
    # ---- m4a
    m4a = str(base) + ".m4a"
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate,duration",
                         "-of", "json", m4a], capture_output=True, text=True)
    dec = TMP / "m4a_dec.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", m4a, "-c:a", "pcm_f32le", str(dec)], check=True)
    y, fs = sf.read(str(dec), always_2d=True)
    n = min(len(y), len(x))
    _, e1 = rms_env(x[:n].mean(axis=1), 0.005, 0.0005)
    _, e2 = rms_env(y[:n].mean(axis=1), 0.005, 0.0005)
    e1, e2 = e1 - e1.mean(), e2 - e2.mean()
    lags = range(-200, 201)
    cc = [np.dot(e1[max(0, k): len(e1) + min(0, k)], e2[max(0, -k): len(e2) - max(0, k)]) for k in lags]
    upy = resample_poly(y, 4, 1, axis=0)
    res["m4a"] = dict(ffprobe=json.loads(pr.stdout)["streams"], decoded_samplerate=fs, decoded_len_minus_wav=len(y) - len(x),
                      env_lag_ms=round(0.5 * list(lags)[int(np.argmax(cc))], 1),
                      decoded_true_peak_dbtp=round(float(db(np.max(np.abs(upy)) ** 2)), 2),
                      decoded_clipped=int(np.sum(np.abs(y) >= 0.99999)),
                      ebur128=ebur128(m4a))
    # ---- balance (K-weighted dry stems, 2 s windows where all four play)
    stems = {}
    for inst in ("vn1", "vn2", "va", "vc"):
        st, _ = sf.read(f"{base}_stem_{inst}.wav", always_2d=True)
        stems[inst] = kweight(st.mean(axis=1))
    nwin = int(2 * SR)
    lv = {k: [] for k in stems}
    for s0 in range(0, min(len(v) for v in stems.values()) - nwin, nwin // 2):
        ls = {k: float(db(np.mean(v[s0: s0 + nwin] ** 2))) for k, v in stems.items()}
        if min(ls.values()) < max(ls.values()) - 25:          # someone is resting
            continue
        mx = max(ls.values())
        for k in ls:
            lv[k].append(ls[k] - mx)
    res["balance_k_weighted_re_loudest"] = {k: dict(median=round(float(np.median(v)), 1), p10=round(float(np.percentile(v, 10)), 1),
                                                    loudest_share=round(float(np.mean(np.array(v) == 0)), 2))
                                            for k, v in lv.items()}
    res["balance_k_weighted_re_loudest"]["windows"] = len(lv["vn1"])
    # ---- clarity of short notes and low cello notes: dry stem, dry sum of the four stems, final mix,
    # and (if rendered) the same MIDI with --hall none and --wet -8
    stem_raw = {inst: sf.read(f"{base}_stem_{inst}.wav", always_2d=True)[0].mean(axis=1) for inst in ("vn1", "vn2", "va", "vc")}
    sigs = {"mix": x.mean(axis=1), "dry_sum": sum(stem_raw.values())}
    for nm, suffix in (("hall_none", "_dryhall"), ("wet_minus8", "_wet8")):
        p_ = Path(str(TMP / a.tag) + suffix + ".wav")
        if p_.exists():
            z, _ = sf.read(str(p_), always_2d=True)
            rz = json.loads(Path(str(TMP / a.tag) + suffix + ".json").read_text())
            d = int(round((rz["offset_s"] - off) * SR))            # align to this render's timeline
            zz = z.mean(axis=1)
            sigs[nm] = np.concatenate([np.zeros(d), zz])[: len(sigs["mix"])] if d >= 0 else zz[-d:]
    res["clarity"] = clarity(midi, off, stem_raw, sigs)
    # ---- low-end: share of the mix below 150 Hz vs the dry stems' sum
    drysum = sigs["dry_sum"]
    mixm = sigs["mix"]
    def lf_share(z):
        Z = np.abs(np.fft.rfft(z[: 1 << 22] if len(z) > 1 << 22 else z)) ** 2
        f = np.fft.rfftfreq(len(z[: 1 << 22] if len(z) > 1 << 22 else z), 1 / SR)
        return float(db(Z[f < 150].sum() / Z.sum())), float(db(Z[(f >= 150) & (f < 500)].sum() / Z.sum()))
    res["low_end"] = dict(mix_lt150_share_db=round(lf_share(mixm)[0], 1), dry_lt150_share_db=round(lf_share(drysum)[0], 1),
                          mix_150_500_share_db=round(lf_share(mixm)[1], 1), dry_150_500_share_db=round(lf_share(drysum)[1], 1))
    # ---- hall
    import hall
    H = hall.Hall("detmold", SR)
    ir = H.ir
    mono = ir.mean(axis=1)
    hres = {}
    g2 = 10 ** (-4 / 10)
    for fc in hall.OCTAVES[:8]:
        b = sosfiltfilt(hall._octave_sos(fc, SR), ir, axis=0)
        eb = np.sum(b ** 2, axis=1)
        edc = np.cumsum(eb[::-1])[::-1]
        edc_db = db(edc / edc[0])
        tt = np.arange(len(edc)) / SR

        def t_at(level):
            k = np.flatnonzero(edc_db <= level)
            return float(tt[k[0]]) if len(k) else None

        def fit(l0, l1):
            a0, a1 = t_at(l0), t_at(l1)
            if a0 is None or a1 is None:
                return None
            sel = (tt >= a0) & (tt <= a1)
            sl = np.polyfit(tt[sel], edc_db[sel], 1)[0]
            return round(float(-60 / sl), 2)
        # local decay slope before / after the splice (energy envelope, 50 ms)
        w = int(0.05 * SR)
        env = db(np.convolve(eb, np.ones(w) / w, "same"))
        def slope(t0, t1):
            sel = (tt >= t0) & (tt <= t1)
            return round(float(-60 / np.polyfit(tt[sel], env[sel], 1)[0]), 2)
        n80 = int(0.08 * SR)
        # dry: a band-limited impulse through the same band, energy 1 (place_dry keeps energy)
        hres[fc] = dict(EDT=fit(0, -10), T20=fit(-5, -25), T30=fit(-5, -35),
                        rt_local_0p5_1p0=slope(0.5, 1.0), rt_local_1p2_1p44=slope(1.2, 1.44), rt_local_1p5_2p5=slope(1.5, 2.5),
                        level_step_at_1p44_db=round(float(np.mean(env[int(1.45 * SR): int(1.55 * SR)]) - np.mean(env[int(1.33 * SR): int(1.43 * SR)])), 1),
                        late_re_early_db=round(float(db(eb[n80:].sum() / eb[:n80].sum())), 1),
                        band_energy_share_db=round(float(db(eb.sum() / np.sum(ir ** 2))), 1))
    # program material: the demo's own dry stems placed and convolved exactly as render_quartet does, early
    # (first 80 ms of the IR) and late parts separately -> reverb re dry and C80 on the music, per instrument
    import render_quartet as rq
    n80 = int(0.08 * SR)
    prog = {}
    tot = dict(dry=0.0, early=0.0, late=0.0)
    for inst in ("vn1", "vn2", "va", "vc"):
        st, _ = sf.read(f"{base}_stem_{inst}.wav", always_2d=True)
        az, dep = rq.INSTR[inst]["az"], rq.INSTR[inst]["depth"]
        dry_ = hall.place_dry(st, az, depth=dep)
        h = H.ir if az >= 0 else H.mirror
        # the IR gain the renderer applied: since the round-2 fix --wet is hall re dry on the music and
        # the report's hall_stats.ir_scale_db is the impulse-referenced gain (before: wet_db itself)
        g = 10 ** ((rep.get("hall_stats") or {}).get("ir_scale_db", rep["wet_db"]) / 20)
        mono_ = st.mean(axis=1)
        from scipy.signal import fftconvolve
        early = g * np.stack([fftconvolve(mono_, h[:n80, c])[: len(mono_)] for c in range(2)], axis=1)
        late = g * np.stack([fftconvolve(mono_, np.concatenate([np.zeros(n80), h[n80:, c]]))[: len(mono_)] for c in range(2)], axis=1)
        ed, ee, el = float(np.sum(dry_ ** 2)), float(np.sum(early ** 2)), float(np.sum(late ** 2))
        ew = float(np.sum((early + late) ** 2))
        prog[inst] = dict(reverb_re_dry_db=round(float(db(ew / ed)), 1), c80_db=round(float(db((ed + ee) / el)), 1))
        tot["dry"] += ed
        tot["early"] += ee
        tot["late"] += el
        tot["wet"] = tot.get("wet", 0.0) + ew
    prog["all"] = dict(reverb_re_dry_db=round(float(db(tot["wet"] / tot["dry"])), 1),
                       c80_db=round(float(db((tot["dry"] + tot["early"]) / tot["late"])), 1))
    noise = np.random.default_rng(0).standard_normal(SR * 10)
    wn_d = hall.place_dry(np.stack([noise, noise], axis=1), 30.0)
    wn_w = H.source(noise, 30.0, rep["wet_db"])
    prog["white_noise_reverb_re_dry_db"] = round(float(db(np.sum(wn_w ** 2) / np.sum(wn_d ** 2))), 1)
    res["hall"] = dict(ir_len_s=round(len(ir) / SR, 2), c80_reported=rep.get("c80_db"), wet_flag_db=rep["wet_db"],
                       program=prog, octave=hres)
    # ---- clicks at note boundaries (dry stems)
    ontimes = {"vn1": [], "vn2": [], "va": [], "vc": []}
    for j in rep["jobs"]:
        for (on, of, key, vel, art), pre in zip(j["note_list"], j["pre_ms"]):
            ontimes[j["inst"]] += [on - pre / 1000 - off, of - off]
    clicks = {}
    for inst, ts in ontimes.items():
        clicks[inst] = click_scan(stem_raw[inst], sorted(ts))
    mixclicks = click_scan(mixm, sorted(t for v in ontimes.values() for t in v))
    res["clicks"] = dict(validation=validate_clicks(), per_stem={k: dict(n=len(v), worst=sorted(v, key=lambda h: -h["re_fullband_db"])[:5])
                                                                 for k, v in clicks.items()},
                         mix=dict(n=len(mixclicks), worst=sorted(mixclicks, key=lambda h: -h["re_fullband_db"])[:5]))
    save(f"mix_{a.tag}.json", res)
    print(json.dumps({k: v for k, v in res.items() if k not in ("hall",)}, indent=1, default=float)[:6000])
    for fc, h in res["hall"]["octave"].items():
        print(fc, h)


if __name__ == "__main__":
    main()
