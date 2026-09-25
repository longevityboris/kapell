#!/usr/bin/env python3
"""Held notes at fixed CC1: level steadiness and pitch inside the layer crossfades.

p (62), mp (75) and f (101) -- most of a performance -- sit between the recorded
layers, where two recordings of the same key (independent vibrato, each with its
own tune= and pitch_random) sound together.  Two nearly-unison harmonic tones
interfere: their sum swells and fades as their phase drifts.  This renders every
third key of each instrument for 8 s at CC1 49 / 62 / 75 / 88 / 101 / 114
(CC20 = 0, velocity 90) straight through sfizz with the renderer's SFZ, and
reports over 1.5-7.5 s: the 100 ms level's standard deviation and peak-to-peak
(dB), the strongest slow modulation (0.1-3 Hz), and the median pitch (cents).
Anchors (49 / 88 / 114 = one layer alone) are the reference.

  python3 qa_layers.py [--inst violin,violin2,viola,cello,bass] [--every 3]
  python3 qa_layers.py --interference   # proof: each layer alone vs their sum

--interference renders a held note at CC1 62, 68, 101 and 107 (68 and 107 lie in the
SFZ's narrow crossfade zones, which render_quartet.py never parks in) three times, each time with
only one layer's regions kept (pitch_random=0), then compares the level wander of
each layer alone, of their actual sum, and of their power sum (what uncorrelated
layers would give): if the sum wanders far more than the power sum, the layers
interfere (comb filtering / beating between two recordings of the same pitch).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import QUARTET, SR, TMP, load, pitch_spectral, save, state  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iowa_common import INSTRUMENTS, SFIZZ_RENDER  # noqa: E402

CCS = [49, 62, 75, 88, 101, 114]
NOTE_S, STEP_S = 8.0, 9.5


def interference():
    import re
    out = {}
    hop = int(0.1 * SR)

    def track(x):
        s = x[int(1.8 * SR): int(7.8 * SR)]
        m = len(s) // hop
        return 10 * np.log10(np.mean(s[: m * hop].reshape(m, hop) ** 2, axis=1) + 1e-20)
    for inst, key in (("violin2", 67), ("cello", 60), ("viola", 54)):
        src = (QUARTET / f"{inst}.sfz").read_text().splitlines()
        for cc in (62, 68, 101, 107):     # 68 / 107: inside the SFZ's narrow crossfade zones
            mf = mido.MidiFile(type=0, ticks_per_beat=960)
            tr = mido.MidiTrack()
            mf.tracks.append(tr)
            tr.append(mido.MetaMessage("set_tempo", tempo=500000))
            last = 0
            for t, m in ((0.1, mido.Message("control_change", control=1, value=cc)),
                         (0.1, mido.Message("control_change", control=20, value=0)),
                         (0.3, mido.Message("note_on", note=key, velocity=90)),
                         (8.3, mido.Message("note_off", note=key, velocity=0))):
                tk = int(round(t * 1920))
                tr.append(m.copy(time=tk - last))
                last = tk
            mp = TMP / f"beat_{inst}_{cc}.mid"
            mf.save(str(mp))
            sig = {}
            for lay in ("pp", "mf", "ff"):
                lines, cur = [], None
                for ln in src:
                    g = re.match(r"<group> // (\w+) art", ln)
                    if g:
                        cur = g.group(1)
                    if ln.startswith("<region>") and cur != lay:
                        continue
                    lines.append(ln.replace("sample=samples/", f"sample={QUARTET}/samples/")
                                 .replace("pitch_random=3", "pitch_random=0"))
                sfz = TMP / f"{inst}_{lay}_only.sfz"
                sfz.write_text("\n".join(lines) + "\n")
                wav = TMP / f"beat_{inst}_{cc}_{lay}.wav"
                subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(mp), "--wav", str(wav), "-s",
                                str(SR)], check=True, capture_output=True)
                sig[lay] = load(wav)
            n = min(len(v) for v in sig.values())
            tr_l = {l: track(v[:n]) for l, v in sig.items() if np.max(np.abs(v)) > 0}
            summ = track(sum(v[:n] for v in sig.values()))
            pw = 10 * np.log10(sum(10 ** (t / 10) for t in tr_l.values()))
            out[f"{inst}/{key}/cc1={cc}"] = dict(
                layer_alone_p2p_db={l: round(float(t.max() - t.min()), 1) for l, t in tr_l.items()},
                layer_level_db={l: round(float(t.mean()), 1) for l, t in tr_l.items()},
                actual_sum_p2p_db=round(float(summ.max() - summ.min()), 1),
                power_sum_p2p_db=round(float(pw.max() - pw.min()), 1))
            print(inst, key, cc, out[f"{inst}/{key}/cc1={cc}"])
    save("layers_interference.json", dict(state=state(), results=out))


def main():
    if "--interference" in sys.argv:
        return interference()
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", default="violin,violin2,viola,cello,bass")
    ap.add_argument("--every", type=int, default=3)
    a = ap.parse_args()
    d = TMP / "layers"
    d.mkdir(parents=True, exist_ok=True)
    res = dict(state=state(), cc1=CCS, note_s=NOTE_S, instruments={})
    for inst in a.inst.split(","):
        lo, hi = INSTRUMENTS[inst]["lo"], INSTRUMENTS[inst]["hi"]
        keys = list(range(lo, hi + 1, a.every))
        mf = mido.MidiFile(type=0, ticks_per_beat=960)
        tr = mido.MidiTrack()
        mf.tracks.append(tr)
        tr.append(mido.MetaMessage("set_tempo", tempo=500000))
        ev, sched = [], []
        t = 0.3
        for k in keys:
            for cc in CCS:
                ev += [(t - 0.1, 0, mido.Message("control_change", control=1, value=cc)),
                       (t - 0.1, 0, mido.Message("control_change", control=20, value=0)),
                       (t - 0.1, 0, mido.Message("control_change", control=21, value=20)),
                       (t, 2, mido.Message("note_on", note=k, velocity=90)),
                       (t + NOTE_S, 1, mido.Message("note_off", note=k, velocity=0))]
                sched.append((k, cc, t))
                t += STEP_S
        ev.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for s, _, m in ev:
            tk = int(round(s * 1920))
            tr.append(m.copy(time=tk - last))
            last = tk
        mp, wav = d / f"{inst}.mid", d / f"{inst}.wav"
        mf.save(str(mp))
        subprocess.run([str(SFIZZ_RENDER), "--sfz", str(QUARTET / f"{inst}.sfz"), "--midi", str(mp), "--wav",
                        str(wav), "-s", str(SR), "-q", "3"], check=True, capture_output=True)
        x = load(wav)
        rows = []
        for k, cc, t in sched:
            seg = x[int((t + 1.5) * SR): int((t + 7.5) * SR)]
            hop = int(0.1 * SR)
            n = len(seg) // hop
            lv = 10 * np.log10(np.mean(seg[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20)
            L = lv - lv.mean()
            F = np.abs(np.fft.rfft(L * np.hanning(len(L)), 256))
            fq = np.fft.rfftfreq(256, 0.1)
            band = (fq >= 0.1) & (fq <= 3)
            fmod = float(fq[band][int(np.argmax(F[band]))])
            m, _ = pitch_spectral(seg, k, span=2)
            rows.append(dict(key=k, cc1=cc, level_db=round(float(10 * np.log10(np.mean(seg ** 2) + 1e-20)), 2),
                             std_db=round(float(lv.std()), 2), p2p_db=round(float(lv.max() - lv.min()), 2),
                             slow_mod_hz=round(fmod, 2), cents=round(100 * (m - k), 1)))
        summ = {}
        for cc in CCS:
            r = [q for q in rows if q["cc1"] == cc]
            summ[cc] = dict(median_std_db=round(float(np.median([q["std_db"] for q in r])), 2),
                            max_std_db=round(float(np.max([q["std_db"] for q in r])), 2),
                            median_p2p_db=round(float(np.median([q["p2p_db"] for q in r])), 2),
                            max_p2p_db=round(float(np.max([q["p2p_db"] for q in r])), 2),
                            median_abs_cents=round(float(np.median([abs(q["cents"]) for q in r])), 1),
                            max_abs_cents=round(float(np.max([abs(q["cents"]) for q in r])), 1))
        # loudness steps between consecutive CC1 values, per key
        steps = []
        for k in keys:
            lv = [next(q["level_db"] for q in rows if q["key"] == k and q["cc1"] == cc) for cc in CCS]
            steps.append(np.diff(lv))
        steps = np.array(steps)
        summ["level_step_db_per_13cc"] = dict(median=[round(float(v), 1) for v in np.median(steps, axis=0)],
                                              min=[round(float(v), 1) for v in steps.min(axis=0)],
                                              max=[round(float(v), 1) for v in steps.max(axis=0)],
                                              nonmonotonic=int((steps < 0).sum()))
        worst = sorted(rows, key=lambda q: -q["p2p_db"])[:8]
        res["instruments"][inst] = dict(summary=summ, worst_p2p=worst, rows=rows)
        print(inst, {cc: (summ[cc]["median_p2p_db"], summ[cc]["max_p2p_db"], summ[cc]["max_abs_cents"]) for cc in CCS},
              "steps", summ["level_step_db_per_13cc"])
        print("   worst", [(w["key"], w["cc1"], w["p2p_db"], w["slow_mod_hz"]) for w in worst[:5]])
    p = save("layers.json", res)
    print("->", p)


if __name__ == "__main__":
    main()
