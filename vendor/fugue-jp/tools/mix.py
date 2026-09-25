#!/usr/bin/env python3
"""Render an orchestrated piece group by group and mix the groups in one hall.

usage:
  python3 mix.py MANIFEST.json                 render (cached), align, verify, place, master
  python3 mix.py MANIFEST.json --rerender      render every group again even if its cache is fresh
  python3 mix.py MANIFEST.json --recalibrate   measure the renderer calibration again
  options: --out PATH (overrides the manifest's "out"),
           --keep-stems (also write each stem as it enters the hall: OUT.stems/<group>_<stem>.wav),
           --max-lag-ms 5 (tolerance on the renderers' time-base difference; above it the mix is
           still written but flagged: alignment_ok false, exit code 3)

MANIFEST.json is written by orchestrate.py (OUTDIR/manifest.json) from the spec's "mix" section and
can be edited; paths in it are relative to its own directory. Format: tools/ORCHESTRATION.md.

What it does
  1. Render: each group's MIDI goes to its renderer's own command line (piano render_piano.py,
     quartet render_quartet.py, orchestra render_orchestra.py, organ render_organ.py) with dry
     stems and no reverb, one group at a time, into MANIFEST_DIR/render/<group>/. A render is
     reused while the MIDI, the sidecar, the renderer script and the arguments are unchanged.
  2. Align: every stem is put on one timeline whose sample 0 is MIDI time -lead_in, from what
     each renderer reports about its own output (piano and organ: sample 0 = MIDI -lead_in;
     quartet and orchestra: offset_s in their report). All groups share orchestrate.py's tempo map.
  3. Level: stems are brought to each renderer's raw (pre-normalisation) scale (the quartet's
     stems are normalised by its render; the gain is recovered from its report's pre-normalisation
     stem levels), then renderers are levelled against each other with a calibration chorale
     (orchestration/calibration/: the same four-part mf chorale through orchestrate.py and each
     renderer; equal K-weighted loudness; cached per renderer script hash), then the manifest's
     gain_db per group.
  4. Verify (before placement; seat delays are physical): onset envelopes (1 ms frames, four
     bands) are cross-correlated with impulse trains at MIDI note-ons. Gate, under --max-lag-ms
     (5 ms): the renderers' time bases, measured by a timing probe (the calibration chorale
     with every note short, through the same render / offset / stem path, cached with the
     calibration), agree. A failed gate flags the mix (alignment_ok false, exit code 3) but
     still writes it. Information only: where groups double each other, the direct
     cross-correlation of the two groups' envelopes around the shared onsets (all of them, and
     those both renderers attack), with its peak prominence; each group's lag on the attacks in
     the music, per quarter of the piece (articulation shows there: bowed pre-roll, slurs).
     "latency_ms" ("auto" = its own probe time base, or ms) shifts a group earlier; default
     "auto" for the organ (pipe speech), none for the others.
  5. Place and reverberate: each stem is panned to its seat (audio/strings/hall.py place_dry:
     azimuth, width, depth delay and -1 dB/m), and each group feeds the same measured Detmold
     Konzerthaus response (hall.Hall, unit energy, tail continued; right-hand sources get the
     mirrored response) at its own wet level. Orchestra stems arrive already seated by their
     renderer and are only reverberated.
  6. Master: 18 Hz high-pass, silent tail trimmed, true peak (4x oversampled) normalised to
     peak_dbtp (-1 dBTP), 48 kHz 24-bit WAV with credits in its INFO chunk, AAC 256 kb/s m4a by
     afconvert (its decoded true peak is measured and the encode repeated lower if it overshoots).
  7. Report (OUT.mix.json): alignment lags, calibration and gains, per-group loudness where each
     plays, integrated loudness, loudness range, true peak of WAV and m4a, C80 per group,
     stereo correlation, a click scan and a loudness curve per bar range.
Nothing is played through the speakers.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import mido
import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, resample_poly, sosfilt

TOOLS = Path(__file__).resolve().parent
RICERCAR = TOOLS.parent
AUDIO = RICERCAR / "audio"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(AUDIO / "strings"))
import hall as hallmod  # noqa: E402  (audio/strings/hall.py: the shared Detmold hall and stage placement)

SR = 48000
CAL_DIR = RICERCAR / "orchestration" / "calibration"
CAL_VERSION = 4           # bump when the calibration method (seating, loudness measure, raw scale) changes
                          # 3: organ stems taken back to the organ's pre-normalisation scale
                          # 4: probe peak searched within +-TB_SEARCH_MS
CAL_PARTS = {"piano": ["soprano", "alto", "tenor", "bass"], "quartet": ["vn1", "vn2", "va", "vc"],
             "orchestra": ["vn1", "vn2", "va", "vc"], "organ": ["soprano", "alto", "tenor", "bass"]}
SCRIPTS = {"piano": AUDIO / "piano" / "render_piano.py", "quartet": AUDIO / "strings" / "render_quartet.py",
           "orchestra": AUDIO / "orchestra" / "render_orchestra.py", "organ": AUDIO / "organ" / "render_organ.py"}
DEFAULT_STAGE = {"piano": {"az": 0.0, "depth": 1.2, "width": 0.7},
                 "organ": {"az": 0.0, "depth": 0.0, "width": 0.8}}
CREDITS = ("Salamander Grand Piano V3 by Alexander Holm (CC-BY 3.0); University of Iowa MIS strings; "
           "Detmold Konzerthaus SRIR, Amengual Gari, Sahin, Eddy, Kob, AES 2020 (CC BY 4.0); "
           "rendered with sfizz (BSD-2-Clause)")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16] if Path(path).exists() else "-"


# ----------------------------------------------------------------------------- engine fingerprint
# A render (and a renderer's calibration) depends on more than its main script: the local modules
# it imports (the orchestra imports orch_common and the quartet's render_quartet; the quartet
# iowa_build and hall; the organ pipe_engine and odf) and the built instruments and data it loads.
# engine_hash covers the renderer script, every local module it imports (transitively, found by
# name in the renderer's directory and audio/strings), and its instrument definitions as text
# (SFZ files, the organ's ODF, pipe model and registrations); samples are not hashed (a rebuild
# rewrites its SFZ, and the SFZ's mtime is part of the hash).
ENGINE_SEARCH = {"piano": [AUDIO / "piano"], "quartet": [AUDIO / "strings"],
                 "orchestra": [AUDIO / "orchestra", AUDIO / "strings"], "organ": [AUDIO / "organ"]}
_ENGINE = {}


def local_modules(script: Path, dirs: list) -> list:
    import re
    rx = re.compile(r"^[ \t]*(?:from[ \t]+([\w.]+)[ \t]+import|import[ \t]+([\w., \t]+))", re.M)
    seen, todo = set(), [script]
    while todo:
        f = todo.pop()
        if f in seen or not f.exists():
            continue
        seen.add(f)
        for m in rx.finditer(f.read_text(errors="replace")):
            names = [m.group(1)] if m.group(1) else [x.strip().split(" ")[0] for x in m.group(2).split(",")]
            for nm in names:
                c = next((d / f"{nm.split('.')[0]}.py" for d in dirs if (d / f"{nm.split('.')[0]}.py").exists()), None)
                if c is not None:
                    todo.append(c)
    return sorted(seen)


def instrument_files(renderer: str) -> list:
    lib = Path(os.environ.get("SAMPLE_LIBRARIES", Path.home() / "Music" / "SampleLibraries"))
    if renderer == "piano":       # the derived SFZ and make_sfz.py's calibration (velocity map)
        d = lib / "SalamanderGrandPiano" / "SalamanderGrandPiano-SFZ+FLAC-V3+20200602"
        return sorted(d.glob("*.sfz")) + sorted(d.glob("*.json"))
    if renderer == "quartet":     # SFZ, tuning corrections, sample checksums
        d = Path(os.environ.get("IOWA_QUARTET_DIR", lib / "IowaMIS" / "quartet"))
        return sorted(d.rglob("*.sfz")) + sorted(d.glob("*.json")) + sorted(d.glob("*.sha256"))
    if renderer == "orchestra":   # SFZ, tuning corrections, latency table, layer maps
        d = lib / "Orchestra" / "built"
        return sorted(d.rglob("*.sfz")) + sorted(d.rglob("*.json"))
    if renderer == "organ":
        return [AUDIO / "organ" / "registrations.json", AUDIO / "organ" / "data" / "norrfjarden_pipes.json",
                lib / "Organ" / "NorrfjardenChurch" / "NorrfjardenChurch.organ"]
    return []


def engine_hash(renderer: str) -> str:
    """Fingerprint of everything a renderer's output depends on besides its input (see above)."""
    if renderer not in _ENGINE:
        h = hashlib.sha256()
        for f in local_modules(SCRIPTS[renderer], ENGINE_SEARCH[renderer]):
            h.update(f.name.encode() + b"\0" + f.read_bytes())
        for f in instrument_files(renderer):
            if f.exists():
                st = f.stat()
                h.update(f"{f}:{st.st_size}:{st.st_mtime_ns}".encode())
                if st.st_size < 8_000_000:
                    h.update(f.read_bytes())
        _ENGINE[renderer] = h.hexdigest()[:16]
    return _ENGINE[renderer]


