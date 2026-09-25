"""Shared paths, instrument tables and DSP helpers for the Iowa MIS string quartet.

The University of Iowa Electronic Music Studios "Musical Instrument Samples"
(MIS, 2012 re-recordings) contain solo violin, viola, cello and double bass,
played arco with vibrato at three real dynamics (pp, mf, ff), one chromatic
run per string, recorded in an anechoic chamber.  Licence (from the MIS site):
"freely available ... may be downloaded and used for any projects, without
restrictions".  https://theremin.music.uiowa.edu/MIS.html
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import numpy as np

LIB_ROOT = Path(os.environ.get("SAMPLE_LIBRARIES", Path.home() / "Music" / "SampleLibraries"))
IOWA_ROOT = LIB_ROOT / "IowaMIS"
RAW_DIR = IOWA_ROOT / "raw"
# generated samples + SFZ live here; IOWA_QUARTET_DIR builds into a staging copy (render_quartet.py
# --sfz-dir plays it), so a rebuild never leaves the live instruments half-written
QUARTET_DIR = Path(os.environ.get("IOWA_QUARTET_DIR", IOWA_ROOT / "quartet"))
# the same pinned, float-output sfizz_render the piano renderer builds (setup_piano.sh / setup_strings.sh)
SFIZZ_RENDER = Path(os.environ.get("SFIZZ_RENDER", LIB_ROOT / "tools" / "sfizz" / "build" / "library" / "bin" / "sfizz_render"))
IR_ROOT = LIB_ROOT / "IR"

DYNAMICS = ("pp", "mf", "ff")

IOWA_BASE = "https://theremin.music.uiowa.edu/"
INSTRUMENTS = {
    # name: Iowa page, open strings (MIDI), playable range used for mapping
    "violin": dict(page="MISviolin2012.html", strings={"G": 55, "D": 62, "A": 69, "E": 76}, lo=55, hi=100),
    # The 2012 viola files are 24-bit recordings whose AIFF headers say 44.1 kHz
    # although the audio is 96 kHz (pitches come out 1.35 octaves low and every
    # note lasts 2.18x too long); true_sr overrides the header.
    # Second violin: the same Iowa violin recordings, but each note taken from the next
    # lower string where it was recorded there (a G/D-string colour, as inner-voice
    # players often choose), so Violin I and II are two distinct sounds, never one
    # sample set played twice.
    "violin2": dict(page="MISviolin2012.html", strings={"G": 55, "D": 62, "A": 69, "E": 76}, lo=55, hi=100,
                    variant_of="violin", string_shift=1),
    "viola": dict(page="MISviola2012.html", strings={"C": 48, "G": 55, "D": 62, "A": 69}, lo=48, hi=91,
                  true_sr=96000),
    "cello": dict(page="MIScello2012.html", strings={"C": 36, "G": 43, "D": 50, "A": 57}, lo=36, hi=81),
    # Iowa names the sounding pitch for the bass; C extension string = C1.
    "bass": dict(page="MISdoublebass2012.html", strings={"C": 24, "E": 28, "A": 33, "D": 38, "G": 43}, lo=24, hi=67),
}

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NOTE_RE = re.compile(r"([A-G])(b|#)?(\d)")
NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def note_to_midi(name: str) -> int:
    m = NOTE_RE.fullmatch(name)
    if not m:
        raise ValueError(name)
    acc = {"b": -1, "#": 1, None: 0}[m.group(2)]
    return 12 * (int(m.group(3)) + 1) + PC[m.group(1)] + acc


def midi_name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def midi_to_hz(m: float) -> float:
    return 440.0 * 2.0 ** ((m - 69.0) / 12.0)


def parse_iowa_name(fname: str):
    """'Violin.arco.pp.sulG.G3B3.stereo.aif' / 'Viola.arco.sulC.pp.C3B3.stereo.aif'
    -> dict(dyn, string, lo, hi).  hi == lo for single-note files ('C6')."""
    toks = [t.strip() for t in fname.split(".")]
    dyn = next(t for t in toks if t in DYNAMICS)
    string = next(t for t in toks if t.startswith("sul"))[3:]
    rng = next(t for t in toks if re.fullmatch(r"([A-G][b#]?\d){1,2}", t))
    notes = NOTE_RE.findall(rng)
    lo = note_to_midi("".join(notes[0]))
    hi = note_to_midi("".join(notes[-1]))
    return dict(dyn=dyn, string=string, lo=lo, hi=hi)


def base_of(inst: str) -> str:
    """Recording set an instrument is built from (violin2 -> violin)."""
    return INSTRUMENTS[inst].get("variant_of", inst)


def load_iowa(inst: str, path: Path) -> tuple[np.ndarray, int]:
    """Load a raw Iowa file with the instrument's true sample rate."""
    x, sr = load_audio(path)
    return x, INSTRUMENTS[inst].get("true_sr", sr)


def load_audio(path: Path, sr: int | None = None) -> tuple[np.ndarray, int]:
    """Decode any audio file with ffmpeg to float32 (frames, channels)."""
    import soundfile as sf
    try:
        x, fs = sf.read(str(path), dtype="float32", always_2d=True)
        if sr is None or fs == sr:
            return x, fs
    except Exception:
        pass
    args = ["ffmpeg", "-loglevel", "error", "-i", str(path)]
    if sr:
        args += ["-ar", str(sr)]
    args += ["-f", "f32le", "-acodec", "pcm_f32le", "-"]
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                            "stream=channels,sample_rate", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    fs0, ch = int(probe[0]), int(probe[1])
    raw = subprocess.run(args, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, ch).copy(), (sr or fs0)


def env_db(mono: np.ndarray, sr: int, win_s: float = 0.01) -> tuple[np.ndarray, int]:
    """RMS envelope in dB with hop = win."""
    hop = max(1, int(sr * win_s))
    n = len(mono) // hop
    fr = mono[: n * hop].reshape(n, hop)
    return 10.0 * np.log10(np.mean(fr.astype(np.float64) ** 2, axis=1) + 1e-20), hop


def harmonic_score(spec: np.ndarray, df: float, f0: float, nh: int = 10) -> float:
    """Harmonic comb score minus inter-harmonic energy (suppresses octave errors)."""
    s = 0.0
    nyq = len(spec) * df
    for k in range(1, nh + 1):
        fk = k * f0
        if fk >= nyq * 0.95:
            break
        i = int(round(fk / df))
        j = int(round((k - 0.5) * f0 / df))
        w = 1.0 / np.sqrt(k)
        s += w * (spec[max(i - 1, 0): i + 2].max() - spec[max(j - 1, 0): j + 2].max())
    return s


def estimate_f0(mono: np.ndarray, sr: int, lo_midi: float, hi_midi: float) -> tuple[float, float]:
    """Return (midi_float, confidence) for a steady tone.  Coarse comb search over
    [lo, hi] in 10-cent steps, then refine to 0.5 cents."""
    n = len(mono)
    nfft = 1 << int(np.ceil(np.log2(max(n, 1) * 4)))
    spec = np.abs(np.fft.rfft(mono * np.hanning(n), nfft))
    spec = np.log1p(spec / (np.median(spec) + 1e-12))
    df = sr / nfft
    cands = np.arange(lo_midi, hi_midi, 0.1)
    scores = np.array([harmonic_score(spec, df, midi_to_hz(c)) for c in cands])
    best = cands[int(np.argmax(scores))]
    fine = np.arange(best - 0.12, best + 0.12, 0.005)
    fs = np.array([harmonic_score(spec, df, midi_to_hz(c)) for c in fine])
    return float(fine[int(np.argmax(fs))]), float(scores.max())
