#!/usr/bin/env python3
"""CC1 ladder check of a built string instrument (through sfizz).

For every 3rd key of the range, a 1.6 s note is played at each CC1 value of a
ladder from ppp (36) to fff (127) on perform.py's scale.  For each note the
A-weighted level and the spectral centroid of the steady part are measured.
Reports, per instrument:
  * loudness vs CC1 (median over keys, dB re ff) against the design target,
  * the worst non-monotonic step (a louder CC1 value that sounds softer),
  * the spread of the pp->ff level range over keys (evenness of the layers),
  * the centroid ratio ff / pp (timbre change; 1.0 would be gain-only).

Usage:
  python3 verify_dynamics.py violin viola cello [--lib iowa|vpo3] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from iowa_common import INSTRUMENTS, QUARTET_DIR, SFIZZ_RENDER, midi_name  # noqa: E402
from measure_dynamics import a_weight  # noqa: E402
from scipy.signal import lfilter  # noqa: E402

SR = 48000
LADDER = [36, 42, 49, 55, 62, 68, 75, 81, 88, 94, 101, 107, 114, 120, 127]
NOTE_S, STEP_S = 1.6, 2.1


def target_db():
    from iowa_build import CC1_TARGET
    tx, ty = zip(*CC1_TARGET)
    return {c: float(np.interp(c, tx, ty)) for c in LADDER}


def render(sfz: Path, keys, tmp: Path, tag: str):
    mid = mido.MidiFile(type=0, ticks_per_beat=960)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("set_tempo", tempo=500000))
    tps = 1920
    ev = [(0, 0, mido.Message("control_change", control=11, value=127))]
    order = []
    i = 0
    for k in keys:
        for c in LADDER:
            t0 = int((0.2 + i * STEP_S) * tps)
            ev.append((t0 - 20, 0, mido.Message("control_change", control=1, value=c)))
            ev.append((t0, 1, mido.Message("note_on", note=k, velocity=100)))
            ev.append((t0 + int(NOTE_S * tps), 1, mido.Message("note_off", note=k, velocity=0)))
            order.append((k, c, 0.2 + i * STEP_S))
            i += 1
    ev.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for t, _, m in ev:
        tr.append(m.copy(time=max(0, t - last)))
        last = max(last, t)
    tr.append(mido.MetaMessage("end_of_track", time=tps))
    mid.tracks.append(tr)
    mp, wp = tmp / f"{tag}.mid", tmp / f"{tag}.wav"
    mid.save(str(mp))
    r = subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(mp), "--wav", str(wp),
                        "-s", str(SR), "-q", "3"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    x, _ = sf.read(str(wp), dtype="float64", always_2d=True)
    return x.mean(axis=1), order


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inst", nargs="+")
    ap.add_argument("--lib", default="iowa", choices=["iowa", "vpo3"])
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="dyn_"))
    aw = a_weight(SR)
    tgt = target_db()
    report = {}
    for inst in a.inst:
        if a.lib == "iowa":
            sfz = QUARTET_DIR / f"{inst}.sfz"
            lo, hi = INSTRUMENTS[inst]["lo"], INSTRUMENTS[inst]["hi"]
        else:
            from vpo3 import VPO3_RANGE, VPO3_SFZ
            sfz = VPO3_SFZ[inst]
            lo, hi = VPO3_RANGE[inst]
        keys = list(range(lo, hi + 1, 3))
        m, order = render(sfz, keys, tmp, inst)
        am = lfilter(*aw, m)
        lv, cen = {}, {}
        for k, c, t in order:
            a0, a1 = int((t + 0.45) * SR), int((t + NOTE_S - 0.1) * SR)
            lv[(k, c)] = 10 * np.log10(np.mean(am[a0:a1] ** 2) + 1e-20)
            seg = m[a0:a1] * np.hanning(a1 - a0)
            P = np.abs(np.fft.rfft(seg)) ** 2
            f = np.fft.rfftfreq(len(seg), 1 / SR)
            cen[(k, c)] = float((P * f).sum() / (P.sum() + 1e-20))
        rows = []
        worst = (0.0, None)
        spans = []
        cratio = []
        for k in keys:
            ref = lv[(k, 114)]
            rel = [lv[(k, c)] - ref for c in LADDER]
            for (c0, r0), (c1, r1) in zip(zip(LADDER, rel), zip(LADDER[1:], rel[1:])):
                if r0 - r1 > worst[0]:
                    worst = (r0 - r1, f"{midi_name(k)} {c0}->{c1}")
            spans.append(lv[(k, 114)] - lv[(k, 49)])
            cratio.append(cen[(k, 114)] / cen[(k, 49)])
            rows.append(dict(key=k, name=midi_name(k), rel_db=[round(r, 2) for r in rel],
                             centroid=[round(cen[(k, c)]) for c in LADDER]))
        med = np.median(np.array([r["rel_db"] for r in rows]), axis=0)
        dev = [round(float(mv - tgt[c]), 2) for mv, c in zip(med, LADDER)]
        report[inst] = dict(ladder=LADDER, median_rel_db=[round(float(v), 2) for v in med],
                            target_rel_db=[tgt[c] for c in LADDER], worst_inversion_db=round(worst[0], 2),
                            worst_inversion_at=worst[1], pp_to_ff_span_db=dict(
                                median=round(float(np.median(spans)), 2), min=round(float(np.min(spans)), 2),
                                max=round(float(np.max(spans)), 2)),
                            centroid_ratio_ff_over_pp=dict(median=round(float(np.median(cratio)), 3),
                                                           min=round(float(np.min(cratio)), 3)),
                            keys=rows)
        print(f"{inst:7s} {a.lib}: dB re ff at CC1 " + " ".join(f"{c}:{v:+.1f}" for c, v in zip(LADDER, med)))
        print(f"        deviation from target (dB): " + " ".join(f"{d:+.1f}" for d in dev))
        print(f"        worst inversion {worst[0]:.2f} dB ({worst[1]}); pp->ff span median "
              f"{np.median(spans):.1f} dB (min {np.min(spans):.1f}, max {np.max(spans):.1f}); "
              f"centroid ff/pp median {np.median(cratio):.2f} (min {np.min(cratio):.2f})")
    if a.json:
        a.json.write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