def db(x: float) -> float:
    return 10 * math.log10(max(x, 1e-30))


def true_peak(x: np.ndarray) -> float:
    return float(np.max(np.abs(resample_poly(x, 4, 1, axis=0))))


# ----------------------------------------------------------------------------- renderer adapters
def quartet_instr() -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        import render_quartet as rq  # noqa: E402
    return rq.INSTR


def render_group(renderer: str, midi: Path, rdir: Path, lead_in: float, extra: list, force: bool,
                 sidecar: Path | None = None) -> dict:
    """Run the renderer (or reuse a fresh cache). -> {"stems": [(name, path)], "offset_s", "report"}."""
    script = SCRIPTS[renderer]
    if not script.exists():
        raise SystemExit(f"{renderer}: renderer {script} not found (not built yet?)")
    rdir.mkdir(parents=True, exist_ok=True)
    base = rdir / "render"
    stems_dir = rdir / "stems"
    if renderer == "piano":
        report = rdir / "render.json"
        cmd = [sys.executable, str(script), str(midi), "-o", str(base), "--no-reverb", "--no-m4a",
               "--stems", str(stems_dir), "--lead-in", f"{lead_in}", "--json", str(report)]
    elif renderer == "quartet":
        report = rdir / "render.report.json"
        cmd = [sys.executable, str(script), str(midi), "-o", str(base), "--hall", "none", "--stems",
               "--report", str(report), "--lead-in", f"{lead_in}",
               "--map", "Violin I=vn1,Violin II=vn2,Viola=va,Cello=vc,Contrabass=cb"]
    elif renderer == "orchestra":
        report = rdir / "render.json"
        cmd = [sys.executable, str(script), str(midi), "-o", str(base), "--stems", "--no-reverb",
               "--lead-in", f"{lead_in}"]
        if sidecar is not None and sidecar.exists():
            cmd += ["--sidecar", str(sidecar)]
    elif renderer == "organ":
        report = rdir / "render.json"
        cmd = [sys.executable, str(script), str(midi), "-o", str(base), "--stems", str(stems_dir),
               "--no-reverb", "--no-m4a", "--lead-in", f"{lead_in}", "--json", str(report)]
        if sidecar is not None and sidecar.exists():
            cmd += ["--registration", str(sidecar)]
    else:
        raise SystemExit(f"unknown renderer {renderer!r}")
    cmd += [str(x) for x in extra]
    stamp = {"midi": sha(midi), "sidecar": sha(sidecar) if sidecar else None, "script": sha(script),
             "engine": engine_hash(renderer), "cmd": cmd[2:]}
    stamp_path = rdir / "stamp.json"
    have_stems = any(stems_dir.glob("*.wav")) or any(rdir.glob("render_stem_*.wav")) \
        or any((rdir / "render.stems").glob("*.wav"))
    fresh = (not force and stamp_path.exists() and report.exists() and have_stems
             and json.loads(stamp_path.read_text()) == stamp)
    if not fresh:
        for p in (stems_dir, rdir / "render.stems"):
            if p.exists():
                shutil.rmtree(p)
        for p in rdir.glob("render_stem_*.wav"):
            p.unlink()
        print(f"  rendering {renderer}: {' '.join(Path(c).name if '/' in c else c for c in cmd[1:])}", flush=True)
        log = rdir / "render.log"
        with open(log, "w") as fh:
            r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            raise SystemExit(f"{renderer} render failed (exit {r.returncode}); see {log}:\n"
                             + "\n".join(log.read_text().splitlines()[-15:]))
        stamp_path.write_text(json.dumps(stamp, indent=1))
    else:
        print(f"  {renderer}: cached render in {rdir}")
    rep = json.loads(report.read_text())
    if renderer == "piano":
        stems = [(p.stem, p) for p in sorted(stems_dir.glob("*.wav"))]
        offset = -lead_in
    elif renderer == "quartet":
        stems = [(p.stem.split("_stem_")[-1], p) for p in sorted(rdir.glob("render_stem_*.wav"))]
        offset = float(rep["offset_s"])
    elif renderer == "orchestra":
        sd = rdir / "render.stems"
        stems = [(p.stem, p) for p in sorted(sd.glob("*.wav"))]
        offset = float(rep.get("offset_s", -lead_in))
    else:
        stems = [(p.stem, p) for p in sorted(stems_dir.glob("*.wav"))]
        offset = float(rep.get("offset_s", -lead_in))
    if not stems:
        raise SystemExit(f"{renderer}: no stems in {rdir}")
    return {"stems": stems, "offset_s": offset, "report": rep, "dir": rdir}


def moved_notes(renderer: str, res: dict) -> dict:
    """Notes the renderer moved by octaves into an instrument's compass (they sound in the wrong
    octave): {track: [[MIDI s, key in, key played], ...]} for the orchestra, {division: count} for
    the organ, {job: count} for the quartet (from its log). orchestrate.py's integrity check
    refuses them for orchestra parts unless the spec lists the part in allow_octave_shift."""
    rep = res["report"]
    if renderer == "orchestra":
        return {t["name"]: [[s, a, b] for s, a, b in t["octave_shifted"]]
                for t in rep.get("tracks", []) if t.get("octave_shifted")}
    if renderer == "organ":
        return {k: v for k, v in (rep.get("folded_notes") or {}).items() if v}
    if renderer == "quartet":           # render_quartet.py logs "<job>: N notes outside ... octave-shifted"
        import re
        log = res["dir"] / "render.log"
        rx = re.compile(r"^\s*(?:note:\s*)?(.+?): (\d+) notes outside .* octave-shifted")
        found = [rx.match(ln) for ln in log.read_text().splitlines()] if log.exists() else []
        return {m.group(1): int(m.group(2)) for m in found if m}
    return {}


