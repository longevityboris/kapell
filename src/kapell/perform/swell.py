#!/usr/bin/env python3
"""Deepen the swell on long notes in an orchestrate.py quartet MIDI (in place).

usage: python3 swell.py GROUP.mid [--extra LEVELS] [--min-beats B] [--no-extra A-B ...] [--report OUT.json]

perform.py --target strings already gives every note of a half note or longer a sine swell of
0.45 dynamic levels on the CC1/CC11 envelope (a messa di voce of about 1.5 dB). For the
Beethoven quartet reading the swell is deepened: each such note gets an extra
EXTRA * k * 13 * sin(pi * phase), phase in real seconds, CC units (13 = one dynamic level on perform.py's scale, about
3.5 dB on the quartet renderer) on both CC1 and CC11 of its own track, from its note-on to its
note-off; k = 1 for a note at mf or softer, 0.5 at f, 0 at ff and louder (read at the note's
ends), so the climaxes are not pushed to the CC ceiling. --no-extra A-B (bar:beat positions,
repeatable) leaves out the extra swell for the long notes that start in [A, B): where every part
holds a long note at once (the C7 chord at 62:1, inside the planned diminuendo after the tune's
peak) four swells and the hall's build-up made the held chord louder than the peak itself. Outside long notes the envelope is left exactly as orchestrate.py wrote it (same
ticks, same values). Notes, velocities, tempo and every other event are untouched, so
orchestrate.py's integrity check (--check) still applies unchanged; render.sh re-runs it.
"""
import argparse
import bisect
import json
import math
import sys

import mido

STEP_S = 0.1        # swell sampling step (s); the renderer interpolates linearly between CC events
CC_PER_LEVEL = 13
CC_MIN = 20         # perform.py's floor
FULL_FROM = 88      # mf on perform.py's CC scale: full extra swell at and below
FULL_TO = 114       # ff: no extra swell at and above


class TempoMap:
    """ticks <-> seconds from the tempo track (perform.py writes every tempo change there)."""

    def __init__(self, mid):
        self.tpq = mid.ticks_per_beat
        pts, t = [], 0
        for m in mid.tracks[0]:
            t += m.time
            if m.type == "set_tempo":
                pts.append((t, m.tempo))
        if not pts or pts[0][0] != 0:
            pts.insert(0, (0, 500000))
        self.ticks, self.us, self.secs = [], [], []
        s, pt, pu = 0.0, 0, pts[0][1]
        for tk, us in pts:
            s += (tk - pt) * pu / 1e6 / self.tpq
            self.ticks.append(tk)
            self.us.append(us)
            self.secs.append(s)
            pt, pu = tk, us

    def sec(self, tk):
        i = bisect.bisect_right(self.ticks, tk) - 1
        return self.secs[i] + (tk - self.ticks[i]) * self.us[i] / 1e6 / self.tpq

    def tick(self, s):
        i = bisect.bisect_right(self.secs, s) - 1
        return int(round(self.ticks[i] + (s - self.secs[i]) * 1e6 * self.tpq / self.us[i]))


def abs_events(track):
    t = 0
    for i, m in enumerate(track):
        t += m.time
        yield t, i, m


