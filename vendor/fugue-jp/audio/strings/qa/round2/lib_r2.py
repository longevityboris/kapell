"""Round-2 adversarial QA helpers for render_quartet.py (independent of qa/qa_lib.py).

MIDI timing: mido's merged, tempo-aware playback (seconds), grouped per channel.
Pitch: two estimators -- per-frame harmonic peaks (partials 1-3, 40 ms or 6-period
Hann frames, x8 zero-padding, log-parabolic interpolation; 10 % trimmed time mean)
and a YIN difference function (median over 40 ms frames, x4 upsampled above 600 Hz),
plus an octave check (energy at 0.5/1.5/2.5 f0 and at the odd partials).  Onsets: pitch-specific narrow-band energy of the note's own
partials (partials shared with the neighbouring note excluded).  Audio goes to
/tmp/sqa2 (never committed); numbers go to qa/round2/results/*.json.
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
from scipy.signal import butter, sosfiltfilt, stft

R2 = Path(__file__).resolve().parent
STRINGS = R2.parents[1]
ROOT = STRINGS.parents[2]
PERFORM = STRINGS.parents[1] / "tools" / "perform.py"
RENDER = STRINGS / "render_quartet.py"
TMP = Path("/tmp/sqa2")
RESULTS = R2 / "results"
SR = 48000
QUARTET = Path("/Users/biobook/Music/SampleLibraries/IowaMIS/quartet")


def hz(k):
    return 440.0 * 2 ** ((k - 69) / 12)


def db(x):
    return 10 * np.log10(np.maximum(x, 1e-20))


def state() -> dict:
    def sh(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
    g = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()
    return dict(head=g("rev-parse", "--short", "HEAD"),
                render_quartet_sha=sh(RENDER), perform_sha=sh(PERFORM),
                sfz={p.name: sh(p) for p in sorted(QUARTET.glob("*.sfz"))})


def save(name: str, obj: dict):
    RESULTS.mkdir(parents=True, exist_ok=True)
    obj = dict(obj, state=state())
    (RESULTS / name).write_text(json.dumps(obj, indent=1, default=float))


def perform(score, plan, out_mid, target="strings"):
    r = subprocess.run([sys.executable, str(PERFORM), str(score), str(plan), str(out_mid), "--target", target],
                       check=True, capture_output=True, text=True)
    return r.stdout


def render(mid, out, *extra, keep_temp=True) -> dict:
    """render_quartet.py with --stems --report (--keep-temp: job WAVs in MIDI time)."""
    cmd = [sys.executable, str(RENDER), str(mid), "-o", str(out), "--stems", "--report", str(out) + ".json", *extra]
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


def job_wavs(rep) -> list:
    """[(job dict, mono float array in MIDI time)] from a --keep-temp render."""
    out = []
    for i, j in enumerate(rep["jobs"]):
        p = Path(rep["temp"]) / f"j{i}_{j['inst']}.wav"
        x, sr = sf.read(str(p), dtype="float64", always_2d=True)
        assert sr == SR
        out.append((j, x.mean(axis=1)))
    return out


def midi_voices(path) -> dict:
    """{channel: dict(name, notes=[dict(on, off, key, vel)], cc={num: [(t, v)]})}."""
    mf = mido.MidiFile(str(path))
    names = {}
    for tr in mf.tracks:
        nm = next((m.name for m in tr if m.type == "track_name"), None)
        chs = {m.channel for m in tr if hasattr(m, "channel")}
        for c in chs:
            names[c] = nm
    t = 0.0
    pend, out = {}, {}
    for msg in mf:
        t += msg.time
        if not hasattr(msg, "channel"):
            continue
        v = out.setdefault(msg.channel, dict(name=names.get(msg.channel), notes=[], cc={}))
        if msg.type == "note_on" and msg.velocity > 0:
            pend.setdefault((msg.channel, msg.note), []).append((t, msg.velocity))
        elif msg.type in ("note_on", "note_off"):
            lst = pend.get((msg.channel, msg.note))
            if lst:
                on, vel = lst.pop(0)
                v["notes"].append(dict(on=on, off=t, key=msg.note, vel=vel))
        elif msg.type == "control_change":
            v["cc"].setdefault(msg.control, []).append((t, msg.value))
    for (ch, key), lst in pend.items():
        for on, vel in lst:
            out[ch]["notes"].append(dict(on=on, off=None, key=key, vel=vel, hanging=True))
    for v in out.values():
        v["notes"].sort(key=lambda n: (n["on"], n["key"]))
    return out


# ------------------------------------------------------------------ pitch
def pitch_frames(seg, key, nh=3, hop=0.01, span_c=80):
    """Per-frame f0 (Hz): peaks near k*f0 (k=1..nh, +-span_c cents) of a Hann frame of max(40 ms, 6 periods),
    zero-padded x8, Gaussian (log-parabolic) interpolation, magnitude-weighted mean of f_k/k."""
    f0 = hz(key)
    W = int(max(0.04, 6.0 / f0) * SR)
    H = int(hop * SR)
    nfft = 1 << int(np.ceil(np.log2(W * 8)))
    df = SR / nfft
    win = np.hanning(W)
    out = []
    for s in range(0, len(seg) - W + 1, H):
        X = np.abs(np.fft.rfft(seg[s: s + W] * win, nfft))
        est, w = [], []
        for k in range(1, nh + 1):
            fk = k * f0
            lo, hi = int(fk * 2 ** (-span_c / 1200) / df), int(fk * 2 ** (span_c / 1200) / df) + 1
            if hi >= len(X) - 1:
                break
            i = lo + int(np.argmax(X[lo:hi]))
            if lo < i < hi - 1:
                a, b, c = np.log(X[i - 1] + 1e-12), np.log(X[i] + 1e-12), np.log(X[i + 1] + 1e-12)
                den = a - 2 * b + c
                p = 0.5 * (a - c) / den if den != 0 else 0.0
                est.append((i + p) * df / k)
                w.append(X[i])
        if est:
            out.append(float(np.average(est, weights=w)))
    return np.array(out)


def pitch_fft(seg, key):
    """Time-mean f0 from pitch_frames (10 % trimmed mean), or None."""
    fr = pitch_frames(seg, key)
    if len(fr) < 3:
        return None
    c = np.sort(1200 * np.log2(fr / hz(key)))
    k = len(c) // 10
    c = c[k: len(c) - k] if len(c) > 10 else c
    return float(hz(key) * 2 ** (np.mean(c) / 1200))


def octave_check(seg, key):
    """dB of energy at the would-be partials of the octave below (0.5, 1.5, 2.5 f0) and of the odd partials that
    an octave-up note would lack (f0, 3 f0) re the note's own partials (f0, 2 f0, 3 f0)."""
    n = len(seg)
    nfft = 1 << int(np.ceil(np.log2(n * 2)))
    X = np.abs(np.fft.rfft(seg * np.hanning(n), nfft)) ** 2
    f = np.fft.rfftfreq(nfft, 1 / SR)
    f0 = hz(key)

    def e(mults):
        tot = 0.0
        for m in mults:
            band = (f > m * f0 * 2 ** (-0.5 / 12)) & (f < m * f0 * 2 ** (0.5 / 12))
            tot += X[band].sum()
        return tot
    own = e([1, 2, 3])
    return dict(sub_db=float(db(e([0.5, 1.5, 2.5]) / own)), odd_db=float(db(e([1, 3]) / e([2, 4]))))


