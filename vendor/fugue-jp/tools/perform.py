#!/usr/bin/env python3
"""Expressive performance renderer: LilyPond score -> multi-track MIDI.

usage:
  python3 perform.py SCORE.ly PLAN.json OUT.mid [--target piano|strings] [--cues]

The score's voices are \\absolute variables (notes, rests, ties, bar checks). The plan (JSON)
describes the performance; positions are "bar:beat" strings (beat = quarter-note beat, 1-based,
fractions allowed, e.g. "12:2.5").

PLAN keys (all optional except voices):
  "voices":   ["soprano", "alto", "tenor", "bass"]           top to bottom
  "measure":  "1"                                             bar length in whole notes (1 = 4/4 or 2/2)
  "tempo":    [{"at": "1:1", "bpm": 60, "unit": "half"},       step change at a position
               {"at": "40:1", "until": "42:1", "to_bpm": 50}]  linear rit./accel. to to_bpm over the span
  "breaths":  [{"at": "12:1", "ms": 120}]                      caesura before a position: the 16th
              before it is stretched by the breath, and notes that end at the position (and a pedal
              that lifts there) release before the added time, so the breath is silence and hall
              tail, not a longer note; notes held across the position are held through it
  "fermatas": [{"at": "96:1", "extra_beats": 2}]               lengthen the moment starting at a position
  "dynamics": [{"at": "1:1", "level": "p"},                    global level (ppp..fff or number 1..8)
               {"at": "9:1", "until": "16:1", "to": "f"},      hairpin (linear in level)
               {"at": "20:1", "level": "mf", "voice": "bass"}] per-voice override (from that point on)
  "roles":    [{"voice": "alto", "at": "1:1", "until": "5:1", "role": "subject"}]
              roles: subject | answer | cf (cantus firmus) | cs (countersubject) | free (default)
  "role_boost": {"subject": 9, "answer": 9, "cf": 8, "cs": 2, "free": -4}   velocity offsets (piano)
  "role_level": {"subject": 0.7, "answer": 0.7, "cs": 0.2, "free": -0.2}    optional, strings target:
              dynamic-level offsets per role added to the CC1/CC11 envelope (default: none), so
              entries are brought out by bow pressure/timbre, not only by the note-on accent
  "pedal":    [{"at": "90:1", "until": "96:1", "every": "harmony"|"bar"|"half"}]   CC64 re-pedalled
  "humanize": {"ms": 6, "vel": 2}

Target "piano": velocities carry dynamics + voicing, one channel per voice (program 0).
Target "strings": CC11 (expression) and CC1 (dynamics crossfade) carry the dynamic envelope per voice
(sampled every 16th, with a gentle swell on long notes), velocities carry accents; programs
violin, violin, viola, cello.
"""
import json
import math
import sys
from fractions import Fraction as F

import mido

sys.path.insert(0, __import__('os').path.dirname(__file__))
from lyparse import parse_voice  # noqa: E402

LEVELS = {'ppp': 1, 'pp': 2, 'p': 3, 'mp': 4, 'mf': 5, 'f': 6, 'ff': 7, 'fff': 8}
VEL_AT = {1: 22, 2: 32, 3: 44, 4: 56, 5: 68, 6: 82, 7: 98, 8: 112}
TPQ = 960


def lvl(x):
    return float(LEVELS.get(x, x)) if isinstance(x, str) else float(x)


def vel_of_level(L):
    L = min(8.0, max(1.0, L))
    lo = math.floor(L)
    hi = min(8, lo + 1)
    return VEL_AT[lo] + (VEL_AT[hi] - VEL_AT[lo]) * (L - lo)