def raw_scale_db(renderer: str, rep: dict, stems: dict) -> tuple[float, dict]:
    """Gain (dB) that takes this render's stems back to the renderer's pre-normalisation scale.
    piano: stems are pre-normalisation already; orchestra: stems are at the pre-normalisation gain
    by contract; organ: its stems carry the render's normalisation gain (audio/organ/CONTRACT.md,
    --stems), which its report gives; quartet: its stems carry the mix's normalisation, recovered
    from the report's stem levels (computed before normalisation, on the same signal)."""
    if renderer == "organ":
        if "normalisation_gain_db" not in rep:
            raise SystemExit("organ report has no normalisation_gain_db: cannot undo its normalisation")
        return -float(rep["normalisation_gain_db"]), {"normalisation_gain_db": rep["normalisation_gain_db"]}
    if renderer != "quartet":
        return 0.0, {}
    ref = rep.get("stem_rms_db_when_active", {})
    names = quartet_instr()
    est = {}
    for inst, x in stems.items():
        target = ref.get(names[inst]["name"]) if inst in names else None
        if target is None:
            continue
        mono = x.mean(axis=1)
        g = 0.0
        for _ in range(3):          # the report counts samples above 1e-5 on its own scale
            act = np.abs(mono) > 1e-5 * 10 ** (g / 20)
            g = db(float(np.mean(mono[act] ** 2))) - target
        est[inst] = round(-g, 3)
    if not est:
        raise SystemExit("quartet report has no stem_rms_db_when_active: cannot undo its normalisation")
    vals = list(est.values())
    if max(vals) - min(vals) > 0.1:
        print(f"  warning: quartet normalisation estimates disagree: {est}")
    return float(np.median(vals)), est


def load_stems(stems: list, offset_s: float, lead_in: float, n: int) -> dict:
    """-> {name: (n, 2) float64 on the common timeline (sample 0 = MIDI time -lead_in)}."""
    out = {}
    shift = int(round((offset_s + lead_in) * SR))
    for name, path in stems:
        x, sr = sf.read(str(path), dtype="float64", always_2d=True)
        if sr != SR:
            raise SystemExit(f"{path}: {sr} Hz, expected {SR}")
        if x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)
        y = np.zeros((n, 2))
        a = max(0, shift)
        b = max(0, -shift)
        m = min(n - a, len(x) - b)
        if m > 0:
            y[a:a + m] = x[b:b + m]
        out[name] = y
    return out


# ----------------------------------------------------------------------------- timing
def midi_onsets(midi: Path) -> list:
    """(seconds, track name, key, velocity) of every note-on, through the file's tempo map."""
    mid = mido.MidiFile(str(midi))
    tempos = sorted((t, m.tempo) for tr in mid.tracks for t, m in _abs(tr) if m.type == "set_tempo")
    pts, s, lt, us = [], 0.0, 0, 500000
    for t, tempo in tempos:
        s += (t - lt) * us / 1e6 / mid.ticks_per_beat
        pts.append((t, s, tempo))
        lt, us = t, tempo
    if not pts or pts[0][0] > 0:
        pts.insert(0, (0, 0.0, 500000))
    ticks = np.array([p[0] for p in pts])

    def sec(tick):
        i = int(np.searchsorted(ticks, tick, side="right")) - 1
        t, s0, u = pts[i]
        return s0 + (tick - t) * u / 1e6 / mid.ticks_per_beat

    out = []
    for tr in mid.tracks:
        name = next((m.name for m in tr if m.type == "track_name"), "")
        for t, m in _abs(tr):
            if m.type == "note_on" and m.velocity > 0:
                out.append((sec(t), name, m.note, m.velocity))
    return sorted(out)


def _abs(tr):
    t = 0
    for m in tr:
        t += m.time
        yield t, m


def onset_envelope(x: np.ndarray) -> np.ndarray:
    """Onset strength at 1 ms frames: rises of log energy in four bands (5 ms smoothing), summed."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    hop, win = SR // 1000, SR // 200
    edges = [(80, 400), (400, 1600), (1600, 6400), (6400, 16000)]
    total = None
    for lo, hi in edges:
        sos = butter(2, [lo, hi], "bandpass", fs=SR, output="sos")
        e = sosfilt(sos, mono) ** 2
        c = np.concatenate([[0.0], np.cumsum(e)])
        idx = np.arange(0, len(mono) - win, hop)
        en = (c[idx + win] - c[idx]) / win
        le = 10 * np.log10(en + 1e-12 + 1e-4 * en.mean())
        d = np.zeros_like(le)
        d[2:] = le[2:] - le[:-2]
        d = np.maximum(d, 0)
        total = d if total is None else total + d
    # frame k covers samples [k*hop, k*hop + win) and d[k] compares it with frame k-2, so a step at
    # time T peaks at k = T - 1.5 ms: two leading frames put the peak on T (within 0.5 ms)
    return np.concatenate([np.zeros(2), total])


def fit(x: np.ndarray, n: int) -> np.ndarray:
    return x[:n] if len(x) >= n else np.concatenate([x, np.zeros(n - len(x))])


def onset_train(times_s: list, n: int, sigma_ms: float = 2.0) -> np.ndarray:
    tr = np.zeros(n)
    for t in times_s:
        k = int(round(t * 1000))
        if 0 <= k < n:
            tr[k] += 1.0
    r = int(4 * sigma_ms)
    ker = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_ms) ** 2)
    return np.convolve(tr, ker, mode="same")


def xcorr_lag(a: np.ndarray, b: np.ndarray, max_lag: int = 80, mask: np.ndarray | None = None) -> tuple:
    """Lag (ms, parabolic peak) that best aligns a to b: a(t) ~ b(t - lag); lag > 0 = a is late."""
    n = min(len(a), len(b))
    a, b = a[:n].copy(), b[:n].copy()
    if mask is not None:
        a *= mask[:n]
    a = (a - a.mean()) / (a.std() + 1e-12)
    b = (b - b.mean()) / (b.std() + 1e-12)
    lags = np.arange(-max_lag, max_lag + 1)
    c = np.array([np.dot(a[max(0, L):n + min(0, L)], b[max(0, -L):n - max(0, L)]) for L in lags]) / n
    i = int(np.argmax(c))
    frac = 0.0
    if 0 < i < len(c) - 1:
        den = c[i - 1] - 2 * c[i] + c[i + 1]
        frac = 0.5 * (c[i - 1] - c[i + 1]) / den if den != 0 else 0.0
    others = np.concatenate([c[:max(0, i - 10)], c[i + 11:]])
    return float(lags[i] + frac), float(c[i]), float(c[i] / (np.max(others) + 1e-12)) if len(others) else 0.0


def xcorr_curve(a: np.ndarray, b: np.ndarray, max_lag: int = 80) -> np.ndarray:
    """c[L + max_lag] = sum_t z(a)[t + L] z(b)[t] / n: peak at L > 0 means a is late."""
    n = min(len(a), len(b))
    a = (a[:n] - a[:n].mean()) / (a[:n].std() + 1e-12)
    b = (b[:n] - b[:n].mean()) / (b[:n].std() + 1e-12)
    return np.array([np.dot(a[max(0, L):n + min(0, L)], b[max(0, -L):n - max(0, L)])
                     for L in range(-max_lag, max_lag + 1)]) / n


# A time base is the few-ms lag of a note's attack after its note-on (the organ's pipe speech, the
# slowest, about 11 ms after its anticipation). Peaks are searched within +-TB_SEARCH_MS: a renderer
# that starts its samples early by their measured onset latency (the orchestra's VPO3 violins, about
# 80 ms) puts a slow pre-attack rising out of digital silence before every note that follows a rest,
# and on the log-energy envelope that rise outscores the tone's (probe: -76.7 ms globally, +2.5 ms per
# note median, +4 ms within the window; doubled onsets with the piano -1.8 ms). A peak on the edge of
# the window is flagged: that time base is not measured.
TB_SEARCH_MS = 30


def peak_of(c: np.ndarray, lim: int | None = None) -> float:
    max_lag = (len(c) - 1) // 2
    if lim is not None and lim < max_lag:
        i = max_lag - lim + int(np.argmax(c[max_lag - lim:max_lag + lim + 1]))
    else:
        i = int(np.argmax(c))
    frac = 0.0
    if 0 < i < len(c) - 1:
        den = c[i - 1] - 2 * c[i] + c[i + 1]
        frac = 0.5 * (c[i - 1] - c[i + 1]) / den if den != 0 else 0.0
    return float(i - max_lag + frac)


def midi_notes(midi: Path) -> dict:
    """{track name: [(on_s, off_s, key, velocity)]} through the file's tempo map."""
    mid = mido.MidiFile(str(midi))
    tempos = sorted((t, m.tempo) for tr in mid.tracks for t, m in _abs(tr) if m.type == "set_tempo")
    pts, s, lt, us = [], 0.0, 0, 500000
    for t, tempo in tempos:
        s += (t - lt) * us / 1e6 / mid.ticks_per_beat
        pts.append((t, s, tempo))
        lt, us = t, tempo
    if not pts or pts[0][0] > 0:
        pts.insert(0, (0, 0.0, 500000))
    ticks = np.array([p[0] for p in pts])

    def sec(tick):
        i = int(np.searchsorted(ticks, tick, side="right")) - 1
        t, s0, u = pts[i]
        return s0 + (tick - t) * u / 1e6 / mid.ticks_per_beat

    out = {}
    for tr in mid.tracks:
        name = next((m.name for m in tr if m.type == "track_name"), "")
        pend, lst = {}, []
        for t, m in _abs(tr):
            if m.type == "note_on" and m.velocity > 0:
                pend.setdefault(m.note, []).append((sec(t), m.velocity))
            elif m.type in ("note_off", "note_on") and pend.get(m.note):
                on, vel = pend[m.note].pop(0)
                lst.append((on, sec(t), m.note, vel))
        if lst:
            out[name] = sorted(lst)
    return out


