#!/usr/bin/env python3
"""End-to-end chain QA: fugue.ly + plan -> perform.py --target piano -> render_piano.py.

For each plan (the demo plan and qa/fugue_qa.plan.json):

1. MIDI layer: the input MIDI (parsed independently with mido) against the per-voice
   stem MIDIs that sfizz actually rendered (--keep-temp): note count, pitch
   (+ transpose), onset time, note-off pairing, and what key sharing changed.
2. Audio layer: on each dry stem, every MIDI note-on must produce an onset
   (log spectral flux peak) within +-20 ms, and the note's own harmonics must
   rise at that moment (presence check). Reports latency distribution, misses.
3. Releases: for notes whose key is not struck again in that voice for 1.2 s,
   the energy in the note's harmonic bands 0.35-0.45 s after the note-off
   relative to 0-0.05 s before it (should fall by >= 15 dB unless the pedal is down).

    python3 qa/qa_chain.py      # writes qa/results/chain_<plan>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import mido
import numpy as np
from scipy.signal import find_peaks

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import (LEAD_IN, PIANO, QA, ROOT, SR, TMP, harmonic_band_energy, midi_notes, onset_flux,  # noqa: E402
                    perform, read, render, save)

PLANS = {"demo": PIANO / "plans" / "fugue_jp.plan.json", "qa": QA / "fugue_qa.plan.json"}
TRANSPOSE = {"pedal": -12}


def stem_midi_notes(path: Path) -> list[dict]:
    mf = mido.MidiFile(path)
    t, out, pend = 0.0, [], {}
    for m in mf:  # mido applies the (single) tempo
        t += m.time
        if m.type == "note_on" and m.velocity > 0:
            pend.setdefault(m.note, []).append((t, m.velocity))
        elif m.type in ("note_on", "note_off"):
            if pend.get(m.note):
                st, v = pend[m.note].pop(0)
                out.append(dict(key=m.note, start=st, end=t, vel=v))
    unterminated = sum(len(v) for v in pend.values())
    return out, unterminated


def analyse(name: str, plan: Path) -> dict:
    mid = TMP / f"fugue_{name}.mid"
    perform(ROOT / "fugue.ly", plan, mid, "piano")
    out = TMP / f"fugue_{name}"
    rep = render(mid, out, "--transpose", "pedal=-12", "--keep-temp")
    temp = Path(rep["temp"])
    notes = midi_notes(mid)
    voices = list(rep["voices"])  # stem order == report order
    res = {"render": {k: rep[k] for k in ("duration_s", "key_sharing", "c80_db", "normalise_gain_db", "rms_dbfs",
                                          "measured")},
           "voices": {}}
    for i, v in enumerate(voices):
        vin = [n for n in notes if n["voice"] == v]
        sm, unterminated = stem_midi_notes(temp / f"stem{i:02d}.mid")
        tr = TRANSPOSE.get(v, 0)
        # --- MIDI layer: match by (key, onset) --------------------------------------------
        used = set()
        dt_midi, missing, key_err = [], [], 0
        for n in vin:
            best = None
            for j, s in enumerate(sm):
                if j in used or s["key"] != n["key"] + tr:
                    continue
                d = s["start"] - (n["start"] + LEAD_IN)
                if abs(d) < 0.005 and (best is None or abs(d) < abs(best[1])):
                    best = (j, d)
            if best is None:
                missing.append(n)
            else:
                used.add(best[0])
                dt_midi.append(best[1])
                s = sm[best[0]]
                n["stem_end"] = s["end"] - LEAD_IN
        dur_changed = [n for n in vin if "stem_end" in n and abs(n["stem_end"] - n["end"]) > 0.002]
        # --- audio layer -------------------------------------------------------------------
        x = read(Path(str(out) + "_stems") / f"{v}.wav")
        ft, flux = onset_flux(x)
        pk, _ = find_peaks(flux, height=np.percentile(flux, 50), distance=int(0.02 * SR / 48))
        pt = ft[pk]
        lat, miss_audio, weak = [], [], []
        for n in vin:
            t_on = n["start"] + LEAD_IN
            near = pt[(pt > t_on - 0.02) & (pt < t_on + 0.03)]
            if len(near) == 0:
                miss_audio.append(n)
            else:
                # frame centre of a 512-sample window: the flux peak sits ~ half a window after the attack
                lat.append(float(near[np.argmin(np.abs(near - t_on - 0.005))] - t_on))
            k = n["key"] + tr
            pre = harmonic_band_energy(x, k, t_on - 0.06, t_on - 0.002)
            post = harmonic_band_energy(x, k, t_on + 0.005, t_on + 0.065)
            n["rise_db"] = post - pre
            if post - pre < 3:
                weak.append(dict(key=k, t=round(n["start"], 3), rise_db=round(post - pre, 1), vel=n["vel"]))
        # --- releases ------------------------------------------------------------------------
        rel = []
        for n in vin:
            k = n["key"] + tr
            e = n.get("stem_end", n["end"]) + LEAD_IN
            again = [m for m in vin if m is not n and abs((m["key"] + tr) - k) in (0, 12, 19, 24)
                     and e - 0.05 < m["start"] + LEAD_IN < e + 0.5]
            if again or n["end"] - n["start"] < 0.15:
                continue
            before = harmonic_band_energy(x, k, e - 0.05, e, nharm=2)
            after = harmonic_band_energy(x, k, e + 0.35, e + 0.45, nharm=2)
            rel.append(after - before)
        lat = np.array(lat)
        res["voices"][v] = dict(
            midi_notes_in=len(vin), stem_notes=len(sm), stem_unterminated=unterminated,
            midi_missing_in_stem=[(n["key"], round(n["start"], 3)) for n in missing],
            midi_onset_shift_ms_maxabs=round(1000 * float(np.max(np.abs(dt_midi))), 3) if dt_midi else None,
            durations_changed=[(n["key"], round(n["start"], 3), round(n["end"] - n["start"], 3),
                                round(n["stem_end"] - n["start"], 3)) for n in dur_changed],
            audio_onsets_found=int(len(lat)), audio_onsets_missing=[(n["key"] + tr, round(n["start"], 3), n["vel"])
                                                                    for n in miss_audio],
            flux_peak_offset_ms={"median": round(1000 * float(np.median(lat)), 2),
                                 "p05": round(1000 * float(np.percentile(lat, 5)), 2),
                                 "p95": round(1000 * float(np.percentile(lat, 95)), 2),
                                 "max_abs_dev_from_median": round(1000 * float(np.max(np.abs(lat - np.median(lat)))), 2)},
            harmonic_rise_db={"median": round(float(np.median([n["rise_db"] for n in vin])), 1),
                              "min": round(float(np.min([n["rise_db"] for n in vin])), 1)},
            weak_onsets=weak,
            release_drop_db={"n": len(rel), "median": round(float(np.median(rel)), 1) if rel else None,
                             "worst": round(float(np.max(rel)), 1) if rel else None},
            stem_seconds=round(len(x) / SR, 2),
            last_note_off_s=round(max(n.get("stem_end", n["end"]) for n in vin) + LEAD_IN, 2),
        )
        print(v, json.dumps({k: res["voices"][v][k] for k in ("midi_notes_in", "stem_notes", "audio_onsets_found",
                                                               "flux_peak_offset_ms", "harmonic_rise_db",
                                                               "release_drop_db")}))
    return res


def main() -> None:
    TMP.mkdir(exist_ok=True)
    allres = {}
    for name, plan in PLANS.items():
        allres[name] = analyse(name, plan)
        save(f"chain_{name}", allres[name])


if __name__ == "__main__":
    main()
