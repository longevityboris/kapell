#!/usr/bin/env python3
"""Render a multi-voice MIDI file on a sampled North German baroque pipe organ in a church.

Usage
-----
::

    python3 render_organ.py IN.mid [--registration REG.json | PRESET] -o OUT [options]

    # the chain: LilyPond score + performance plan -> MIDI -> organ
    python3 ../../tools/perform.py SCORE.ly PLAN.json out/x.mid --target piano
    python3 render_organ.py out/x.mid --registration demo/skeleton_registration.json -o out/x
    # the demo (skeleton of the ricercar): demo/render_demo.sh

Writes ``OUT.wav`` (48 kHz, 24-bit stereo, true peak normalised to -1 dBTP) and ``OUT.m4a`` (AAC
256 kb/s, afconvert). Nothing is played through the speakers. Run ``setup_organ.sh`` once first.

The MIDI and registration contract is ``CONTRACT.md`` (voices = tracks, divisions HW/POS/OW/PED,
registration sidecar with bar:beat positions, velocity ignored, CC11 = swell on enclosed divisions).

Options: ``--stems DIR`` (dry stem per voice, same length and gain as the mix), ``--no-reverb``,
``--wet-db`` (the church's added reverberation, energy relative to the dry organ, measured on the
render; default -4 dB), ``--ir PATH``, ``--lead-in`` (s, default 0.5), ``--peak-db`` (-1),
``--temperament equal|vallotti|werckmeister3`` (default equal), ``--a4`` (440), ``--jobs`` (8),
``--anticipate`` (keys are played early by this fraction of the median speech time of the pipes
they open, at most 40 ms, as an organist does for slow pipes; default 0.5, 0 = off),
``--seed``, ``--no-fold``, ``--no-m4a``, ``--json PATH`` (render report), ``--list-stops``,
``--list-registrations``.

Instrument: the Norrfjärden Church organ (Grönlunds Orgelbyggeri 1997), a reconstruction of the 1684
organ of the German Church in Stockholm: Hauptwerck, Rückpositief, Oberwerck and Pedahl, 36 stops,
sampled per pipe by Lars Palo (stereo, 44.1 kHz/24-bit, multiple loops, releases by key-press time;
CC BY-SA 4.0). Played by ``pipe_engine.py`` (retuned from the organ's 1/4-comma meantone at hoher
Chorton to the chosen temperament at A4, phase-aligned releases). Church: OpenAIR Lady Chapel,
St Albans Cathedral (ORTF, CC BY 4.0) added by convolution to the Norrfjärden church sound that the
samples already carry. Details and measurements: README.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss
import soundfile as sf
import soxr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from odf import DIVISION_NAMES, norm_name  # noqa: E402
from organ_paths import IR_FILE, PIPES_JSON, REGISTRATIONS_JSON, SR  # noqa: E402
from pipe_engine import PipeBank, ReleaseCache, SampleCache, render_event  # noqa: E402

DIVS = ('HW', 'POS', 'OW', 'PED')
DEFAULT_DIVISION = {'soprano': 'HW', 'alto': 'HW', 'tenor': 'POS', 'bass': 'PED'}
COMPASS = {'HW': (36, 85), 'POS': (36, 85), 'OW': (36, 85), 'PED': (36, 64)}
SNAP_S = 0.030        # a note starting this little before a change starts with the new setting
MIN_PIECE_S = 0.080   # a stop change reaches a held key only if the key stays down this long after it
HANDOVER_S = 0.050    # a key taken over by another voice this close to its release is re-struck
WET_DB_DEFAULT = -4.0
ANTICIPATE_DEFAULT = 0.5    # fraction of the pipes' speech time (to -6 dB) by which keys are played early
ANTICIPATE_MAX_S = 0.040

CREDIT = ("Organ: Norrfjärden Church Baroque Replica (Grönlunds Orgelbyggeri 1997, after the 1684 organ "
          "of the German Church in Stockholm), sample set by Lars Palo, CC BY-SA 4.0 "
          "(https://creativecommons.org/licenses/by-sa/4.0/, familjenpalo.se). Church: OpenAIR "
          "impulse response, Lady Chapel, St Albans Cathedral (University of York, Audiolab), CC BY 4.0 "
          "(https://creativecommons.org/licenses/by/4.0/). Rendered by ricercar/audio/organ/render_organ.py.")
COPYRIGHT = ("Samples: Lars Palo, Norrfjärden Church organ, CC BY-SA 4.0. Impulse response: OpenAIR "
             "Lady Chapel St Albans Cathedral, CC BY 4.0.")
SOFTWARE = 'ricercar render_organ.py'


# -------------------------------------------------------------------------------------------------
# MIDI

class TempoMap:
    def __init__(self, tpb, tempos):
        self.tpb = tpb
        tempos = sorted(tempos)
        if not tempos or tempos[0][0] != 0:
            tempos.insert(0, (0, 500_000))
        self.ticks, self.secs, self.tempo = [], [], []
        sec, last_tick, last_tempo = 0.0, 0, tempos[0][1]
        for tick, tempo in tempos:
            sec += (tick - last_tick) * last_tempo / 1e6 / tpb
            self.ticks.append(tick)
            self.secs.append(sec)
            self.tempo.append(tempo)
            last_tick, last_tempo = tick, tempo

    def seconds(self, tick):
        i = bisect_right(self.ticks, tick) - 1
        return self.secs[i] + (tick - self.ticks[i]) * self.tempo[i] / 1e6 / self.tpb


def load_midi(path, warn):
    mf = mido.MidiFile(path)
    if mf.type == 2:
        raise SystemExit('MIDI type 2 is not supported')
    tempos, names, evs, texts = [], {}, [], []
    for ti, tr in enumerate(mf.tracks):
        tick = 0
        for msg in tr:
            tick += msg.time
            if msg.type == 'set_tempo':
                tempos.append((tick, msg.tempo))
            elif msg.type == 'track_name' and ti not in names:
                names[ti] = msg.name.strip().rstrip(':').strip()
            elif msg.type in ('text', 'marker') and msg.text.strip().lower().startswith('organ:'):
                texts.append((tick, msg.text.strip()[6:].strip()))
            elif msg.type in ('note_on', 'note_off') or (msg.type == 'control_change' and msg.control == 11):
                evs.append((tick, ti, msg))
    tmap = TempoMap(mf.ticks_per_beat, tempos)
    chans = defaultdict(set)
    for _, ti, m in evs:
        if m.type != 'control_change':
            chans[ti].add(m.channel)
    base, used = {}, {}
    for ti in sorted(chans):
        b = (names.get(ti) or f'track{ti}').lower()
        used[b] = used.get(b, 0) + 1
        if used[b] > 1:
            warn(f'track {ti}: name "{b}" repeated, renamed {b}.{used[b]}')
            b = f'{b}.{used[b]}'
        base[ti] = b

    def vname(ti, ch):
        return f'{base[ti]}.ch{ch + 1}' if len(chans[ti]) > 1 else base[ti]
    voices = defaultdict(lambda: {'notes': [], 'cc11': []})
    pending = {}
    orphan_off = {}          # note-off with nothing pending: a zero-length note if its note-on follows at the same tick
    # note-offs before note-ons at the same tick
    evs.sort(key=lambda e: (e[0], 0 if (e[2].type == 'note_off' or (e[2].type == 'note_on' and e[2].velocity == 0)) else 1))
    last_tick = 0
    for tick, ti, m in evs:
        last_tick = max(last_tick, tick)
        if ti not in base:
            continue
        v = vname(ti, m.channel)
        if m.type == 'control_change':
            voices[v]['cc11'].append((tmap.seconds(tick), m.value))
            continue
        k = (v, m.note)
        if m.type == 'note_on' and m.velocity > 0:
            if k in pending:                        # re-press without release: close the old note
                t0 = pending.pop(k)
                voices[v]['notes'].append([m.note, t0, tick])
            if orphan_off.pop(k, None) == tick:     # note-on and note-off on the same tick
                voices[v]['notes'].append([m.note, tick, tick])
                continue
            pending[k] = tick
        else:
            if k in pending:
                voices[v]['notes'].append([m.note, pending.pop(k), tick])
            else:
                orphan_off[k] = tick
    for (v, note), t0 in pending.items():
        warn(f'{v}: note {note} at tick {t0} has no note-off; closed after 2 s')
        voices[v]['notes'].append([note, t0, None])
    out = {}
    for v, d in voices.items():
        if not d['notes']:
            continue
        notes = []
        for note, a, b in sorted(d['notes'], key=lambda n: n[1]):
            ta = tmap.seconds(a)
            tb = ta + 2.0 if b is None else tmap.seconds(b)
            if tb - ta < 0.03:
                if tb <= ta:
                    warn(f'{v}: zero-length note {note} at {ta:.3f} s played as a 30 ms touch')
                tb = ta + 0.03
            notes.append({'key': note, 'on': ta, 'off': tb, 'tick': a})
        out[v] = {'notes': notes, 'cc11': d['cc11']}
    return out, tmap, texts


# -------------------------------------------------------------------------------------------------
# registration

class Registrations:
    def __init__(self, bank, custom=None):
        self.db = json.load(open(REGISTRATIONS_JSON))
        self.bank = bank
        self.custom = custom or {}
        self.lookup = {}
        for sk, st in bank.stops.items():
            self.lookup[(st['division'], norm_name(st['name']))] = sk

    def stops(self, div, spec):
        """registration name / explicit list -> sorted list of stop keys ('HW/Principal 8'')."""
        if spec in (None, 'off', []):
            return []
        if isinstance(spec, str):
            if spec in self.custom:
                c = self.custom[spec]
                names = c['stops'] if isinstance(c, dict) else c
            elif spec in self.db['divisions'].get(div, {}):
                names = self.db['divisions'][div][spec]
            else:
                known = sorted(self.db['divisions'].get(div, {})) + sorted(self.custom)
                raise SystemExit(f'unknown registration "{spec}" for {div}; known: {", ".join(known)}')
        else:
            names = spec
        out = []
        for n in names:
            if isinstance(n, str) and ':' in n and n.split(':')[0] in DIVS and n.split(':')[0] != div:
                raise SystemExit(f'{div}: stop "{n}" belongs to another division (couplers are not modelled)')
            key = self.lookup.get((div, norm_name(n.split(':')[-1] if n.split(':')[0] in DIVS else n)))
            if key is None:
                names_ = [st['name'] for st in self.bank.stops.values() if st['division'] == div]
                raise SystemExit(f'{div}: unknown stop "{n}"; stops: {", ".join(names_)}')
            out.append(key)
        return sorted(set(out))


def parse_pos(e, measure, tpb, tmap):
    if 'at_sec' in e:
        return float(e['at_sec'])
    if 'at_tick' in e:
        return tmap.seconds(int(e['at_tick']))
    bar, beat = str(e['at']).split(':')
    q = (int(bar) - 1) * measure * 4 + (Fraction(beat) - 1)
    return tmap.seconds(int(round(q * tpb)))


def build_timelines(reg_arg, voices, tmap, texts, bank, warn):
    """-> (division timeline per voice, registration timeline per division, sidecar dict)."""
    side = {}
    preset = None
    if reg_arg:
        p = Path(reg_arg)
        if p.exists():
            side = json.load(open(p))
        else:
            db = json.load(open(REGISTRATIONS_JSON))
            if reg_arg not in db['presets']:
                raise SystemExit(f'--registration {reg_arg}: neither a file nor a preset '
                                 f'({", ".join(db["presets"])})')
            preset = db['presets'][reg_arg]
    regs = Registrations(bank, side.get('custom'))
    measure = Fraction(str(side.get('measure', '1')))
    tpb = tmap.tpb
    db = regs.db
    # registration timeline: [(t, {div: [stops]})]
    cur = {d: regs.stops(d, db['defaults'][d]) for d in DIVS}
    if preset:
        cur.update({d: regs.stops(d, n) for d, n in preset.items()})
    changes = []
    for e in side.get('changes', []):
        t = parse_pos(e, measure, tpb, tmap)
        for d in DIVS:
            if d in e:
                changes.append((t, 0, d, e[d]))
    # voice -> division
    vdiv = {v: DEFAULT_DIVISION.get(v.split('.')[0], 'HW') for v in voices}
    for v, d in side.get('manuals', {}).items():
        if v not in vdiv:
            warn(f'registration: voice "{v}" not in the MIDI (voices: {", ".join(voices)})')
        vdiv[v] = d
    moves = []
    for e in side.get('manual_changes', []):
        moves.append((parse_pos(e, measure, tpb, tmap), e['voice'], e['division']))
    for tick, cmd in texts:
        t = tmap.seconds(tick)
        for part in cmd.split():
            if '->' in part:
                v, d = part.split('->')
                moves.append((t + 1e-6, v.strip().lower(), d.strip()))
            elif '=' in part:
                d, n = part.split('=')
                changes.append((t + 1e-6, 1, d.strip(), n.strip()))
    for _, _, d, _ in changes:
        if d not in DIVS:
            raise SystemExit(f'registration change for unknown division {d} ({", ".join(DIVS)})')
    for _, v, d in moves:
        if d not in DIVS:
            raise SystemExit(f'manual change to unknown division {d}')
    for v, d in vdiv.items():
        if d not in DIVS:
            raise SystemExit(f'voice {v}: unknown division {d}')
    reg_tl = {d: [(-1e9, cur[d])] for d in DIVS}
    for t, _, d, name in sorted(changes, key=lambda c: (c[0], c[1])):
        if t <= 1e-6 and len(reg_tl[d]) == 1:          # a change at the very start sets the initial state
            reg_tl[d][0] = (-1e9, regs.stops(d, name))
        else:
            reg_tl[d].append((t, regs.stops(d, name)))
    div_tl = {v: [(-1e9, d)] for v, d in vdiv.items()}
    for t, v, d in sorted(moves):
        tl = div_tl.setdefault(v, [(-1e9, 'HW')])
        if t <= 1e-6 and len(tl) == 1:
            tl[0] = (-1e9, d)
        else:
            tl.append((t, d))
    enclosed = set(side.get('enclosed', []))
    return div_tl, reg_tl, side, enclosed


def at(tl, t):
    i = bisect_right([x[0] for x in tl], t) - 1
    return tl[max(i, 0)][1]


# -------------------------------------------------------------------------------------------------
# key logic

def division_of(div_tl, v, t):
    tl = div_tl[v]
    return at(tl, t + SNAP_S)


def fold(key, div, allow, warn, counts):
    lo, hi = COMPASS[div]
    k = key
    while k < lo:
        k += 12
    while k > hi:
        k -= 12
    if k != key:
        if not allow:
            raise SystemExit(f'key {key} is outside the {div} compass {lo}-{hi} (--no-fold)')
        counts[div] += 1
    return k


def key_intervals(voices, div_tl, allow_fold, warn):
    """merge notes per (division, key): one pipe-set per key, first presser owns it."""
    per = defaultdict(list)
    folded = defaultdict(int)
    for v, d in voices.items():
        for n in d['notes']:
            div = division_of(div_tl, v, n['on'])
            k = fold(n['key'], div, allow_fold, warn, folded)
            per[(div, k)].append((n['on'], n['off'], v))
    merged, shared, handovers = [], 0, 0
    for (div, k), lst in per.items():
        lst.sort()
        cur = None
        for on, off, v in lst:
            if cur and on < cur[1] - 1e-6:          # key already down
                if v != cur[2] and cur[1] - on < HANDOVER_S and on - cur[0] > HANDOVER_S:
                    # one voice lets go as the other takes the key (humanised timing overlaps by a
                    # few ms): a re-strike, as an organist passing a key between hands plays it
                    handovers += 1
                    cur[1] = max(cur[0] + 0.03, on - 0.02)
                    merged.append((div, k, *cur))
                    cur = [on, off, v]
                    continue
                if v != cur[2]:
                    shared += 1                     # both hold it: one set of pipes
                cur[1] = max(cur[1], off)
            else:
                if cur:
                    merged.append((div, k, *cur))
                cur = [on, off, v]
        if cur:
            merged.append((div, k, *cur))
    for div, c in folded.items():
        warn(f'{c} notes folded by octaves into the {div} compass {COMPASS[div]}')
    return merged, shared, handovers, dict(folded)


def pipe_events(merged, reg_tl):
    """split held keys at registration changes -> [(owner, stop, key, t0, t1, starts_at_key_down)]."""
    out = []
    for div, k, on, off, v in merged:
        tl = reg_tl[div]
        cuts = [t for t, _ in tl if on + SNAP_S < t < off - MIN_PIECE_S]
        bounds = [on] + cuts + [off]
        active = {}
        for i in range(len(bounds) - 1):
            a, b = bounds[i], bounds[i + 1]
            stops = set(at(tl, a + SNAP_S)) if i == 0 else set(at(tl, a))
            for s in list(active):
                if s not in stops:
                    t0 = active.pop(s)
                    out.append((v, s, k, t0, a, t0 == on))
            for s in stops:
                if s not in active:
                    active[s] = a
        for s, a in active.items():
            out.append((v, s, k, a, off, a == on))
    return out


# -------------------------------------------------------------------------------------------------
# DSP helpers

def swell(x, cc, lead_in):
    """swell box: CC11 0..127 -> gain -18..0 dB and a one-pole low-pass 1.5 kHz..20 kHz, 60 ms smoothing."""
    n = len(x)
    ctl = np.full(n, 127.0)
    for t, v in sorted(cc):
        i = int((t + lead_in) * SR)
        if 0 <= i < n:
            ctl[i:] = v
    a = math.exp(-1.0 / (0.060 * SR))
    ctl = ss.lfilter([1 - a], [1, -a], ctl, zi=[ctl[0] * a])[0]
    o = np.clip(ctl / 127.0, 0, 1)
    gain = 10 ** (-18 * (1 - o) / 20)
    fc = 1500.0 * (20000.0 / 1500.0) ** o
    y = np.empty_like(x)
    zi = np.zeros((1, 2))
    B = 64
    for i in range(0, n, B):
        al = 1 - math.exp(-2 * math.pi * float(fc[i]) / SR)
        seg, zi = ss.lfilter([al], [1, -(1 - al)], x[i:i + B], axis=0, zi=zi)
        y[i:i + B] = seg
    return y * gain[:, None]


def load_ir(path):
    ir, sr = sf.read(str(path), dtype='float64', always_2d=True)
    if ir.shape[1] == 1:
        ir = np.repeat(ir, 2, axis=1)
    ir = ir[:, :2]
    if sr != SR:
        ir = soxr.resample(ir, sr, SR, quality='VHQ')
    pk = int(np.argmax(np.abs(ir).sum(axis=1)))
    # remove the direct sound (the samples carry their own), keep the early reflections
    cut = pk + int(0.0025 * SR)
    f = int(0.001 * SR)
    ir[:cut - f] = 0.0
    ir[cut - f:cut] *= np.linspace(0, 1, f)[:, None]
    ir = ir[max(0, pk - f):]
    ir /= math.sqrt(float(np.sum(ir ** 2)) / 2)
    return ir, pk


def true_peak(x):
    return float(np.abs(ss.resample_poly(x, 4, 1, axis=0)).max())


def edc_decay(x, t0, t_end):
    """T20 of the render's decay after t0 (broadband, Schroeder)."""
    y = (x[int(t0 * SR):int(t_end * SR)] ** 2).sum(axis=1)
    if len(y) < SR // 2:
        return None
    e = np.cumsum(y[::-1])[::-1]
    db = 10 * np.log10(e / e[0] + 1e-30)
    i5, i25 = int(np.argmax(db <= -5)), int(np.argmax(db <= -25))
    if not (i25 > i5 > 0):
        return None
    tt = np.arange(i5, i25) / SR
    return float(-60 / np.polyfit(tt, db[i5:i25], 1)[0])


def stereo_stats(x):
    """L/R correlation and mono fold-down (mean of L and R, power re the stereo power): overall and
    the worst 1 s window among windows within 30 dB of the loudest."""
    L, R = x[:, 0].astype(np.float64), x[:, 1].astype(np.float64)
    ps = float(np.mean((L ** 2 + R ** 2) / 2)) + 1e-24
    out = {'lr_correlation': round(float(np.corrcoef(L, R)[0, 1]), 3),
           'mono_folddown_db': round(10 * math.log10(float(np.mean(((L + R) / 2) ** 2)) / ps + 1e-24), 2)}
    w = SR
    n = len(L) // w
    if n:
        P = ((L[:n * w] ** 2 + R[:n * w] ** 2) / 2).reshape(n, w).mean(axis=1)
        M = (((L[:n * w] + R[:n * w]) / 2) ** 2).reshape(n, w).mean(axis=1)
        ok = P > P.max() * 1e-3
        if ok.any():
            out['mono_folddown_worst_1s_db'] = round(float(10 * np.log10(M[ok] / P[ok]).min()), 2)
    return out


def measure_file(path):
    if shutil.which('ffmpeg') is None:
        return None
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-filter_complex',
                        'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True)
    summ = r.stderr[r.stderr.rfind('Summary:'):]
    out = {}
    for key, label in (('integrated_lufs', 'I:'), ('lra_lu', 'LRA:'), ('true_peak_dbtp', 'Peak:')):
        for line in summ.splitlines():
            if line.strip().startswith(label):
                try:
                    out[key] = float(line.split()[1])
                except ValueError:
                    pass
                break
    return out or None


def write_wav(x, path, title):
    lsb = 2.0 ** -23
    d = (np.random.default_rng(0).random(x.shape) - np.random.default_rng(1).random(x.shape)) * lsb
    with sf.SoundFile(str(path), 'w', SR, x.shape[1], subtype='PCM_24', format='WAV') as f:
        f.title = title
        f.artist = 'Norrfjärden Church organ (Lars Palo samples), rendered by render_organ.py'
        f.comment = CREDIT
        f.copyright = COPYRIGHT
        f.software = SOFTWARE
        f.write(np.clip(x + d, -1, 1 - lsb))


def write_m4a(wav, m4a, title):
    if m4a.exists():
        m4a.unlink()
    subprocess.run(['afconvert', '-f', 'm4af', '-d', 'aac', '-b', '256000', str(wav), str(m4a)], check=True)
    if shutil.which('ffmpeg') is None:
        return False
    tmp = m4a.with_name(m4a.stem + '.tagging.m4a')
    r = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(m4a), '-map', '0',
                        '-c', 'copy', '-map_metadata', '0', '-metadata', f'title={title}',
                        '-metadata', 'artist=Norrfjärden Church organ (Lars Palo samples), render_organ.py',
                        '-metadata', f'comment={CREDIT}', '-metadata', f'copyright={COPYRIGHT}',
                        '-metadata', f'encoder={SOFTWARE}', str(tmp)], capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, m4a)
    return True