def pitch_yin(seg, key, frame=0.04, hop=0.01, thr=0.15):
    """Median YIN f0 over frames, lag search within +-4 semitones of the key."""
    f0 = hz(key)
    up = 4 if f0 > 600 else 1
    if up > 1:
        from scipy.signal import resample_poly
        seg = resample_poly(seg, up, 1)
    sr = SR * up
    lmin, lmax = int(sr / (f0 * 2 ** (4 / 12))), int(sr / (f0 * 2 ** (-4 / 12))) + 2
    W = max(int(frame * sr), 3 * lmax)
    H = int(hop * sr)
    fs = []
    nf = 1 << int(np.ceil(np.log2(2 * (W + lmax + 1))))
    for s in range(0, len(seg) - W - lmax - 1, H):
        x = seg[s: s + W + lmax + 1]
        c = np.concatenate([[0.0], np.cumsum(x ** 2)])
        e0 = c[W]
        et = c[np.arange(lmax + 1) + W] - c[np.arange(lmax + 1)]
        C = np.fft.irfft(np.conj(np.fft.rfft(x[:W], nf)) * np.fft.rfft(x, nf), nf)[: lmax + 1]
        d = np.maximum(e0 + et - 2 * C, 0.0)
        cm = d[1:] * np.arange(1, lmax + 1) / np.maximum(np.cumsum(d[1:]), 1e-20)
        cm = np.concatenate([[1.0], cm])
        rng = cm[lmin: lmax]
        i = int(np.argmin(rng)) + lmin
        if cm[i] > thr * 3:
            continue
        if 1 <= i < lmax:
            a, b, c = cm[i - 1], cm[i], cm[i + 1]
            p = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        else:
            p = 0.0
        fs.append(sr / (i + p))
    if len(fs) < 3:
        return None
    return float(np.median(fs))