class Plan:
    def __init__(self, d):
        self.d = d
        self.measure = F(d.get('measure', '1'))
        self.voices = d['voices']

    def pos(self, s):
        bar, beat = s.split(':')
        return (int(bar) - 1) * self.measure + (F(beat) - 1) / 4

    # ---- dynamics -------------------------------------------------------
    def level_fn(self, voice):
        """piecewise-linear level over time for a voice (global events, then voice overrides)."""
        pts = []  # (t, level, kind) kind: 'step' or ('ramp', t_end, L_end)
        cur = 4.0
        events = sorted(self.d.get('dynamics', []), key=lambda e: self.pos(e['at']))
        segs = []  # list of (t0, t1, L0, L1) linear pieces, applied in order
        for e in events:
            if e.get('voice') not in (None, 'all', voice):
                continue
            t0 = self.pos(e['at'])
            if 'until' in e:
                segs.append((t0, self.pos(e['until']), None, lvl(e['to'])))
            else:
                segs.append((t0, t0, None, lvl(e['level'])))

        def f(t):
            L = cur
            for t0, t1, _, L1 in segs:
                if t < t0:
                    break
                if t1 == t0 or t >= t1:
                    L = L1
                else:
                    L = L + (L1 - L) * float((t - t0) / (t1 - t0))
            return L
        return f

    def role_fn(self, voice):
        rs = [(self.pos(r['at']), self.pos(r['until']), r['role']) for r in self.d.get('roles', [])
              if r['voice'] == voice]

        def f(t):
            for a, b, r in rs:
                if a <= t < b:
                    return r
            return 'free'
        return f

    # ---- tempo ------------------------------------------------------------
    def bpm_quarter_fn(self):
        ev = sorted(self.d.get('tempo', [{'at': '1:1', 'bpm': 60, 'unit': 'quarter'}]),
                    key=lambda e: self.pos(e['at']))
        segs = []
        cur = 60.0
        for e in ev:
            t0 = self.pos(e['at'])
            mult = 2.0 if e.get('unit', self.d.get('beat_unit', 'quarter')) == 'half' else 1.0
            if 'until' in e:
                segs.append((t0, self.pos(e['until']), e['to_bpm'] * mult))
            else:
                segs.append((t0, t0, e['bpm'] * mult))

        def f(t):
            b = cur
            for t0, t1, target in segs:
                if t < t0:
                    break
                if t1 == t0 or t >= t1:
                    b = target
                else:
                    b = b + (target - b) * float((t - t0) / (t1 - t0))
            return b
        return f