ATTACK_RULE = {
    "piano": "every note-on (the samples are onset-aligned to 0.2 ms)",
    "quartet": "new-bow and short strokes at their note-on (the renderer starts the bow's pre-roll early "
               "so that the stroke lands on the note-on); slurred notes, which enter by crossfade, are left out "
               "(articulation from its report)",
    "orchestra": "new-bow / tongued and short notes at their note-on plus the seat's depth delay (the "
                 "renderer's stems arrive seated; articulation and seats from its report); slurred notes are "
                 "left out",
    "organ": "every note-on (each key press is a pipe attack; the pipe's speech time is part of the "
             "instrument)",
    "default": "notes after at least 100 ms of silence in their part",
}


def attack_starts(renderer: str, rep: dict, by_track: dict, track_of: dict) -> dict:
    """{stem name: [MIDI seconds]} at which the renderer starts a note's attack."""
    stem_of = {t: s for s, t in track_of.items()}
    if renderer in ("piano", "organ"):
        return {stem_of[t]: [on for on, *_ in v] for t, v in by_track.items() if t in stem_of}
    if renderer == "quartet":
        out = {}
        for j in rep.get("jobs", []):
            if j.get("kind") != "main":
                continue
            ts = [on for (on, off, key, vel, art) in j["note_list"] if art is None or art < 64 or art >= 96]
            out.setdefault(j["inst"], []).extend(ts)
        return {k: sorted(v) for k, v in out.items()}
    if renderer == "orchestra":
        delay = seat_delays(renderer, rep)
        out = {}
        for t in rep.get("tracks", []):
            d = delay.get(t["name"], 0.0)
            out[t["name"]] = sorted(on + d for (on, off, key, vel, art) in t.get("note_list", [])
                                    if art is None or art < 64 or art >= 96)
        return out
    return {stem_of[t]: entry_onsets(v) for t, v in by_track.items() if t in stem_of}


def entry_onsets(notes: list, gap_s: float = 0.1) -> list:
    """Onsets of notes that follow at least gap_s of silence in their own part (or start it):
    their attack is unambiguous on every instrument (a bowed slur's is not)."""
    out, last_off = [], -1e9
    for on, off, *_ in sorted(notes):
        if on - last_off >= gap_s:
            out.append(on)
        last_off = max(last_off, off)
    return out


def stem_track_map(gm: dict, stems: dict) -> dict:
    """stem name -> the MIDI track it renders (quartet stems are named by instrument id)."""
    parts = gm.get("parts", {})
    by_inst = {v.get("instrument"): v.get("track") for v in parts.values() if v.get("instrument")}
    tracks = {v.get("track"): v.get("track") for v in parts.values()}
    low = {str(t).lower(): t for t in tracks}
    # the orchestra writes a track's stem as its name with every character other than a
    # letter, digit, '.', '_' or '-' replaced by '_' (its CONTRACT section 1: 'fl:oct' -> fl_oct)
    safe = {"".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(t)): t for t in tracks}
    out = {}
    for name in stems:
        if gm["renderer"] == "quartet" and name in by_inst:
            out[name] = by_inst[name]
        elif name in tracks:
            out[name] = name
        elif name.lower() in low:
            out[name] = low[name.lower()]
        elif name in safe:
            out[name] = safe[name]
    return out


def per_note_lags(env: np.ndarray, times_s: list, pre_ms=30, post_ms=60) -> np.ndarray:
    out = []
    for t in times_s:
        k = int(round(t * 1000))
        a, b = k - pre_ms, k + post_ms
        if a < 0 or b >= len(env):
            continue
        seg = env[a:b]
        if seg.max() <= 0:
            continue
        out.append(int(np.argmax(seg)) - pre_ms)
    return np.array(out)


