#!/usr/bin/env python3
"""Build the orchestra's sampled instruments (SFZ + prepared samples) from the
free libraries, one "set" per (part, library).

  python3 orch_build.py [--only fl,vn1] [--sets iowa,vsco] [--jobs 8] [--force] [--sfz-only]

For every note of a set it
  1. cuts the note (Iowa chromatic runs are segmented on the silences; VSCO and
     VPO3 files are one note each), high-passes just below the fundamental
     (sustains) and resamples to 48 kHz;
  2. trims to the onset and measures: pitch (harmonic-comb estimate on the
     steady part, octave checked), K-weighted (BS.1770) steady level, rise
     times t20 / t3 (steady -20 / -3 dB), the most stable stretch;
  3. extends sustains shorter than SUSTAIN_S by pitch-synchronous grain
     splicing (the quartet's extend_sustain: cross-correlation aligned splices,
     70 ms crossfades, random grain order) and sets loop points for longer notes;
  4. writes 24-bit WAVs under $SAMPLE_LIBRARIES/Orchestra/built/<part>/<set>/ and
     meta.json.

Then write_sfz() writes built/<part>/<set>.sfz:
  * every layer calibrated to the same loudness on a smooth register curve
    (register slope kept to +-2 dB): the SFZ layers carry TIMBRE only; the
    renderer applies all loudness (CC1 -> BALANCE table, CC11, CC7) as gain;
  * dynamic layers crossfade on CC1 only inside narrow zones between their
    anchors (two recordings of one note sounding together interfere); the
    renderer's layer plan keeps sfizz out of the zones;
  * CC2 = the true dynamic level: a high shelf (2.2 kHz) follows it relative to
    the playing layer's anchor, so the timbre also moves inside a layer;
  * CC20 articulation groups: 0-63 normal (recorded attack, slow swells cut to
    NORMAL_RISE), 64-95 legato (enters in the sustain, 30 ms fade-in), 96-127
    short (staccato samples where the library has them, else the attack of the
    sustain sample with a short decay);  timpani: 0-63 strokes, 64-127 rolls;
  * CC21 release time 0.03 + 1.2 s x v/127;  velocity: accent (vel 64 = 0 dB,
    127 = +3 dB, 1 = -1.4 dB) and attack speed;
  * tune per region = measured error (+ closed-loop corrections from
    verify_tuning, built/tuning_corrections.json); hint_ram_based=1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orch_common import (BUILT, IOWA_WINDS, PARTS, SR, VPO3_ROOT, VSCO_ROOT, midi_name,  # noqa: E402
                         midi_to_hz, note_to_midi)
from iowa_common import env_db, estimate_f0, load_audio  # noqa: E402  (strings helpers, read-only)
from iowa_analyze import segment  # noqa: E402
from iowa_build import extend_sustain, find_loop, k_level_db, stable_window  # noqa: E402

SUSTAIN_S = 8.0
BUILD_VERSION = 3
REF_DB = -20.0                  # K-weighted steady level every layer is calibrated to (mid-register)
REGISTER_SLOPE_DB = 2.0
NORMAL_RISE = 0.09
SHORT_RISE = 0.03
EQ_FREQ = 2200
# brightness shelf depth (dB per 127 CC2 steps) by family; 0 dB at the playing layer's anchor
EQ_DEPTH = {"strings": 14.0, "winds": 10.0, "brass": 16.0, "perc": 8.0}
# layer anchors on perform.py's CC1 scale, by the number of recorded layers
ANCHORS = {1: [88], 2: [62, 101], 3: [49, 88, 114], 4: [49, 75, 101, 120]}
XF_HALF = 3.5                   # crossfade zone half width (CC steps) around the midpoint of two anchors
CORR_PATH = BUILT / "tuning_corrections.json"
# the controller each articulation's layer crossfade listens to (the renderer runs one
# layer plan per articulation, so a held value never sits in another one's zone)
LAYER_CC = {"sus": 1, "hit": 1, "stac": 3, "roll": 3}


# =============================================================== catalogs
def _iowa_range(tok: str):
    m = re.fullmatch(r"([A-G][b#]?\d)([A-G][b#]?\d)?", tok.strip())
    if not m:
        return None
    lo = note_to_midi(m.group(1))
    hi = note_to_midi(m.group(2)) if m.group(2) else lo
    return lo, hi


IOWA_FILES = {  # part -> (filename prefix, style filter)
    "fl": ("Flute.vib.", None), "ob": ("Oboe.", None), "cl": ("BbClar.", None), "bn": ("Bassoon.", None),
    "hn": ("Horn.", None), "tpt": ("Trumpet.novib.", None), "tbn": ("TenorTrombone.", None),
    "btbn": ("BassTrombone.", None), "tba": ("Tuba.", None),
}


def cat_iowa(part: str) -> list[dict]:
    pre, _ = IOWA_FILES[part]
    out = []
    for f in sorted(IOWA_WINDS.glob(pre + "*.aif*")):
        rest = f.name[len(pre):].rsplit(".", 1)[0]          # 'pp.B3B4' or 'mf. E2B2'
        dyn, _, rng = rest.partition(".")
        if dyn not in ("pp", "mf", "ff"):
            continue
        r = _iowa_range(rng)
        if r is None:
            continue
        out.append(dict(kind="iowa_run", file=str(f), layer=dyn, lo=r[0], hi=r[1], art="sus"))
    return out


VSCO_DIRS = {  # part -> [(dir, art)]
    "fl": [("Woodwinds/Flute/susvib", "sus"), ("Woodwinds/Flute/stac", "stac")],
    "ob": [("Woodwinds/Oboe/Vib", "sus"), ("Woodwinds/Oboe/Stacc", "stac")],
    "cl": [("Woodwinds/Clarinet/susLong", "sus"), ("Woodwinds/Clarinet/stac", "stac")],
    "bn": [("Woodwinds/Bassoon/sus", "sus"), ("Woodwinds/Bassoon/stac", "stac")],
    "hn": [("Brass/F Horn/sus", "sus"), ("Brass/F Horn/stac", "stac")],
    "tpt": [("Brass/Trumpet/sus", "sus"), ("Brass/Trumpet/stac", "stac")],
    "tbn": [("Brass/Tenor Trombone/sus", "sus"), ("Brass/Tenor Trombone/stac", "stac")],
    "tba": [("Brass/Tuba/sus", "sus"), ("Brass/Tuba/stac", "stac")],
    "vn1": [("Strings/Violin Section/susVib", "sus"), ("Strings/Violin Section/Spic", "stac")],
    "vn2": [("Strings/Violin Section/susVib", "sus"), ("Strings/Violin Section/Spic", "stac")],
    "va": [("Strings/Viola Section/susvib", "sus"), ("Strings/Viola Section/spic", "stac")],
    "vc": [("Strings/Cello Section/susvib", "sus"), ("Strings/Cello Section/spic", "stac")],
    "cb": [("Strings/Solo Contrabass/SusVib", "sus"), ("Strings/Solo Contrabass/Spic", "stac")],
    "timp": [("Percussion/Timpani", "hit"), ("Percussion/Timpani/Rolls", "roll")],
}
VSCO_NOTE = re.compile(r"_([A-G]#?-?\d)_")
VSCO_VEL = re.compile(r"_v(\d)")
VSCO_RR = re.compile(r"_(?:rr)?(\d)(?:_[A-Za-z]+)?\.wav$", re.I)


def cat_vsco(part: str) -> list[dict]:
    out = []
    for d, art in VSCO_DIRS.get(part, []):
        for f in sorted((VSCO_ROOT / d).glob("*.wav")):
            v = VSCO_VEL.search(f.name)
            rr = re.search(r"_rr(\d)", f.name)
            e = dict(kind="file", file=str(f), art=art, vlayer=int(v.group(1)) if v else 1,
                     rr=int(rr.group(1)) if rr else 1)
            if part == "timp":
                dm = re.match(r"Timpani(\d)_", f.name)
                e["drum"] = int(dm.group(1)) if dm else 0
                e["nominal"] = None
            else:
                m = VSCO_NOTE.search(f.name)
                if not m:
                    continue
                e["nominal"] = note_to_midi(m.group(1))        # octave checked by measurement
            out.append(e)
    # the stac/spic sets of a few instruments carry more velocity layers than the
    # sustains; layers are ranked per articulation later
    return out


def parse_sfz(path: Path) -> list[dict]:
    """Minimal SFZ reader (VPO3 patches): <group>/<region> opcode inheritance."""
    txt = path.read_text(errors="replace")
    txt = re.sub(r"//[^\n]*", "", txt)
    regions, group, cur, ctl = [], {}, None, {}
    tokens = re.split(r"(<\w+>)", txt)
    header = None
    for tok in tokens:
        if re.fullmatch(r"<\w+>", tok):
            if cur is not None:
                regions.append(cur)
                cur = None
            header = tok
            if header == "<group>":
                group = {}
            elif header == "<region>":
                cur = dict(group)
            continue
        for m in re.finditer(r"(\w+)=(.*?)(?=\s+\w+=|$)", tok.replace("\n", " ")):
            k, v = m.group(1), m.group(2).strip()
            if header == "<region>" and cur is not None:
                cur[k] = v
            elif header == "<group>":
                group[k] = v
            elif header == "<control>":
                ctl[k] = v
    if cur is not None:
        regions.append(cur)
    base = path.parent / ctl.get("default_path", "")
    for r in regions:
        r["_path"] = str((base / r["sample"].replace("\\", "/")).resolve())
    return regions


def _key(v: str) -> int:
    v = v.strip()
    return int(v) if re.fullmatch(r"-?\d+", v) else note_to_midi(v[0].upper() + v[1:])


VPO3_PATCH = {  # part -> [(patch, art)]   (sections the VSCO/Iowa sets do not have, and comparisons)
    "vn1": [("Strings/1st-violin-SEC-sustain.sfz", "sus"), ("Strings/1st-violin-SEC-staccato.sfz", "stac")],
    "vn2": [("Strings/2nd-violin-SEC-sustain.sfz", "sus"), ("Strings/2nd-violin-SEC-staccato.sfz", "stac")],
    "va": [("Strings/viola-SEC-sustain.sfz", "sus"), ("Strings/viola-SEC-staccato.sfz", "stac")],
    "vc": [("Strings/cello-SEC-sustain.sfz", "sus"), ("Strings/cello-SEC-staccato.sfz", "stac")],
    "cb": [("Strings/bass-SEC-sustain.sfz", "sus"), ("Strings/bass-SEC-staccato.sfz", "stac")],
    "hn": [("Brass/french-horn-SEC-sustain.sfz", "sus"), ("Brass/french-horn-SEC-staccato.sfz", "stac")],
    "btbn": [("Brass/bass-trombone-SOLO-sustain.sfz", "sus"), ("Brass/bass-trombone-SOLO-staccato.sfz", "stac")],
    "fl": [("Woodwinds/flute-SOLO-sustain.sfz", "sus")],
    "ob": [("Woodwinds/oboe-SOLO-sustain.sfz", "sus")],
    "cl": [("Woodwinds/clarinet-SOLO-sustain.sfz", "sus")],
    "bn": [("Woodwinds/bassoon-SOLO-sustain.sfz", "sus")],
    "tpt": [("Brass/trumpet-SOLO-sustain.sfz", "sus")],
    "tbn": [("Brass/trombone-SOLO-sustain.sfz", "sus")],
    "tba": [("Brass/tuba-SOLO-sustain.sfz", "sus")],
    "timp": [("Percussion/timpani-hit.sfz", "hit"), ("Percussion/timpani-roll.sfz", "roll")],
}


def cat_vpo3(part: str) -> list[dict]:
    out, seen = [], set()
    for patch, art in VPO3_PATCH.get(part, []):
        p = VPO3_ROOT / patch
        if not p.exists():
            continue
        for r in parse_sfz(p):
            if "pitch_keycenter" not in r and "key" not in r:
                continue
            k = _key(r.get("pitch_keycenter", r.get("key")))
            lovel = int(r.get("lovel", 1))
            key = (r["_path"], art)
            if part == "timp" and (art == "roll") != ("roll" in Path(r["_path"]).name.lower()):
                continue
            if "/VSCO2-CE/" in r["_path"]:
                continue                      # the 'vsco' set has these recordings (a stack must not double them)
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(kind="file", file=r["_path"], art=art, nominal=k, vlayer=lovel, rr=1,
                            vpo3_tune=float(r.get("tune", 0))))
    return out


CATALOG = {"iowa": cat_iowa, "vsco": cat_vsco, "vpo3": cat_vpo3}
# which sets exist for which part (candidates; the renderer's players come from SETS_USED in orch_parts.json)
CANDIDATES = {
    "fl": ["iowa", "vsco", "vpo3"], "ob": ["iowa", "vsco", "vpo3"], "cl": ["iowa", "vsco", "vpo3"],
    "bn": ["iowa", "vsco", "vpo3"], "hn": ["iowa", "vsco", "vpo3"], "tpt": ["iowa", "vsco", "vpo3"],
    "tbn": ["iowa", "vsco", "vpo3"], "btbn": ["iowa", "vpo3"], "tba": ["iowa", "vsco", "vpo3"],
    "timp": ["vsco", "vpo3"], "vn1": ["vsco", "vpo3"], "vn2": ["vsco", "vpo3"], "va": ["vsco", "vpo3"],
    "vc": ["vsco", "vpo3"], "cb": ["vsco", "vpo3"],
}


# =============================================================== DSP
def to48(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return x
    from fractions import Fraction
    fr = Fraction(SR, sr).limit_denominator(1000)
    return resample_poly(x, fr.numerator, fr.denominator, axis=0).astype(np.float32)


def hpf(x: np.ndarray, fc: float, order: int = 4) -> np.ndarray:
    sos = butter(order, fc, btype="highpass", fs=SR, output="sos")
    return sosfiltfilt(sos, x, axis=0).astype(np.float32)


def envelope(mono: np.ndarray, hop_s: float = 0.005):
    db, hop = env_db(mono, SR, hop_s)
    return db, hop


def measure(x: np.ndarray, art: str, lo: float, hi: float) -> dict:
    """Onset, rise times, steady level window, pitch of one note (48 kHz)."""
    mono = x.mean(axis=1)
    db, hop = envelope(mono)
    pk = float(db.max())
    above = np.flatnonzero(np.abs(mono) > 10 ** ((pk - 45) / 20) * np.sqrt(2))
    onset = max(0, int(above[0]) - int(0.004 * SR)) if len(above) else 0
    on_f = onset // hop
    last = np.flatnonzero(db > pk - 60)
    end = min(len(mono), (int(last[-1]) + 1) * hop + int(0.05 * SR)) if len(last) else len(mono)
    body = np.flatnonzero(db > pk - 12)
    body_end = int(body[-1]) if len(body) else on_f + 1
    core = db[on_f:body_end + 1]
    if art in ("sus", "roll") and len(core) > 8:
        steady = float(np.median(core[len(core) // 4:]))
    else:
        steady = pk
    rel = db[on_f:]
    r20 = np.flatnonzero(rel > steady - 20.0)
    r3 = np.flatnonzero(rel > steady - 3.0)
    t20 = float(r20[0] * hop / SR) if len(r20) else 0.0
    t3 = float(r3[0] * hop / SR) if len(r3) else t20 + 0.05
    sus = np.flatnonzero(db[: body_end + 1] > steady - 6.0)
    sus_end = float(sus[-1] * hop / SR) if len(sus) else body_end * hop / SR
    # pitch: steady part after the attack (strokes: 40-250 ms after the onset)
    if art in ("sus", "roll"):
        p0 = onset + int(max(t3, 0.15) * SR)
        p1 = min(int(sus_end * SR), p0 + int(1.2 * SR))
        if p1 - p0 < int(0.25 * SR):
            p0, p1 = onset + int(t20 * SR), max(onset + int(0.3 * SR), int(sus_end * SR))
    else:
        p0 = onset + int(max(t3, 0.03) * SR)
        p1 = min(len(mono), p0 + int(0.25 * SR))
    seg = mono[p0:p1] if p1 - p0 > 2048 else mono[onset:onset + int(0.4 * SR)]
    f0, conf = estimate_f0(seg, SR, lo, hi)
    return dict(onset=int(onset), end=int(end), peak_db=pk, steady_db=steady, t20=t20, t3=t3,
                sus_end=sus_end, f0=f0, conf=conf)


TIMP_PARTIALS = [(1.0, 1.0), (1.5, 0.8), (2.0, 0.6), (2.44, 0.35), (2.9, 0.25)]


def timp_pitch(x: np.ndarray, onset: int, nominal: int | None = None) -> float:
    """Principal tone of a timpano (MIDI, fractional).  A kettledrum's modes sit
    near 1 : 1.5 : 2 : 2.44 : 2.9 of the principal and the 1.5 mode is often the
    strongest, so a single peak or a harmonic comb picks the fifth or the
    octave below.  Instead every candidate principal (5-cent steps) is scored
    by the log spectrum at all five mode ratios (+-1.5 %), 0.1-1.0 s after the
    stroke.  Search: nominal +-2 semitones when the file is named by pitch,
    else D2-C4."""
    mono = x.mean(axis=1)
    seg = mono[onset + int(0.10 * SR): onset + int(1.0 * SR)]
    n = 1 << 18
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n))
    ls = np.log(spec / (np.median(spec[: int(2000 * n / SR)]) + 1e-12) + 1e-9)
    df = SR / n
    lo, hi = (nominal - 2.0, nominal + 2.0) if nominal else (37.0, 61.0)
    cands = np.arange(lo, hi, 0.05)
    best, arg = -1e9, lo
    for c in cands:
        f = 440.0 * 2 ** ((c - 69) / 12)
        sc = 0.0
        for r, w in TIMP_PARTIALS:
            i0, i1 = int(f * r * 0.985 / df), int(f * r * 1.015 / df) + 1
            sc += w * float(ls[i0:i1].max())
        if sc > best:
            best, arg = sc, c
    # refine on the principal's own peak
    f = 440.0 * 2 ** ((arg - 69) / 12)
    i0, i1 = int(f * 0.985 / df), int(f * 1.015 / df) + 1
    i = i0 + int(np.argmax(spec[i0:i1]))
    a_, b_, c_ = np.log(spec[i - 1:i + 2] + 1e-12)
    d = 0.5 * (a_ - c_) / (a_ - 2 * b_ + c_) if (a_ - 2 * b_ + c_) != 0 else 0.0
    return 69 + 12 * np.log2((i + d) * df / 440.0)


def pitch_with_octave(x: np.ndarray, art: str, nominal: int) -> dict:
    """Measure with the nominal key, and one octave either side; keep the best comb score."""
    best = None
    for off in (0, -12, 12):
        k = nominal + off
        if not 12 <= k <= 115:
            continue
        m = measure(x, art, k - 1.5, k + 1.5)
        m["key"] = k
        if best is None or m["conf"] > best["conf"] * 1.15:
            best = m
    return best


def segment_run(mono: np.ndarray, lo: int, hi: int) -> list[tuple[int, int, float]]:
    """Split an Iowa chromatic run (48 kHz mono) into notes -> [(start, end, f0 midi)].
    Wind and brass runs are often played almost legato (gaps of 20-100 ms, or
    none), so besides silences it splits at envelope dips (>= 9 dB below the
    level 0.15 s either side) and where the pitch track steps by >= 0.6 semitone."""
    hop = int(0.01 * SR)
    wlen = int(max(0.01, 3.0 / midi_to_hz(lo)) * SR)            # >= 3 periods: no waveform ripple
    pw = np.convolve(mono.astype(np.float64) ** 2, np.ones(wlen) / wlen, mode="same")
    db = 10 * np.log10(pw[::hop][: len(mono) // hop] + 1e-20)
    pk = float(db.max())
    floor = float(np.percentile(db, 2))
    act = db > max(floor + 10.0, pk - 45.0)
    n = len(db)
    w = 15
    left = np.array([db[max(0, i - w):i].max() if i > 0 else -200 for i in range(n)])
    right = np.array([db[i + 1:i + 1 + w].max() if i + 1 < n else -200 for i in range(n)])
    dip = (db < np.minimum(left, right) - 9.0) & (db < pk - 6)
    act &= ~dip
    regions, i = [], 0
    while i < n:
        if act[i]:
            j = i
            while j < n and act[j]:
                j += 1
            if j - i >= 25:
                regions.append((i, j))
            i = j
        else:
            i += 1
    out = []
    step = 5                                            # pitch every 50 ms
    win = max(4, int(np.ceil(8 / midi_to_hz(lo - 1) / 0.01)))   # at least 8 periods of the lowest note
    for a, b in regions:
        times, pitch = [], []
        for f in range(a + 2, b - win, step):
            seg = mono[f * hop: (f + win) * hop]
            p, c = estimate_f0(seg, SR, lo - 1.5, hi + 1.5)
            times.append(f)
            pitch.append(p if c > 2.5 else np.nan)
        pitch = np.array(pitch)
        cuts = [a]
        last = None
        run = []
        for f, p in zip(times, pitch):
            if np.isnan(p):
                continue
            if last is not None and abs(p - last) >= 0.6:
                run.append(f)
                if len(run) >= 2:                        # two frames agree: a new note
                    cuts.append(run[0])
                    last = p
                    run = []
                continue
            run = []
            last = p if last is None else 0.7 * last + 0.3 * p
        cuts.append(b)
        for x0, x1 in zip(cuts, cuts[1:]):
            if x1 - x0 < 35:
                continue
            seg = mono[x0 * hop + int(0.1 * SR): min(x1 * hop, x0 * hop + int(1.3 * SR))]
            if len(seg) < 4096:
                continue
            f0, conf = estimate_f0(seg, SR, lo - 1.5, hi + 1.5)
            if conf >= 3.0:
                out.append((x0 * hop, x1 * hop, f0))
    return out


# =============================================================== one note
def process(job: dict) -> dict | None:
    """job: part, set, entry (+ seg for Iowa), out path -> meta dict."""
    part, e = job["part"], job["entry"]
    x, sr = load_audio(Path(e["file"]))
    if "seg" in job:
        a, b = job["seg"]
        x = x[a:b]
    x = to48(np.asarray(x, dtype=np.float32), sr)
    art = e["art"]
    if part == "timp":
        x = hpf(x, 25.0, 2)
    else:
        nom = job.get("key") or e.get("nominal") or 60
        x = hpf(x, 0.7 * midi_to_hz(min(nom, PARTS[part]["lo"]) - 1))
    if part == "timp":
        m = measure(x, art, 36, 61)
        m["f0"] = timp_pitch(x, m["onset"], e.get("nominal") if job["set"] == "vpo3" else None)
        m["key"] = int(round(m["f0"]))
    elif "key" in job:
        m = measure(x, art, job["key"] - 1.5, job["key"] + 1.5)
        m["key"] = job["key"]
    else:
        m = pitch_with_octave(x, art, e["nominal"])
    on = max(0, m["onset"])
    y = x[on:m["end"]].copy()
    fi = int(0.002 * SR)
    y[:fi] *= np.linspace(0, 1, fi)[:, None]
    for k in ("sus_end",):
        m[k] = max(0.0, m[k] - on / SR)
    cents = round(100.0 * (m["f0"] - m["key"]), 1)
    meta = dict(part=part, set=job["set"], art=art, layer=job["layer"], key=int(m["key"]), cents=cents,
                f0=round(m["f0"], 3), conf=round(m["conf"], 2), t20=round(m["t20"], 4), t3=round(m["t3"], 4),
                src=Path(e["file"]).name, rr=e.get("rr", 1), ch=int(y.shape[1]), nominal=e.get("nominal"))
    if "drum" in e:
        meta["drum"] = e["drum"]
    s0 = s1 = None
    if art in ("sus", "roll"):
        s0, s1 = stable_window(y, SR, m["t3"], max(m["sus_end"], m["t3"] + 0.4))
        s1 = max(s1, s0 + int(0.2 * SR))
        steady = y[s0:s1]
        # always rebuild the sustain from the stable stretch: a recorded release or
        # fade after it is never looped
        seed = int(hashlib.sha1(meta["src"].encode()).hexdigest()[:8], 16)
        y = extend_sustain(y, SR, midi_to_hz(m["f0"]), s0, s1, int(SUSTAIN_S * SR), seed=seed)
        ls, le = find_loop(y.mean(axis=1).astype(np.float64), SR, midi_to_hz(m["f0"]))
        meta.update(loop_start=int(ls), loop_end=int(le))
    else:
        a = int(m["t20"] * SR)
        steady = y[a: a + int(0.15 * SR)]
        tail = int(0.03 * SR)
        y[-tail:] *= np.linspace(1, 0, tail)[:, None]
    meta["klevel_db"] = round(k_level_db(steady.astype(np.float64)), 2)
    meta["s0"], meta["s1"] = (int(s0), int(s1)) if s0 is not None else (0, 0)
    meta["len"] = int(len(y))
    # peak-normalise the file to -1 dBFS for storage; the gain goes into the SFZ
    pk = float(np.max(np.abs(y))) + 1e-9
    g = 10 ** (-1 / 20) / pk
    meta["norm_gain_db"] = round(20 * np.log10(g), 3)
    meta["klevel_db"] = round(meta["klevel_db"] + meta["norm_gain_db"], 2)
    out = Path(job["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), (y * g).astype(np.float32), SR, subtype="PCM_24")
    meta["path"] = str(out.relative_to(BUILT))
    return meta


# =============================================================== jobs per set
def rank_layers(entries: list[dict], field: str = "vlayer") -> dict:
    vals = sorted({e[field] for e in entries})
    return {v: i for i, v in enumerate(vals)}


def jobs_for(part: str, setname: str) -> list[dict]:
    ents = CATALOG[setname](part)
    jobs = []
    root = BUILT / part / setname
    if setname == "iowa":
        for e in ents:
            x, sr = load_audio(Path(e["file"]))
            x48 = to48(np.asarray(x, dtype=np.float32), sr)
            mono = hpf(x48, 0.7 * midi_to_hz(e["lo"] - 1)).mean(axis=1)
            found = segment_run(mono, e["lo"], e["hi"])
            if not found:
                continue
            n_exp = e["hi"] - e["lo"] + 1
            # the file's tuning offset (circular mean, so -0.45 and +0.55 agree)
            off = float(np.angle(np.mean(np.exp(2j * np.pi * np.array([f for _, _, f in found])))) / (2 * np.pi))
            used = set()
            for a, b, f0 in sorted(found, key=lambda s_: s_[0] - s_[1]):     # longest first wins a key
                k = int(round(f0 - off))
                if k in used or not e["lo"] - 1 <= k <= e["hi"] + 1:
                    continue
                used.add(k)
                # segments are in 48 kHz frames of the resampled file; map back to the source rate
                a0 = int(max(0, a - int(0.02 * SR)) * sr / SR)
                b0 = int(min(len(mono), b + int(0.05 * SR)) * sr / SR)
                jobs.append(dict(part=part, set=setname, entry=e, seg=(a0, b0), key=k, layer=e["layer"],
                                 out=str(root / f"{e['layer']}_{k:03d}_{midi_name(k)}.wav")))
            if len(used) < n_exp:
                print(f"  {Path(e['file']).name}: {len(used)}/{n_exp} notes found")
        return jobs
    # one note per file
    by_art = defaultdict(list)
    for e in ents:
        by_art[e["art"]].append(e)
    for art, es in by_art.items():
        rk = rank_layers(es)
        nl = len(rk)
        for i, e in enumerate(es):
            li = rk[e["vlayer"]]
            layer = f"L{li + 1}of{nl}"
            tag = f"{art}_{layer}_{i:03d}_rr{e.get('rr', 1)}"
            jobs.append(dict(part=part, set=setname, entry=e, layer=layer, out=str(root / f"{tag}.wav")))
    return jobs


def build_set(part: str, setname: str, jobs_n: int, force: bool) -> list[dict]:
    root = BUILT / part / setname
    meta_p = root / "meta.json"
    if meta_p.exists() and not force:
        m = json.loads(meta_p.read_text())
        if m.get("version") == BUILD_VERSION:
            return m["notes"]
    jobs = jobs_for(part, setname)
    if not jobs:
        return []
    with ProcessPoolExecutor(jobs_n) as ex:
        metas = [m for m in ex.map(process, jobs, chunksize=2) if m]
        # one octave convention per library (VSCO names sound an octave higher than
        # C4 = 60 would say): a file measured in another octave (a clarinet's weak
        # even harmonics fool the octave check) is re-measured at the consensus pitch
        offs = [m["key"] - m["nominal"] for m in metas if m.get("nominal") is not None and part != "timp"]
        if offs:
            octs = [12 * round(o / 12) for o in offs]
            mode = max(set(octs), key=octs.count)
            redo = [dict(j, key=j["entry"]["nominal"] + mode) for j, m in zip(jobs, metas)
                    if m.get("nominal") is not None and 12 * round((m["key"] - m["nominal"]) / 12) != mode]
            if redo:
                print(f"  {part}/{setname}: {len(redo)} files re-measured at the library's octave ({mode:+d})")
                fixed = {j["out"]: m for j, m in zip(redo, ex.map(process, redo)) if m}
                metas = [fixed.get(str(BUILT / m["path"]), m) for m in metas]
    # Iowa: drop duplicate keys per layer (keep the more confident)
    best = {}
    for m in metas:
        k = (m["art"], m["layer"], m["key"], m.get("rr", 1), m.get("drum", 0), m["src"])
        if k not in best or m["conf"] > best[k]["conf"]:
            best[k] = m
    metas = sorted(best.values(), key=lambda m: (m["art"], m["layer"], m["key"]))
    if part == "timp":
        drums = defaultdict(list)
        for m in metas:
            if m.get("drum"):
                drums[m["drum"]].append(m["f0"])
        for m in metas:
            if m.get("drum"):
                f0 = float(np.median(drums[m["drum"]]))
                m["f0_own"] = m["f0"]
                m["f0"], m["key"] = round(f0, 3), int(round(f0))
                m["cents"] = round(100 * (f0 - m["key"]), 1)
    root.mkdir(parents=True, exist_ok=True)
    meta_p.write_text(json.dumps(dict(version=BUILD_VERSION, part=part, set=setname, notes=metas), indent=0))
    return metas


# =============================================================== SFZ
def load_corrections() -> dict:
    return json.loads(CORR_PATH.read_text()) if CORR_PATH.exists() else {}


def layer_order(metas: list[dict], art: str) -> list[str]:
    """Layers of one articulation from soft to loud.  Iowa: pp/mf/ff by name;
    library layers (L1of3...) by index (VSCO v1 < v2 < v3 is soft to loud)."""
    names = sorted({m["layer"] for m in metas if m["art"] == art})
    order = {"pp": 0, "p": 1, "mp": 2, "mf": 3, "f": 4, "ff": 5}
    return sorted(names, key=lambda n: order.get(n, 10 + int(re.sub(r"\D", "", n.split("of")[0]) or 0)))


def smooth_cal(metas: list[dict]) -> dict:
    """Per sample volume (dB) so each layer follows a smooth register curve at
    REF_DB (register slope kept to +-REGISTER_SLOPE_DB, 30 % of each key's own
    deviation kept, identical for all layers of that key)."""
    out = {}
    by = defaultdict(list)
    for m in metas:
        by[(m["art"], m["layer"])].append(m)
    for (art, lay), ms in by.items():
        ks = np.array([m["key"] for m in ms], dtype=float)
        vs = np.array([m["klevel_db"] for m in ms])
        if len(ms) >= 3:
            med = np.array([np.median(vs[np.abs(ks - k) <= 3]) for k in ks])
            coef = np.polyfit(ks, med, 2 if len(ms) > 6 else 1)
        else:
            coef = np.array([float(np.mean(vs))])
        kmid = float(np.median(ks))
        for m in ms:
            fit = float(np.polyval(coef, m["key"]))
            slope = float(np.clip(fit - float(np.polyval(coef, kmid)), -REGISTER_SLOPE_DB, REGISTER_SLOPE_DB))
            keep = 0.3 * float(np.clip(m["klevel_db"] - fit, -3, 3))
            out[m["path"]] = REF_DB + slope + keep - m["klevel_db"]
    return out


def key_bounds(keys: list[int], lo_all: int, hi_all: int, ext: int = 3):
    """Key range of each sample.  The lowest and highest samples reach at least
    `ext` semitones beyond themselves and always the part's whole compass
    (lo_all..hi_all): a note the contract accepts must never be silent, even if
    it is a few semitones beyond the recordings (the renderer routes such notes
    to a set that has a closer sample where the part has one)."""
    out = []
    for j, k in enumerate(keys):
        lo = min(lo_all, k - ext) if j == 0 else (keys[j - 1] + k) // 2 + 1
        hi = max(hi_all, k + ext) if j == len(keys) - 1 else (k + keys[j + 1]) // 2
        if j == 0:
            lo = min(lo, k)
        if j == len(keys) - 1:
            hi = max(hi, k)
        out.append((lo, hi))
    return out


def xf_zones(anchors: list[int]):
    """Per layer (xfin_lo, xfin_hi, xfout_lo, xfout_hi) on CC1 and its home range."""
    zones, home = [], []
    n = len(anchors)
    for i, a in enumerate(anchors):
        lo_mid = (anchors[i - 1] + a) / 2 if i > 0 else None
        hi_mid = (a + anchors[i + 1]) / 2 if i < n - 1 else None
        xin = (int(round(lo_mid - XF_HALF)), int(round(lo_mid + XF_HALF))) if lo_mid else None
        xout = (int(round(hi_mid - XF_HALF)), int(round(hi_mid + XF_HALF))) if hi_mid else None
        zones.append((xin, xout))
        home.append((xin[1] if xin else 0, xout[0] if xout else 127))
    return zones, home


def sparse_layers(metas: list[dict]) -> set:
    """(art, layer) pairs sampled on fewer than 40 % of the keys of the art's
    fullest layer (VSCO horn v4: 2 notes) are left out of the SFZ; holes in
    the other layers are filled from the neighbouring layer (fill_layers)."""
    out = set()
    for art in {m["art"] for m in metas}:
        cnt = {}
        for m in metas:
            if m["art"] == art:
                cnt.setdefault(m["layer"], set()).add(m["key"])
        full = max(len(v) for v in cnt.values())
        out |= {(art, k) for k, v in cnt.items() if len(v) < 0.4 * full}
    return out


def fill_layers(metas: list[dict]) -> list[dict]:
    """A layer that lacks a key the articulation's other layers have borrows
    that key's sample from the nearest layer (Iowa horn pp has no C2-B3: the mf
    notes stand in, a little brighter).  Borrowed entries carry 'borrowed'."""
    out = list(metas)
    for art in {m["art"] for m in metas}:
        names = layer_order(metas, art)
        by = {n: {} for n in names}
        for m in metas:
            if m["art"] == art:
                by[m["layer"]].setdefault(m["key"], []).append(m)
        keys = sorted({k for d in by.values() for k in d})
        for i, n in enumerate(names):
            own = np.array(sorted(by[n])) if by[n] else np.array([999])
            for k in keys:
                if k in by[n] or np.min(np.abs(own - k)) <= 3:
                    continue
                for j in sorted(range(len(names)), key=lambda j: (abs(j - i), -j if i == 0 else j)):
                    if k in by[names[j]]:
                        for m in by[names[j]][k]:
                            out.append(dict(m, layer=n, borrowed=names[j]))
                        break
    return out


def sfz_layers(metas: list[dict]) -> dict:
    """art -> [(layer name, anchor)] soft to loud."""
    out = {}
    drop = sparse_layers(metas)
    metas = [m for m in metas if (m["art"], m["layer"]) not in drop]
    for art in sorted({m["art"] for m in metas}):
        names = layer_order(metas, art)
        anchors = ANCHORS.get(len(names)) or list(np.linspace(49, 114, len(names)).round().astype(int))
        out[art] = list(zip(names, anchors))
    return out


VEL_CURVE = "amp_veltrack=100 amp_velcurve_1=0.605 amp_velcurve_64=0.708 amp_velcurve_127=1"


def write_sfz(part: str, setname: str, metas: list[dict]) -> Path:
    fam = PARTS[part]["family"]
    drop = sparse_layers(metas)
    metas = [m for m in metas if (m["art"], m["layer"]) not in drop]
    corr = load_corrections()
    cal = smooth_cal(metas)
    metas = fill_layers(metas)          # after calibration: a borrowed sample keeps its own volume
    lay = sfz_layers(metas)
    depth = EQ_DEPTH[fam]
    lo_all, hi_all = PARTS[part]["lo"], PARTS[part]["hi"]
    L = [f"// {PARTS[part]['name']} - set '{setname}' - generated by ricercar/audio/orchestra/orch_build.py",
         "// layers carry timbre only (all calibrated to one loudness); render_orchestra.py applies the dynamics",
         "// CC1 = dynamic layer (narrow crossfade zones), CC2 = true dynamic level (brightness shelf),",
         "// CC20 = articulation, CC21 = release, velocity = accent",
         "<control>", "hint_ram_based=1", "set_cc1=88", "set_cc2=88", "set_cc3=88", "set_cc20=0", "set_cc21=30",
         "<global>",
         f"{VEL_CURVE} volume=3",
         "ampeg_release=0.03 ampeg_release_oncc21=1.2",
         "bend_up=200 bend_down=-200"]
    arts_sus = [(0, 63, "normal"), (64, 95, "legato")]
    has_stac = "stac" in lay
    for art, groups in (("sus", arts_sus + ([] if has_stac else [(96, 127, "short")])),
                        ("stac", [(96, 127, "short")] if has_stac else []),
                        ("hit", [(0, 63, "hit")]), ("roll", [(64, 127, "roll")])):
        if art not in lay or not groups:
            continue
        zones, home = xf_zones([a for _, a in lay[art]])
        for li, (lname, anchor) in enumerate(lay[art]):
            ms = [m for m in metas if m["art"] == art and m["layer"] == lname]
            if part == "timp":
                ms_by_key = defaultdict(list)
                for m in ms:
                    ms_by_key[m["key"]].append(m)
            else:
                ms_by_key = defaultdict(list)
                for m in ms:
                    ms_by_key[m["key"]].append(m)
            keys = sorted(ms_by_key)
            bounds = key_bounds(keys, lo_all, hi_all, ext=5 if part == "timp" else 3)
            xin, xout = zones[li]
            for (lc, hc, kind) in groups:
                g = [f"<group> // {art} {lname} anchor cc1 {anchor} art {kind}",
                     f"locc20={lc} hicc20={hc}"]
                cc = LAYER_CC[art]
                if xin:
                    g.append(f"xfin_locc{cc}={xin[0]} xfin_hicc{cc}={xin[1]}")
                if xout:
                    g.append(f"xfout_locc{cc}={xout[0]} xfout_hicc{cc}={xout[1]}")
                g.append("xf_cccurve=power")
                g.append(f"eq1_type=hshelf eq1_freq={EQ_FREQ} eq1_bw=1 eq1_gain={-depth * anchor / 127:.2f} "
                         f"eq1_gain_oncc2={depth:g}")
                if kind in ("normal", "short", "hit") and art in ("sus", "roll"):
                    g.append("loop_mode=loop_continuous loop_crossfade=0.1")
                if kind == "normal":
                    g.append("ampeg_attack=0.03 ampeg_vel2attack=-0.022")
                elif kind == "legato":
                    g.append("loop_mode=loop_continuous loop_crossfade=0.1 ampeg_attack=0.03")
                elif kind == "short" and art == "sus":
                    g.append("ampeg_attack=0.006 ampeg_hold=0.03 ampeg_decay=0.14 ampeg_sustain=55")
                elif kind == "short":
                    g.append("loop_mode=one_shot ampeg_attack=0.002")
                elif kind == "hit":
                    g.append("loop_mode=no_loop ampeg_attack=0.001")    # damped at the note-off (CONTRACT section 4)
                elif kind == "roll":
                    g.append("loop_mode=loop_continuous loop_crossfade=0.15 ampeg_attack=0.02")
                L.append(g[0])
                L.append(" ".join(g[1:]))
                for k, (klo, khi) in zip(keys, bounds):
                    alts = sorted(ms_by_key[k], key=lambda m: (m.get("rr", 1), m["src"]))
                    n_rr = len(alts)
                    for ri, m in enumerate(alts):
                        tune = -m["cents"] + corr.get(f"{part}/{setname}/{art}/{lname}/{k}", 0.0)
                        vol = cal[m["path"]]               # the file is stored peak-normalised
                        rel = Path(m["path"]).relative_to(part)   # the SFZ sits in built/<part>/
                        reg = (f"<region> sample={rel} lokey={klo} hikey={khi} pitch_keycenter={k} "
                               f"tune={tune:.1f} volume={vol:.2f}")
                        if n_rr > 1:
                            reg += f" lorand={ri / n_rr:.3f} hirand={(ri + 1) / n_rr:.3f}"
                        if art in ("sus", "roll"):
                            reg += f" loop_start={m['loop_start']} loop_end={m['loop_end']}"
                        if kind in ("normal", "short", "legato") and art == "sus":
                            reg += f" offset={offset_for(m, kind)}"
                        reg += f"  // {midi_name(k)} {m['src']}"
                        L.append(reg)
    out = BUILT / part / f"{setname}.sfz"
    out.write_text("\n".join(L) + "\n")
    # the layer table the renderer's layer plan needs, with the measured onset
    # latency per articulation (tune_orchestra.py: note-on -> 6 dB below the peak)
    lat_p = BUILT / "latency.json"
    lat = json.loads(lat_p.read_text()).get(f"{part}/{setname}", {}) if lat_p.exists() else {}
    (BUILT / part / f"{setname}.layers.json").write_text(json.dumps(
        {art: dict(cc=LAYER_CC[art], anchors=[a for _, a in v], home=xf_zones([a for _, a in v])[1],
                   names=[n for n, _ in v], latency_ms=lat.get(art, {}).get("_median"),
                   latency_short_ms=lat.get("sus_short", {}).get("_median") if art == "sus" else None)
         for art, v in lay.items()}, indent=1))
    return out


def offset_for(m: dict, kind: str) -> int:
    """Sample start for an articulation (frames).  Every stroke starts no earlier
    than 5 ms before the tone reaches -20 dB, so all sets speak on the note-on;
    a normal note keeps at most NORMAL_RISE of a slow swell, a short one
    SHORT_RISE; a legato note enters in the sustain (after the attack)."""
    t20, t3 = m["t20"], m["t3"]
    start = max(0.0, t20 - 0.005)
    if kind == "normal":
        t = max(start, t3 - NORMAL_RISE)
    elif kind == "short":
        t = max(start, t3 - SHORT_RISE)
    else:
        t = float(np.clip(max(t3 + 0.04, 0.10), 0.10, max(0.10, m["s1"] / SR - 0.2 if m["s1"] else 0.3)))
    return int(t * SR)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", default="")
    ap.add_argument("--sets", default="")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sfz-only", action="store_true")
    a = ap.parse_args(argv)
    only = [p for p in a.only.split(",") if p] or list(PARTS)
    sets = [s for s in a.sets.split(",") if s]
    summary = {}
    for part in only:
        for s in CANDIDATES[part]:
            if sets and s not in sets:
                continue
            if a.sfz_only:
                mp = BUILT / part / s / "meta.json"
                if not mp.exists():
                    continue
                metas = json.loads(mp.read_text())["notes"]
            else:
                metas = build_set(part, s, a.jobs, a.force)
            if not metas:
                print(f"{part}/{s}: nothing built")
                continue
            p = write_sfz(part, s, metas)
            cents = np.array([m["cents"] for m in metas if m["art"] in ("sus", "roll")])
            summary[f"{part}/{s}"] = dict(notes=len(metas), sfz=str(p.relative_to(BUILT)),
                                          layers={k: v for k, v in
                                                  ((art, [n for n, _ in v]) for art, v in sfz_layers(metas).items())},
                                          keys=[min(m["key"] for m in metas), max(m["key"] for m in metas)],
                                          cents_abs_median=float(np.median(np.abs(cents))) if len(cents) else None)
            print(f"{part}/{s}: {len(metas)} samples -> {p.name} {summary[f'{part}/{s}']['layers']} "
                  f"keys {summary[f'{part}/{s}']['keys']}")
    (BUILT / "build_summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
