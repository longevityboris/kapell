#!/usr/bin/env python3
"""Demo MIDI files for the orchestra renderer (all in CONTRACT.md form) and
their renders.

  python3 make_demo.py [--render] [--only instruments,tutti,crescendo,skeleton]
      [--score SK.ly --plan plan.json]

  demo_instruments   every part in score order: a four-note phrase at pp, mf and
                     ff (CC1 49 / 88 / 114) and a held note; timpani strokes on F
                     and B-flat at pp / mf / ff and a crescendo roll
  demo_tutti         a B-flat minor chord for the full orchestra, struck ff and held
  demo_crescendo     the same chord from pp to fff in 10 s: strings from the
                     start, woodwinds, horns, brass and a timpani roll join in turn
  skeleton_orchestra the ricercar skeleton through the real chain (perform.py and
                     tools/orchestrate.py with specs/skeleton_symphonic.json): the
                     strings carry the four voices (basses 8vb in the full sections),
                     the arioso's lament on a solo clarinet, woodwinds double the
                     entering voices, a horn and a timpani roll hold the dominant
                     pedal, brass only in the two climaxes and the apotheosis peak
Outputs: out/<name>.mid (+ .wav/.m4a/.json with --render).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import mido

HERE = Path(__file__).resolve().parent
R = HERE.parents[1]
sys.path.insert(0, str(HERE))
from orch_common import PARTS  # noqa: E402

OUT = HERE / "out"
TPQ = 480
ORDER = ["fl", "ob", "cl", "bn", "hn", "tpt", "tbn", "btbn", "tba", "timp", "vn1", "vn2", "va", "vc", "cb"]
PHRASE_ROOT = {"fl": 74, "ob": 69, "cl": 62, "bn": 46, "hn": 58, "tpt": 67, "tbn": 53, "btbn": 43, "tba": 34,
               "vn1": 74, "vn2": 67, "va": 58, "vc": 46, "cb": 34}


def write(tracks: dict, path: Path, tempo_us: int = 1_000_000):
    """tracks: name -> [(t_sec, prio, msg)] at 60 bpm (1 s = 1 beat = TPQ ticks)."""
    mid = mido.MidiFile(type=1, ticks_per_beat=TPQ)
    tt = mido.MidiTrack()
    tt.append(mido.MetaMessage("track_name", name="tempo"))
    tt.append(mido.MetaMessage("set_tempo", tempo=tempo_us))
    mid.tracks.append(tt)
    for name, ev in tracks.items():
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        last = 0
        for t, _, msg in sorted(ev, key=lambda e: (e[0], e[1])):
            tk = int(round(t * TPQ))
            tr.append(msg.copy(time=max(0, tk - last)))
            last = max(last, tk)
        mid.tracks.append(tr)
    path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(path))
    return path


def cc(t, c, v):
    return (t, 0, mido.Message("control_change", control=c, value=int(v)))


def note(ev, on, off, key, vel=70):
    ev.append((on, 2, mido.Message("note_on", note=key, velocity=vel)))
    ev.append((off, 1, mido.Message("note_off", note=key, velocity=0)))


# ------------------------------------------------------------------ instruments
def demo_instruments() -> Path:
    tracks = {}
    t = 0.5
    for p in ORDER:
        ev = []
        if p == "timp":
            for key in (41, 46):
                for c in (49, 88, 114):
                    ev.append(cc(t - 0.05, 1, c))
                    ev.append(cc(t - 0.05, 20, 0))
                    note(ev, t, t + 0.8, key)
                    t += 0.9
            ev.append(cc(t - 0.05, 20, 100))
            for i in range(41):
                ev.append(cc(t + i * 0.1, 1, 40 + 2 * i))
            note(ev, t, t + 4.0, 46)
            t += 5.0
        else:
            r = PHRASE_ROOT[p]
            for c in (49, 88, 114):
                ev.append(cc(t - 0.05, 1, c))
                for i, s in enumerate((0, 2, 3, 5)):
                    note(ev, t + 0.45 * i, t + 0.45 * i + 0.42, r + s)
                note(ev, t + 1.8, t + 3.3, r + 7)
                t += 3.7
            t += 0.6
        tracks[p] = ev
    return write(tracks, OUT / "demo_instruments.mid")


# ------------------------------------------------------------------ tutti chord / crescendo
CHORD = {  # B-flat minor, full orchestra (sounding pitch)
    "fl": [82], "ob": [77], "cl": [73], "bn": [58], "hn.1": [65], "hn.2": [61], "tpt": [70], "tbn": [53],
    "btbn": [46], "tba": [34], "timp": [46], "vn1": [82], "vn2": [77], "va": [70], "vc": [53], "cb": [34],
}


def demo_tutti() -> Path:
    tracks = {}
    for name, keys in CHORD.items():
        ev = [cc(0.0, 1, 114), cc(0.0, 11, 127)]
        if name.startswith("hn"):
            ev.append(cc(0.0, 16, 64))                      # a2: horns 1-2 and 3-4
        if name == "timp":
            ev.append(cc(0.0, 20, 100))
        for k in keys:
            note(ev, 0.5, 5.0, k, vel=110)
        tracks[name] = ev
    return write(tracks, OUT / "demo_tutti.mid")


def demo_crescendo() -> Path:
    tracks = {}
    start = {"vn1": 0.5, "vn2": 0.5, "va": 0.5, "vc": 0.5, "cb": 0.5, "cl": 2.0, "bn": 2.0, "fl": 3.5,
             "ob": 3.5, "hn.1": 4.5, "hn.2": 4.5, "timp": 5.5, "tbn": 6.5, "btbn": 6.5, "tba": 6.5, "tpt": 7.5}
    for name, keys in CHORD.items():
        t0 = start[name]
        ev = [cc(0.0, 11, 127)]
        if name.startswith("hn"):
            ev.append(cc(0.0, 16, 64))
        if name == "timp":
            ev.append(cc(0.0, 20, 100))
        for i in range(0, 101):                              # CC1 36 -> 127 over 0.5 .. 10.5 s
            t = 0.5 + i * 0.1
            if t >= t0 - 0.05:
                ev.append(cc(t, 1, 36 + round(91 * i / 100)))
        ev.append(cc(max(0.0, t0 - 0.02), 1, 36 + round(91 * max(0.0, t0 - 0.5) / 10)))
        for k in keys:
            note(ev, t0, 11.0, k, vel=64)
        tracks[name] = ev
    return write(tracks, OUT / "demo_crescendo.mid")


# ------------------------------------------------------------------ skeleton
SPEC = HERE / "specs" / "skeleton_symphonic.json"


def skeleton(score: Path, plan: Path) -> Path:
    """The skeleton through the real chain: perform.py and orchestrate.py with
    specs/skeleton_symphonic.json (its integrity check must pass), then its
    orchestra group as out/skeleton_orchestra.mid + .orchestra.json (sidecar)."""
    od = OUT / "skeleton_symphonic"
    subprocess.run([sys.executable, str(R / "tools" / "orchestrate.py"), str(score), str(plan), str(SPEC), str(od)],
                   check=True)
    p = OUT / "skeleton_orchestra.mid"
    shutil.copyfile(od / "orchestra.mid", p)
    shutil.copyfile(od / "orchestra.orchestra.json", OUT / "skeleton_orchestra.orchestra.json")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--only", default="instruments,tutti,crescendo,skeleton")
    ap.add_argument("--score", type=Path, default=R / "design" / "final-lab" / "SK_final.ly")
    ap.add_argument("--plan", type=Path, default=R / "design" / "final-lab" / "plan.json")
    ap.add_argument("--stems", action="store_true")
    a = ap.parse_args(argv)
    todo = a.only.split(",")
    mids = []
    if "instruments" in todo:
        mids.append(demo_instruments())
    if "tutti" in todo:
        mids.append(demo_tutti())
    if "crescendo" in todo:
        mids.append(demo_crescendo())
    if "skeleton" in todo:
        mids.append(skeleton(a.score, a.plan))
    for m in mids:
        print("wrote", m)
        if a.render:
            cmd = [sys.executable, str(HERE / "render_orchestra.py"), str(m), "-o", str(m.with_suffix(""))]
            if a.stems:
                cmd.append("--stems")
            subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
