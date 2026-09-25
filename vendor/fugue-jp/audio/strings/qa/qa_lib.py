"""Shared helpers for the adversarial audio QA of render_quartet.py.

Independent of the renderer's own code: MIDI timing comes from mido's merged
playback iterator (seconds, tempo-aware), pitch from a spectral harmonic-peak
estimator (the renderer's tuning loop uses YIN and a harmonic comb), levels
from plain numpy.  Audio goes to /tmp/sqa (never committed); numbers go to
qa/results/*.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

QA = Path(__file__).resolve().parent
STRINGS = QA.parent
ROOT = STRINGS.parents[2]                      # fugue-jp
PERFORM = STRINGS.parents[1] / "tools" / "perform.py"
TMP = Path("/tmp/sqa")
RESULTS = QA / "results"
SR = 48000
LIB = Path("/Users/biobook/Music/SampleLibraries")
QUARTET = LIB / "IowaMIS" / "quartet"


def state() -> dict:
    """Code + instrument state the numbers refer to."""
    def sh(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
    g = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()
    return dict(head=g("rev-parse", "--short", "HEAD"),
                render_quartet_commit=g("log", "-1", "--format=%h", "--", "ricercar/audio/strings/render_quartet.py"),
                render_quartet_sha=sh(STRINGS / "render_quartet.py"),
                sfz={p.name: sh(p) for p in sorted(QUARTET.glob("*.sfz"))})


def render(mid: Path, out: Path, *extra: str, keep_temp: bool = False) -> dict:
    """Run render_quartet.py with stems + report; returns the report (plus 'temp' dir if kept)."""
    cmd = [sys.executable, str(STRINGS / "render_quartet.py"), str(mid), "-o", str(out), "--stems",
           "--report", str(out) + ".json", *extra]
    if keep_temp:
        cmd.append("--keep-temp")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"render failed: {' '.join(cmd)}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    rep = json.loads(Path(str(out) + ".json").read_text())
    rep["stdout"] = r.stdout
    for line in r.stdout.splitlines():
        if line.startswith("temp: "):
            rep["temp"] = line[6:].strip()
    return rep


def perform(score: Path, plan: Path, out_mid: Path, target: str = "strings") -> str:
    r = subprocess.run([sys.executable, str(PERFORM), str(score), str(plan), str(out_mid), "--target", target],
                       check=True, capture_output=True, text=True)
    return r.stdout


def midi_notes(path: Path) -> dict:
    """{channel: [dict(on, off, key, vel)]} from mido's merged, tempo-aware playback."""
    mf = mido.MidiFile(str(path))
    t = 0.0
    pend, out = {}, {}
    for msg in mf:                                  # msg.time = seconds since previous message
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            pend.setdefault((msg.channel, msg.note), []).append((t, msg.velocity))
        elif msg.type in ("note_on", "note_off"):
            lst = pend.get((msg.channel, msg.note))
            if lst:
                on, v = lst.pop(0)
                out.setdefault(msg.channel, []).append(dict(on=on, off=t, key=msg.note, vel=v))
    for ch in out:
        out[ch].sort(key=lambda n: n["on"])
    hanging = sum(len(v) for v in pend.values())
    return dict(notes=out, hanging=hanging, length=mf.length)


def midi_cc(path: Path) -> dict:
    """{channel: {cc: [(t, v)]}}"""
    mf = mido.MidiFile(str(path))
    t = 0.0
    out = {}
    for msg in mf:
        t += msg.time
        if msg.type == "control_change":
            out.setdefault(msg.channel, {}).setdefault(msg.control, []).append((t, msg.value))
    return out


def load(path, mono=True):
    x, sr = sf.read(str(path), dtype="float64", always_2d=True)
    assert sr == SR, sr
    return x.mean(axis=1) if mono else x


def env_db(x: np.ndarray, win_s: float = 0.02, hop_s: float = 0.005, sr: int = SR):
    """Sliding RMS (window win_s centred on each hop) in dB; returns (db, hop_samples)."""
    hop = int(hop_s * sr)
    w = max(1, int(win_s * sr))
    p = np.convolve(x.astype(np.float64) ** 2, np.ones(w) / w, mode="same")
    return 10 * np.log10(p[::hop] + 1e-20), hop


def k_weight(x, sr=SR):
    """ITU-R BS.1770 K-weighting, 48 kHz biquads (stated in the standard)."""
    from scipy.signal import lfilter
    y = lfilter([1.53512485958697, -2.69169618940638, 1.19839281085285],
                [1.0, -1.69065929318241, 0.73248077421585], x)
    return lfilter([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621], y)


def db(x):
    return float(10 * np.log10(np.mean(np.asarray(x, dtype=np.float64) ** 2) + 1e-20))


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def pitch_spectral(seg: np.ndarray, key: int, sr: int = SR, span: int = 13, nh: int = 8):
    """Independent pitch estimate of a (roughly steady) segment.

    Harmonic-peak method: zero-padded Hann spectrum; candidates key-span..key+span
    in 5-cent steps scored by log magnitude at harmonics 1..nh minus the
    half-harmonics (suppresses octave-below errors); the winner is refined from
    parabolic-interpolated harmonic peaks (magnitude-weighted mean of f_k / k).
    Returns (midi_float, harmonic_to_noise_db)."""
    n = len(seg)
    if n < 256:
        return float("nan"), 0.0
    nfft = 1 << int(np.ceil(np.log2(max(n * 4, 1 << 16))))
    X = np.abs(np.fft.rfft(seg * np.hanning(n), nfft))
    L = np.log(X + 1e-9 * X.max() + 1e-20)
    # floor 60 dB below the peak: on a clean 24-bit dry stem the half-harmonics of
    # the octave-below candidate sit in the noise floor, and without a floor their
    # very low log magnitude "rewards" that candidate (an A#5 read as A#4, -1203 c)
    L = np.maximum(L, L.max() - 6.9)
    df = sr / nfft
    nyq = sr / 2 * 0.9

    def score(m):
        f0 = hz(m)
        s, c = 0.0, 0
        for k in range(1, nh + 1):
            if k * f0 > nyq:
                break
            i = int(round(k * f0 / df))
            j = int(round((k - 0.5) * f0 / df))
            s += L[max(i - 2, 0): i + 3].max() - L[max(j - 2, 0): j + 3].max()
            c += 1
        return s / max(c, 1)
    cands = np.arange(key - span, key + span + 0.001, 0.05)
    sc = np.array([score(m) for m in cands])
    best = cands[int(np.argmax(sc))]
    f0 = hz(best)
    ests, ws = [], []
    for k in range(1, 7):
        fk = k * f0
        if fk > nyq:
            break
        i0 = int(round(fk * 2 ** (-0.35 / 12) / df))
        i1 = int(round(fk * 2 ** (0.35 / 12) / df)) + 1
        if i1 - i0 < 3:
            continue
        i = i0 + int(np.argmax(X[i0:i1]))
        if 0 < i < len(X) - 1:
            a, b, c = L[i - 1], L[i], L[i + 1]
            d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
            ests.append((i + d) * df / k)
            ws.append(X[i])
    if not ests:
        return float(best), float(sc.max())
    f = float(np.average(ests, weights=ws))
    return float(69 + 12 * np.log2(f / 440.0)), float(sc.max() * 20 / np.log(10))


def save(name: str, obj: dict):
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / name
    p.write_text(json.dumps(obj, indent=1, default=lambda o: float(o) if isinstance(o, np.floating) else
                            int(o) if isinstance(o, np.integer) else str(o)))
    return p
