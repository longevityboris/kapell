#!/usr/bin/env python3
"""The Bach organ version's shape, measured on the render: the checks of the listening QA.

usage: python3 levels.py ORGAN.mid PLAN.json STEMS_DIR MIX.wav [--lead 0.5] [-o LEVELS.json]

Positions ("bar:beat") are turned into audio seconds with the MIDI's tempo map (articulate.py's
TempoMap) plus the render's lead-in. Loudness is BS.1770: K-weighted power summed over the two
channels, -0.691 + 10 log10(mean). On the mix, ffmpeg's ebur128 gives the momentary (400 ms) and
short-term (3 s) series; bar and stem levels are the K-weighted mean over the span. Stems are the
dry voices (no added church), so a voice's level there is what it contributes, not its reverb.

Checks (each with its criterion and a pass flag):
* pauses: every breath position of the plan: the key-up before it, the dry stem sum's level in
  100 ms steps from the key-up to the next attack, and the mix's (with church) level there.
* climaxes: the loudest short-term 3 s inside Climax I (26:3-30:1), Climax II (52:1-54:1) and
  the apotheosis (59:1-61:3); Climax II must be at least 1.5 dB above Climax I and 1 dB above
  the apotheosis, and hold the loudest 3 s of the piece.
* arioso: the soprano's solo stem against each accompanying stem, bar by bar (31-34: at least
  3 dB over every one); the arioso's mix level (30:1-35:1) under the exposition's (1:1-13:1).
* hinge: bar levels 52-55 and half bars in 54, so the step down after Climax II is gradual.
* coda: momentary level at the coda's attacks, the final chord against the p opening (bars 1-4),
  and the tenor's last subject head (65:1-67:1) against the other voices.
* entries: each thematic entry's first two bars, the entering voice's stem against the loudest
  other voice (lead in dB), and the alto's diminution head at 52:1 and 53:1 beat by beat.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss
import soundfile as sf

HERE = Path(__file__).resolve().parent
R = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(R / "tools"))
from articulate import TempoMap  # noqa: E402
import perform  # noqa: E402

VOICES = ["soprano", "alto", "tenor", "bass"]


def kweight(x, sr):
    """BS.1770 K-weighting along time (axis 0), coefficients for 48 kHz."""
    assert sr == 48000, sr
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
    return ss.lfilter(b2, a2, ss.lfilter(b1, a1, x, axis=0), axis=0)


class Power:
    """cumulative K-weighted power (sum of channels) for fast window means."""

    def __init__(self, x, sr):
        self.sr = sr
        y = kweight(x, sr)
        p = (y ** 2).sum(axis=1) if y.ndim == 2 else y ** 2
        self.c = np.concatenate([[0.0], np.cumsum(p)])
        self.raw = np.concatenate([[0.0], np.cumsum((x ** 2).mean(axis=1) if x.ndim == 2 else x ** 2)])

    def lufs(self, t0, t1):
        i0, i1 = int(t0 * self.sr), int(t1 * self.sr)
        i0, i1 = max(0, i0), min(len(self.c) - 1, i1)
        if i1 <= i0:
            return None
        m = (self.c[i1] - self.c[i0]) / (i1 - i0)
        return round(-0.691 + 10 * math.log10(m + 1e-20), 1)

    def dbfs(self, t0, t1):
        """plain RMS level in dBFS (mean of the channels' power), unweighted."""
        i0, i1 = max(0, int(t0 * self.sr)), min(len(self.raw) - 1, int(t1 * self.sr))
        m = (self.raw[i1] - self.raw[i0]) / max(1, i1 - i0)
        return round(10 * math.log10(m + 1e-20), 1)


def ebur_series(wav):
    p = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(wav), "-af", "ebur128",
                        "-f", "null", "-"], capture_output=True, text=True)
    t, M, S = [], [], []
    for line in p.stderr.splitlines():
        m = re.search(r"t:\s*([\d.]+)\s+TARGET.*?M:\s*(-?[\d.]+)\s+S:\s*(-?[\d.]+)", line)
        if m:
            t.append(float(m.group(1)))
            M.append(float(m.group(2)))
            S.append(float(m.group(3)))
    return np.array(t), np.array(M), np.array(S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("midi")
    ap.add_argument("plan")
    ap.add_argument("stems")
    ap.add_argument("wav")
    ap.add_argument("--lead", type=float, default=0.5)
    ap.add_argument("-o")
    a = ap.parse_args()

    plan = perform.Plan(json.loads(Path(a.plan).read_text()))
    mid = mido.MidiFile(a.midi)
    tm = TempoMap(mid)
    tpq = mid.ticks_per_beat

    def T(pos):
        return tm.sec(int(plan.pos(pos) * 4 * tpq)) + a.lead

    # note-offs and note-ons per voice, in audio seconds
    events = {}
    for tr in mid.tracks[1:]:
        name = tr.name.strip().lower()
        t, ons, offs = 0, [], []
        for msg in tr:
            t += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                ons.append(tm.sec(t) + a.lead)
            elif msg.type in ("note_off", "note_on"):
                offs.append(tm.sec(t) + a.lead)
        events[name] = (sorted(ons), sorted(offs))

    x, sr = sf.read(a.wav, dtype="float64")
    mix = Power(x, sr)
    stems_raw = {v: sf.read(str(Path(a.stems) / f"{v}.wav"), dtype="float64")[0] for v in VOICES}
    stems = {v: Power(s, sr) for v, s in stems_raw.items()}
    n = min(len(s) for s in stems_raw.values())
    drysum = Power(sum(s[:n] for s in stems_raw.values()), sr)
    et, eM, eS = ebur_series(a.wav)
    res = {"midi": a.midi, "wav": a.wav, "lead_in_s": a.lead}

    def bar(b):
        return mix.lufs(T(f"{b}:1"), T(f"{b + 1}:1"))

    res["bars_lufs"] = {str(b): bar(b) for b in range(1, 67)}
    res["section_starts_s"] = {k: round(T(p), 2) for k, p in
                               [("I exposition 1:1", "1:1"), ("entry 4 13:1", "13:1"), ("stretto 20:1", "20:1"),
                                ("Climax I 26:3", "26:3"), ("II arioso 30:1", "30:1"),
                                ("III fuga inversa 35:1", "35:1"), ("IV dominant pedal 46:1", "46:1"),
                                ("Climax II 52:1", "52:1"), ("hinge 54:1", "54:1"), ("V apotheosis 55:1", "55:1"),
                                ("apotheosis peak 59:1", "59:1"), ("coda 63:1", "63:1"), ("final chord 66:1", "66:1")]}

    # ---- pauses ---------------------------------------------------------------------------
    pauses = []
    for b in plan.d.get("breaths", []):
        tp = T(b["at"])
        offs = [o for v in VOICES for o in events[v][1] if tp - 3.0 < o <= tp + 0.01]
        ons = [o for v in VOICES for o in events[v][0] if o >= tp - 0.05]
        keyup = max(offs) if offs else None
        nxt = min(ons) if ons else tp
        before = drysum.dbfs(keyup - 1.0, keyup) if keyup else None
        steps = []
        if keyup:
            t0 = keyup
            while t0 + 0.1 <= nxt - 0.03:
                steps.append({"t_s": round(t0, 2), "dry_dbfs": drysum.dbfs(t0, t0 + 0.1),
                              "mix_dbfs": mix.dbfs(t0, t0 + 0.1)})
                t0 += 0.1
        tail = steps[-5:] if steps else []
        pauses.append({"at": b["at"], "breath_ms": b["ms"], "last_key_up_s": round(keyup, 3) if keyup else None,
                       "next_attack_s": round(nxt, 3), "silence_s": round(nxt - keyup, 3) if keyup else None,
                       "dry_dbfs_1s_before_key_up": before,
                       "dry_dbfs_last_0.5s_before_attack_max": max(s["dry_dbfs"] for s in tail) if tail else None,
                       "mix_dbfs_last_0.5s_before_attack_max": max(s["mix_dbfs"] for s in tail) if tail else None,
                       "dry_steps_100ms": steps})
    res["pauses"] = pauses

    # ---- climaxes ---------------------------------------------------------------------------
    def smax(t0, t1):
        sel = (et - 3.0 >= t0 - 0.05) & (et <= t1 + 0.05)
        i = np.argmax(np.where(sel, eS, -999))
        mm = (et - 0.4 >= t0 - 0.05) & (et <= t1 + 0.05)
        j = np.argmax(np.where(mm, eM, -999))
        return {"short_term_max_lufs": float(eS[i]), "window_s": [round(et[i] - 3, 1), round(et[i], 1)],
                "momentary_max_lufs": float(eM[j]), "momentary_at_s": round(et[j] - 0.2, 2)}

    cl = {"Climax I 26:3-30:1": smax(T("26:3"), T("30:1")),
          "Climax II 52:1-54:1": smax(T("52:1"), T("54:1")),
          "apotheosis 59:1-61:3": smax(T("59:1"), T("61:3"))}
    for k, c in cl.items():
        c["stems_in_window_lufs"] = {v: stems[v].lufs(*c["window_s"]) for v in VOICES}
    i = int(np.argmax(eS))
    whole = {"short_term_max_lufs": float(eS[i]), "window_s": [round(et[i] - 3, 1), round(et[i], 1)]}
    c1, c2, ap_ = (cl[k]["short_term_max_lufs"] for k in cl)
    res["climaxes"] = {**cl, "whole_piece": whole,
                       "climax_II_over_I_db": round(c2 - c1, 1), "climax_II_over_apotheosis_db": round(c2 - ap_, 1),
                       "pass": bool(c2 - c1 >= 1.5 and c2 - ap_ >= 1.0 and
                                    T("52:1") - 0.1 <= et[i] - 3 and et[i] <= T("54:1") + 0.5)}

    # ---- arioso ----------------------------------------------------------------------------
    ar = {}
    ok = True
    for b in range(30, 35):
        t0, t1 = T(f"{b}:1"), T(f"{b + 1}:1")
        lv = {v: stems[v].lufs(t0, t1) for v in VOICES}
        lead = round(lv["soprano"] - max(lv[v] for v in ("alto", "tenor", "bass")), 1)
        ar[str(b)] = {**lv, "solo_lead_db": lead, "mix_lufs": bar(b)}
        if b >= 31 and lead < 3.0:
            ok = False
    lv = {v: stems[v].lufs(T("30:1"), T("34:1")) for v in VOICES}
    expo = mix.lufs(T("1:1"), T("13:1"))
    ario = mix.lufs(T("30:1"), T("35:1"))
    res["arioso"] = {"bars": ar, "30:1-34:1": {**lv, "solo_lead_db": round(lv["soprano"] - max(lv[v] for v in ("alto", "tenor", "bass")), 1)},
                     "exposition_1-12_lufs": expo, "arioso_30-34_lufs": ario,
                     "opening_1-4_lufs": mix.lufs(T("1:1"), T("5:1")), "inversa_35_lufs": bar(35),
                     "pass": bool(ok and ario < expo)}

    # ---- hinge -----------------------------------------------------------------------------
    t54 = T("54:1")
    sel = (et - 0.4 >= T("53:4") - 0.05) & (et <= t54 + 0.05)
    after = [(round(float(tt - 0.2 - t54), 2), float(m)) for tt, m in zip(et, eM) if t54 < tt - 0.2 <= t54 + 2.0][::5]
    res["hinge"] = {"bars_lufs": {str(b): bar(b) for b in (52, 53, 54, 55, 56)},
                    "54:1-54:3": mix.lufs(T("54:1"), T("54:3")), "54:3-55:1": mix.lufs(T("54:3"), T("55:1")),
                    "momentary_max_53:4": float(np.max(np.where(sel, eM, -999))),
                    "momentary_after_54:1 (s after, LUFS)": after,
                    "reference_f_bars_24_25_61": [bar(24), bar(25), bar(61)]}

    # ---- coda ------------------------------------------------------------------------------
    def mom(pos):
        t0 = T(pos)
        sel = (et - 0.2 >= t0) & (et - 0.2 <= t0 + 0.6)
        return float(np.max(np.where(sel, eM, -999)))

    last_off = max(o for v in VOICES for o in events[v][1])
    fin = mix.lufs(T("66:1"), last_off)
    opening = mix.lufs(T("1:1"), T("5:1"))
    head = {v: stems[v].lufs(T("65:1"), T("66:4")) for v in VOICES}
    res["coda"] = {"momentary_at": {p: mom(p) for p in ("63:1", "64:1", "65:1", "65:3", "66:1", "66:3")},
                   "bars_lufs": {str(b): bar(b) for b in (62, 63, 64, 65, 66)},
                   "final_chord_66:1_to_key_up_lufs": fin, "opening_1-4_lufs": opening,
                   "bars_1-4_lufs": [bar(b) for b in (1, 2, 3, 4)],
                   "tenor_head_65:1-66:4_stems": head,
                   "final_chord_stems": {v: stems[v].lufs(T("66:1"), last_off) for v in VOICES},
                   "tenor_head_lead_db": round(head["tenor"] - max(head[v] for v in ("soprano", "alto", "bass")), 1),
                   "pass": bool(fin <= opening + 0.5)}

    # ---- entries and balance ---------------------------------------------------------------
    entries = [("alto", "5:1", "7:1", "answer"), ("bass", "9:1", "11:1", "subject"),
               ("tenor", "13:1", "15:1", "answer"), ("tenor", "20:1", "22:1", "subject"),
               ("soprano", "22:1", "24:1", "subject"), ("bass", "26:3", "27:1", "subject, stretto"),
               ("tenor", "27:1", "27:3", "subject, stretto"), ("alto", "27:3", "28:1", "subject, stretto"),
               ("soprano", "28:1", "28:4", "subject, stretto"),
               ("bass", "35:1", "37:1", "inversion"), ("tenor", "37:1", "39:1", "inversion, answer"),
               ("soprano", "41:1", "43:1", "inversion"), ("bass", "46:1", "48:1", "augmented inversion"),
               ("alto", "48:1", "50:1", "S2"), ("tenor", "48:1", "50:1", "S1"),
               ("soprano", "50:3", "52:1", "diminution"), ("soprano", "55:1", "57:1", "the tune"),
               ("soprano", "59:1", "61:1", "the tune, peak"), ("tenor", "65:1", "66:4", "last head")]
    ent = []
    for v, p0, p1, what in entries:
        t0, t1 = T(p0), T(p1)
        lv = {u: stems[u].lufs(t0, t1) for u in VOICES}
        others = {u: l for u, l in lv.items() if u != v and l is not None and l > -70}
        loud = max(others, key=others.get) if others else None
        ent.append({"voice": v, "at": p0, "until": p1, "what": what, "stems_lufs": lv,
                    "loudest_other": loud, "lead_db": round(lv[v] - others[loud], 1) if loud else None})
    res["entries"] = ent
    beats = {}
    for p0, p1 in (("52:1", "52:2"), ("52:2", "52:3"), ("52:3", "53:1"), ("53:1", "53:2"), ("53:2", "53:3")):
        beats[p0] = {v: stems[v].lufs(T(p0), T(p1)) for v in VOICES}
    res["alto_diminution_head"] = beats
    res["tutti_balance"] = {f"{p0}-{p1}": {v: stems[v].lufs(T(p0), T(p1)) for v in VOICES}
                            for p0, p1 in (("27:1", "30:1"), ("52:1", "54:1"), ("59:1", "61:1"))}
    res["pedal_cf_46_47"] = {str(b): {v: stems[v].lufs(T(f"{b}:1"), T(f"{b + 1}:1")) for v in ("bass", "tenor")}
                             for b in (46, 47, 48)}

    print(json.dumps({k: res[k] for k in ("climaxes",)}, indent=1))
    for p in pauses:
        print(f"breath {p['at']}: key-up {p['last_key_up_s']} s, next attack {p['next_attack_s']} s, dry "
              f"{p['dry_dbfs_1s_before_key_up']} dBFS before, max {p['dry_dbfs_last_0.5s_before_attack_max']} "
              f"dBFS in the last 0.5 s (mix {p['mix_dbfs_last_0.5s_before_attack_max']})")
    print("arioso", {b: r["solo_lead_db"] for b, r in ar.items()}, "expo", expo, "arioso", ario,
          "pass", res["arioso"]["pass"])
    print("hinge", res["hinge"]["bars_lufs"], res["hinge"]["54:1-54:3"], res["hinge"]["54:3-55:1"])
    print("coda", res["coda"]["momentary_at"], "final", fin, "opening", opening, "tenor head lead",
          res["coda"]["tenor_head_lead_db"])
    for e in ent:
        print(f"entry {e['voice']:7s} {e['at']:5s} {e['what']:22s} lead {e['lead_db']:+.1f} dB over {e['loudest_other']}")
    if a.o:
        Path(a.o).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
