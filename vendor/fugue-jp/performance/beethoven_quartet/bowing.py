#!/usr/bin/env python3
"""Bow lifts at the plan's breaths, and the articulation of hinted parts, in an orchestrate.py quartet MIDI (in place).

usage: python3 bowing.py GROUP.mid --orchestration ORCHESTRATION.json [--short-ms MS]
                         [--breath POS[=LEVELS] ...] [--taper-s S] [--taper-levels L] [--report OUT.json]

1. Breaths. Since commit 3c1dc3b perform.py ends the notes that end at a breath before the time it
   adds (before, a bowed chord was held through the breath at full level and slurred into the next
   note: the fermata chord at 29:1 sounded 8.06 s at about -13 LUFS and the general pause before
   the arioso was lost). --breath POS (a breath of the plan) shapes the bow lift into it: the notes
   that end at the breath's start (POS minus its length, within 100 ms) get their track's CC1 and
   CC11 tapered by LEVELS (default --taper-levels) dynamic levels (13 CC each, perform.py's scale)
   over their last --taper-s seconds, so the players lift together out of a diminuendo instead of
   stopping at full bow. The tapered value holds through the release (the renderer holds a CC value
   over gaps longer than 0.6 s and ramps in their last 60 ms) and the value after the breath is in
   place 45 ms before it, so the next note, which may start up to 38 ms early, starts at its
   level. A note that still sounds into the breath (off within 100 ms of POS: a perform.py without
   that change) is first ended at the breath's start.
2. Articulation. A part that carries a CC20 hint must carry one on every note, because the quartet
   renderer stops inferring as soon as a track has CC20. orchestrate.py writes the renderer's own
   inference for the "auto" notes of such a part, but at the renderer's default --short-ms (260),
   not at the value the spec passes in its render_args (480 here): the fugue's eighths at 78 bpm
   (0.385 s) would be slurred or new-bowed on the hinted parts and short strokes on the others
   (67 of violin II's, 68 of the viola's and 34 of the cello's notes differed on this spec).
   Here every note of a hinted track whose window (orchestration.json) is "auto" gets the value
   render_quartet.py's shape_articulation infers at --short-ms, run on the notes as they are after
   step 1 (a note after a breath is not taken as slurred); notes of windows with an explicit
   articulation keep orchestrate.py's value. Tracks without CC20 are left to the renderer.
Notes keep their keys, velocities, note-ons and (unless one still sounds into a breath) note-offs,
so orchestrate.py --check applies unchanged. Run it after orchestrate.py and before
swell.py (swell.py shapes each long note over its real length); render.sh re-runs the check.
"""
import argparse
import bisect
import json
import sys
from pathlib import Path

import mido

HERE = Path(__file__).resolve().parent
R = HERE.parents[1]
sys.path.insert(0, str(R / "tools"))
sys.path.insert(0, str(R / "audio" / "strings"))
import perform  # noqa: E402  (positions: perform.Plan.pos)
import render_quartet as rq  # noqa: E402  (tempo_map, Note, shape_articulation: the renderer's own rules)
from swell import TempoMap  # noqa: E402  (seconds -> ticks)

CC_PER_LEVEL = 13
CC_MIN = 20          # perform.py's floor
STEP_S = 0.02        # taper sampling (s)
AT_POS_S = 0.10      # a note "sounds into" a breath when its off is this close to the breath
EDGE_S = 0.03        # humanising and melody lead move a note-on at most 13 ms before its window
LEAD_S = 0.045       # after a breath: the next value in place before the next note's sfizz note-on


def abs_events(track):
    t = 0
    for m in track:
        t += m.time
        yield t, m


def notes_of(track):
    pend, out = {}, []
    for t, m in abs_events(track):
        if m.type == "note_on" and m.velocity > 0:
            pend.setdefault(m.note, []).append((t, m.velocity))
        elif m.type in ("note_off", "note_on") and pend.get(m.note):
            a, v = pend[m.note].pop(0)
            out.append([a, t, m.note, v])
    return sorted(out, key=lambda n: (n[0], -n[2]))


def cc_list(track, c):
    return [(t, m.value) for t, m in abs_events(track) if m.type == "control_change" and m.control == c]


def held_at(ev, tick, default=0):
    """value in force at `tick` (a per-note controller such as CC20: no ramps)."""
    i = bisect.bisect_right([t for t, _ in ev], tick) - 1
    return ev[i][1] if i >= 0 else default


