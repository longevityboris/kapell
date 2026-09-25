#!/usr/bin/env python3
"""Final-mix checks on a quartet render (default: the QA fugue from qa_chain.py).

  python3 qa_mix.py [/tmp/sqa/fugue_qa]

format        WAV rate / channels / subtype / duration; m4a codec, rate, bitrate,
              duration (ffprobe) and its decoded true peak
level         true peak (4x oversampled) of WAV and decoded m4a, clipped samples,
              integrated loudness (BS.1770 gated), loudness range (10th-95th pct
              of 3 s short-term loudness), DC offset per channel
noise         quietest 100 ms of the programme, level before the first note,
              and in the long rest of the old fugue's exposition (alto alone)
tail          level of the last 0.5 s before the fade vs the programme peak;
              where the mix falls to -60 dB re its last-note level; IR length vs
              the 4 s the renderer keeps after the last stem sample
stereo        L/R correlation (whole, 1 s windows), mono fold-down loss, side/mid,
              and each instrument's pan (dry single-instrument renders from qa_edge)
balance       tutti windows: every stem's K-weighted level re the loudest
runs          consecutive short (16th) notes: dip between notes in the dry stem and
              in the mix (does the reverb fill the articulation?), and whether each
              16th's own pitch beats its predecessor's in the mix at its centre
bass          octave-band wet/dry ratio (mix vs the sum of the dry stems) and the
              IR's decay time per octave band (LF build-up)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LIB, SR, TMP, db, env_db, hz, k_weight, load, save, state  # noqa: E402
from qa_chain import harm_score  # noqa: E402


def true_peak_db(x):
    return float(20 * np.log10(np.max(np.abs(resample_poly(x, 4, 1, axis=0))) + 1e-20))


def lufs(x):
    """BS.1770-4 integrated loudness of a stereo array (absolute -70 and relative -10 LU gates)."""
    k = np.stack([k_weight(x[:, c]) for c in range(x.shape[1])], axis=1)
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    ms = np.array([np.sum(np.mean(k[i:i + blk] ** 2, axis=0)) for i in range(0, len(k) - blk, hop)])
    L = -0.691 + 10 * np.log10(ms + 1e-20)
    g = ms[L > -70]
    Lg = -0.691 + 10 * np.log10(np.mean(g))
    g2 = ms[L > Lg - 10]
    integ = -0.691 + 10 * np.log10(np.mean(g2))
    st = int(3 * SR)
    sl = np.array([-0.691 + 10 * np.log10(np.sum(np.mean(k[i:i + st] ** 2, axis=0)) + 1e-20)
                   for i in range(0, len(k) - st, int(SR))])
    sl = sl[sl > integ - 20]
    return float(integ), float(np.percentile(sl, 95) - np.percentile(sl, 10))


def octave_bands(x, centres=(63, 125, 250, 500, 1000, 2000, 4000)):
    out = {}
    for c in centres:
        sos = butter(4, [c / np.sqrt(2), c * np.sqrt(2)], "bandpass", fs=SR, output="sos")
        out[c] = sosfilt(sos, x)
    return out


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else TMP / "fugue_qa"
    wavp, m4ap = Path(str(base) + ".wav"), Path(str(base) + ".m4a")
    rep = json.loads(Path(str(base) + ".json").read_text())
    res = dict(state=state(), render=str(base))
    info = sf.info(str(wavp))
    x, sr = sf.read(str(wavp), dtype="float64", always_2d=True)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                       str(m4ap)], capture_output=True, text=True).stdout)
    st = probe["streams"][0]
    dec = TMP / "m4a_decoded.wav"
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEF32", str(m4ap), str(dec)], check=True)
    y, _ = sf.read(str(dec), dtype="float64", always_2d=True)
    res["format"] = dict(wav_rate=info.samplerate, wav_channels=info.channels, wav_subtype=info.subtype,
                         wav_s=round(info.duration, 3), m4a_codec=st["codec_name"], m4a_rate=int(st["sample_rate"]),
                         m4a_channels=st["channels"], m4a_bitrate=int(st.get("bit_rate", 0)),
                         m4a_s=round(float(probe["format"]["duration"]), 3))
    integ, lra = lufs(x)
    res["level"] = dict(true_peak_wav_dbtp=round(true_peak_db(x), 2), sample_peak_wav_dbfs=round(
        float(20 * np.log10(np.abs(x).max())), 2), clipped_samples=int(np.sum(np.abs(x) >= 0.9999)),
        true_peak_m4a_decoded_dbtp=round(true_peak_db(y), 2),
        m4a_decoded_samples_over_0dbfs=int(np.sum(np.abs(y) > 1.0)),
        integrated_lufs=round(integ, 1), loudness_range_lu=round(lra, 1),
        dc_offset=[float(f"{v:.2e}") for v in x.mean(axis=0)],
        dc_re_rms_db=[round(float(20 * np.log10(abs(x[:, c].mean()) / np.sqrt(np.mean(x[:, c] ** 2)) + 1e-20)), 1)
                      for c in range(2)])
    m = x.mean(axis=1)
    e, hop = env_db(m, 0.1, 0.05)
    act = e[: len(e) - int(3 / 0.05)]
    first_note = min(n[0] for j in rep["jobs"] for n in j["note_list"]) - rep["offset_s"]
    pre = m[: max(1, int((first_note - 0.01) * SR))]
    res["noise"] = dict(quietest_100ms_during_programme_db=round(float(np.percentile(act, 0.5)), 1),
                        programme_peak_100ms_db=round(float(e.max()), 1),
                        before_first_note_s=round(first_note, 3),
                        before_first_note_db=round(db(pre), 1) if len(pre) > 1 else None)
    # tail
    last_off = max(n[1] for j in rep["jobs"] for n in j["note_list"]) - rep["offset_s"]
    lv_last = float(np.max(e[int((last_off - 1.0) / 0.05): int(last_off / 0.05)]))
    after = e[int(last_off / 0.05):]
    i60 = np.flatnonzero(after < lv_last - 60)
    ir_file, _ = sf.read(str(LIB / "IR" / "Detmold-Konzerthaus-S1R163-MS-48k.wav"), always_2d=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import hall                                     # the response the renderer convolves with (tail continued)
    ir = hall.Hall("detmold", SR).ir
    irm = (ir ** 2).sum(axis=1)
    sch = np.cumsum(irm[::-1])[::-1]
    sch_db = 10 * np.log10(sch / sch[0] + 1e-30)
    res["tail"] = dict(file_end_after_last_note_off_s=round(len(m) / SR - last_off, 2),
                       last_note_level_db=round(lv_last, 1),
                       minus60_re_last_note_after_s=round(float(i60[0] * 0.05), 2) if len(i60) else None,
                       last_0p5s_before_fade_db_re_peak=round(db(m[-int(0.8 * SR): -int(0.3 * SR)]) - float(e.max()), 1),
                       ir_file_length_s=round(len(ir_file) / SR, 2), ir_length_s=round(len(ir) / SR, 2),
                       ir_energy_after_4s_db=round(float(sch_db[int(4 * SR)]), 1) if len(ir) > 4 * SR else None)
    # stereo
    L, R = x[:, 0], x[:, 1]
    corr = float(np.sum(L * R) / np.sqrt(np.sum(L ** 2) * np.sum(R ** 2)))
    w = int(SR)
    wc = []
    for i in range(0, len(L) - w, w):
        a, b = L[i:i + w], R[i:i + w]
        if np.mean(a ** 2) > 1e-7:
            wc.append(np.sum(a * b) / np.sqrt(np.sum(a ** 2) * np.sum(b ** 2) + 1e-30))
    mono = 0.5 * (L + R)
    side = 0.5 * (L - R)
    pans = {}
    for tag in ("vn1", "va", "vc"):
        p = TMP / "edge" / f"slur_{tag}.wav"
        if p.exists():
            s, _ = sf.read(str(p), always_2d=True)
            pans[tag] = dict(L_minus_R_db=round(db(s[:, 0]) - db(s[:, 1]), 1),
                             corr=round(float(np.sum(s[:, 0] * s[:, 1]) / np.sqrt(np.sum(s[:, 0] ** 2) * np.sum(s[:, 1] ** 2))), 3))
    res["stereo"] = dict(lr_correlation=round(corr, 3), window_corr_min=round(float(np.min(wc)), 3),
                         window_corr_median=round(float(np.median(wc)), 3),
                         mono_foldown_loss_db=round(db(mono) - 0.5 * (db(L) + db(R)), 2),
                         side_re_mid_db=round(db(side) - db(mono), 1),
                         L_minus_R_db=round(db(L) - db(R), 2), dry_single_instrument_pan=pans)
    # balance from stems
    off = rep["offset_s"]
    stems = {}
    for inst in ("vn1", "vn2", "va", "vc", "cb"):
        p = Path(f"{base}_stem_{inst}.wav")
        if p.exists():
            stems[inst] = load(p)
    notes = {}
    for j in rep["jobs"]:
        notes.setdefault(j["inst"], []).extend(j["note_list"])
    K = {i: k_weight(s) for i, s in stems.items()}
    quart = [i for i in ("vn1", "vn2", "va", "vc") if i in K]
    rows = []
    for w0 in np.arange(0, len(m) / SR - 0.4, 0.2):
        t0, t1 = w0 + off, w0 + off + 0.4
        if all(sum(max(0.0, min(t1, n[1]) - max(t0, n[0])) for n in notes.get(i, [])) >= 0.28 for i in quart):
            i0, i1 = int(w0 * SR), int((w0 + 0.4) * SR)
            rows.append([db(K[i][i0:i1]) for i in quart])
    Lb = np.array(rows)
    rel = Lb - Lb.max(axis=1, keepdims=True)
    res["balance"] = dict(windows=len(rows), median_db_re_loudest={i: round(float(np.median(rel[:, k])), 1)
                                                                   for k, i in enumerate(quart)},
                          p10_db_re_loudest={i: round(float(np.percentile(rel[:, k], 10)), 1) for k, i in enumerate(quart)},
                          median_k_db={i: round(float(np.median(Lb[:, k])), 1) for k, i in enumerate(quart)})
    # runs of short notes
    dips_dry, dips_mix, own = [], [], []
    for inst, nl in notes.items():
        nl = sorted(nl)
        if inst not in stems:
            continue
        ed, hp = env_db(stems[inst], 0.01, 0.002)
        em, _ = env_db(m, 0.01, 0.002)
        fr = SR / hp
        for a, b in zip(nl, nl[1:]):
            if (a[4] or 0) >= 96 and (b[4] or 0) >= 96 and 0 <= b[0] - a[1] < 0.08 and b[0] - a[0] < 0.3:
                t = b[0] - off
                seg_d = ed[int((t - 0.03) * fr): int((t + 0.02) * fr)]
                pk_d = max(ed[int((t - 0.12) * fr): int((t - 0.03) * fr)].max(), ed[int((t + 0.02) * fr): int((t + 0.1) * fr)].max())
                dips_dry.append(pk_d - seg_d.min())
                seg_m = em[int((t - 0.03) * fr): int((t + 0.02) * fr)]
                pk_m = max(em[int((t - 0.12) * fr): int((t - 0.03) * fr)].max(), em[int((t + 0.02) * fr): int((t + 0.1) * fr)].max())
                dips_mix.append(pk_m - seg_m.min())
                if a[2] != b[2]:
                    c = (b[0] + b[1]) / 2 - off
                    seg = m[int((c - 0.04) * SR): int((c + 0.04) * SR)]
                    own.append(harm_score(seg, b[2]) > harm_score(seg, a[2]))
    res["runs"] = dict(pairs=len(dips_dry), dry_dip_db_median=round(float(np.median(dips_dry)), 1),
                       mix_dip_db_median=round(float(np.median(dips_mix)), 1),
                       mix_dip_db_p10=round(float(np.percentile(dips_mix, 10)), 1),
                       sixteenth_own_pitch_dominant_in_mix=round(float(np.mean(own)), 3), n_pitch=len(own))
    # bass: wet/dry per octave band
    drysum = sum(stems[i] for i in stems)
    n = min(len(drysum), len(m))
    bm, bd = octave_bands(m[:n]), octave_bands(drysum[:n])
    wd = {c: round(db(bm[c]) - db(bd[c]), 1) for c in bm}
    ref = wd[1000]
    irb = octave_bands(ir.mean(axis=1))
    t30 = {}
    for c, h in irb.items():
        en = h ** 2
        s = np.cumsum(en[::-1])[::-1]
        sd = 10 * np.log10(s / s[0] + 1e-30)
        i5, i35 = np.flatnonzero(sd <= -5), np.flatnonzero(sd <= -35)
        if len(i5) and len(i35):
            t30[c] = round(float(2 * (i35[0] - i5[0]) / SR), 2)
    res["bass"] = dict(mix_over_dry_db_by_octave={c: v for c, v in wd.items()},
                       re_1k_db={c: round(v - ref, 1) for c, v in wd.items()}, ir_t30_s_by_octave=t30,
                       mix_octave_levels_db={c: round(db(bm[c]), 1) for c in bm})
    p = save(f"mix_{base.name}.json", res)
    print(json.dumps(res, indent=1, default=str))
    print("->", p)


if __name__ == "__main__":
    main()