# -------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('midi', nargs='?')
    ap.add_argument('-o', '--out')
    ap.add_argument('--registration')
    ap.add_argument('--stems')
    ap.add_argument('--no-reverb', action='store_true')
    ap.add_argument('--wet-db', type=float, default=WET_DB_DEFAULT)
    ap.add_argument('--ir', default=str(IR_FILE))
    ap.add_argument('--lead-in', type=float, default=0.5)
    ap.add_argument('--peak-db', type=float, default=-1.0)
    ap.add_argument('--temperament', default='equal')
    ap.add_argument('--a4', type=float, default=440.0)
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--anticipate', type=float, default=ANTICIPATE_DEFAULT)
    ap.add_argument('--no-fold', action='store_true')
    ap.add_argument('--no-m4a', action='store_true')
    ap.add_argument('--json')
    ap.add_argument('--list-stops', action='store_true')
    ap.add_argument('--list-registrations', action='store_true')
    a = ap.parse_args(argv)
    if not PIPES_JSON.exists():
        raise SystemExit(f'{PIPES_JSON} missing: run setup_organ.sh')
    bank = PipeBank(a.temperament, a.a4)
    if a.list_stops:
        for d in DIVS:
            print(f'{d} ({DIVISION_NAMES[d]}):')
            for sk, st in bank.stops.items():
                if st['division'] == d:
                    print(f'    {st["name"]}')
        return {}
    if a.list_registrations:
        db = json.load(open(REGISTRATIONS_JSON))
        for d, regs in db['divisions'].items():
            print(f'{d}:')
            for n, stops in regs.items():
                print(f'    {n:18s} {", ".join(stops)}')
        print('presets:', ', '.join(db['presets']))
        return {}
    if not a.midi or not a.out:
        ap.error('IN.mid and -o OUT are required')
    t_start = time.time()
    warnings = []

    def warn(m):
        warnings.append(m)
        print('warning:', m, file=sys.stderr)

    voices, tmap, texts = load_midi(a.midi, warn)
    if not voices:
        raise SystemExit('no notes in the MIDI file')
    div_tl, reg_tl, side, enclosed = build_timelines(a.registration, voices, tmap, texts, bank, warn)
    merged, shared, handovers, folded = key_intervals(voices, div_tl, not a.no_fold, warn)
    events = pipe_events(merged, reg_tl)
    # reconciliation: every key press must open at least one pipe (unless its division is "off")
    with_pipes = {(e[0], e[2], round(e[3], 6)) for e in events if e[5]}
    silent = [(div, k, on, v) for div, k, on, off, v in merged if (v, k, round(on, 6)) not in with_pipes]
    for div, k, on, v in silent[:10]:
        if at(reg_tl[div], on + SNAP_S):
            warn(f'{v}: key {k} at {on:.3f} s opened no pipe')
    # pipe choice, grouped by sample for cache locality
    groups = defaultdict(list)
    borrowed = defaultdict(int)
    missing = defaultdict(int)
    chosen = []
    for v, sk, k, t0, t1, kd in events:
        pc = bank.choose(sk, k)
        if pc is None:
            missing[f'{sk} key {k}'] += 1
            continue
        if abs(pc.shift_cents) > 50:
            borrowed[f'{sk} key {k}'] += 1
        chosen.append([v, sk, k, t0, t1, pc, kd])
    # anticipation: an organist plays a key a little early for slow-speaking pipes; the whole key
    # (all its ranks) moves by a fraction of the median speech time of the pipes it opens
    antic = []
    if a.anticipate > 0:
        presses = defaultdict(list)
        for e in chosen:
            if e[6]:
                presses[(e[0], e[2], round(e[3], 6))].append(e)
        for es in presses.values():
            sp = float(np.median([bank.files[e[5].file]['speech_ms'] for e in es])) / 1000.0
            d = min(a.anticipate * sp, ANTICIPATE_MAX_S)
            antic.append(d * 1000)
            for e in es:
                e[3] -= d
    for v, sk, k, t0, t1, pc, kd in chosen:
        groups[pc.file].append((v, sk, k, t0, t1, pc))
    for m, c in missing.items():
        warn(f'no pipe for {m} ({c} events)')
    last = max(e[4] for e in events) if events else 0.0
    first = min((e[3] for g in groups.values() for e in g), default=0.0)
    if first + a.lead_in < 0:
        raise SystemExit(f'--lead-in {a.lead_in} is shorter than the anticipation of the first key')
    n_total = int((a.lead_in + last + 4.0) * SR)
    vnames = sorted(voices)
    stems = {v: np.zeros((n_total, 2), np.float32) for v in vnames}
    samples = SampleCache()
    rels = ReleaseCache(samples)
    rel_stats = []
    end_max = [0]

    # deterministic rng per sample file (python's str hash is salted, so use a digest)
    def stable(s):
        return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)

    def work_stable(item):
        fname, evs = item
        rng = np.random.default_rng(stable(f'{fname}|{a.seed}'))
        local_stats, parts = [], []
        for v, sk, k, t0, t1, pc in sorted(evs, key=lambda e: (e[3], e[1])):
            y, _ = render_event(bank, pc, t1 - t0, samples, rels, rng, local_stats)
            parts.append((v, int(round((t0 + a.lead_in) * SR)), y))
        used = {fname}
        for e in evs:
            used |= {f for f, _ in e[5].attacks} | {r[0] for r in e[5].releases}
        samples.drop(used)
        rels.drop(used)
        return local_stats, parts
    t_r = time.time()
    items = sorted(groups.items())
    chunk = max(8, 2 * a.jobs)
    with ThreadPoolExecutor(a.jobs) as ex:
        for c0 in range(0, len(items), chunk):
            # results are added in a fixed order, so renders are bit-identical from run to run
            for st, parts in ex.map(work_stable, items[c0:c0 + chunk]):
                rel_stats.extend(st)
                for v, i0, y in parts:
                    n = min(len(y), n_total - i0)
                    if n > 0:
                        stems[v][i0:i0 + n] += y[:n]
                        end_max[0] = max(end_max[0], i0 + n)
    t_render = time.time() - t_r
    # swell box on enclosed divisions (per voice, where the voice sits on an enclosed division)
    for v in vnames:
        if enclosed and voices[v]['cc11']:
            divs = {d for _, d in div_tl[v]}
            if divs & enclosed:
                stems[v] = swell(stems[v], voices[v]['cc11'], a.lead_in).astype(np.float32)
    for v, g in side.get('gain_db', {}).items():
        if v in stems:
            stems[v] *= 10 ** (g / 20)
    n_used = min(n_total, end_max[0] + int(0.05 * SR))
    dry = sum(stems[v][:n_used].astype(np.float64) for v in vnames)
    report = {'input': str(a.midi), 'voices': {}, 'warnings': warnings}
    # reverb
    hall = {}
    if a.no_reverb:
        mix = dry
    else:
        ir, _ = load_ir(a.ir)
        wet = np.stack([ss.oaconvolve(dry[:, c], ir[:, c]) for c in range(2)], axis=1)
        e_dry = float(np.sum(dry ** 2))
        g = math.sqrt(10 ** (a.wet_db / 10) * e_dry / float(np.sum(wet ** 2)))
        n80 = int(0.080 * SR)
        early = np.stack([ss.oaconvolve(dry[:, c], ir[:n80, c]) for c in range(2)], axis=1)
        mix = np.zeros_like(wet)
        mix[:len(dry)] += dry
        mix += g * wet
        late = wet.copy()
        late[:len(early)] -= early
        e_early = float(np.sum((np.pad(dry, ((0, len(early) - len(dry)), (0, 0))) + g * early) ** 2))
        hall = {'ir': str(a.ir), 'wet_db': a.wet_db, 'gain': g,
                'hall_re_dry_db': round(10 * math.log10(g * g * float(np.sum(wet ** 2)) / e_dry), 2),
                'c80_added_db': round(10 * math.log10(e_early / (g * g * float(np.sum(late ** 2)))), 2)}
    # trim the tail where it has decayed 80 dB below the loudest moment (at most 8 s after the last
    # pipe stops), then a 0.2 s fade: below the 24-bit dither of a quiet final chord's reverberation
    env = np.abs(mix).max(axis=1)
    thr = env.max() * 10 ** (-80 / 20)
    idx = np.nonzero(env > thr)[0]
    end = min(len(mix), int(idx[-1]) + int(0.2 * SR)) if len(idx) else len(mix)
    end = min(end, n_used + int(8.0 * SR))
    mix = mix[:end]
    fade = min(int(0.2 * SR), end // 4)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    tp = true_peak(mix)
    norm = 10 ** (a.peak_db / 20) / tp
    mix *= norm
    out = Path(a.out)
    if out.suffix.lower() in ('.wav', '.m4a'):
        out = out.with_suffix('')
    out.parent.mkdir(parents=True, exist_ok=True)
    wav = out.with_suffix('.wav')
    write_wav(mix.astype(np.float64), wav, out.name)
    res = {'wav': str(wav)}
    if not a.no_m4a:
        m4a = out.with_suffix('.m4a')
        res['m4a_tagged'] = write_m4a(wav, m4a, out.name)
        res['m4a'] = str(m4a)
    if a.stems:
        sd = Path(a.stems)
        sd.mkdir(parents=True, exist_ok=True)
        for v in vnames:
            s = np.zeros((end, 2))
            m = min(end, n_used)
            s[:m] = stems[v][:m] * norm
            pk = float(np.abs(s).max())
            if pk >= 1.0:
                sf.write(str(sd / f'{v}.wav'), s.astype(np.float32), SR, subtype='FLOAT')
                warn(f'stem {v} peaks at {20 * math.log10(pk):+.1f} dBFS: written as 32-bit float')
            else:
                write_wav(s, sd / f'{v}.wav', f'{out.name} {v} (dry stem)')
    # report
    last_off = max(n['off'] for d in voices.values() for n in d['notes'])
    decay = edc_decay(mix, a.lead_in + last_off + 0.05, len(mix) / SR) if not a.no_reverb else None
    for v in vnames:
        seg = stems[v][:n_used].astype(np.float64) * norm
        act = np.abs(seg).max(axis=1) > 1e-4
        rms = float(np.sqrt(np.mean(seg[act] ** 2))) if act.any() else 0.0
        report['voices'][v] = {
            'notes': len(voices[v]['notes']),
            'divisions': [(round(t, 3) if t > -1e8 else 0.0, d) for t, d in div_tl.get(v, [])],
            'rms_dbfs_when_sounding': round(20 * math.log10(rms + 1e-12), 2),
            'peak_dbfs': round(20 * math.log10(float(np.abs(seg).max()) + 1e-12), 2),
            'stereo': stereo_stats(seg)}
    report['registration'] = {d: [{'t': round(t, 3) if t > -1e8 else 0.0,
                                   'stops': [bank.stops[s]['name'] for s in stops]}
                                  for t, stops in reg_tl[d]] for d in DIVS}
    rs = np.array(rel_stats) if rel_stats else np.zeros((0, 3))
    report.update({
        'output': res, 'duration_s': round(len(mix) / SR, 3), 'lead_in_s': a.lead_in,
        'temperament': a.temperament, 'a4': a.a4, 'pipe_events': sum(len(g) for g in groups.values()),
        'notes_in': sum(len(d['notes']) for d in voices.values()), 'key_presses': len(merged),
        'key_presses_without_pipes': len(silent),
        'pipes_used': len(groups), 'shared_keys': shared, 'handover_restrikes': handovers,
        'folded_notes': folded,
        'anticipation_ms': None if not antic else {
            'fraction_of_speech': a.anticipate, 'median': round(float(np.median(antic)), 1),
            'p95': round(float(np.percentile(antic, 95)), 1), 'max': round(float(np.max(antic)), 1)},
        'borrowed_pipe_events': dict(borrowed), 'missing': dict(missing),
        'release_join': None if not len(rs) else {
            'corr_median': round(float(np.median(rs[:, 0])), 4), 'corr_p5': round(float(np.percentile(rs[:, 0], 5)), 4),
            'keyup_shift_ms_max_abs': round(float(np.abs(rs[:, 1]).max()), 2),
            'level_match_db_range': [round(float(rs[:, 2].min()), 2), round(float(rs[:, 2].max()), 2)]},
        'hall': hall, 'final_decay_T20_s': None if decay is None else round(decay, 2),
        'stereo_mix': stereo_stats(mix), 'stereo_dry_sum': stereo_stats(dry[:n_used] * norm),
        'normalisation_gain_db': round(20 * math.log10(norm), 2), 'true_peak_dbtp': a.peak_db,
        'loudness': measure_file(wav), 'render_seconds': round(time.time() - t_start, 1),
        'pipe_render_seconds': round(t_render, 1)})
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        json.dump(report, open(a.json, 'w'), indent=1, ensure_ascii=False)
    print(f'wrote {wav} ({report["duration_s"]} s, {report["pipe_events"]} pipe events, '
          f'{len(groups)} pipes, render {report["render_seconds"]} s)'
          + (f', C80(added) {hall["c80_added_db"]:+.1f} dB' if hall else '')
          + (f', final decay T20 {report["final_decay_T20_s"]} s' if decay else ''))
    return report


if __name__ == '__main__':
    main()