def value_at(ev, tick, sec):
    """the renderer's reading of a CC stream at `tick`: linear between events up to 0.6 s apart,
    else the held value (cc1_curve)."""
    ts = [t for t, _ in ev]
    i = bisect.bisect_right(ts, tick) - 1
    if i < 0:
        return ev[0][1] if ev else 88
    if i + 1 < len(ev):
        (t0, v0), (t1, v1) = ev[i], ev[i + 1]
        s0, s1, s = sec(t0), sec(t1), sec(tick)
        if s1 - s0 <= 0.6 and s1 > s0:
            return v0 + (v1 - v0) * (s - s0) / (s1 - s0)
    return ev[i][1]


def rebuild(track, notes, ccs, drop_cc):
    """track with its notes and the given CC streams replaced; every other event keeps its tick
    and order; CCs go before notes on the same tick."""
    rows = []
    for i, (t, m) in enumerate(abs_events(track)):
        if m.type in ("note_on", "note_off") or m.type == "end_of_track":
            continue
        if m.type == "control_change" and m.control in drop_cc:
            continue
        prio = 0 if m.is_meta or m.type == "program_change" else -1
        rows.append((t, prio, i, m))
    ch = next((m.channel for _, m in abs_events(track) if hasattr(m, "channel")), 0)
    for c, lst in ccs.items():
        for t, v in lst:
            rows.append((t, -1, -1, mido.Message("control_change", channel=ch, control=c, value=int(v))))
    for a, b, k, v in notes:
        rows.append((a, 2, 0, mido.Message("note_on", channel=ch, note=k, velocity=v)))
        rows.append((b, 1, 0, mido.Message("note_off", channel=ch, note=k, velocity=0)))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    tr = mido.MidiTrack()
    lt = 0
    for t, _, _, m in rows:
        tr.append(m.copy(time=t - lt))
        lt = t
    tr.append(mido.MetaMessage("end_of_track", time=0))
    return tr


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("midi")
    ap.add_argument("--orchestration", required=True, help="orchestrate.py's orchestration.json (windows)")
    ap.add_argument("--short-ms", type=float,
                    help="the render's --short-ms (default: from the group's render_args in manifest.json "
                         "next to ORCHESTRATION.json, else the renderer's 260)")
    ap.add_argument("--breath", action="append", default=[], metavar="POS[=LEVELS]",
                    help="a breath of the plan: taper the notes ending at its start by LEVELS")
    ap.add_argument("--taper-s", type=float, default=0.3)
    ap.add_argument("--taper-levels", type=float, default=2.0)
    ap.add_argument("--report")
    a = ap.parse_args()

    mid = mido.MidiFile(a.midi)
    if any(m.type == "text" and m.text.startswith("bowing.py") for tr in mid.tracks for m in tr):
        sys.exit(f"{a.midi}: already processed by bowing.py (re-run orchestrate.py first)")
    orch = json.loads(Path(a.orchestration).read_text())
    if a.short_ms is None:
        a.short_ms = 260.0
        man = Path(a.orchestration).with_name("manifest.json")
        if man.exists():
            for g in json.loads(man.read_text())["groups"].values():
                args = [str(x) for x in g.get("render_args", [])]
                if g.get("renderer") == "quartet" and "--short-ms" in args:
                    a.short_ms = float(args[args.index("--short-ms") + 1])
    plan = perform.Plan(json.loads(Path(orch["plan"]).read_text()))
    tpq = mid.ticks_per_beat
    sec = rq.tempo_map(mid)
    tick = TempoMap(mid).tick

    def pos_tick(s):
        return int(plan.pos(s) * 4 * tpq)

    plan_breaths = {pos_tick(b["at"]): b["ms"] / 1000.0 for b in plan.d.get("breaths", [])}
    breaths = []
    for b in a.breath:
        p, _, lv = b.partition("=")
        if pos_tick(p) not in plan_breaths:
            sys.exit(f"--breath {p}: no breath there in the plan ({sorted(x['at'] for x in plan.d['breaths'])})")
        breaths.append((p, pos_tick(p), plan_breaths[pos_tick(p)], float(lv) if lv else a.taper_levels))
    windows = {}
    for g in orch["groups"].values():
        for part in g["parts"].values():
            windows[part["track"]] = part["windows"]

    rep = {"short_ms": a.short_ms, "taper_s": a.taper_s, "taper_levels": a.taper_levels,
           "breaths": [], "articulation": {}}
    for k, tr in enumerate(mid.tracks):
        name = next((m.name for m in tr if m.type == "track_name"), f"track{k}")
        notes = notes_of(tr)
        if not notes:
            continue
        ccs = {c: cc_list(tr, c) for c in (1, 11, 20)}
        drop = set()
        # 1. breaths
        for p, bt, blen, levels in breaths:
            tb = sec(bt)
            ts = tb - blen                         # the breath's start: the notes before it end here
            for n in notes:                        # still sounding into the breath: end at its start
                if abs(sec(n[1]) - tb) <= AT_POS_S and sec(n[0]) < ts - 0.04:
                    rep["breaths"].append({"at": p, "track": name, "key": n[2], "cut_from_s": round(sec(n[1]), 3),
                                           "to_s": round(ts, 3)})
                    n[1] = tick(ts)
                    drop.add(0)                    # notes changed: rebuild the track
            into = [n for n in notes if ts - AT_POS_S <= sec(n[1]) <= ts + 0.02 and sec(n[0]) < ts - a.taper_s]
            if not into:
                continue
            new_off_s = max(sec(n[1]) for n in into)
            for n in into:
                rep["breaths"].append({"at": p, "track": name, "key": n[2], "on_s": round(sec(n[0]), 3),
                                       "off_s": round(sec(n[1]), 3), "breath_s": blen})
            # taper CC1 / CC11 over the last taper_s of the note, hold until the breath's next event
            ta = tick(new_off_s - a.taper_s)
            te = max(n[1] for n in into)
            for c in (1, 11):
                ev = ccs[c]
                if not ev:
                    continue
                v0 = value_at(ev, ta, sec)
                v1 = max(CC_MIN, v0 - levels * CC_PER_LEVEL)
                k_steps = max(2, int(round(a.taper_s / STEP_S)))
                taper = [(tick(new_off_s - a.taper_s + a.taper_s * i / k_steps),
                          int(round(v0 + (v1 - v0) * i / k_steps))) for i in range(k_steps + 1)]
                # the value after the breath is reached 45 ms before it, ahead of the next note's early
                # start (humanising, melody lead and the bow's pre-roll: up to 38 ms), so that note
                # starts at its planned level; the renderer holds the tapered value through the
                # release and ramps in the last 60 ms (gaps over 0.6 s), or ramps across a shorter gap
                vb = held_at(ev, bt, ev[0][1])
                tv = tick(sec(bt) - LEAD_S)
                back = [(tv, vb)] if sec(tv) > sec(te) + 0.05 else []
                kept = [(t, v) for t, v in ev if not ta <= t < bt]
                ccs[c] = sorted(kept + taper + back)
                drop.add(c)
                rep["breaths"].append({"at": p, "track": name, "cc": c, "taper_from": round(v0, 1), "to": round(v1, 1),
                                       "after": vb,
                                       "from_s": round(sec(ta), 3), "to_s": round(sec(te), 3)})
        # 2. articulation of hinted tracks at the render's --short-ms
        if ccs[20]:
            ws = windows.get(name, [])
            rn = []
            explicit = 0
            for on, off, key, vel in notes:
                s_on = sec(on)
                w = next((w for w in ws if w["t0_s"] - EDGE_S <= s_on < w["t1_s"] - EDGE_S), None)
                art = None
                if w is not None and w["articulation"] != "auto":
                    art = held_at(ccs[20], on)          # orchestrate.py's value at the note-on
                    explicit += 1
                rn.append(rq.Note(s_on, sec(off), key, vel, art))
            rq.shape_articulation(rn, a.short_ms / 1000.0, 0.005)
            before = {t: v for t, v in ccs[20]}
            ccs[20] = [(n[0], x.art) for n, x in zip(notes, rn)]
            drop.add(20)
            kinds = {"normal": 0, "legato": 0, "short": 0}
            for x in rn:
                kinds["short" if x.art >= 96 else "legato" if x.art >= 64 else "normal"] += 1
            rep["articulation"][name] = {
                "notes": len(rn), "explicit": explicit, "inferred": len(rn) - explicit, **kinds,
                "changed_from_orchestrate": sum(1 for n, x in zip(notes, rn) if before.get(n[0]) != x.art)}
        if drop:
            mid.tracks[k] = rebuild(tr, notes, {c: ccs[c] for c in drop if c}, drop)
    t0 = mid.tracks[0]
    at = 0
    while at < len(t0) and t0[at].time == 0 and t0[at].is_meta and t0[at].type in ("track_name", "text"):
        at += 1
    t0.insert(at, mido.MetaMessage("text", text=f"bowing.py short_ms={a.short_ms:g} breaths="
                                   + ",".join(a.breath), time=0))
    mid.save(a.midi)
    lifted = [x for x in rep["breaths"] if "on_s" in x]
    cut = [x for x in rep["breaths"] if "cut_from_s" in x]
    print(f"bowing.py: {a.midi}: {len(lifted)} notes tapered into {len(breaths)} breaths ({len(cut)} ended at "
          f"the breath's start); articulation "
          + ", ".join(f"{k} {v['explicit']} given + {v['inferred']} inferred at {a.short_ms:g} ms "
                      f"({v['changed_from_orchestrate']} changed)" for k, v in rep["articulation"].items()))
    if a.report:
        Path(a.report).write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
