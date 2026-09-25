#!/usr/bin/env python3
"""Measure the orchestra renders (the evidence in README.md).

  python3 qa_orchestra.py [--skip-render] [--midi out/skeleton_orchestra.mid]

Renders the skeleton demo again with --stems --keep-start (dry, placed stems
aligned to MIDI time 0) into out/qa/, plus demo_instruments and
demo_crescendo, and writes evidence/qa.json:

  chain      every MIDI note of every track: pitch (YIN within +-1.2 semitones of
             the key, middle of the note), onset (the note's fundamental+2nd
             harmonic band reaching 6 dB below its peak, minus the seat's
             distance delay), dropped (band never within 30 dB of the track's
             level), stuck (the key's band 0.8 s after the note-off not 20 dB
             below the note, where no other note of that pitch class follows)
  entries    every entry after >= 0.3 s of silence in its track: the time the band of
             the note's harmonics 1-3 (20 ms STFT, 2 ms hop) reaches 12 dB below its peak
             in the first 300 ms, minus the note-on and the seat's delay (the -6 dB
             criterion above is the one the renderer's latency compensation targets, so
             it cannot see an entry that swells in early); per track median / worst,
             and the gap between two tracks entering on the same MIDI onset (a flam)
  artefacts  clicks (>6 kHz jumps 30 dB above the local level) per stem and in the
             mix; sustain smoothness: largest 50 ms level step inside notes of
             2 s or more (loops, splices, layer switches), excluding the first 0.3 s
  dynamics   demo_instruments: per part pp / mf / ff K-weighted level, spectral
             centroid, harmonic richness (harmonics 3.. re 1-2, noise removed)
  crescendo  demo_crescendo mix: 0.5 s loudness and centroid vs time
  balance    skeleton: per string voice, level re the loudest active string voice
             (median / p10) in 100 ms frames; per section loudness
  file       format, true peak (4x oversampled), m4a decoded peak, integrated
             loudness (BS.1770-4, gated), loudness range, L/R correlation, lead-in
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import lfilter, resample_poly

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from orch_common import PARTS, SR, midi_name  # noqa: E402
import orch_measure as M  # noqa: E402

QA = HERE / "out" / "qa"
EV = HERE / "evidence"


def render(mid: Path, out: Path, *extra):
    cmd = [sys.executable, str(HERE / "render_orchestra.py"), str(mid), "-o", str(out), *extra]
    subprocess.run(cmd, check=True, capture_output=True)
    return json.loads(out.with_suffix(".json").read_text())


def kweight(x):
    y = lfilter([1.53512485958697, -2.69169618940638, 1.19839281085285],
                [1.0, -1.69065929318241, 0.73248077421585], x, axis=0)
    return lfilter([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621], y, axis=0)


def lufs(x):
    """BS.1770-4 integrated loudness and EBU loudness range (LU)."""
    y = kweight(x)
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    ms = np.array([np.sum(np.mean(y[i:i + blk] ** 2, axis=0)) for i in range(0, len(y) - blk, hop)])
    L = -0.691 + 10 * np.log10(ms + 1e-20)
    g = ms[L > -70]
    rel = -0.691 + 10 * np.log10(np.mean(g)) - 10
    g2 = ms[(L > -70) & (L > rel)]
    I = -0.691 + 10 * np.log10(np.mean(g2))
    blk3 = int(3 * SR)
    st = np.array([np.sum(np.mean(y[i:i + blk3] ** 2, axis=0)) for i in range(0, len(y) - blk3, int(SR))])
    Ls = -0.691 + 10 * np.log10(st + 1e-20)
    Ls = Ls[(Ls > -70)]
    Ls = Ls[Ls > (-0.691 + 10 * np.log10(np.mean(10 ** ((Ls + 0.691) / 10))) - 20)]
    lra = float(np.percentile(Ls, 95) - np.percentile(Ls, 10)) if len(Ls) > 2 else 0.0
    return float(I), lra


def true_peak_db(x):
    return float(20 * np.log10(np.max(np.abs(resample_poly(x, 4, 1, axis=0))) + 1e-20))


# ----------------------------------------------------------------- chain
def pitch_track(x: np.ndarray, lo_key: int, hi_key: int, hop: float = 0.005) -> np.ndarray:
    f0, f1 = 440 * 2 ** ((lo_key - 70.5) / 12), 440 * 2 ** ((hi_key - 67.5) / 12)
    W = int(min(2048, max(768, 4 * SR / f0)))
    return M.yin(x, SR, f0, f1, W=W, hop=int(hop * SR), thr=0.25)


def handover_ms(m: np.ndarray, on: float, k_old: int, k_new: int) -> float | None:
    """Slurred note: when the new pitch takes over (the YIN track crosses the
    midpoint between the two pitches), in ms re the note-on."""
    a = int((on - 0.2) * SR)
    seg = m[max(0, a): int((on + 0.25) * SR)]
    tr = pitch_track(seg, min(k_old, k_new), max(k_old, k_new))
    if len(tr) < 10:
        return None
    mid = 440 * 2 ** (((k_old + k_new) / 2 - 69) / 12)
    new_side = (tr > mid) if k_new > k_old else (tr < mid)
    ok = np.isfinite(tr)
    for i in range(len(tr) - 3):
        if ok[i] and new_side[i:i + 4].all() and ok[i:i + 4].all():
            W = int(min(2048, max(768, 4 * SR / (440 * 2 ** ((min(k_old, k_new) - 70.5) / 12)))))
            return 1000 * (i * 0.005 + W / 2 / SR - 0.2)
    return None


def chain(rep: dict, stem_dir: Path) -> dict:
    depth = {}
    for j in rep["jobs"]:
        depth.setdefault(j["label"].split("/")[0], j["seat_depth_m"])
    out = {"tracks": {}, "all": {}}
    all_c, all_det, all_leg, dropped, stuck, ntot = [], [], [], [], [], 0
    for tr in rep["tracks"]:
        name = tr["name"]
        x, _ = sf.read(str(stem_file(rep, stem_dir, name)), dtype="float64", always_2d=True)
        m = x.mean(axis=1)
        d = depth.get(name, 0.0) / 343.0
        notes = tr["note_list"]
        env, hop = M.env_db(m, 0.02, 0.005)
        p95 = float(np.percentile(env[env > -150], 95)) if (env > -150).any() else -200
        cents, det, leg = [], [], []
        for i, (on, off, key, vel, art) in enumerate(notes):
            ntot += 1
            a, b = int((on + d) * SR), int((off + d) * SR)
            dur = off - on
            got_pitch = False
            if tr["part"] != "timp" and dur >= 0.15:
                s0 = a + int(min(0.25, 0.35 * dur) * SR)
                s1 = b - int(0.04 * SR)
                c = M.pitch_cents(m[s0:s1], key) if s1 - s0 > 3000 else None
                if c is not None:
                    cents.append((c, on, key))
                    got_pitch = abs(c) < 50
            mid_lv = float(np.max(env[int((on + d) / hop): max(int((on + d) / hop) + 1, int((off + d) / hop))]))
            if not got_pitch and mid_lv < p95 - 45:
                dropped.append(f"{name} {midi_name(key)} at {on:.2f}s ({mid_lv - p95:+.0f} dB re the track's p95)")
            prev = notes[i - 1] if i else None
            chord = prev is not None and abs(prev[0] - on) < 0.03
            if chord:
                continue
            if prev is None or on - prev[1] >= 0.05 or tr["part"] == "timp":
                i0, i1 = int((on + d - 0.15) / hop), int((on + d + min(0.3, dur)) / hop)
                e = env[max(0, i0): i1]
                if len(e) > 10 and e[:6].max() < e.max() - 10:
                    i6 = int(np.flatnonzero(e >= e.max() - 6)[0])
                    det.append(1000 * (i6 * hop - 0.15 + max(0, -i0) * hop))
            elif prev[2] != key and abs(prev[2] - key) <= 12:
                h = handover_ms(m, on + d, prev[2], key)
                if h is not None:
                    leg.append(h)
        # stuck: sound through the rests (>= 1 s) and after the last note of the track
        rests = [(n[1], nxt[0]) for n, nxt in zip(notes, notes[1:]) if nxt[0] - max(z[1] for z in notes[:notes.index(nxt)]) >= 1.0]
        rests.append((max(n[1] for n in notes), max(n[1] for n in notes) + 3.0))
        for r0, r1 in rests:
            last = [n for n in notes if n[1] <= r0 + 1e-6 and n[1] > r0 - 3]
            ref = max((float(np.max(env[int((n[0] + d) / hop): int((n[1] + d) / hop) + 1])) for n in last), default=None)
            j = int((r0 + d + 0.8) / hop)
            if ref is not None and j < len(env) and float(np.max(env[j: j + 20])) > ref - 30:
                stuck.append(f"{name}: {float(np.max(env[j:j + 20])) - ref:+.0f} dB 0.8 s into the rest after {r0:.2f}s")
        cl = M.clicks(x)
        steps = []
        for on, off, key, vel, art in notes:
            if off - on >= 2.0:
                e, _ = M.env_db(m[int((on + d + 0.3) * SR): int((off + d - 0.1) * SR)], 0.05, 0.05)
                if len(e) > 3:
                    steps.append(float(np.max(np.abs(np.diff(e)))))
        ac = np.abs([c for c, _, _ in cents]) if cents else np.array([np.nan])
        worst = max(cents, key=lambda z: abs(z[0])) if cents else (np.nan, 0, 0)
        out["tracks"][name] = dict(part=tr["part"], notes=len(notes), pitch_measured=len(cents),
                                   pitch_med_abs_c=round(float(np.median(ac)), 1),
                                   pitch_p95_abs_c=round(float(np.percentile(ac, 95)), 1),
                                   pitch_worst=f"{worst[0]:+.0f} c {midi_name(int(worst[2]))} at {worst[1]:.2f}s",
                                   detached_onsets=len(det),
                                   onset_med_ms=round(float(np.median(det)), 1) if det else None,
                                   onset_p90_abs_ms=round(float(np.percentile(np.abs(det), 90)), 1) if det else None,
                                   slurs=len(leg), handover_med_ms=round(float(np.median(leg)), 1) if leg else None,
                                   handover_p90_ms=round(float(np.percentile(leg, 90)), 1) if leg else None,
                                   clicks=[round(t, 3) for t in cl][:20],
                                   sustain_max_step_db=round(max(steps), 1) if steps else None,
                                   sustain_steps_over_3db=int(sum(s_ > 3 for s_ in steps)), long_notes=len(steps))
        all_c += [abs(c) for c, _, _ in cents]
        all_det += det
        all_leg += leg
    out["all"] = dict(notes=ntot, pitch_measured=len(all_c), pitch_med_abs_c=round(float(np.median(all_c)), 1),
                      pitch_p95_abs_c=round(float(np.percentile(all_c, 95)), 1),
                      pitch_over_25c=int(sum(c > 25 for c in all_c)),
                      detached_onsets=len(all_det), onset_med_ms=round(float(np.median(all_det)), 1),
                      onset_within_30ms_pct=round(100 * float(np.mean(np.abs(all_det) <= 30)), 1),
                      onset_p90_abs_ms=round(float(np.percentile(np.abs(all_det), 90)), 1),
                      slurs=len(all_leg), handover_med_ms=round(float(np.median(all_leg)), 1),
                      handover_p90_ms=round(float(np.percentile(all_leg, 90)), 1),
                      handover_within_40ms_pct=round(100 * float(np.mean(np.abs(all_leg) <= 40)), 1),
                      dropped=dropped, stuck=stuck)
    return out


# ----------------------------------------------------------------- entries
def stem_file(rep: dict, stem_dir: Path, name: str) -> Path:
    for safe, tr in (rep.get("stems") or {}).items():
        if tr == name:
            return stem_dir / f"{safe}.wav"
    return stem_dir / f"{''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in name)}.wav"


def band_onset(x: np.ndarray, t0: float, key: int, thr_db: float = 12.0) -> float | None:
    """Time (s) at which the band of harmonics 1-3 of `key` first reaches thr_db below
    its peak in [t0 - 0.15, t0 + 0.30] (20 ms Hann STFT, 2 ms hop, window centre)."""
    a = t0 - 0.15
    seg = x[max(0, int(a * SR)): int((t0 + 0.30) * SR)]
    w, hop = 960, 96
    if a < 0 or len(seg) < w + hop:
        return None
    f0 = 440 * 2 ** ((key - 69) / 12)
    fr = np.fft.rfftfreq(w, 1 / SR)
    m = np.zeros_like(fr, bool)
    for h in (1, 2, 3):
        m |= np.abs(fr - h * f0) < max(30, 0.03 * h * f0)
    win = np.hanning(w)
    fr_idx = np.arange(0, len(seg) - w, hop)
    frames = np.stack([seg[i:i + w] * win for i in fr_idx])
    env = 10 * np.log10(np.sum(np.abs(np.fft.rfft(frames, axis=1))[:, m] ** 2, axis=1) + 1e-20)
    i = int(np.argmax(env >= env.max() - thr_db))
    return a + (i * hop + w / 2) / SR


def entries(rep: dict, stem_dir: Path, min_gap: float = 0.3, thr_db: float = 12.0) -> dict:
    delay = {}
    for j in rep["jobs"]:
        delay.setdefault(j["label"].split("/")[0], []).append(j["seat_depth_m"] / 343.0 + j["delay_ms"] / 1000)
    delay = {k: min(v) for k, v in delay.items()}
    per, allo = {}, []
    for tr in rep["tracks"]:
        name = tr["name"]
        x, _ = sf.read(str(stem_file(rep, stem_dir, name)), dtype="float64", always_2d=True)
        x = x.mean(axis=1)
        d = delay.get(name, 0.0)
        prev_end, errs = -9.0, []
        for on, off, key, vel, art in tr["note_list"]:
            gap = on - prev_end
            prev_end = max(prev_end, off)
            if gap < min_gap or tr["part"] == "timp":
                continue
            t = band_onset(x, on + d, key, thr_db)
            if t is None:
                continue
            e = 1000 * (t - on - d)
            errs.append(e)
            allo.append((name, on, e))
        if errs:
            per[name] = dict(n=len(errs), median_ms=round(float(np.median(errs)), 1),
                             earliest_ms=round(min(errs), 1), latest_ms=round(max(errs), 1))
    flams = {}
    for i, (ta, oa, ea) in enumerate(allo):
        for tb, ob, eb in allo[i + 1:]:
            if ta != tb and abs(oa - ob) < 0.005:
                k = "/".join(sorted((ta, tb)))
                flams.setdefault(k, []).append(round(abs(ea - eb), 1))
    ev = [e for _, _, e in allo]
    str_ev = [e for n, _, e in allo if PARTS[next(t["part"] for t in rep["tracks"] if t["name"] == n)]["family"]
              == "strings"]
    gaps = [g for v in flams.values() for g in v]
    return dict(rule=f"harmonics 1-3 band reaches -{thr_db:g} dB re its peak; entries after >= {min_gap:g} s "
                     "of silence; minus note-on and seat delay",
                all=dict(n=len(ev), median_ms=round(float(np.median(ev)), 1) if ev else None,
                         p10_p90_ms=[round(float(np.percentile(ev, q)), 1) for q in (10, 90)] if ev else None,
                         earliest_ms=round(min(ev), 1) if ev else None),
                strings=dict(n=len(str_ev), median_ms=round(float(np.median(str_ev)), 1) if str_ev else None,
                             earliest_ms=round(min(str_ev), 1) if str_ev else None),
                tracks=per,
                doubled_entry_gap_ms=dict(pairs=len(gaps), worst=max(gaps) if gaps else None,
                                          by_pair={k: v for k, v in sorted(flams.items(), key=lambda z: -max(z[1]))}))


# ----------------------------------------------------------------- dynamics
def dynamics(rep: dict, wav: Path) -> dict:
    x, _ = sf.read(str(wav), dtype="float64", always_2d=True)
    off = rep["offset_s"]
    res = {}
    for tr in rep["tracks"]:
        notes = tr["note_list"]
        p = tr["part"]
        rows = []
        if p == "timp":
            for (on, o2, key, vel, art) in notes[:6]:
                seg = x[int((on - off + 0.01) * SR): int((on - off + 0.5) * SR)]
                rows.append((M.k_level_db(seg), M.centroid(seg), M.harmonic_richness(seg, key)))
            rows = [rows[0], rows[1], rows[2]]
        else:
            held = [n for n in notes if n[1] - n[0] > 1.2][:3]
            for (on, o2, key, vel, art) in held:
                seg = x[int((on - off + 0.5) * SR): int((o2 - off - 0.2) * SR)]
                rows.append((M.k_level_db(seg), M.centroid(seg), M.harmonic_richness(seg, key)))
        if len(rows) == 3:
            res[p] = dict(klevel_pp_mf_ff=[round(r[0], 1) for r in rows],
                          centroid_pp_mf_ff=[round(r[1]) for r in rows],
                          richness_pp_mf_ff=[None if r[2] is None else round(r[2], 1) for r in rows],
                          pp_to_ff_db=round(rows[2][0] - rows[0][0], 1),
                          richness_change_db=None if None in (rows[0][2], rows[2][2]) else round(rows[2][2] - rows[0][2], 1))
    return res


def crescendo(rep: dict, wav: Path) -> dict:
    x, _ = sf.read(str(wav), dtype="float64", always_2d=True)
    off = rep["offset_s"]
    t = np.arange(1.0, 10.5, 0.5)
    lv, ce = [], []
    for s in t:
        seg = x[int((s - off) * SR): int((s + 0.5 - off) * SR)]
        lv.append(M.k_level_db(seg))
        ce.append(M.centroid(seg))
    cc1 = 36 + 91 * (t + 0.25 - 0.5) / 10
    return dict(t_s=t.tolist(), klevel_db=[round(v, 1) for v in lv], centroid_hz=[round(c) for c in ce],
                level_span_db=round(lv[-1] - lv[0], 1), corr_level_cc1=round(float(np.corrcoef(lv, cc1)[0, 1]), 3),
                corr_centroid_cc1=round(float(np.corrcoef(ce, cc1)[0, 1]), 3),
                non_monotonic_steps=int(sum(np.diff(lv) < -0.5)))


# ----------------------------------------------------------------- balance
def balance(rep: dict, stem_dir: Path, mix: Path) -> dict:
    lv = {}
    for name in ("vn1", "vn2", "va", "vc"):
        x, _ = sf.read(str(stem_dir / f"{name}.wav"), dtype="float64", always_2d=True)
        y = kweight(x.mean(axis=1))
        h = int(0.1 * SR)
        n = len(y) // h
        lv[name] = 10 * np.log10(np.mean(y[: n * h].reshape(n, h) ** 2, axis=1) + 1e-20)
    n = min(len(v) for v in lv.values())
    L = np.stack([lv[k][:n] for k in lv])
    loud = L.max(axis=0)
    res = {}
    for i, k in enumerate(lv):
        act = (L[i] > loud - 40) & (loud > loud.max() - 50)
        rel = (L[i] - loud)[act]
        res[k] = dict(median_db=round(float(np.median(rel)), 1), p10_db=round(float(np.percentile(rel, 10)), 1))
    x, _ = sf.read(str(mix), dtype="float64", always_2d=True)
    return dict(string_voices_re_loudest=res)


def file_checks(wav: Path, rep: dict) -> dict:
    info = sf.info(str(wav))
    x, _ = sf.read(str(wav), dtype="float64", always_2d=True)
    I, lra = lufs(x)
    m4a = wav.with_suffix(".m4a")
    dec = QA / "_m4a_check.wav"
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI24", str(m4a), str(dec)], check=True, capture_output=True)
    y, _ = sf.read(str(dec), dtype="float64", always_2d=True)
    dec.unlink()
    first = np.flatnonzero(np.max(np.abs(x), axis=1) > 10 ** (-60 / 20))
    first_any = np.flatnonzero(np.max(np.abs(x), axis=1) > 1e-5)
    return dict(samplerate=info.samplerate, channels=info.channels, subtype=info.subtype,
                duration_s=round(info.duration, 2), true_peak_dbtp=round(true_peak_db(x), 2),
                m4a_decoded_peak_dbfs=round(float(20 * np.log10(np.max(np.abs(y)))), 2),
                integrated_lufs=round(I, 1), loudness_range_lu=round(lra, 1),
                lr_correlation=round(float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]), 3),
                first_sound_s=round(first[0] / SR, 3) if len(first) else None,
                first_sound_re_midi_ms=round(1000 * (first_any[0] / SR + rep["offset_s"]), 1)
                if len(first_any) else None,
                offset_s=rep["offset_s"], c80_db=rep["c80_db"], wet_db=rep["wet_db"],
                clicks_in_mix=len(M.clicks(x)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--midi", type=Path, default=HERE / "out" / "skeleton_orchestra.mid")
    a = ap.parse_args(argv)
    QA.mkdir(parents=True, exist_ok=True)
    EV.mkdir(exist_ok=True)
    sk = QA / "skeleton"
    if not a.skip_render:
        render(a.midi, sk, "--stems", "--keep-start")
        render(HERE / "out" / "demo_instruments.mid", QA / "instruments", "--no-reverb", "--keep-start")
        render(HERE / "out" / "demo_crescendo.mid", QA / "crescendo", "--keep-start")
    rep = json.loads(sk.with_suffix(".json").read_text())
    res = dict(chain=chain(rep, QA / "skeleton.stems"))
    res["entries"] = entries(rep, QA / "skeleton.stems")
    res["dynamics"] = dynamics(json.loads((QA / "instruments.json").read_text()), QA / "instruments.wav")
    res["crescendo"] = crescendo(json.loads((QA / "crescendo.json").read_text()), QA / "crescendo.wav")
    res["balance"] = balance(rep, QA / "skeleton.stems", sk.with_suffix(".wav"))
    fin = HERE / "out" / "skeleton_orchestra.wav"
    res["file"] = file_checks(fin, json.loads(fin.with_suffix(".json").read_text()))
    (EV / "qa.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res["chain"]["all"], indent=1))
    for k, v in res["chain"]["tracks"].items():
        print(k, {x: v[x] for x in ("notes", "pitch_med_abs_c", "pitch_p95_abs_c", "pitch_worst", "detached_onsets",
                                   "onset_med_ms", "onset_p90_abs_ms", "slurs", "handover_med_ms", "handover_p90_ms",
                                   "sustain_max_step_db", "sustain_steps_over_3db")},
              "clicks", len(v["clicks"]))
    en = res["entries"]
    print("entries (-12 dB rule):", en["all"], "strings", en["strings"], "doubled-entry gaps", 
          {k: en["doubled_entry_gap_ms"][k] for k in ("pairs", "worst")})
    for k, v in en["tracks"].items():
        print("  ", k, v)
    print(json.dumps({k: res[k] for k in ("dynamics", "crescendo", "balance", "file")}, indent=0)[:6000])


if __name__ == "__main__":
    main()