def build(score_path, plan_path, out_path, target='piano', cues=False):
    src = open(score_path).read()
    plan = Plan(json.load(open(plan_path)))
    voices = {v: parse_voice(src, v, plan.measure) for v in plan.voices}
    voices = {v: n for v, n in voices.items() if n}
    end = max(n[-1].end for n in voices.values())
    boost = {'subject': 9, 'answer': 9, 'cf': 8, 'cs': 2, 'free': -4}
    boost.update(plan.d.get('role_boost', {}))
    hum = plan.d.get('humanize', {'ms': 6, 'vel': 2})

    # tempo grid: 16th-note steps; seconds per step from bpm at that step
    step = F(1, 16)
    bpmf = plan.bpm_quarter_fn()
    breaths = {plan.pos(b['at']): b['ms'] / 1000 for b in plan.d.get('breaths', [])}
    ferm = {plan.pos(x['at']): x['extra_beats'] for x in plan.d.get('fermatas', [])}
    grid_t, grid_s = [F(0)], [0.0]
    t, s = F(0), 0.0
    tempo_events = []  # (tick, microseconds per quarter)
    while t < end + F(1, 2):
        bpm = bpmf(t)
        stretch = 1.0
        if t in ferm:
            stretch += ferm[t] / 0.25  # extra quarter beats spread over this 16th
        if t + step in breaths:
            # add the breath to this step
            stretch += breaths[t + step] / (60.0 / bpm / 4)
        sec = 60.0 / bpm / 4 * stretch
        tempo_events.append((int(t * 4 * TPQ), int(sec * 4 * 1e6)))
        t += step
        s += sec
        grid_t.append(t)
        grid_s.append(s)

    def secs(x):
        i = int(x / step)
        if i >= len(grid_s) - 1:
            return grid_s[-1]
        frac = float((x - grid_t[i]) / step)
        return grid_s[i] + (grid_s[i + 1] - grid_s[i]) * frac

    mid = mido.MidiFile(type=1, ticks_per_beat=TPQ)
    tt = mido.MidiTrack()
    tt.append(mido.MetaMessage('track_name', name='tempo', time=0))
    # Provenance marker: tells a renderer which velocity scale and CC meaning to expect.
    tt.append(mido.MetaMessage('text', text=f'perform.py target={target}', time=0))
    last = 0
    prev_us = None
    for tick, us in tempo_events:
        if us != prev_us:
            tt.append(mido.MetaMessage('set_tempo', tempo=us, time=tick - last))
            last = tick
            prev_us = us
    mid.tracks.append(tt)

    programs = {'piano': [0, 0, 0, 0, 0, 0], 'strings': [40, 40, 41, 42, 43, 42]}[target]
    import random
    rnd = random.Random(7)
    for ci, (v, notes) in enumerate(voices.items()):
        lf, rf = plan.level_fn(v), plan.role_fn(v)
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage('track_name', name=v, time=0))
        tr.append(mido.Message('program_change', channel=ci, program=programs[ci], time=0))
        evs = []  # (tick, order, msg)
        sounding = [n for n in notes if n.midi is not None]
        for i, n in enumerate(sounding):
            # local contour reference: mean pitch within +-1 bar
            neigh = [m.midi for m in sounding if abs(m.start - n.start) <= plan.measure]
            mean = sum(neigh) / len(neigh)
            L = lf(n.start)
            role = rf(n.start)
            vel = vel_of_level(L)
            beatpos = (n.start % plan.measure) * 4  # quarter beats from bar start
            if beatpos == 0:
                vel += 3
            elif beatpos == 2:
                vel += 1.5
            elif beatpos != int(beatpos):
                vel -= 2 if (beatpos * 2) == int(beatpos * 2) else 3
            vel += max(-6, min(6, 0.35 * (n.midi - mean)))
            if n.dur >= F(1, 2):
                vel += 2
            if target == 'piano':
                vel += boost.get(role, 0)
            else:
                vel += boost.get(role, 0) * 0.5
            vel += rnd.uniform(-hum.get('vel', 2), hum.get('vel', 2))
            vel = int(max(8, min(124, round(vel))))
            # articulation
            nxt = sounding[i + 1] if i + 1 < len(sounding) else None
            on_s = secs(n.start) + rnd.uniform(-hum.get('ms', 6), hum.get('ms', 6)) / 1000
            if role in ('subject', 'answer', 'cf'):
                on_s -= 0.008  # slight melody lead
            # a note that ends at a breath releases before the breath's added time (a caesura)
            off_s = secs(n.end) - breaths.get(n.end, 0.0)
            short = n.dur < F(1, 4)
            if target == 'piano':
                off_s -= 0.04 if short else 0.012
            else:
                off_s -= 0.02 if short else 0.0
            if nxt is not None and nxt.midi == n.midi and nxt.start == n.end:
                off_s = min(off_s, secs(n.end) - 0.06)
            off_s = max(off_s, on_s + 0.04)
            evs.append((on_s, 1, ('on', n.midi, vel)))
            evs.append((off_s, 0, ('off', n.midi, 0)))
        if target == 'strings':
            role_level = plan.d.get('role_level', {})
            tcur = F(0)
            while tcur < end:
                L = lf(tcur) + role_level.get(rf(tcur), 0.0)
                # swell inside long notes
                sw = 0.0
                for n in sounding:
                    if n.start <= tcur < n.end and n.dur >= F(1, 2):
                        ph = float((tcur - n.start) / n.dur)
                        sw = 0.45 * math.sin(math.pi * ph)
                        break
                val = int(max(20, min(127, 36 + (L + sw - 1) * 13)))
                evs.append((secs(tcur), -1, ('cc', 11, val)))
                evs.append((secs(tcur), -1, ('cc', 1, val)))
                tcur += step
        for p in plan.d.get('pedal', []):
            a, b = plan.pos(p['at']), plan.pos(p['until'])
            every = {'bar': plan.measure, 'half': F(1, 2)}.get(p.get('every', 'half'), F(1, 2))
            x = a
            while x < b:
                evs.append((secs(x) + 0.03, 2, ('cc', 64, 127)))
                lift = min(x + every, b)
                evs.append((secs(lift) - breaths.get(lift, 0.0) - 0.005, -2, ('cc', 64, 0)))
                x += every
        # seconds -> ticks via inverse of tempo map: use the tempo grid
        def ticks(sec):
            lo, hi = 0, len(grid_s) - 1
            while lo < hi - 1:
                mdl = (lo + hi) // 2
                if grid_s[mdl] <= sec:
                    lo = mdl
                else:
                    hi = mdl
            span = grid_s[hi] - grid_s[lo]
            frac = 0 if span == 0 else (sec - grid_s[lo]) / span
            return int(round((float(grid_t[lo]) + frac * float(step)) * 4 * TPQ))
        evs.sort(key=lambda e: (e[0], e[1]))
        lastt = 0
        for sec, _, e in evs:
            tk = max(0, ticks(max(0.0, sec)))
            dt = max(0, tk - lastt)
            lastt = max(lastt, tk)
            if e[0] == 'on':
                tr.append(mido.Message('note_on', channel=ci, note=e[1], velocity=e[2], time=dt))
            elif e[0] == 'off':
                tr.append(mido.Message('note_off', channel=ci, note=e[1], velocity=0, time=dt))
            else:
                tr.append(mido.Message('control_change', channel=ci, control=e[1], value=e[2], time=dt))
        mid.tracks.append(tr)
    mid.save(out_path)
    total = secs(end)
    print(f"wrote {out_path}: {len(voices)} voices, {float(end / plan.measure):g} bars, {total:.1f} s")
    if cues:
        nb = int(end / plan.measure)
        for b in range(1, nb + 1, 4):
            x = secs((b - 1) * plan.measure)
            print(f"  bar {b:3d}  {int(x // 60)}:{x % 60:04.1f}")
    return total


if __name__ == '__main__':
    a = sys.argv[1:]
    tgt = a[a.index('--target') + 1] if '--target' in a else 'piano'
    build(a[0], a[1], a[2], tgt, '--cues' in a)