# ----------------------------------------------------------------------------- calibration
def calibrate(renderers: set, lead_in: float, force: bool) -> dict:
    """K-weighted loudness (LUFS, raw scale, placed dry sum) of the calibration chorale per renderer."""
    import orchestrate
    import pyloudnorm as pyln
    cal_path = CAL_DIR / "calibration.json"
    cal = json.loads(cal_path.read_text()) if cal_path.exists() else {}
    score, plan = CAL_DIR / "chorale.ly", CAL_DIR / "chorale.plan.json"
    for r in sorted(renderers):
        key = (f"v{CAL_VERSION}:{engine_hash(r)}:{sha(score)}:{sha(plan)}:{sha(Path(orchestrate.__file__))}:"
               f"{sha(Path(hallmod.__file__))}")
        if not force and cal.get(r, {}).get("key") == key:
            continue
        print(f"  calibrating {r} (four-part mf chorale)", flush=True)
        work = CAL_DIR / "render" / r
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        parts = CAL_PARTS[r]
        spec = {"groups": {"cal": {"renderer": r, "parts": parts}},
                "assignments": [{"voice": v, "part": p} for v, p in zip(["soprano", "alto", "tenor", "bass"], parts)]}
        sp = work / "spec.json"
        sp.write_text(json.dumps(spec))
        with contextlib.redirect_stdout(io.StringIO()):
            rep = orchestrate.build(score, plan, sp, work / "orch", quiet=True)
        if not rep["ok"]:
            raise SystemExit(f"calibration orchestration failed: {rep['errors']}")
        side = work / "orch" / ("cal.orchestra.json" if r == "orchestra" else "cal.registration.json")
        res = render_group(r, work / "orch" / "cal.mid", work / "render", lead_in, [], True,
                           side if side.exists() else None)
        n = max(sf.info(str(p)).frames for _, p in res["stems"]) + SR
        stems = load_stems(res["stems"], res["offset_s"], lead_in, n)
        g_db, est = raw_scale_db(r, res["report"], stems)
        dry = np.zeros((n, 2))
        for name, x in stems.items():
            dry += place(x * 10 ** (g_db / 20), stage_for(r, name, name, name, {}), r)
        lufs = pyln.Meter(SR).integrated_loudness(dry)
        cal[r] = {"key": key, "lufs_raw": round(float(lufs), 3), "raw_scale_db": round(g_db, 3),
                  "stems": len(stems), "note": "four-part mf chorale, placed dry sum, pre-normalisation scale"}
        cleanup_render(work / "render")
        # timing probe: the same chorale with every note short (no bow pre-roll, no slur crossfade:
        # a plain attack on the note-on), through the same render / offset / stem path as a mix
        print(f"  timing probe {r} (the chorale, every note short)", flush=True)
        spec["assignments"] = [dict(x, articulation="short") for x in spec["assignments"]]
        sp.write_text(json.dumps(spec))
        with contextlib.redirect_stdout(io.StringIO()):
            rep = orchestrate.build(score, plan, sp, work / "probe", quiet=True)
        side = work / "probe" / ("cal.orchestra.json" if r == "orchestra" else "cal.registration.json")
        res = render_group(r, work / "probe" / "cal.mid", work / "probe_render", lead_in, [], True,
                           side if side.exists() else None)
        n = max(sf.info(str(p)).frames for _, p in res["stems"]) + SR
        stems = load_stems(res["stems"], res["offset_s"], lead_in, n)
        gm = {"renderer": r, "parts": {p: {"track": orchestrate.part_track(r, p, {})["track"],
                                           "instrument": orchestrate.part_track(r, p, {})["instrument"]}
                                       for p in parts}}
        by_track = midi_notes(work / "probe" / "cal.mid")
        track_of = stem_track_map(gm, stems)
        delays = seat_delays(r, res["report"])
        nfr = n // (SR // 1000)
        tot, pn, cnt = None, [], 0
        for name, x in stems.items():
            tr = track_of.get(name)
            if tr not in by_track:
                continue
            ts = [on + lead_in + delays.get(name, 0.0) for on, *_ in by_track[tr]]
            env = fit(onset_envelope(x), nfr)
            c = xcorr_curve(env, onset_train(ts, nfr)) * len(ts)
            tot = c if tot is None else tot + c
            pn += list(per_note_lags(env, ts))
            cnt += len(ts)
        tb = peak_of(tot, TB_SEARCH_MS)
        if abs(tb) >= TB_SEARCH_MS - 1:
            print(f"  WARNING: {r}: the timing probe's peak is on the edge of its +-{TB_SEARCH_MS} ms search: "
                  "time base not measured")
        cal[r].update({"time_base_lag_ms": round(tb, 2), "time_base_search_ms": TB_SEARCH_MS,
                       "time_base_at_search_edge": abs(tb) >= TB_SEARCH_MS - 1,
                       "time_base_global_peak_ms": round(peak_of(tot), 2), "time_base_notes": cnt,
                       "time_base_per_note_median_ms": float(np.median(pn)),
                       "time_base_per_note_p10_p90_ms": [float(np.percentile(pn, 10)), float(np.percentile(pn, 90))]})
        cal_path.write_text(json.dumps(cal, indent=1))
        cleanup_render(work / "probe_render")
    return cal


def cleanup_render(rdir: Path):
    shutil.rmtree(rdir / "stems", ignore_errors=True)
    shutil.rmtree(rdir / "render.stems", ignore_errors=True)
    for p in rdir.glob("*.wav"):
        p.unlink()
    for p in rdir.glob("*.m4a"):
        p.unlink()


def seat_delays(renderer: str, rep: dict) -> dict:
    """Orchestra stems arrive seated: {track: mean depth delay (s) of its players}."""
    if renderer != "orchestra":
        return {}
    delay = {}
    for j in rep.get("jobs", []):
        delay.setdefault(str(j.get("label", "")).split("/")[0], []).append(float(j.get("seat_depth_m", 0.0)) / 343.0)
    return {k: float(np.mean(v)) for k, v in delay.items()}


# ----------------------------------------------------------------------------- placement
def stage_for(renderer: str, part: str | None, track: str | None, inst: str | None, stage: dict) -> dict:
    st = {}
    if renderer == "quartet":
        q = quartet_instr().get(inst or "", {})
        st = {"az": q.get("az", 0.0), "depth": q.get("depth", 0.0), "width": 0.35}
    else:
        st = dict(DEFAULT_STAGE.get(renderer, {"az": 0.0, "depth": 0.0, "width": 0.35}))
    for k in ("*", inst, track, part):
        if k and k in stage:
            st.update(stage[k])
    return st


def place(x: np.ndarray, st: dict, renderer: str) -> np.ndarray:
    if renderer == "orchestra":        # its stems arrive seated (pan, width, depth) by the renderer
        return x
    return hallmod.place_dry(x, float(st.get("az", 0.0)), float(st.get("width", 0.35)),
                             float(st.get("depth", 0.0)))


def side_of(x: np.ndarray, st: dict, renderer: str) -> float:
    """Azimuth sign for the hall (only the side matters: hall.Hall mirrors the IR for the right)."""
    if renderer == "orchestra":
        el, er = float(np.sum(x[:, 0] ** 2)), float(np.sum(x[:, 1] ** 2))
        return 1.0 if el >= er else -1.0
    return 1.0 if float(st.get("az", 0.0)) >= 0 else -1.0


# ----------------------------------------------------------------------------- measurements
def loudness_stats(x: np.ndarray) -> dict:
    import pyloudnorm as pyln
    meter = pyln.Meter(SR)
    I = meter.integrated_loudness(x)
    # short-term (3 s, 1 s hop) for the loudness range, EBU 3342 style (relative gate -20 LU)
    st = []
    for a in range(0, max(1, len(x) - 3 * SR), SR):
        seg = x[a:a + 3 * SR]
        if len(seg) < 3 * SR:
            break
        z = np.mean(sosfilt_k(seg) ** 2, axis=0).sum()
        st.append(-0.691 + 10 * math.log10(max(z, 1e-20)))
    st = np.array(st)
    g = st[st > -70]
    g = g[g > (10 * math.log10(np.mean(10 ** (g / 10))) - 20)] if len(g) else g
    lra = float(np.percentile(g, 95) - np.percentile(g, 10)) if len(g) > 2 else 0.0
    return {"integrated_lufs": round(float(I), 2), "loudness_range_lu": round(lra, 2),
            "short_term_max_lufs": round(float(st.max()), 2) if len(st) else None}


_KW = None


def sosfilt_k(x: np.ndarray) -> np.ndarray:
    """BS.1770 K-weighting (pre-filter + RLB) at 48 kHz."""
    global _KW
    if _KW is None:
        b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
        b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
        from scipy.signal import tf2sos
        _KW = np.vstack([tf2sos(b1, a1), tf2sos(b2, a2)])
    return sosfilt(_KW, x, axis=0)


def kw_level(x: np.ndarray) -> float:
    return -0.691 + db(float(np.mean(sosfilt_k(x) ** 2, axis=0).sum()))


def click_scan(x: np.ndarray, onsets_s: list, lead_in: float) -> dict:
    """Clicks: 1 ms blocks whose energy above 12 kHz is more than 15 dB over the median of the
    surrounding +-20 ms and above -90 dBFS, isolated (no other such block 3-60 ms away) and further
    than 30 ms from any note onset. The isolation rule drops periodic trains: a low brass note's
    lip pulses (bass trombone C2 every 15.3 ms, tuba F1 every 22.9 ms) cross the threshold on
    every period, while a click from a cut sample or a truncated release is a single event."""
    from scipy.ndimage import median_filter
    mono = x.mean(axis=1)
    hp = sosfilt(butter(4, 12000, "high", fs=SR, output="sos"), mono)
    b = SR // 1000
    nb = len(hp) // b
    e = (hp[: nb * b] ** 2).reshape(nb, b).mean(axis=1)
    bg = median_filter(e, size=41, mode="nearest") + 1e-14
    cand = np.nonzero((e / bg > 10 ** 1.5) & (e > 1e-9))[0]
    iso = [k for k in cand if not np.any((np.abs(cand - k) > 2) & (np.abs(cand - k) <= 60))]
    ons = np.array(sorted(onsets_s)) + lead_in
    hits = [round(float(k) / 1000, 3) for k in iso if not (len(ons) and np.min(np.abs(ons - k / 1000)) < 0.03)]
    return {"clicks_away_from_onsets": len(hits), "click_times_s": hits[:20],
            "periodic_candidates_dropped": int(len(cand) - len(iso))}


