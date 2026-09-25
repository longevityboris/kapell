#!/usr/bin/env python3
"""Independent QA of an orchestrated mix: every part note on the rendered stems, and the final files.

usage: python3 qa_mix.py OUTDIR [--out RESULTS.json]
  OUTDIR = orchestrate.py's output directory after mix.py has run (manifest.json, <group>.mid,
  render/<group>/ stems, and the mix next to OUTDIR: <OUTDIR>.wav/.m4a/.mix.json)

Per note of every part (read from the group MIDI with mido, not from orchestrate.py):
  * pitch: the strongest of partials 1-4 near the expected frequency, parabolic peak, in cents
    re equal temperament (A4 = 440), in the steady part of the note (60 ms after the onset, up to
    400 ms); a note whose partials are no stronger than their surroundings counts as dropped;
  * onset: peak of the stem's onset envelope within -30..+60 ms of the note-on;
  * body level: the median of 20 ms RMS frames over the note's body (60 ms after the onset to
    20 ms before the note-off, at most 1.5 s), in dB re the stem's peak. A note is flagged as cut
    (silent) when its body is below -80 dB re peak, or more than 20 dB under both the previous and
    the next note on the same stem. The pitch check looks at the first 400 ms, where the previous
    note's release may still ring at the same pitch: a note the renderer cuts (a same-key note-off
    arriving after the new note-on) passed it. Comparing with both neighbours keeps a subito or a
    hairpin's first note from counting.
Per part: silence where it rests for over 1.5 s (a stuck or misrouted note would sound there) and
after its last note (2 s after the note-off).
Final files: format, true peak and loudness by ffmpeg (ebur128, independent of mix.py), m4a vs
WAV alignment by cross-correlation, duration.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
R = HERE.parent.parent
sys.path.insert(0, str(R / "tools"))
import mix  # noqa: E402  (stem loading and the onset envelope only)

SR = 48000


def notes_of(midi: Path) -> dict:
    """{track name: [(on_s, off_s, key)]} through the tempo map."""
    mid = mido.MidiFile(str(midi))
    ons = mix.midi_onsets(midi)
    out = {}
    # pair offs: re-read with seconds
    tempos = sorted((t, m.tempo) for tr in mid.tracks for t, m in mix._abs(tr) if m.type == "set_tempo")
    pts, s, lt, us = [], 0.0, 0, 500000
    for t, tempo in tempos:
        s += (t - lt) * us / 1e6 / mid.ticks_per_beat
        pts.append((t, s, tempo))
        lt, us = t, tempo
    ticks = np.array([p[0] for p in pts])

    def sec(tick):
        i = max(0, int(np.searchsorted(ticks, tick, side="right")) - 1)
        t, s0, u = pts[i]
        return s0 + (tick - t) * u / 1e6 / mid.ticks_per_beat

    for tr in mid.tracks:
        name = next((m.name for m in tr if m.type == "track_name"), "")
        pend, lst = {}, []
        for t, m in mix._abs(tr):
            if m.type == "note_on" and m.velocity > 0:
                pend.setdefault(m.note, []).append(sec(t))
            elif m.type in ("note_off", "note_on") and pend.get(m.note):
                lst.append((pend[m.note].pop(0), sec(t), m.note))
        if lst:
            out[name] = sorted(lst)
    del ons
    return out


def pitch_cents(x: np.ndarray, key: int) -> tuple:
    """-> (cents re key, partial used, prominence dB) or (None, None, prominence)."""
    f0 = 440.0 * 2 ** ((key - 69) / 12)
    n = len(x)
    if n < 1024:
        return None, None, 0.0
    w = np.hanning(n)
    nfft = 1 << int(math.ceil(math.log2(n * 8)))
    spec = np.abs(np.fft.rfft(x * w, nfft))
    freqs = np.fft.rfftfreq(nfft, 1 / SR)
    best = None
    for h in (1, 2, 3, 4):
        fc = f0 * h
        if fc > SR / 2 - 1000:
            break
        lo, hi = fc * 2 ** (-60 / 1200), fc * 2 ** (60 / 1200)
        band = (freqs >= lo) & (freqs <= hi)
        if not band.any():
            continue
        idx = np.nonzero(band)[0]
        k = idx[np.argmax(spec[idx])]
        if k in (idx[0], idx[-1]):     # the band's edge on the slope of a neighbour (e.g. a note still
            continue                   # ringing a semitone away): not this note's partial
        # surroundings: a semitone band either side, excluding the partial's own band
        wl, wh = fc * 2 ** (-200 / 1200), fc * 2 ** (200 / 1200)
        around = (freqs >= wl) & (freqs <= wh) & ~band
        prom = 20 * math.log10(spec[k] / (np.median(spec[around]) + 1e-12))
        if best is None or spec[k] > best[0]:
            if 0 < k < len(spec) - 1:
                a, b, c = np.log(spec[k - 1] + 1e-20), np.log(spec[k] + 1e-20), np.log(spec[k + 1] + 1e-20)
                d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
            else:
                d = 0.0
            f = (k + d) * SR / nfft
            best = (spec[k], 1200 * math.log2(f / fc), h, prom)
    if best is None:
        return None, None, 0.0
    return best[1], best[2], best[3]


BODY_FRAME_S = 0.02
BODY_FLOOR_DB = -80.0       # re the stem's peak
BODY_DROP_DB = 20.0         # under both neighbours


def body_levels(mono: np.ndarray, lst: list, lead: float) -> list:
    """Per note: median 20 ms RMS frame level over its body, dB re the stem's sample peak."""
    hop = int(BODY_FRAME_S * SR)
    nfr = len(mono) // hop
    fr = np.sqrt(np.mean(mono[:nfr * hop].reshape(nfr, hop) ** 2, axis=1))
    peak = np.max(np.abs(mono)) + 1e-12
    out = []
    for on, off, _ in lst:
        a, b = on + 0.06, min(off - 0.02, on + 1.5)
        if b - a < 2 * BODY_FRAME_S:
            a, b = on + 0.02, max(off, on + 0.06)
        i, j = int((a + lead) / BODY_FRAME_S), max(int((b + lead) / BODY_FRAME_S), int((a + lead) / BODY_FRAME_S) + 1)
        seg = fr[i:j]
        lv = 20 * math.log10(float(np.median(seg)) / peak + 1e-12) if len(seg) else -240.0
        out.append(round(lv, 1))
    return out


