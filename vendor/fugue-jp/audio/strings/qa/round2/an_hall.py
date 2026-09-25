#!/usr/bin/env python3
"""Round-2: what --wet -4 means per frequency band, against what the renderer prints and documents.

  python3 an_hall.py [--tag sk_final] [--wet -4]

The renderer prints "C80 +8.4 dB" and documents --wet as "reverb energy relative to the dry sound".
Both are computed on the broadband IR, i.e. for white noise, where the 4-8 kHz octaves carry most of
the energy.  Here, from the IR the renderer convolves with (hall.Hall('detmold')) and a unit dry
impulse placed the way render_quartet places it:
  * per octave band 63 Hz-8 kHz: reverb re dry (dB) and C80 (dB) of dry + g*IR;
  * ISO 3382-style single number C80(500-2k) = mean of the 500 / 1k / 2k octave values;
  * the same two figures weighted by the test music's own dry spectrum (octave-band energy of the
    four dry stems of the default render) - what the file actually carries;
  * the IR's octave-band gain re a flat (white) response of the same total energy.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_r2 import SR, STRINGS, TMP, db, save  # noqa: E402

sys.path.insert(0, str(STRINGS))
import hall  # noqa: E402

BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


def band(x, fc):
    return sosfiltfilt(hall._octave_sos(fc, SR), x, axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="sk_final")
    ap.add_argument("--wet", type=float, default=-4.0)
    a = ap.parse_args()
    H = hall.Hall("detmold", SR)
    g2 = 10 ** (a.wet / 10)
    n = len(H.ir) + SR
    imp = np.zeros(n)
    imp[SR // 2] = 1.0
    dry = np.stack([imp, imp], axis=1)
    rows = {}
    n80 = int(0.080 * SR)
    for fc in BANDS:
        d = band(dry, fc)
        ed = float(np.sum(d ** 2)) / 2                        # mono impulse over 2 identical channels -> energy 1 (place_dry)
        h = band(H.ir, fc)
        eh = np.sum(h ** 2, axis=1)
        early, late = float(eh[:n80].sum()) * g2, float(eh[n80:].sum()) * g2
        rows[fc] = dict(reverb_re_dry_db=round(float(db((early + late) / ed)), 1),
                        c80_db=round(float(db((ed + early) / late)), 1),
                        ir_gain_re_flat_db=round(float(db((early + late) / g2 / ed)), 1))
    iso = float(np.mean([rows[f]["c80_db"] for f in (500, 1000, 2000)]))
    # the test music's dry spectrum
    E = np.zeros(len(BANDS))
    for inst in ("vn1", "vn2", "va", "vc"):
        st, _ = sf.read(str(TMP / f"{a.tag}_def_stem_{inst}.wav"), always_2d=True)
        m = st.mean(axis=1)[: 120 * SR]
        E += np.array([float(np.mean(band(m, fc) ** 2)) for fc in BANDS])
    w = E / E.sum()
    lin = lambda k: np.array([10 ** (rows[f][k] / 10) for f in BANDS])  # noqa: E731
    rr = lin("reverb_re_dry_db")
    prog_rev = float(db(np.sum(w * rr)))
    # program C80: dry + early vs late energies, weighted by the music's band energies
    # per band (dry = 1): c = (1 + e) / l and e + l = r  ->  l = (1 + r) / (c + 1)
    c80_lin = lin("c80_db")
    l_b = (1 + rr) / (c80_lin + 1)
    e_b = rr - l_b
    prog_c80 = float(db(np.sum(w * (1 + e_b)) / np.sum(w * l_b)))
    res = dict(wet_db=a.wet, printed_c80_db=round(H.c80(10 ** (a.wet / 20)), 1), per_octave=rows,
               c80_iso_500_2k_db=round(iso, 1),
               test_music_band_share_db={f: round(float(db(x)), 1) for f, x in zip(BANDS, w)},
               test_music_reverb_re_dry_db=round(prog_rev, 1), test_music_c80_db=round(prog_c80, 1))
    save(f"hall_{a.tag}_wet{int(a.wet)}.json", res)
    import json
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