def cents(f, key):
    return None if f is None else float(1200 * np.log2(f / hz(key)))


# ------------------------------------------------------------ envelopes
def rms_env(x, win=0.01, hop=0.005):
    W, H = int(win * SR), int(hop * SR)
    n = max(1, (len(x) - W) // H + 1)
    idx = np.arange(n) * H
    c = np.concatenate([[0.0], np.cumsum(x ** 2)])
    e = (c[idx + W] - c[idx]) / W
    return idx / SR + win / 2, db(e)


class Spec:
    """Magnitude STFT of a mono signal for partial-band energies (50 ms window, 5 ms hop)."""

    def __init__(self, x, win=0.05, hop=0.005):
        nper = int(win * SR)
        f, t, Z = stft(x, SR, nperseg=nper, noverlap=nper - int(hop * SR), nfft=1 << int(np.ceil(np.log2(nper * 2))),
                       boundary=None, padded=False)
        self.f, self.t, self.P = f, t, np.abs(Z) ** 2
        self.df = f[1] - f[0]

    def band_energy(self, key, exclude_keys=(), nh=6, width_c=40):
        """Energy per frame in the partials of `key` that are not within 60 c of a partial of exclude_keys."""
        f0 = hz(key)
        others = [k2 * hz(e) for e in exclude_keys for k2 in range(1, 16)]
        rows = np.zeros(len(self.f), bool)
        used = 0
        for k in range(1, nh + 1):
            fk = k * f0
            if fk > 12000:
                break
            if any(abs(1200 * np.log2(fk / o)) < 60 for o in others):
                continue
            lo, hi = fk * 2 ** (-width_c / 1200), fk * 2 ** (width_c / 1200)
            m = (self.f >= lo - self.df) & (self.f <= hi + self.df)
            rows |= m
            used += 1
        if used == 0:
            return None
        return db(self.P[rows].sum(axis=0))


def hp(x, fc, order=4):
    return sosfiltfilt(butter(order, fc, "highpass", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=4):
    return sosfiltfilt(butter(order, [lo, hi], "bandpass", fs=SR, output="sos"), x)


def centroid(x, fmax=12000):
    n = len(x)
    X = np.abs(np.fft.rfft(x * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    m = f <= fmax
    return float(np.sum(f[m] * X[m]) / np.sum(X[m]))


def band_share(x, lo, hi=None):
    n = len(x)
    X = np.abs(np.fft.rfft(x * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    m = (f >= lo) & ((f < hi) if hi else True)
    return float(np.sum(X[m]) / np.sum(X))


def pct(a, q):
    a = [x for x in a if x is not None]
    return float(np.percentile(a, q)) if a else None


def yin_track(x, t0, t1, kmin, kmax, frame=0.025, hop=0.0025):
    """YIN f0 track (times = frame centres, Hz or nan) over [t0, t1] with lags for keys kmin-2 .. kmax+2."""
    lmin = int(SR / hz(kmax + 2))
    lmax = int(SR / hz(kmin - 2)) + 2
    W = max(int(frame * SR), 2 * lmax)
    H = int(hop * SR)
    a = max(0, int(t0 * SR) - W // 2)
    b = min(len(x), int(t1 * SR) + W // 2 + lmax + 1)
    seg = x[a:b]
    nf = 1 << int(np.ceil(np.log2(2 * (W + lmax + 1))))
    ts, fs = [], []
    for s in range(0, len(seg) - W - lmax - 1, H):
        y = seg[s: s + W + lmax + 1]
        c = np.concatenate([[0.0], np.cumsum(y ** 2)])
        e0 = c[W]
        et = c[np.arange(lmax + 1) + W] - c[np.arange(lmax + 1)]
        C = np.fft.irfft(np.conj(np.fft.rfft(y[:W], nf)) * np.fft.rfft(y, nf), nf)[: lmax + 1]
        d = np.maximum(e0 + et - 2 * C, 0.0)
        cm = d[1:] * np.arange(1, lmax + 1) / np.maximum(np.cumsum(d[1:]), 1e-20)
        cm = np.concatenate([[1.0], cm])
        i = int(np.argmin(cm[lmin:lmax])) + lmin
        ts.append((a + s + W / 2) / SR)
        if cm[i] > 0.35 or e0 < 1e-12:
            fs.append(np.nan)
            continue
        aa, bb, cc = cm[i - 1], cm[i], cm[i + 1]
        den = aa - 2 * bb + cc
        p = 0.5 * (aa - cc) / den if den != 0 else 0.0
        fs.append(SR / (i + p))
    return np.array(ts), np.array(fs)


def pitch_switch(x, on, k_old, k_new, span=(-0.1, 0.15)):
    """Time (s, re on) from which the YIN track sits nearer the new key than the old one for 3 frames."""
    ts, fs = yin_track(x, on + span[0], on + span[1], min(k_old, k_new), max(k_old, k_new))
    with np.errstate(invalid="ignore", divide="ignore"):
        cn = np.abs(1200 * np.log2(fs / hz(k_new)))
        co = np.abs(1200 * np.log2(fs / hz(k_old)))
    near_new = (cn < co) & (cn < 60)
    for i in range(len(ts) - 2):
        if ts[i] < on + span[0]:
            continue
        if near_new[i] and near_new[i + 1] and near_new[i + 2]:
            if i > 0 and near_new[:i].all():
                return None                     # already the new pitch at the start: no switch seen
            return float(ts[i] - on)
    return None


def interharmonic_db(x, key, frame=0.1, fmax=8000.0, rel=0.04):
    """Per 100 ms frame: energy between the partials of `key` (outside +-4 % of k*f0, f0/2..fmax) re the
    energy in the partials, dB.  Zipper noise or clicks from stepped gain raise it; a clean gain ramp does not."""
    f0 = hz(key)
    W = int(frame * SR)
    f = np.fft.rfftfreq(W, 1 / SR)
    harm = np.zeros(len(f), bool)
    k = 1
    while k * f0 < fmax:
        harm |= np.abs(f - k * f0) <= max(rel * k * f0, 12.0)
        k += 1
    band = (f >= f0 / 2) & (f <= fmax)
    win = np.hanning(W)
    out = []
    for s in range(0, len(x) - W + 1, W // 2):
        X = np.abs(np.fft.rfft(x[s: s + W] * win)) ** 2
        out.append(float(db(X[band & ~harm].sum() / max(X[band & harm].sum(), 1e-30))))
    return np.array(out)
