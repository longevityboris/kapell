#!/usr/bin/env python3
"""Round-2 scan of every built sustain sample for a late plateau or a notch in its first second.

  python3 an_samples.py [--tag sk_final --temp QUARTET_TEMP_DIR]

Found on the test music: every violin I Eb5 at mf (CC1 71-104, the p..f range) sits 3-4 dB low for
0.55 s, dips to -7 dB, then jumps +5 dB to its steady level - in the built sample itself
(violin_mf_075_Eb5.wav from both the normal and the legato offset), not in the renderer's CC1.
The builder's NORMAL_RISE (keep at most 0.1 s of a recorded swell) did not catch it.

For every region of the four quartet SFZ with a normal (CC20 0-63) or slurred (64-95) articulation:
50 ms RMS from the region's offset for 3 s; steady = median over 1.2-3.0 s;
  early_db  = mean level 0.15-0.7 s re steady (late plateau),
  notch_db  = lowest 50 ms frame 0.15-1.2 s re steady,
  jump_db   = largest rise over 150 ms inside 0.15-1.2 s.
Flag: early_db <= -3, or notch_db <= -5.5 with a jump_db >= 4.5 back up (dip and recovery, the Eb5 shape).  With --temp, count the test music's notes >= 0.5 s that use each
flagged region (layer from the CC1 the job sends at the note-on, articulation from the render report).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import SR, TMP, rms_env, save  # noqa: E402

Q = Path("/Users/biobook/Music/SampleLibraries/IowaMIS/quartet")
SFZ = {"vn1": "violin.sfz", "vn2": "violin2.sfz", "va": "viola.sfz", "vc": "cello.sfz"}


def regions(path):
    out, grp = [], None
    for line in path.read_text().splitlines():
        m = re.match(r"<group> // (\w+) art cc20 (\d+)-(\d+)", line)
        if m:
            grp = (m.group(1), int(m.group(2)))
            continue
        if line.startswith("<region>") and grp:
            kv = dict(re.findall(r"(\w+)=(\S+)", line.split("//")[0]))
            art = "normal" if grp[1] == 0 else "legato" if grp[1] == 64 else "short"
            out.append(dict(layer=grp[0], art=art, sample=kv["sample"], offset=int(kv.get("offset", 0)),
                            lokey=int(kv["lokey"]), hikey=int(kv["hikey"]), center=int(kv["pitch_keycenter"])))
    return out


def shape(sample, offset):
    x, sr = sf.read(str(Q / sample), always_2d=True)
    assert sr == SR
    seg = x[offset: offset + 3 * SR].mean(axis=1)
    t, e = rms_env(seg, 0.05, 0.025)
    steady = float(np.median(e[(t >= 1.2) & (t <= 3.0)]))
    early = float(np.mean(e[(t >= 0.15) & (t <= 0.7)]) - steady)
    w = (t >= 0.15) & (t <= 1.2)
    notch = float(np.min(e[w]) - steady)
    ew, tw = e[w], t[w]
    k = 6                                   # 150 ms at 25 ms hop
    jump = float(np.max(ew[k:] - ew[:-k])) if len(ew) > k else 0.0
    notch_t = float(tw[np.argmin(ew)])
    return dict(early_db=round(early, 1), notch_db=round(notch, 1), notch_at_s=round(notch_t, 2), jump_db=round(jump, 1))


def layer_of_sfz(c):
    return "pp" if c <= 65 else "mf" if c <= 104 else "ff"


def usage(tag, temp):
    """{(inst, layer, art, key): n notes >= 0.5 s} for the test music."""
    rep = json.loads((TMP / f"chain_{tag}.json").read_text())
    use = {}
    for i, j in enumerate(rep["jobs"]):
        ev, t = [], 0.0
        for msg in mido.MidiFile(str(Path(temp) / f"j{i}_{j['inst']}.mid")):
            t += msg.time
            if msg.type == "control_change" and msg.control == 1:
                ev.append((t, msg.value))
        et = np.array([e[0] for e in ev])
        for (on, off, key, vel, art), pre in zip(j["note_list"], j["pre_ms"]):
            if off - on < 0.5:
                continue
            k = np.searchsorted(et, on - pre / 1000 + 0.06, side="right") - 1   # after a 50 ms note-on switch
            c = ev[max(k, 0)][1]
            a = "normal" if art < 64 else "legato" if art < 96 else "short"
            kk = (j["inst"], layer_of_sfz(c), a, key)
            use[kk] = use.get(kk, 0) + 1
    return use


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="sk_final")
    ap.add_argument("--temp")
    a = ap.parse_args()
    use = usage(a.tag, a.temp) if a.temp else {}
    rows, cache = [], {}
    for inst, f in SFZ.items():
        for r in regions(Q / f):
            if r["art"] == "short":
                continue
            ck = (r["sample"], r["offset"])
            if ck not in cache:
                cache[ck] = shape(*ck)
            s = cache[ck]
            n_use = sum(use.get((inst, r["layer"], r["art"], k), 0) for k in range(r["lokey"], r["hikey"] + 1))
            rows.append(dict(inst=inst, layer=r["layer"], art=r["art"], key=r["center"], keys=[r["lokey"], r["hikey"]],
                             sample=r["sample"], offset=r["offset"], test_music_notes=n_use, **s))
    flag = [r for r in rows if r["early_db"] <= -3 or (r["notch_db"] <= -5.5 and r["jump_db"] >= 4.5)]
    per = {}
    for inst in SFZ:
        rr = [r for r in rows if r["inst"] == inst]
        ff = [r for r in flag if r["inst"] == inst]
        per[inst] = dict(regions=len(rr), flagged=len(ff), flagged_used_by_test_music=sum(1 for r in ff if r["test_music_notes"]),
                         test_music_notes_on_flagged=sum(r["test_music_notes"] for r in ff))
    res = dict(per_inst=per, n_regions=len(rows), n_flagged=len(flag),
               flagged_by_use=sorted(flag, key=lambda r: (-r["test_music_notes"], r["notch_db"])),
               distribution=dict(early_db_p5=float(np.percentile([r["early_db"] for r in rows], 5)),
                                 notch_db_p5=float(np.percentile([r["notch_db"] for r in rows], 5))))
    save("samples_shape.json", res)
    print(json.dumps(per))
    for r in res["flagged_by_use"][:25]:
        print({k: r[k] for k in ("inst", "layer", "art", "key", "test_music_notes", "early_db", "notch_db", "notch_at_s", "jump_db")})


if __name__ == "__main__":
    main()