# ----------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--rerender", action="store_true")
    ap.add_argument("--recalibrate", action="store_true")
    ap.add_argument("--keep-stems", action="store_true")
    ap.add_argument("--max-lag-ms", type=float, default=5.0)
    a = ap.parse_args(argv)

    man_path = a.manifest.resolve()
    base = man_path.parent
    man = json.loads(man_path.read_text())
    lead_in = float(man.get("lead_in", 0.5))
    peak_db = float(man.get("peak_dbtp", -1.0))
    out = (a.out or (base / man.get("out", f"../{base.name}"))).resolve()
    groups = man["groups"]
    ref_group = man.get("reference_group") or next(iter(groups))
    if man.get("hall", "detmold") not in ("detmold", "synthetic"):
        raise SystemExit(f"hall {man.get('hall')!r}: detmold | synthetic")
    report = {"manifest": str(man_path), "out": str(out), "lead_in_s": lead_in, "groups": {}}

    # 1. render
    print(f"{man.get('title', man_path.name)}: {len(groups)} group(s)")
    renders = {}
    for g, gm in groups.items():
        side = None
        if gm["renderer"] == "orchestra":
            side = base / f"{g}.orchestra.json"
        elif gm["renderer"] == "organ":
            side = base / f"{g}.registration.json"
        renders[g] = render_group(gm["renderer"], base / gm["midi"], base / "render" / g, lead_in,
                                  gm.get("render_args", []), a.rerender, side)
    n = 0
    for g, r in renders.items():
        for _, p in r["stems"]:
            n = max(n, sf.info(str(p)).frames + int(round((r["offset_s"] + lead_in) * SR)))
    n += int(0.5 * SR)

    # 3. levels: raw scale, renderer calibration, manifest gain
    rset = {gm["renderer"] for gm in groups.values()}
    cal = calibrate(rset, lead_in, a.recalibrate) if len(groups) > 1 else {}
    ref_lufs = cal.get(groups[ref_group]["renderer"], {}).get("lufs_raw")
    aligned = {}
    for g, gm in groups.items():
        r = renders[g]
        stems = load_stems(r["stems"], r["offset_s"], lead_in, n)
        raw_db, est = raw_scale_db(gm["renderer"], r["report"], stems)
        cal_db = 0.0 if ref_lufs is None else ref_lufs - cal[gm["renderer"]]["lufs_raw"]
        gain_db = raw_db + cal_db + float(gm.get("gain_db", 0.0))
        for k in stems:
            stems[k] *= 10 ** (gain_db / 20)
        aligned[g] = stems
        report["groups"][g] = {"renderer": gm["renderer"], "midi": gm["midi"], "stems": sorted(stems),
                               "offset_s": r["offset_s"], "raw_scale_db": round(raw_db, 3),
                               "raw_scale_estimates": est, "calibration_db": round(cal_db, 3),
                               "gain_db": float(gm.get("gain_db", 0.0)), "total_gain_db": round(gain_db, 3)}
        mv = moved_notes(gm["renderer"], r)
        if mv:
            report["groups"][g]["octave_shifted"] = mv
            for k, v in mv.items():
                w = (f"{g}/{k}: {len(v) if isinstance(v, list) else v} note(s) moved by octaves into the compass "
                     "by the renderer (they sound in the wrong octave)"
                     + (f": {v[:4]}" if isinstance(v, list) else ""))
                report.setdefault("warnings", []).append(w)
                print("  WARNING:", w)
    report["calibration"] = {k: v for k, v in cal.items() if k in rset}

    # 4. verify alignment (before placement: the stage's depth delays are physical, not errors)
    print("  verifying alignment", flush=True)
    nframes = n // (SR // 1000)
    ons, env_group, env_stem, entries, attacks = {}, {}, {}, {}, {}
    for g, gm in groups.items():
        ons[g] = midi_onsets(base / gm["midi"])
        by_track = midi_notes(base / gm["midi"])
        track_of = stem_track_map(gm, aligned[g])
        env_group[g] = fit(onset_envelope(sum(aligned[g].values())), nframes)
        env_stem[g], entries[g] = {}, {}
        for name, x in aligned[g].items():
            tr = track_of.get(name)
            if tr is None or tr not in by_track:
                continue
            env_stem[g][name] = fit(onset_envelope(x), nframes)
            entries[g][name] = [t + lead_in for t in entry_onsets(by_track[tr])]
        attacks[g] = {k: [t + lead_in for t in v]
                      for k, v in attack_starts(gm["renderer"], renders[g]["report"], by_track, track_of).items()
                      if k in env_stem[g]}

    def entry_lag(g, shift_ms=0.0, window=None, which=None):
        """cross-correlation of each stem's onset envelope with the times at which its renderer
        starts an attack (attack_starts), curves summed over the group's stems -> peak"""
        which = attacks if which is None else which
        tot, cnt, pn = None, 0, []
        for name, env in env_stem[g].items():
            ts = [t - shift_ms / 1000 for t in which[g].get(name, [])]
            if window is not None:
                ts = [t for t in ts if window[0] <= t * 1000 < window[1]]
            if len(ts) < 3:
                continue
            m = None
            if window is not None:
                m = np.zeros(nframes)
                m[int(window[0]):int(window[1])] = 1.0
            c = xcorr_curve(env if m is None else env * m, onset_train(ts, nframes))
            tot = c * len(ts) if tot is None else tot + c * len(ts)
            cnt += len(ts)
            pn += list(per_note_lags(env, ts))
        if tot is None:
            return None, 0, []
        return peak_of(tot, TB_SEARCH_MS), cnt, pn

    lags, report_align = {}, {}
    q_edges = np.linspace(0, nframes, 5)
    for g, gm in groups.items():
        lat = gm.get("latency_ms", 0)
        lag, cnt, pn = entry_lag(g)
        if lag is None:
            print(f"  warning: {g}: no attacks in the music to measure (the probe still gates)")
            lag = 0.0
        lags[g] = lag
        el, ecnt, _ = entry_lag(g, which=entries)
        report_align[g] = {
            "attack_rule": ATTACK_RULE.get(gm["renderer"], ATTACK_RULE["default"]),
            "entry_xcorr_lag_ms": round(lag, 2), "entries": cnt,
            "after_silence_xcorr_lag_ms": None if el is None else round(el, 2), "after_silence_notes": ecnt,
            "entry_lag_ms_by_quarter": [None if x[0] is None or x[1] < 10 else round(x[0], 2) for x in
                                        (entry_lag(g, window=(q0, q1)) for q0, q1 in zip(q_edges[:-1], q_edges[1:]))],
            "entry_per_note_lag_ms_median": float(np.median(pn)) if pn else None,
            "entry_per_note_lag_ms_p10_p90": [float(np.percentile(pn, 10)), float(np.percentile(pn, 90))] if pn else None,
            "requested_latency_ms": lat}
        # every note, the group's summed envelope: shows articulation (bowed slurs lead or trail)
        times = [t + lead_in for t, *_ in ons[g]]
        all_lag = xcorr_lag(env_group[g], onset_train(times, nframes))[0]
        pa = per_note_lags(env_group[g], times)
        report_align[g].update({"all_notes_xcorr_lag_ms": round(all_lag, 2), "all_notes": len(times),
                                "all_notes_per_note_lag_ms_median": float(np.median(pa)) if len(pa) else None})
    # latency compensation: shift a group earlier by latency_ms, or with "auto" by its own time base
    # (the timing probe's lag re MIDI), so its attacks land on the MIDI clock. Default: "auto" for the
    # organ (its pipes speak about 20 ms after the key, and an organist anticipates), none for others
    tbase = {g: cal.get(gm["renderer"], {}).get("time_base_lag_ms") for g, gm in groups.items()}
    for g, gm in groups.items():
        lat = gm.get("latency_ms", "auto" if gm["renderer"] == "organ" else 0)
        if lat == "auto":
            comp = tbase[g] if tbase[g] is not None else lags[g]
        else:
            comp = float(lat)
        report_align[g]["compensation_ms"] = round(comp, 2)
        if comp:
            k = int(round(comp / 1000 * SR))
            for s_ in aligned[g]:
                aligned[g][s_] = np.roll(aligned[g][s_], -k, axis=0)
                if k > 0:
                    aligned[g][s_][-k:] = 0
                else:
                    aligned[g][s_][:-k] = 0
            for name in env_stem[g]:          # measured again on the shifted stems
                env_stem[g][name] = fit(onset_envelope(aligned[g][name]), nframes)
            env_group[g] = fit(onset_envelope(sum(aligned[g].values())), nframes)
            lags[g] = entry_lag(g)[0] or 0.0
        report_align[g]["entry_lag_after_ms"] = round(lags[g], 2)
        report["groups"][g]["alignment"] = report_align[g]
    inter = {}
    names = list(groups)
    for i, g in enumerate(names):
        for h in names[i + 1:]:
            e = {"entry_lag_difference_ms": round(lags[g] - lags[h], 2)}
            qa, qb = report_align[g]["entry_lag_ms_by_quarter"], report_align[h]["entry_lag_ms_by_quarter"]
            e["entry_lag_difference_ms_by_quarter"] = [None if x is None or y is None else round(x - y, 2)
                                                       for x, y in zip(qa, qb)]
            # direct: the two groups' onset envelopes around the onsets they share (doublings)
            tg = {int(round((t + lead_in) * 1000)) for t, *_ in ons[g]}
            th = {int(round((t + lead_in) * 1000)) for t, *_ in ons[h]}
            shared = sorted(k for k in tg if any(k + d in th for d in range(-3, 4)))
            e["shared_onsets"] = len(shared)
            if len(shared) >= 20:
                mask = np.zeros(nframes)
                for k in shared:
                    mask[max(0, k - 60):k + 60] = 1.0
                lag_, _, prom_ = xcorr_lag(env_group[g] * mask, env_group[h] * mask)
                e["direct_xcorr_lag_ms"] = round(lag_, 2)
                e["direct_xcorr_prominence"] = round(prom_, 3)
            # the same on the onsets that both renderers attack (piano/organ: every note; strings and
            # winds: new bow, tongued, short), per stem pair summed: a slurred bowed note enters by
            # crossfade and its envelope peak measures articulation, not the time base
            ag = {int(round(t * 1000)) for v in attacks[g].values() for t in v}
            ah = {int(round(t * 1000)) for v in attacks[h].values() for t in v}
            both = sorted(k for k in ag if any(k + d in ah for d in range(-3, 4)))
            e["shared_attacks"] = len(both)
            if len(both) >= 20:
                mask = np.zeros(nframes)
                for k in both:
                    mask[max(0, k - 60):k + 60] = 1.0
                lag_, _, prom_ = xcorr_lag(env_group[g] * mask, env_group[h] * mask)
                e["direct_xcorr_lag_ms_attacks"] = round(lag_, 2)
                e["direct_xcorr_prominence_attacks"] = round(prom_, 3)
            inter[f"{g}-{h}"] = e
    # the gate: the renderers' time bases, measured by the timing probe (the calibration chorale
    # with every note short, through the same render / offset / stem path), agree within
    # --max-lag-ms. The doubled-onset cross-correlations are information only: on bowed music the
    # curve is flat over several ms (slurred entries, slow bow attacks), so its peak wanders by
    # +-5 ms between subsets of the same notes while the stems sit sample-accurately on the clock
    for g, gm in groups.items():
        tb = tbase[g]
        report["groups"][g]["alignment"]["time_base_lag_ms"] = tb
        report["groups"][g]["alignment"]["time_base_after_compensation_ms"] = \
            None if tb is None else round(tb - report["groups"][g]["alignment"]["compensation_ms"], 2)
    checks = []
    for key_, v in inter.items():
        g, h = key_.split("-", 1)
        tg = report["groups"][g]["alignment"]["time_base_after_compensation_ms"]
        th = report["groups"][h]["alignment"]["time_base_after_compensation_ms"]
        if tg is not None and th is not None:
            v["time_base_difference_ms"] = round(tg - th, 2)
            checks.append(abs(tg - th))
    for g, gm in groups.items():
        if cal.get(gm["renderer"], {}).get("time_base_at_search_edge"):
            checks.append(float(TB_SEARCH_MS))
            report.setdefault("warnings", []).append(f"{g}: its renderer's time base is not measured (probe peak "
                                                     f"on the edge of the +-{TB_SEARCH_MS} ms search)")
    report["inter_group"] = inter
    worst = max(checks, default=0.0)
    report["alignment_gate"] = ("time base difference between groups (timing probe) under "
                                f"{a.max_lag_ms} ms; doubled-onset lags are information")
    report["alignment_ok"] = worst < a.max_lag_ms
    report["alignment_worst_ms"] = round(worst, 2)
    for k, v in inter.items():
        print(f"  {k}: time base difference {v.get('time_base_difference_ms', float('nan')):+.2f} ms (probe, gated)"
              + (f"; info: doubled onsets {v['direct_xcorr_lag_ms']:+.2f} ms over {v['shared_onsets']}"
                 if "direct_xcorr_lag_ms" in v else "")
              + (f", both attacked {v['direct_xcorr_lag_ms_attacks']:+.2f} ms over {v['shared_attacks']}"
                 if "direct_xcorr_lag_ms_attacks" in v else "")
              + f", attacks in the music {v['entry_lag_difference_ms']:+.2f} ms")
    if not report["alignment_ok"]:
        # the mix is still written (a render costs far more than a look at the report), flagged
        print(f"  WARNING: time bases differ by {worst:.2f} ms (limit {a.max_lag_ms} ms): the mix is written "
              "but flagged (alignment_ok false in the report); a renderer's offset or latency is wrong")

    # 5. place and reverberate
    print("  placing and reverberating", flush=True)
    hall = hallmod.Hall(man.get("hall", "detmold"), SR)
    tail = len(hall.ir)
    dry = np.zeros((n + tail, 2))
    wet = np.zeros((n + tail, 2))
    per_group_dry = {}
    stems_out = out.parent / f"{out.name}.stems" if a.keep_stems else None
    if stems_out is not None:
        shutil.rmtree(stems_out, ignore_errors=True)
        stems_out.mkdir(parents=True)
    for g, gm in groups.items():
        rname = gm["renderer"]
        parts = gm.get("parts", {})
        by_track = {v.get("track"): p for p, v in parts.items()}
        by_inst = {v.get("instrument"): p for p, v in parts.items() if v.get("instrument")}
        wet_db = float(gm.get("wet_db", -4.0))
        feeds = {1.0: np.zeros(n), -1.0: np.zeros(n)}
        gdry = np.zeros((n, 2))
        seats = {}
        for name, x in aligned[g].items():
            part = by_track.get(name) or by_inst.get(name) or next(
                (p for t, p in by_track.items() if t and t.lower() == name.lower()), None)
            inst = parts.get(part, {}).get("instrument") if part else name
            st = stage_for(rname, part, name, inst, gm.get("stage", {}))
            y = place(x, st, rname)
            gdry += y
            if stems_out is not None:     # as it enters the hall; scaled to the master's gain below
                sf.write(str(stems_out / f"{g}_{name}.wav"), y.astype(np.float32), SR, subtype="FLOAT")
            feeds[side_of(x, st, rname)] += x.mean(axis=1)
            seats[name] = {k: st.get(k) for k in ("az", "depth", "width")} if rname != "orchestra" else "renderer"
        dry[:n] += gdry
        # the group's hall at unit gain, then scaled: by wet_db (impulse-referenced, hall.py's
        # convention), or so that the hall's energy re the group's dry sound, measured on this
        # music, is hall_re_dry_db (portable between instruments whose spectra excite the hall
        # differently: at the same wet_db the piano's hall is about 2.5 dB stronger than the quartet's)
        gwet = np.zeros((n + tail, 2))
        for sgn, mono in feeds.items():
            if np.any(mono):
                h = hall.ir if sgn > 0 else hall.mirror
                for c in range(2):
                    conv = fftconvolve(mono, h[:, c])[: n + tail]
                    gwet[: len(conv), c] += conv
        unit_ratio = db(float(np.sum(gwet ** 2))) - db(float(np.sum(gdry ** 2)))
        if gm.get("hall_re_dry_db") is not None:
            wet_db = float(gm["hall_re_dry_db"]) - unit_ratio
        wet += gwet * 10 ** (wet_db / 20)
        del gwet
        report["groups"][g]["hall_re_dry_db_program"] = round(unit_ratio + wet_db, 2)
        per_group_dry[g] = gdry
        report["groups"][g]["wet_db"] = round(wet_db, 2)
        report["groups"][g]["c80_db_impulse"] = round(hall.c80(10 ** (wet_db / 20)), 2)
        report["groups"][g]["seats"] = seats
    mix = dry + wet
    del aligned

    # 6. master
    print("  mastering", flush=True)
    mix = sosfilt(butter(2, 18, "high", fs=SR, output="sos"), mix, axis=0)
    env = np.abs(mix).max(axis=1)
    last = int(np.nonzero(env > env.max() * 10 ** (-80 / 20))[0][-1]) + int(0.05 * SR)
    mix = mix[: min(last, len(mix))]
    fade = int(0.3 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    tp = true_peak(mix)
    gnorm = 10 ** (peak_db / 20) / tp
    mix *= gnorm
    out.parent.mkdir(parents=True, exist_ok=True)
    wav, m4a = out.with_suffix(".wav"), out.with_suffix(".m4a")
    with sf.SoundFile(str(wav), "w", SR, 2, subtype="PCM_24") as f:
        f.title = str(man.get("title", out.stem))[:250]
        f.software = "ricercar tools/mix.py"
        f.comment = CREDITS
        f.write(mix.astype(np.float32))
    m4a_tp = encode_m4a(wav, m4a, peak_db)
    if stems_out is not None:
        # dry stems at their level in the master (the master's gain applied, not its 18 Hz high-pass):
        # stems + the hall (wet) = the mix
        for p in sorted(stems_out.glob("*.wav")):
            y = sf.read(str(p), dtype="float64", always_2d=True)[0] * gnorm
            sf.write(str(p), y.astype(np.float32), SR, subtype="FLOAT")
        report["stems_dir"] = str(stems_out)
        report["stems_note"] = ("dry stems as they enter the hall (seated, gains, latency compensation, the "
                                "master's normalisation gain), 32-bit float, same start as the mix; the hall "
                                "and the 18 Hz high-pass are not in them")

    # 7. measurements
    print("  measuring", flush=True)
    wav_x = sf.read(str(wav), dtype="float64", always_2d=True)[0]
    all_on = [t for g in groups for t, *_ in ons[g]]
    report["output"] = {
        "wav": str(wav), "m4a": str(m4a), "duration_s": round(len(wav_x) / SR, 2),
        "format": f"{sf.info(str(wav)).samplerate} Hz, {sf.info(str(wav)).channels} ch, {sf.info(str(wav)).subtype}",
        "true_peak_dbtp_wav": round(20 * math.log10(true_peak(wav_x)), 2),
        "true_peak_dbtp_m4a": m4a_tp, "normalise_gain_db": round(20 * math.log10(gnorm), 2),
        **loudness_stats(wav_x),
        "stereo_correlation": round(float(np.corrcoef(wav_x[:, 0], wav_x[:, 1])[0, 1]), 3),
        "mono_fold_down_db": round(db(float(np.mean(wav_x.mean(axis=1) ** 2)))
                                   - db(float(np.mean(wav_x ** 2))), 2),
        "hall_re_dry_db": round(db(float(np.sum(wet[:len(mix)] ** 2))) - db(float(np.sum(dry[:len(mix)] ** 2))), 2),
        **click_scan(wav_x, all_on, lead_in),
    }
    # balance: each group's K-weighted level (dry, after all gains) while it plays, and the levels
    # of the groups relative to each other where they play together
    act = {}
    for g in groups:
        m = np.zeros(len(mix), bool)
        ts = sorted(t for t, *_ in ons[g])
        for t in ts:
            a0 = int((t + lead_in) * SR)
            m[a0:a0 + int(1.0 * SR)] = True
        x = per_group_dry[g][: len(mix)] * gnorm
        m = m[: len(x)]                      # the mix may run longer than the dry buffers (hall tail)
        act[g] = m
        report["groups"][g]["level_when_playing_lufs"] = round(kw_level(x[m]), 2) if m.any() else None
    if len(groups) > 1:
        L = min(len(m) for m in act.values())
        both = np.all(np.stack([act[g][:L] for g in groups]), axis=0)
        report["balance_where_all_play"] = {
            "seconds": round(float(both.sum()) / SR, 1),
            **{g: round(kw_level(per_group_dry[g][:L][both] * gnorm), 2) for g in groups}} \
            if both.any() else None
    curve = []
    for k in range(0, len(wav_x) - 5 * SR, 5 * SR):
        curve.append(round(kw_level(wav_x[k:k + 5 * SR]), 1))
    report["loudness_curve_5s_lufs"] = curve
    rp = out.parent / f"{out.name}.mix.json"
    rp.write_text(json.dumps(report, indent=1))
    o = report["output"]
    print(f"  -> {wav.name}, {m4a.name}: {o['duration_s']} s, {o['integrated_lufs']} LUFS, LRA {o['loudness_range_lu']} LU, "
          f"true peak {o['true_peak_dbtp_wav']} dBTP (m4a {o['true_peak_dbtp_m4a']}), report {rp.name}")
    return report


def encode_m4a(wav: Path, m4a: Path, peak_db: float) -> float:
    """AAC 256 kb/s with afconvert; if the decoded true peak overshoots by more than 0.1 dB, encode
    again from a copy lowered by the overshoot."""
    src = wav
    tmp = None
    tp = None
    for _ in range(3):
        if m4a.exists():
            m4a.unlink()
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "256000", str(src), str(m4a)], check=True)
        with tempfile.TemporaryDirectory() as td:
            dec = Path(td) / "dec.wav"
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEF32", str(m4a), str(dec)], check=True)
            x = sf.read(str(dec), dtype="float64", always_2d=True)[0]
        tp = 20 * math.log10(true_peak(x))
        if tp <= peak_db + 0.1:
            break
        y = sf.read(str(wav), dtype="float64", always_2d=True)[0] * 10 ** ((peak_db - tp - 0.05) / 20)
        tmp = Path(tempfile.mkdtemp()) / "lower.wav"
        sf.write(str(tmp), y.astype(np.float32), SR, subtype="FLOAT")
        src = tmp
    if tmp is not None:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return round(tp, 2)


if __name__ == "__main__":
    sys.exit(0 if main().get("alignment_ok", True) else 3)
