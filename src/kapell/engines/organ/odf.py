"""GrandOrgue ODF parser and pipe-sample reader for the Norrfjärden sample set.

The ODF (``NorrfjardenChurch.organ``) is an INI file in GrandOrgue's "old" format: every stop lists
its pipes directly (``Pipe001=HvP8\\036-C.wav``), with per-pipe attack alternates, releases chosen by
key-press time (``Pipe001Release001MaxKeyPressTime=150``), pitch and amplitude corrections.
``REF:mmm:sss:ppp`` points at pipe ppp of the sss-th stop of manual mmm.

The sample files are WavPack-compressed although they are named ``.wav``; ``read_sample`` decodes
them with ``wvunpack`` (to a pipe, nothing is written to disk) and returns the audio together with the
RIFF ``smpl`` loops and ``cue`` point that GrandOrgue uses:

* the main file of a pipe holds attack, steady tone (one or more loops) and, after the cue point,
  the recorded release (used for key presses longer than the longest ``MaxKeyPressTime``);
* ``relNNNNN/`` files hold releases recorded after a short key press (<= NNNNN ms); their cue
  point is where the release proper begins, preceded by a little steady tone.
"""
from __future__ import annotations

import re
import struct
import subprocess
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from organ_paths import ODF, SET_DIR, WVUNPACK

# Real divisions of the instrument (manual index in the ODF -> contract name).
DIVISIONS = {'000': 'PED', '001': 'POS', '002': 'HW', '003': 'OW'}
DIVISION_NAMES = {'PED': 'Pedahl', 'POS': 'Rückpositief', 'HW': 'Hauptwerck', 'OW': 'Oberwerck'}


def parse_ini(path=ODF):
    secs = OrderedDict()
    cur = None
    for line in open(path, encoding='latin1').read().splitlines():
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        m = re.match(r'\[(.+)\]$', line)
        if m:
            cur = m.group(1)
            secs[cur] = {}
            continue
        if '=' in line and cur is not None:
            k, v = line.split('=', 1)
            secs[cur][k.strip()] = v.strip()
    return secs


@dataclass
class PipeDef:
    index: int                     # 1-based logical pipe number in the stop
    file: str                      # main sample (attack + loops + release after the cue)
    attacks: list                  # [main file, alternates...]
    releases: list                 # [(file, max_key_press_ms or None)]
    pitch_tuning: float = 0.0      # ODF cents correction (informative; we measure pitch)
    amp: float = 1.0               # pipe AmplitudeLevel / 100
    harmonic: float = 8.0          # GrandOrgue harmonic number (8 = 8', 16 = 4', 4 = 16', 24 = 2 2/3')
    loops: list | None = None      # ODF loop override [(start, end)], else the file's smpl loops


@dataclass
class StopDef:
    division: str
    name: str
    section: str
    amp: float
    harmonic: float
    pipes: list = field(default_factory=list)
    extra_files: list = field(default_factory=list)   # subsemitone pipes (D# beside Eb), same rank


def _path(p):
    return p.replace('\\', '/')


def _pipe(d, i, stop_harm):
    pre = f'Pipe{i:03d}'
    main = _path(d[pre])
    attacks = [main]
    for a in range(1, int(d.get(pre + 'AttackCount', 0)) + 1):
        attacks.append(_path(d[f'{pre}Attack{a:03d}']))
    rels = []
    for r in range(1, int(d.get(pre + 'ReleaseCount', 0)) + 1):
        f = _path(d[f'{pre}Release{r:03d}'])
        mk = d.get(f'{pre}Release{r:03d}MaxKeyPressTime')
        rels.append((f, None if mk in (None, '-1') else float(mk)))
    if not rels and d.get(pre + 'LoadRelease', 'Y') != 'N':
        rels.append((main, None))
    loops = None
    if pre + 'LoopCount' in d:
        loops = [(int(d[f'{pre}Loop{j:03d}Start']), int(d[f'{pre}Loop{j:03d}End']))
                 for j in range(1, int(d[pre + 'LoopCount']) + 1)]
    return PipeDef(index=i, file=main, attacks=attacks, releases=rels,
                   pitch_tuning=float(d.get(pre + 'PitchTuning', 0)),
                   amp=float(d.get(pre + 'AmplitudeLevel', 100)) / 100.0,
                   harmonic=float(d.get(pre + 'HarmonicNumber', stop_harm)), loops=loops)