def body_flags(lst: list, lv: list) -> list:
    """Notes whose body is silent or far under both neighbours: [(on_s, key, dB, prev dB, next dB)]."""
    flags = []
    for i, (on, _, key) in enumerate(lst):
        nb = [lv[k] for k in (i - 1, i + 1) if 0 <= k < len(lv)]
        cut = lv[i] < BODY_FLOOR_DB or (nb and all(lv[i] < x - BODY_DROP_DB for x in nb))
        if cut:
            flags.append((round(on, 2), key, lv[i], lv[i - 1] if i else None, lv[i + 1] if i + 1 < len(lv) else None))
    return flags


def main():
    outdir = Path(sys.argv[1]).resolve()
    res_path = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else \
        HERE / "results" / f"qa_{outdir.name}.json"
    man = json.loads((outdir / "manifest.json").read_text())
    lead = float(man.get("lead_in", 0.5))
    mixrep = json.loads((outdir.parent / f"{outdir.name}.mix.json").read_text())
    results = {"parts": {}, "files": {}}
    all_ok = True
    for g, gm in man["groups"].items():
        rdir = outdir / "render" / g
        rr = mix.render_group(gm["renderer"], outdir / gm["midi"], rdir, lead, gm.get("render_args", []), False,
                              None)
        n = max(sf.info(str(p)).frames for _, p in rr["stems"]) + SR
        stems = mix.load_stems(rr["stems"], rr["offset_s"], lead, n)
        notes = notes_of(outdir / gm["midi"])
        inst_of = {v["track"]: (v.get("instrument") or v["track"]) for v in gm["parts"].values()}
        for track, lst in notes.items():
            stem_name = inst_of.get(track, track) if gm["renderer"] == "quartet" else track
            x = stems.get(stem_name)
            if x is None:
                results["parts"][f"{g}/{track}"] = {"error": "no stem"}
                all_ok = False
                continue
            mono = x.mean(axis=1)
            env = mix.onset_envelope(x)
            cents, drops, lagl, used = [], [], [], []
            for on, off, key in lst:
                a = int((on + lead + 0.06) * SR)
                b = int((min(off, on + 0.4) + lead) * SR)
                if b - a < int(0.05 * SR):
                    a, b = int((on + lead + 0.02) * SR), int((off + lead) * SR)
                c, h, prom = pitch_cents(mono[a:b], key)
                if c is None or prom < 6:
                    drops.append(round(on, 2))
                else:
                    cents.append(c)
                    used.append(h)
                k = int(round((on + lead) * 1000))
                seg = env[max(0, k - 30):k + 60]
                if len(seg) == 90 and seg.max() > 0:
                    lagl.append(int(np.argmax(seg)) - 30)
            cents = np.array(cents)
            body = body_levels(mono, lst, lead)
            cut = body_flags(lst, body)
            # silence in long rests and after the end
            peak = np.max(np.abs(mono)) + 1e-12
            rests, loud = 0, []
            spans = [(lst[i][1], lst[i + 1][0]) for i in range(len(lst) - 1)] + [(lst[-1][1], None)]
            for t0, t1 in spans:
                a = t0 + 2.0
                bnd = (t1 - 0.2) if t1 is not None else a + 1.0
                if bnd - a < 0.5:
                    continue
                rests += 1
                seg = mono[int((a + lead) * SR):int((bnd + lead) * SR)]
                if len(seg):
                    lv = 20 * math.log10(np.sqrt(np.mean(seg ** 2)) / peak + 1e-12)
                    if lv > -60:
                        loud.append((round(a, 1), round(lv, 1)))
            ok = len(drops) == 0 and (len(cents) == 0 or np.percentile(np.abs(cents), 95) < 35) and not loud \
                and not cut
            all_ok &= ok
            results["parts"][f"{g}/{track}"] = {
                "notes": len(lst), "pitched": int(len(cents)), "dropped": drops[:10],
                "body_cut": [list(c) for c in cut[:10]],
                "body_db_re_peak_min_median": [min(body), round(float(np.median(body)), 1)] if body else None,
                "cents_median": round(float(np.median(cents)), 1) if len(cents) else None,
                "cents_abs_p95": round(float(np.percentile(np.abs(cents), 95)), 1) if len(cents) else None,
                "cents_worst": round(float(cents[np.argmax(np.abs(cents))]), 1) if len(cents) else None,
                "partials_used": {str(k): used.count(k) for k in sorted(set(used))},
                "onset_lag_ms_median": float(np.median(lagl)) if lagl else None,
                "onset_lag_ms_p10_p90": [float(np.percentile(lagl, 10)), float(np.percentile(lagl, 90))] if lagl else None,
                "rests_checked": rests, "sound_in_rests_dB_re_peak": loud[:5], "pass": bool(ok)}
            print(f"{g}/{track:12s} {len(lst):4d} notes  drops {len(drops)}  cut {cut[:3]}  cents med "
                  f"{results['parts'][f'{g}/{track}']['cents_median']} p95 {results['parts'][f'{g}/{track}']['cents_abs_p95']}"
                  f"  onset med {results['parts'][f'{g}/{track}']['onset_lag_ms_median']} ms  rests {rests} loud {loud[:2]}")
    # final files
    wav = Path(mixrep["output"]["wav"])
    m4a = Path(mixrep["output"]["m4a"])
    info = sf.info(str(wav))
    results["files"]["wav_format"] = [info.samplerate, info.channels, info.subtype]

    def ebur(p):
        r = subprocess.run(["ffmpeg", "-nostats", "-i", str(p), "-filter_complex", "ebur128=peak=true", "-f", "null",
                            "-"], capture_output=True, text=True)
        tail = r.stderr[r.stderr.rfind("Summary:"):]
        vals = {}
        for line in tail.splitlines():
            line = line.strip()
            for k in ("I:", "LRA:", "Peak:"):
                if line.startswith(k):
                    vals[k[:-1]] = float(line.split()[1])
        return vals
    results["files"]["ffmpeg_wav"] = ebur(wav)
    results["files"]["ffmpeg_m4a"] = ebur(m4a)
    x = sf.read(str(wav), dtype="float64", always_2d=True)[0].mean(axis=1)
    dec = Path("/tmp/qa_mix_dec.wav")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEF32", str(m4a), str(dec)], check=True)
    y = sf.read(str(dec), dtype="float64", always_2d=True)[0].mean(axis=1)
    a, b = x[SR * 20:SR * 40], y[SR * 20:SR * 40 + 4096]
    c = np.correlate(b, a[:SR * 5], mode="valid")
    results["files"]["m4a_lag_samples"] = int(np.argmax(c))
    results["files"]["duration_s"] = [round(len(x) / SR, 2), round(len(y) / SR, 2)]
    tp_ok = results["files"]["ffmpeg_wav"].get("Peak", 0) <= -0.9 and results["files"]["ffmpeg_m4a"].get("Peak", 0) <= -0.8
    results["files"]["pass"] = bool(info.samplerate == 48000 and info.channels == 2 and info.subtype == "PCM_24"
                                    and tp_ok)
    all_ok &= results["files"]["pass"]
    results["pass"] = bool(all_ok)
    res_path.parent.mkdir(parents=True, exist_ok=True)
    res_path.write_text(json.dumps(results, indent=1))
    print(json.dumps(results["files"], indent=1))
    print("QA", "PASS" if all_ok else "FAIL", "->", res_path)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
