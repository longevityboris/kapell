"""Shared helpers for the adversarial audio QA of render_piano.py.

Independent of the renderer's own parsing: MIDI timing comes from mido's
playback iterator (its tempo handling), not from render_piano.TempoMap.
Audio goes to /tmp/pianoqa (never committed); numbers go to qa/results/*.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss
import soundfile as sf

QA = Path(__file__).resolve().parent
PIANO = QA.parent
ROOT = PIANO.parents[2]  # fugue-jp
PERFORM = PIANO.parents[1] / "tools" / "perform.py"
TMP = Path("/tmp/pianoqa")
RESULTS = QA / "results"
SR = 48000
LEAD_IN = 0.3  # render_piano.py default


def render(mid: Path, out: Path, *extra: str, stems: bool = True, json_report: bool = True) -> dict:
    """Run render_piano.py; returns the parsed render report."""
    cmd = [sys.executable, str(PIANO / "render_piano.py"), str(mid), "-o", str(out)]
    if stems:
        cmd += ["--stems", str(out) + "_stems"]
    rep = Path(str(out) + ".render.json")
    if json_report:
        cmd += ["--json", str(rep)]
    cmd += list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"render failed: {' '.join(cmd)}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return json.loads(rep.read_text()) if json_report else {}


def perform(score: Path, plan: Path, out_mid: Path, target: str = "piano") -> None:
    subprocess.run([sys.executable, str(PERFORM), str(score), str(plan), str(out_mid), "--target", target],
                   check=True, capture_output=True, text=True)


def midi_notes(path: Path) -> list[dict]:
    """Notes per track with absolute seconds, via mido's own tempo-aware playback."""
    mf = mido.MidiFile(path)
    # per-track names
    names = {}
    for i, tr in enumerate(mf.tracks):
        for m in tr:
            if m.type == "track_name":
                names[i] = m.name
                break
    # merge with track index: iterate each track separately using the global tempo map
    tempo_ev = []
    for tr in mf.tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "set_tempo":
                tempo_ev.append((t, m.tempo))
    tempo_ev.sort()
    if not tempo_ev or tempo_ev[0][0] != 0:
        tempo_ev.insert(0, (0, 500000))

    def tick2sec(tick):
        s, lt, tempo = 0.0, 0, tempo_ev[0][1]
        for tt, tp in tempo_ev:
            if tt > tick:
                break
            s += mido.tick2second(tt - lt, mf.ticks_per_beat, tempo)
            lt, tempo = tt, tp
        return s + mido.tick2second(tick - lt, mf.ticks_per_beat, tempo)

    notes = []
    for i, tr in enumerate(mf.tracks):
        t = 0
        pend = {}
        for m in tr:
            t += m.time
            if m.type == "note_on" and m.velocity > 0:
                pend.setdefault((m.channel, m.note), []).append((t, m.velocity))
            elif m.type in ("note_off", "note_on"):
                lst = pend.get((m.channel, m.note))
                if lst:
                    st, v = lst.pop(0)
                    notes.append(dict(voice=names.get(i, f"track{i}"), ch=m.channel, key=m.note,
                                      start=tick2sec(st), end=tick2sec(t), vel=v))
    notes.sort(key=lambda n: (n["start"], n["key"]))
    return notes


def read(path: Path) -> np.ndarray:
    x, sr = sf.read(path, dtype="float64", always_2d=True)
    assert sr == SR, (path, sr)
    return x


def db(x: float) -> float:
    return float(10 * np.log10(max(x, 1e-30)))


def rms_db(x: np.ndarray) -> float:
    return db(float(np.mean(x ** 2)))


# ITU-R BS.1770 K-weighting at 48 kHz (same coefficients as make_sfz.py)
_K1 = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585])
_K2 = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])


def kweight(x: np.ndarray) -> np.ndarray:
    return ss.lfilter(*_K2, ss.lfilter(*_K1, x, axis=0), axis=0)


def onset_flux(x: np.ndarray, hop: int = 48, win: int = 512, fmin: float = 60.0, fmax: float = 10000.0):
    """Log-magnitude spectral flux (positive part), frame times in s (frame centre)."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    f, t, Z = ss.stft(m, SR, window="hann", nperseg=win, noverlap=win - hop, boundary=None, padded=False)
    sel = (f >= fmin) & (f <= fmax)
    mag = np.log(np.abs(Z[sel]) + 1e-6)
    d = np.diff(mag, axis=1)
    flux = np.maximum(d, 0).sum(axis=0)
    return t[1:], flux


def harmonic_band_energy(x: np.ndarray, key: int, t0: float, t1: float, nharm: int = 4, cents: float = 40) -> float:
    """Energy (dB) in narrow bands around the first harmonics of a key, between t0 and t1 (s)."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    a, b = max(0, int(t0 * SR)), min(len(m), int(t1 * SR))
    seg = m[a:b]
    if len(seg) < 64:
        return -300.0
    n = max(1 << 14, 1 << int(np.ceil(np.log2(len(seg)))))
    p = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n)) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    f0 = 440 * 2 ** ((key - 69) / 12)
    e = 0.0
    for h in range(1, nharm + 1):
        fh = h * f0
        if fh > SR / 2 - 1000:
            break
        sel = (f > fh * 2 ** (-cents / 1200)) & (f < fh * 2 ** (cents / 1200))
        e += p[sel].sum()
    return db(e)


def f0_estimate(seg: np.ndarray, key: int, partial: int = 1) -> float | None:
    """Frequency of a partial near partial*f_ET(key), zero-padded FFT + parabolic interpolation (Hz/partial)."""
    m = seg.mean(axis=1) if seg.ndim == 2 else seg
    n = 1 << 21
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m)), n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    fk = partial * 440 * 2 ** ((key - 69) / 12)
    band = (freqs > fk * 2 ** (-70 / 1200)) & (freqs < fk * 2 ** (70 / 1200))
    if not band.any():
        return None
    i = int(np.argmax(np.where(band, spec, 0)))
    a, b, c = np.log(spec[i - 1: i + 2] + 1e-30)
    den = a - 2 * b + c
    p = 0.5 * (a - c) / den if den != 0 else 0.0
    return float((i + p) * SR / n / partial)


def save(name: str, data: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / f"{name}.json"
    p.write_text(json.dumps(data, indent=1, default=float))
    return p


def write_midi(path: Path, tracks: dict, tpb: int = 960, tempo: int = 500000, marker: str | None = None,
               mtype: int = 1) -> None:
    """tracks: name -> list of (time_s, msg) with msg a mido.Message (time ignored). Tempo constant."""
    mf = mido.MidiFile(type=mtype, ticks_per_beat=tpb)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage("track_name", name="tempo", time=0))
    if marker:
        t0.append(mido.MetaMessage("text", text=marker, time=0))
    t0.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    mf.tracks.append(t0)
    tps = tpb * 1e6 / tempo
    for name, evs in tracks.items():
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        evs = sorted(evs, key=lambda e: (e[0], 0 if e[1].type == "note_off" or (e[1].type == "note_on" and e[1].velocity == 0) else 1))
        now = 0
        for t, msg in evs:
            tick = int(round(t * tps))
            tr.append(msg.copy(time=tick - now))
            now = tick
        mf.tracks.append(tr)
    mf.save(path)
