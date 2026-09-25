#!/usr/bin/env python3
"""Final-mix QA of the fugue renders made by qa_chain.py (demo plan and QA plan).

Clipping, true peak (own 4x oversampling) of WAV and decoded M4A, M4A format and
alignment, DC, noise floor, tail, stereo (balance, correlation, mono fold-down),
voice balance from the dry stems, subject entries against the other voices, and
low-end build-up.

    python3 qa/qa_mix.py      # writes qa/results/mix.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy.signal as ss

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import LEAD_IN, QA, PIANO, SR, TMP, db, kweight, midi_notes, read, rms_db, save  # noqa: E402


def true_peak_db(x: np.ndarray) -> float:
    up = ss.resample_poly(x, 4, 1, axis=0)
    return round(20 * np.log10(np.abs(up).max()), 3)


def decode_m4a(m4a: Path) -> np.ndarray:
    wav = m4a.with_suffix(".decoded.wav")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEF32@48000", str(m4a), str(wav)], check=True)
    return read(wav)


def band_db(x: np.ndarray, lo: float, hi: float) -> float:
    sos = ss.butter(4, [lo, hi] if lo > 0 else hi, "band" if lo > 0 else "low", fs=SR, output="sos")
    return rms_db(ss.sosfilt(sos, x, axis=0))


def analyse(name: str, plan: Path) -> dict:
    wav = TMP / f"fugue_{name}.wav"
    x = read(wav)
    res = {}
    full = np.abs(x) >= (1 - 2 ** -22)
    res["clipped_samples"] = int(full.sum())
    res["sample_peak_dbfs"] = round(20 * np.log10(np.abs(x).max()), 3)
    res["true_peak_wav_dbtp"] = true_peak_db(x)
    info = subprocess.run(["afinfo", str(wav.with_suffix(".m4a"))], capture_output=True, text=True).stdout
    res["m4a_info"] = [l.strip() for l in info.splitlines() if any(k in l for k in ("Data format", "bit rate", "estimated duration"))]
    y = decode_m4a(wav.with_suffix(".m4a"))
    res["true_peak_m4a_dbtp"] = true_peak_db(y)
    # alignment of decoded m4a vs wav (first 20 s)
    a, b = x[: 20 * SR, 0], y[: 20 * SR + 4800, 0]
    c = ss.correlate(b, a, mode="valid", method="fft")
    lag = int(np.argmax(c))
    res["m4a_lag_samples"] = lag
    res["m4a_length_diff_ms"] = round((len(y) - len(x)) / SR * 1000, 1)
    n = min(len(x), len(y) - lag)
    res["m4a_error_rel_db"] = round(rms_db(y[lag: lag + n] - x[:n]) - rms_db(x[:n]), 1)
    res["dc_per_channel"] = [float(f"{v:.2e}") for v in x.mean(axis=0)]
    res["lead_in_noise_dbfs"] = round(rms_db(x[: int(0.25 * SR)]), 1)
    # tail: 50 ms windows over the last 3 s
    tail = x[-3 * SR:]
    fr = int(0.05 * SR)
    env = [round(rms_db(tail[i * fr:(i + 1) * fr]), 1) for i in range(len(tail) // fr)]
    res["tail_env_db_50ms_last3s"] = env
    steps = np.diff(env[:-1])
    res["tail_max_step_db_excl_fade"] = round(float(steps.max()), 1)
    res["tail_last_window_db_rel_peak"] = round(env[-2] - 20 * np.log10(np.abs(x).max()), 1)
    # stereo
    L, R = x[:, 0], x[:, 1]
    res["lr_balance_db"] = round(db(np.mean(L ** 2)) - db(np.mean(R ** 2)), 2)
    res["lr_corr"] = round(float(np.corrcoef(L, R)[0, 1]), 3)
    res["mono_foldown_loss_db"] = round(db(np.mean(((L + R) / 2) ** 2)) - db(np.mean((L ** 2 + R ** 2) / 2)), 2)
    # per-second mono loss distribution (loud seconds only)
    sec = []
    for i in range(len(x) // SR):
        s = x[i * SR:(i + 1) * SR]
        if rms_db(s) > rms_db(x) - 15:
            sec.append(db(np.mean(((s[:, 0] + s[:, 1]) / 2) ** 2)) - db(np.mean((s ** 2).mean(axis=1))))
    res["mono_loss_per_second_db"] = {"min": round(min(sec), 1), "median": round(float(np.median(sec)), 1)}
    # spectrum balance: octave bands of the whole mix, dB re total
    bands = {}
    tot = rms_db(x)
    for lo, hi in ((20, 63), (63, 125), (125, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 16000)):
        bands[f"{lo}-{hi}"] = round(band_db(x, lo, hi) - tot, 1)
    res["octave_bands_db_re_total"] = bands
    # stems: voice balance
    stems = {p.stem: read(p) for p in sorted(Path(f"/tmp/pianoqa/fugue_{name}_stems").glob("*.wav"))}
    res["stem_rms_db"] = {k: round(rms_db(v), 2) for k, v in stems.items()}
    res["stem_kweighted_db"] = {k: round(rms_db(kweight(v)), 2) for k, v in stems.items()}
    # subject entries: K-weighted level of the entering voice vs the loudest other voice, in its window
    notes = midi_notes(TMP / f"fugue_{name}.mid")
    plan_d = json.loads(plan.read_text())
    tempo_notes = {}
    for n in notes:
        tempo_notes.setdefault(n["voice"], []).append(n)
    # bar starts from the MIDI: perform.py writes no bar markers, so map bars via the demo tempo grid:
    # use the notes' own bar positions from the score instead -> approximate with the QA per-bar clock below
    ent = []
    from qa_lib import PERFORM  # noqa: F401
    sys.path.insert(0, str(PERFORM.parent))
    import perform as P  # the plan clock, for bar -> seconds
    pl = P.Plan(plan_d)
    # rebuild perform.py's seconds grid exactly as build() does
    src = (PIANO.parents[2] / "fugue.ly").read_text()
    from lyparse import parse_voice
    vv = {v: parse_voice(src, v, pl.measure) for v in pl.voices}
    end = max(nn[-1].end for nn in vv.values() if nn)
    from fractions import Fraction as F
    step = F(1, 16)
    bpmf = pl.bpm_quarter_fn()
    breaths = {pl.pos(b["at"]): b["ms"] / 1000 for b in plan_d.get("breaths", [])}
    ferm = {pl.pos(q["at"]): q["extra_beats"] for q in plan_d.get("fermatas", [])}
    gs, t, s = [0.0], F(0), 0.0
    while t < end + F(1, 2):
        bpm = bpmf(t)
        stretch = 1.0 + (ferm[t] / 0.25 if t in ferm else 0) + (breaths[t + step] / (60.0 / bpm / 4) if t + step in breaths else 0)
        s += 60.0 / bpm / 4 * stretch
        t += step
        gs.append(s)

    def bar_s(pos: str) -> float:
        return gs[int(pl.pos(pos) / step)]
    for r in plan_d.get("roles", []):
        if r["role"] not in ("subject", "answer"):
            continue
        a, b = bar_s(r["at"]) + LEAD_IN, bar_s(r["until"]) + LEAD_IN
        seg = {k: rms_db(kweight(v[int(a * SR): int(b * SR)])) for k, v in stems.items()}
        others = [seg[k] for k in seg if k != r["voice"]]
        ent.append(dict(voice=r["voice"], at=r["at"], entering_db=round(seg[r["voice"]], 1),
                        margin_over_loudest_other_db=round(seg[r["voice"]] - max(others), 1),
                        margin_over_mean_other_db=round(seg[r["voice"]] - 10 * np.log10(np.mean([10 ** (o / 10) for o in others])), 1)))
    res["entries"] = ent
    # per-bar loudness (K-weighted, mix) to see the dynamic plan
    bars = []
    nb = int(end / pl.measure)
    for bnum in range(1, nb + 1):
        a, b = bar_s(f"{bnum}:1") + LEAD_IN, bar_s(f"{bnum + 1}:1") + LEAD_IN if bnum < nb else bar_s(f"{bnum}:1") + LEAD_IN + 2
        bars.append(round(rms_db(kweight(x[int(a * SR): int(b * SR)])), 1))
    res["bar_kweighted_db"] = bars
    return res


def main() -> None:
    out = {}
    for name, plan in (("demo", PIANO / "plans" / "fugue_jp.plan.json"), ("qa", QA / "fugue_qa.plan.json")):
        out[name] = analyse(name, plan)
        print(name, json.dumps(out[name])[:3000])
    save("mix", out)


if __name__ == "__main__":
    main()