@lru_cache(maxsize=1)
def load_organ():
    """-> {division: {stop name: StopDef}} for the four real divisions (sounding stops only)."""
    secs = parse_ini()
    manual_stops = {}
    for m in range(int(secs['Organ']['NumberOfManuals']) + 1):
        md = secs.get(f'Manual{m:03d}')
        if md is None:
            continue
        n = int(md.get('NumberOfStops', 0))
        manual_stops[f'{m:03d}'] = [md[f'Stop{s:03d}'] for s in range(1, n + 1)]
    org = {v: OrderedDict() for v in DIVISIONS.values()}
    by_section = {}
    for mi, div in DIVISIONS.items():
        for sid in manual_stops[mi]:
            d = secs[f'Stop{sid}']
            if 'NumberOfLogicalPipes' not in d or int(d['NumberOfLogicalPipes']) < 12:
                continue          # blower, calcant, bird, star, stop-noise pseudo stops
            p1 = d.get('Pipe001', '')
            if 'Effects' in p1 or p1.startswith('REF:'):
                continue
            harm = float(d.get('HarmonicNumber', 8))
            st = StopDef(division=div, name=d['Name'], section=f'Stop{sid}',
                         amp=float(d.get('AmplitudeLevel', 100)) / 100.0, harmonic=harm)
            for i in range(1, int(d['NumberOfLogicalPipes']) + 1):
                st.pipes.append(_pipe(d, i, harm))
            org[div][st.name] = st
            by_section[(mi, manual_stops[mi].index(sid) + 1)] = st
    # subsemitone manuals: stops that REF the main stops except for their own D# pipes
    for mi, sids in manual_stops.items():
        if mi in DIVISIONS:
            continue
        for sid in sids:
            d = secs[f'Stop{sid}']
            refs = [v for k, v in d.items() if re.match(r'Pipe\d{3}$', k) and v.startswith('REF:')]
            if not refs:
                continue
            _, rm, rs, _ = refs[0].split(':')
            target = by_section.get((rm, int(rs)))
            if target is None:
                continue
            harm = float(d.get('HarmonicNumber', target.harmonic))
            for i in range(1, int(d.get('NumberOfLogicalPipes', 0)) + 1):
                v = d.get(f'Pipe{i:03d}', '')
                if v and not v.startswith('REF:'):
                    target.extra_files.append(_pipe(d, i, harm))
    return org


def stop_lookup(org=None):
    """case- and accent-tolerant name -> (division, stop name)."""
    org = org or load_organ()
    out = {}
    for div, stops in org.items():
        for name in stops:
            out[(div, norm_name(name))] = name
    return out


def norm_name(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9/]+', ' ', s.lower()).strip()


# ---------------------------------------------------------------------------------------------
# samples

def parse_riff(data: bytes):
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('not a RIFF/WAVE stream')
    pos, ch = 12, {}
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4].decode('latin1')
        sz = struct.unpack('<I', data[pos + 4:pos + 8])[0]
        ch.setdefault(cid, []).append(data[pos + 8:pos + 8 + sz])
        pos += 8 + sz + (sz & 1)
    return ch


@dataclass
class Sample:
    audio: np.ndarray        # float32 (n, 2)
    sr: int
    loops: list              # [(start, end)] end inclusive (RIFF smpl convention)
    cue: int | None          # release start (sample index)
    smpl_pitch: float | None # MIDI note (fractional) from the smpl chunk


def decode_bytes(path: Path) -> bytes:
    raw = open(path, 'rb').read(4)
    if raw == b'RIFF':
        return open(path, 'rb').read()
    return subprocess.run([WVUNPACK, '-q', '-y', str(path), '-o', '-'], check=True,
                          capture_output=True).stdout


def read_sample(rel: str) -> Sample:
    data = decode_bytes(SET_DIR / rel)
    ch = parse_riff(data)
    fmt = ch['fmt '][0]
    tag, nch, sr = struct.unpack('<HHI', fmt[:8])
    bits = struct.unpack('<H', fmt[14:16])[0]
    raw = ch['data'][0]
    if tag not in (1, 0xFFFE) or bits not in (16, 24, 32):
        raise ValueError(f'{rel}: unsupported format tag={tag} bits={bits}')
    if bits == 24:
        b = np.frombuffer(raw[:len(raw) // 3 * 3], dtype=np.uint8).reshape(-1, 3)
        x = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        x = np.where(x >= 1 << 23, x - (1 << 24), x).astype(np.float32) / float(1 << 23)
    elif bits == 16:
        x = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
    else:
        x = np.frombuffer(raw, dtype='<i4').astype(np.float32) / float(1 << 31)
    x = x[:len(x) // nch * nch].reshape(-1, nch)
    if nch == 1:
        x = np.repeat(x, 2, axis=1)
    loops, pitch, cue = [], None, None
    if 'smpl' in ch:
        b = ch['smpl'][0]
        unity, frac = struct.unpack('<II', b[12:20])
        pitch = unity + frac / 2.0 ** 32
        nl = struct.unpack('<I', b[28:32])[0]
        for i in range(nl):
            _, _, s, e, _, _ = struct.unpack('<IIIIII', b[36 + 24 * i:60 + 24 * i])
            loops.append((int(s), int(e)))
    if 'cue ' in ch:
        b = ch['cue '][0]
        nc = struct.unpack('<I', b[:4])[0]
        offs = [struct.unpack('<II4sIII', b[4 + 24 * i:28 + 24 * i])[5] for i in range(nc)]
        if offs:
            cue = int(min(offs))
    return Sample(audio=np.ascontiguousarray(x), sr=sr, loops=loops, cue=cue, smpl_pitch=pitch)


def file_key(rel: str) -> int:
    """organ key number from the file name ('HvP8/060-C.wav' -> 60)."""
    m = re.match(r'(\d{3})', rel.split('/')[-1])
    return int(m.group(1)) if m else -1


if __name__ == '__main__':
    org = load_organ()
    for div, stops in org.items():
        print(div, DIVISION_NAMES[div])
        for n, st in stops.items():
            files = sorted({p.file for p in st.pipes} | {p.file for p in st.extra_files})
            print(f'   {n:28s} h={st.harmonic:g} amp={st.amp:.2f} pipes={len(st.pipes)} files={len(files)} '
                  f'extra={len(st.extra_files)} rel={len(st.pipes[20].releases)}')