def process(track, extra, min_ticks, tmap, skip=()):
    evs = list(abs_events(track))
    # notes (mono line; perform.py's few-ms legato overlap is paired by key)
    pend, notes = {}, []
    for t, _, m in evs:
        if m.type == "note_on" and m.velocity > 0:
            pend.setdefault(m.note, []).append(t)
        elif m.type in ("note_off", "note_on") and pend.get(m.note):
            notes.append((pend[m.note].pop(0), t, m.note))
    long_notes = sorted((a, b) for a, b, _ in notes if b - a >= min_ticks)
    if not long_notes:
        return track, 0, 0
    ch = next((m.channel for _, _, m in evs if hasattr(m, "channel")), 0)
    out_ccs = {}
    peak = 0
    for c in (1, 11):
        orig = [(t, m.value) for t, _, m in evs if m.type == "control_change" and m.control == c]
        if not orig:
            continue

        otk = [t for t, _ in orig]

        def base(t, orig=orig, otk=otk):
            i = bisect.bisect_right(otk, t) - 1
            return orig[max(0, i)][1]

        # the extra swell is a messa di voce for the lyrical dynamics: full at mf and below,
        # half at f, none at ff and above (there the players hold a full bow; perform.py's own
        # 0.45-level swell stays everywhere). The level is read at the note's ends, where
        # perform.py's swell is zero.
        depth = {}
        for a, b in long_notes:
            m = 0.5 * (base(a) + base(b - 1))
            depth[(a, b)] = extra * max(0.0, min(1.0, (FULL_TO - m) / (FULL_TO - FULL_FROM)))
            if any(s0 <= a < s1 for s0, s1 in skip):
                depth[(a, b)] = 0.0

        def bump(t):
            s = 0.0
            for a, b in long_notes:
                if a <= t < b:
                    sa, sb = tmap.sec(a), tmap.sec(b)
                    s += depth[(a, b)] * CC_PER_LEVEL * math.sin(math.pi * (tmap.sec(t) - sa) / (sb - sa))
            return s
        # sampled in real time (every STEP_S), so a fermata's held 16th swells and fades like any
        # other moment instead of sitting on one grid value
        ticks = {t for t, _ in orig}
        for a, b in long_notes:
            sa, sb = tmap.sec(a), tmap.sec(b)
            k = max(2, int((sb - sa) / STEP_S))
            for i in range(1, k):
                tk = tmap.tick(sa + (sb - sa) * i / k)
                if a < tk < b:
                    ticks.add(tk)
            ticks.add(b)
        new, last = [], None
        for t in sorted(ticks):
            bv = base(t)
            add = bump(t)
            v = int(max(CC_MIN, min(127, round(bv + add))))
            peak = max(peak, v - bv)
            if v != last:
                new.append((t, v))
                last = v
        out_ccs[c] = new
    # rebuild: every other event keeps its tick and order; CCs go before notes on the same tick
    rows = []
    for t, i, m in evs:
        if m.type == "control_change" and m.control in out_ccs:
            continue
        if m.type == "end_of_track":
            continue
        prio = 0 if m.is_meta or m.type == "program_change" else -1 if m.type == "control_change" \
            else 1 if m.type == "note_off" or (m.type == "note_on" and m.velocity == 0) else 2
        rows.append((t, prio, i, m))
    for c, lst in out_ccs.items():
        for t, v in lst:
            rows.append((t, -1, -1, mido.Message("control_change", channel=ch, control=c, value=v)))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    tr = mido.MidiTrack()
    lt = 0
    for t, _, _, m in rows:
        tr.append(m.copy(time=t - lt))
        lt = t
    tr.append(mido.MetaMessage("end_of_track", time=0))
    return tr, len(long_notes), peak


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("midi")
    ap.add_argument("--extra", type=float, default=0.75, help="extra swell in dynamic levels (default 0.75)")
    ap.add_argument("--min-beats", type=float, default=1.75,
                    help="notes at least this many quarter beats long (as performed, in ticks) swell "
                         "(default 1.75: every half note or longer after humanising)")
    ap.add_argument("--no-extra", action="append", default=[], metavar="A-B",
                    help="no extra swell on long notes starting in [A, B) (bar:beat, quarter beats)")
    ap.add_argument("--measure", type=float, default=1.0, help="bar length in whole notes (default 1: 4/4)")
    ap.add_argument("--report")
    a = ap.parse_args()
    mid = mido.MidiFile(a.midi)
    if any(m.type == "text" and m.text.startswith("swell.py") for tr in mid.tracks for m in tr):
        sys.exit(f"{a.midi}: already processed by swell.py (re-run orchestrate.py first)")
    rep = {"extra_levels": a.extra, "min_beats": a.min_beats, "tracks": {}}
    min_ticks = int(a.min_beats * mid.ticks_per_beat)
    tmap = TempoMap(mid)

    def pos_tick(p):             # perform.py's "bar:beat"; humanised onsets may come 60 ticks early
        bar, beat = p.split(":")
        return int(round(((int(bar) - 1) * 4 * a.measure + float(beat) - 1) * mid.ticks_per_beat)) - 60
    skip = [tuple(pos_tick(x) for x in span.split("-")) for span in a.no_extra]
    rep["no_extra"] = a.no_extra
    for k, tr in enumerate(mid.tracks):
        name = next((m.name for m in tr if m.type == "track_name"), f"track{k}")
        if not any(m.type == "note_on" for m in tr):
            continue
        mid.tracks[k], n, peak = process(tr, a.extra, min_ticks, tmap, skip)
        rep["tracks"][name] = {"long_notes": n, "max_cc_added": peak}
    # after perform.py's and orchestrate.py's markers (the renderers read perform.py's)
    t0 = mid.tracks[0]
    at = 0
    while at < len(t0) and t0[at].time == 0 and t0[at].is_meta and t0[at].type in ("track_name", "text"):
        at += 1
    t0.insert(at, mido.MetaMessage("text", text=f"swell.py extra={a.extra} min_beats={a.min_beats}"
                                   + (f" no_extra={','.join(a.no_extra)}" if a.no_extra else ""), time=0))
    mid.save(a.midi)
    print(f"swell.py: {a.midi}: " + ", ".join(f"{k} {v['long_notes']} notes (+{v['max_cc_added']} CC)"
                                             for k, v in rep["tracks"].items()))
    if a.report:
        with open(a.report, "w") as f:
            json.dump(rep, f, indent=1)


if __name__ == "__main__":
    main()
