#!/usr/bin/env python3
"""Re-check the QA round-2 defects after the fixes. Audio goes to /tmp/pianofix2, results to
qa/fixes2/results/*.json. Run make_fix_probes.py first.

    python3 verify_fixes.py contract   # 1, 6: GM CC1 reset, duplicate track names
    python3 verify_fixes.py tail       # 3: ff staccato chord, hall tail per octave band
    python3 verify_fixes.py release    # 5: hammer-noise release timing after key-up (iso probe)
    python3 verify_fixes.py velsweep   # 4: brightness and level across velocity layers
    python3 verify_fixes.py hall       # 2: hall-to-dry and program C80 on the demo; fast16 articulation
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy.signal as ss

HERE = Path(__file__).resolve().parent
PIANO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "round2"))
from lib2 import SR, read  # noqa: E402

P = Path("/tmp/pianofix2")
RES = HERE / "results"


def render(mid: Path, out: str, *extra: str, stems: bool = False) -> dict:
    cmd = [sys.executable, str(PIANO / "render_piano.py"), str(mid), "-o", str(P / out), "--no-m4a",
           "--json", str(P / f"{out}.render.json"), *extra]
    if stems:
        cmd += ["--stems", str(P / f"{out}_stems")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    (P / f"{out}.log").write_text(r.stdout + r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"render {out} failed:\n{r.stderr[-2000:]}")
    return json.loads((P / f"{out}.render.json").read_text())


def save(name: str, res: dict) -> None:
    RES.mkdir(exist_ok=True)
    (RES / f"{name}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1)[:4000])


def contract() -> None:
    def summary(r):
        return {"cc_dynamics": r["cc_dynamics"], "normalise_gain_db": r["normalise_gain_db"],
                "voices": {k: {"notes": v["notes"], "velocity_in": v["velocity_in_range"],
                               "velocity_eff": v["velocity_eff_range"], "rms_dbfs_prenorm": v["rms_dbfs_prenorm"],
                               "cc_dynamics_db_mean": v["cc_dynamics_db_mean"]} for k, v in r["voices"].items()},
                "warnings": r["warnings"]}
    res = {
        "gm_cc1reset_default": summary(render(P / "gm_cc1reset.mid", "gm_default")),
        "gm_cc1reset_--cc-dynamics_velocity": summary(render(P / "gm_cc1reset.mid", "gm_velocity", "--cc-dynamics", "velocity")),
        "gm_cc1reset_--cc-dynamics_off": summary(render(P / "gm_cc1reset.mid", "gm_off", "--cc-dynamics", "off")),
        "odd_names_default": summary(render(P / "odd_names.mid", "odd_names")),
        "odd_names_--transpose_soprano.2=-12": summary(render(P / "odd_names.mid", "odd_names_tr", "--transpose", "soprano.2=-12")),
    }
    save("midi_contract", res)


def band_sos(fc: float):
    return ss.butter(3, [fc / 2 ** 0.5, min(fc * 2 ** 0.5, 23000)], "band", fs=SR, output="sos")


def tail() -> None:
    """ff staccato chord, default render: per-band level after key-up (10 ms frames) and decay
    slopes early (0.5-1.2 s) and late (1.3-2.2 s): a truncated IR shows a cliff after ~1.3 s."""
    rep = render(P / "ffchord_end.mid", "ffchord_end")
    x = read(P / "ffchord_end.wav")
    keyup = 0.3 + 0.5 + 0.4  # lead-in + note-on at 0.5 s (480 ticks = one beat at 120 bpm) + 0.4 s held
    out = {"file_duration_s": round(len(x) / SR, 2), "keyup_s": keyup, "render_wet_db": rep["wet_db"]}
    for fc in (63, 125, 250, 500, 1000):
        y = ss.sosfiltfilt(band_sos(fc), x, axis=0)
        e = (y ** 2).sum(axis=1)
        fr = SR // 100
        n = len(e) // fr
        env = 10 * np.log10(e[: n * fr].reshape(n, fr).mean(axis=1) + 1e-30)
        env -= env.max()
        t = np.arange(n) / 100 - keyup

        def slope(a, b):
            s = (t >= a) & (t < b) & (env > -95)
            return round(float(np.polyfit(t[s], env[s], 1)[0]), 1) if s.sum() > 5 else None
        out[f"band_{fc}"] = {
            "level_db_re_band_peak_after_keyup": {f"{a:g}": round(float(env[np.argmin(np.abs(t - a))]), 1)
                                                  for a in (0.3, 0.6, 0.9, 1.2, 1.3, 1.4, 1.5, 1.8, 2.1, 2.4)
                                                  if a + keyup < len(x) / SR},
            "slope_0p5_1p2s_db_per_s": slope(0.5, 1.2),
            "slope_1p3_1p45s_db_per_s": slope(1.3, 1.45),
            "slope_1p3_2p2s_db_per_s": slope(1.3, 2.2),
        }
    bb = (x ** 2).sum(axis=1)
    fr = SR // 100
    n = len(bb) // fr
    env = 10 * np.log10(bb[: n * fr].reshape(n, fr).mean(axis=1) + 1e-30)
    env -= env.max()
    t = np.arange(n) / 100 - keyup
    out["broadband_db_re_peak"] = {f"{a:g}": round(float(env[np.argmin(np.abs(t - a))]), 1)
                                   for a in (0.5, 1.0, 1.25, 1.3, 1.35, 1.4, 1.45, 1.6, 1.8, 2.0, 2.2)
                                   if a + keyup < len(x) / SR}
    sel = np.nonzero((t > 0.2) & (env > -70))[0]
    steps = env[sel[1:]] - env[sel[1:] - 1]
    out["largest_10ms_drop_after_keyup_above_-70dB"] = round(float(-steps.min()), 1)
    out["before_fix_qa_round2"] = "broadband -49.5 dB at 1.30 s -> -64.6 dB at 1.40 s; 63 Hz band -20.8 dB/s then " \
        "-142.6 dB/s from 1.3 s; 125 Hz -22.0 then -141.6 dB/s (qa/round2/results/tail_truncation.json)"
    save("tail_truncation", out)


def layer_bounds(key: int) -> list[int]:
    """Lower velocity bound of each layer's own (timbre) range, from the calibration JSON."""
    sys.path.insert(0, str(PIANO))
    from piano_paths import CALIBRATION_JSON
    cal = json.loads(CALIBRATION_JSON.read_text())
    roots = {"A": 9, "C": 0, "D#": 3, "F#": 6}
    for root, lay in cal["velocity_layers"]["layout"].items():
        k = 12 * (int(root[-1]) + 1) + roots[root[:-1]]
        if k - 1 <= key <= k + 1:
            return sorted(v[0] for v in lay.values()), lay
    raise KeyError(key)


def velsweep() -> None:
    """C2, C4, C6 struck at velocity 1, 3, ... 127 (the round-2 probe): level and HF ratio
    (energy above 2 kHz) of the first 300 ms, largest steps, steps at the layer bounds."""
    import an_velsweep as av
    from lib2 import midi_notes
    render(P / "velsweep.mid", "velsweep", stems=True)
    res = {}
    for nm in ("c2", "c4", "c6"):
        m = read(P / f"velsweep_stems/{nm}.wav").mean(axis=1)
        notes = [n for n in midi_notes(P / "velsweep.mid") if n["name"] == nm]
        key = notes[0]["key"]
        rows = []
        for n in notes:
            t = n["start"] + 0.3
            a, b = int(t * SR), int((t + 0.3) * SR)
            c, hf = av.spec_stats(m, t, t + 0.3)
            rows.append((n["vel"], 10 * np.log10(np.mean(m[a:b] ** 2) + 1e-30), hf, c))
        vel = np.array([r[0] for r in rows])
        lv = np.array([r[1] for r in rows])
        hf = np.array([r[2] for r in rows])
        bounds, lay = layer_bounds(key)
        dl, dh = np.diff(lv), np.diff(hf)
        at_b = [i for i in range(len(vel) - 1) if any(vel[i] < bb <= vel[i + 1] for bb in bounds[1:])]
        res[nm] = {
            "key": int(key), "layer_lo": bounds, "crossfade_widths": {k: v[2] for k, v in lay.items()},
            "level_span_db": round(float(lv.max() - lv.min()), 1),
            "level_non_monotonic_steps": [(int(vel[i]), int(vel[i + 1]), round(float(dl[i]), 2)) for i in range(len(dl)) if dl[i] < -0.3],
            "max_level_step_db": round(float(dl.max()), 2),
            "corr_level_vs_velocity": round(float(np.corrcoef(vel, lv)[0, 1]), 4),
            "max_hf_step_db_per_2_velocities": round(float(np.abs(dh).max()), 2),
            "max_hf_step_at": [int(vel[int(np.argmax(np.abs(dh)))]), int(vel[int(np.argmax(np.abs(dh))) + 1])],
            "hf_steps_over_3db": [(int(vel[i + 1]), round(float(dh[i]), 2), round(float(dl[i]), 2)) for i in range(len(dh)) if abs(dh[i]) > 3],
            "hf_step_at_layer_bounds_db": [(int(vel[i + 1]), round(float(dh[i]), 2)) for i in at_b],
            "hf_span_db": round(float(hf.max() - hf.min()), 1),
            "rows_vel_level_hf_centroid": [(int(r[0]), round(float(r[1]), 2), round(float(r[2]), 2), round(float(r[3]), 1)) for r in rows],
        }
    res["before_fix_qa_round2"] = ("C2 HF +7.2 dB at v35 and +7.3 dB at v37 (level +1.1/+0.8 dB); C4 +5.0/+4.9 dB; C6 +5.0 dB "
                                   "at v51 and +4.8 dB at v65 (qa/round2/results/velsweep.json)")
    save("velsweep", res)


def hf_env_db(m: np.ndarray, lo: float = 4000.0, hi: float = 16000.0) -> np.ndarray:
    """Energy of the lo-hi band in 1 ms frames, 3 ms smoothing, dB."""
    y = ss.sosfilt(ss.butter(4, [lo, hi], "band", fs=SR, output="sos"), m)
    fr = SR // 1000
    n = len(y) // fr
    e = (y[: n * fr] ** 2).reshape(n, fr).mean(axis=1)
    return 10 * np.log10(np.convolve(e, np.ones(3) / 3, mode="same") + 1e-30)


def hammer_only(sfz_text: str, dst: Path) -> Path:
    """An SFZ holding only the hammer-noise release group of a derived SFZ."""
    sys.path.insert(0, str(PIANO))
    from piano_paths import SALAMANDER_DIR
    lines = sfz_text.splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("//HammerNoise"))
    j = next((k for k in range(i + 1, len(lines)) if lines[k].startswith("//pedalAction")), len(lines))
    # rt_dead=1: sfizz plays a trigger=release region only while an attack voice of its key
    # sounds, and this file has none (release_key regions play regardless)
    body = [l.replace("trigger=release ", "trigger=release rt_dead=1 ") for l in lines[i:j]]
    dst.write_text(f"<control> default_path={SALAMANDER_DIR}/\n" + "\n".join(body) + "\n")
    return dst


def sfizz(sfz: Path, mid: Path, wav: Path) -> np.ndarray:
    sys.path.insert(0, str(PIANO))
    from piano_paths import SFIZZ_RENDER
    subprocess.run([str(SFIZZ_RENDER), "--sfz", str(sfz), "--midi", str(mid), "--wav", str(wav), "-s", str(SR),
                    "-q", "10", "-p", "512", "-b", "256"], check=True, capture_output=True)
    return read(wav)


def events_after(x: np.ndarray, times: list[float], win: float = 0.45) -> list[dict]:
    """For each time: onset (first 1 ms frame within 20 dB of the event's loudest frame) and
    loudest frame of the signal x in [t, t + win], in ms after t."""
    fr = SR // 1000
    n = len(x) // fr
    e = 10 * np.log10((x[: n * fr] ** 2).sum(axis=1).reshape(n, fr).mean(axis=1) + 1e-30)
    out = []
    for t in times:
        a = int(t * 1000)
        seg = e[a: a + int(win * 1000)]
        if not len(seg) or seg.max() < -150:
            out.append({"t": round(t, 3), "event": False})
            continue
        pk = int(np.argmax(seg))
        on = int(np.argmax(seg > seg[pk] - 20))
        out.append({"t": round(t, 3), "onset_ms": on, "peak_ms": pk, "peak_dbfs": round(float(seg[pk]), 1)})
    return out


def release() -> None:
    """Hammer-noise release samples (rel*): delay from key-up to the noise.

    Only the hammer-noise group of the derived SFZ is rendered (sfizz_render, the render's own
    stem MIDI), so the signal is the release noise alone: its onset (first 1 ms within 20 dB of
    its loudest) and its loudest 1 ms after each key-up, for the SFZ before the fix (saved copy)
    and after. iso probe: A0..E6 (damped keys), velocity 80, 1 s held. pedal_rel probe: three
    keys lifted under the pedal (pedal up at 3.0 s), then three without pedal."""
    sys.path.insert(0, str(PIANO))
    from piano_paths import DERIVED_SFZ
    from lib2 import midi_notes
    old = P / "old_Ricercar.sfz"  # copy of the derived SFZ taken before make_sfz.py was changed
    res = {}
    for probe in ("iso", "pedal_rel"):
        rep = render(P / f"{probe}.mid", probe, "--keep-temp", "--no-reverb", stems=True)
        stem_mid = Path(rep["temp"]) / "stem00.mid"
        ups = sorted({round(nt["end"] + 0.3, 4) for nt in midi_notes(P / f"{probe}.mid") if nt["key"] <= 88})
        for lab, src in (("before", old), ("after", DERIVED_SFZ)):
            if not src.exists():
                continue
            x = sfizz(hammer_only(src.read_text(), P / f"hammer_{lab}.sfz"), stem_mid, P / f"hammer_{probe}_{lab}.wav")
            ev = events_after(x, ups)
            if probe == "iso":
                on = np.array([e["onset_ms"] for e in ev if "onset_ms" in e])
                pk = np.array([e["peak_ms"] for e in ev if "onset_ms" in e])
                res[f"iso_{lab}"] = {"keyups": len(ups), "events": int(len(on)),
                                     "onset_after_keyup_ms": {"median": float(np.median(on)), "range": [int(on.min()), int(on.max())]},
                                     "loudest_after_keyup_ms": {"median": float(np.median(pk)), "range": [int(pk.min()), int(pk.max())]}}
            else:
                meta = json.loads((P / "pedal_rel.meta.json").read_text())
                pu = meta["pedal"][1] + 0.3
                res[f"pedal_rel_{lab}"] = {"keyups_under_pedal": ev[:3], "keyups_without_pedal": ev[3:],
                                           "at_pedal_up": events_after(x, [pu], 0.3)[0]}
        import shutil
        shutil.rmtree(rep["temp"], ignore_errors=True)
    # clicks: the full iso stem (onsets protected) near key-ups, and the noise alone at its start
    from lib2 import click_scan
    iso_notes = midi_notes(P / "iso.mid")
    ups = np.array([nt["end"] + 0.3 for nt in iso_notes])
    full = click_scan(read(P / "iso_stems/iso.wav"), protect=[nt["start"] + 0.3 for nt in iso_notes], k=12.0)
    alone = click_scan(read(P / "hammer_iso_after.wav"), k=12.0)
    res["clicks"] = {"iso_stem_within_30ms_after_keyup": [c for c in full if np.min(np.abs(ups - c["t"])) < 0.03],
                     "iso_stem_elsewhere": len(full),
                     "hammer_noise_alone_within_3ms_of_its_start": len([c for c in alone if np.min(np.abs(ups - c["t"])) < 0.003])}
    res["note"] = ("QA round 2 measured the high-frequency event after key-up in the full mix at a median 110 ms "
                   "(75-190 ms); here the noise is rendered alone")
    save("release_timing", res)


def clarity(path: Path, midi: Path, transpose: dict) -> dict:
    """QA round 2's articulation measure (qa/round2/an_demo_clarity.py) on one final file: for
    each note, the rise of its own partials (not shared with the previous notes of its voice)
    from the 150 ms before its onset to the 150 ms after."""
    from lib2 import band_power, db, midi_hz, midi_notes
    byv = {}
    for nt in midi_notes(midi):
        byv.setdefault(nt["name"], []).append(nt)
    m = read(path).mean(axis=1)
    res = {}
    for v, lst in byv.items():
        r = []
        for i, nt in enumerate(lst):
            k = nt["key"] + transpose.get(v, 0)
            t = nt["start"] + 0.3
            prev = [q for q in lst[:i] if q["end"] > nt["start"] - 0.45]
            pp = [midi_hz(q["key"] + transpose.get(v, 0)) * h for q in prev for h in range(1, 21)]
            own = [x for x in (midi_hz(k) * h for h in range(1, 11)) if all(abs(x / y - 1) > 0.02 for y in pp)]
            if not own:
                continue
            r.append(float(db(band_power(m, t + 0.01, t + 0.16, own, rel_bw=0.006)) -
                           db(band_power(m, t - 0.16, t - 0.01, own, rel_bw=0.006))))
        r = np.array(r)
        res[v] = {"n": len(r), "median_db": round(float(np.median(r)), 1), "p10_db": round(float(np.percentile(r, 10)), 1),
                  "n_below_3db": int((r < 3).sum())}
    return res


def hall() -> None:
    """--wet-db is now the hall's energy re the dry piano on the piano's long-term spectrum.
    Demo (out/fugue_jp.mid, pedal -12): what the render report measures at the default, per-band
    hall-to-dry and C80 on the program (QA round 2's an_hall.program), and articulation in the
    final file without reverb, at the default and at the old default's level (hall +5.4 dB re
    dry: the old -4 on the white-noise scale). fast16 probe: 16th-note runs, the same three."""
    import an_hall
    import soundfile as sf
    sys.path.insert(0, str(PIANO))
    import render_piano as rp
    old_equiv = round(-4.0 + rp.hall_gain_on_piano_db(read(rp.HALL_IR)), 1)
    mid = PIANO / "out/fugue_jp.mid"
    tr = ("--transpose", "pedal=-12")
    reps = {"default": render(mid, "demo", *tr, stems=True),
            "no_reverb": render(mid, "demo_dry", *tr, "--no-reverb"),
            "old_default_level": render(mid, "demo_old", *tr, "--wet-db", str(old_equiv))}
    res = {"wet_db_default": reps["default"]["wet_db"], "old_default_equivalent_wet_db": old_equiv,
           "render_report_hall": {k: r["hall"] for k, r in reps.items()}}
    ir, _ = sf.read(rp.HALL_IR, always_2d=True)
    g = 10 ** ((reps["default"]["wet_db"] - reps["default"]["hall"]["ir_gain_on_piano_spectrum_db"]) / 20)
    res["demo_program_per_band_at_default"] = an_hall.program(P / "demo_stems", list(reps["default"]["voices"]), ir, g)
    res["demo_articulation_final_file"] = {k: clarity(P / f"{f}.wav", mid, {"pedal": -12})
                                           for k, f in (("no_reverb", "demo_dry"), ("default", "demo"),
                                                        ("old_default_level", "demo_old"))}
    an_hall.P = P
    render(P / "fast16.mid", "fast16")
    render(P / "fast16.mid", "fast16_dry", "--no-reverb")
    render(P / "fast16.mid", "fast16_old", "--wet-db", str(old_equiv))
    res["fast16_articulation_rise_db"] = {"no_reverb": an_hall.articulation(P / "fast16_dry.wav"),
                                          "default": an_hall.articulation(P / "fast16.wav"),
                                          "old_default_level": an_hall.articulation(P / "fast16_old.wav")}
    res["before_fix_qa_round2"] = ("default -4 (white-noise scale): hall +5.2 dB re dry, program C80 +2.1 dB, while the "
                                   "report said C80 8.4; articulation medians alto 25.4->22.1, tenor 18.3->15.4, pedal "
                                   "14.5->10.6 dB from no reverb to the default (qa/round2/results/hall.json, demo_clarity.json)")
    save("hall", res)


def demo() -> None:
    """The shipped demo (out/fugue_jp_piano.*): QA round 2's entry prominence (qa/round2/an_entries.py)
    on its stems, and how the file ends after the last key-up."""
    import an_entries
    import tempfile
    from lib2 import midi_notes
    d = Path(tempfile.mkdtemp(prefix="pianofix2_demo_"))
    (d / "demo.mid").symlink_to(PIANO / "out/fugue_jp.mid")
    (d / "demo_j4_stems").symlink_to(PIANO / "out/fugue_jp_piano_stems")
    an_entries.P = d
    got = {}
    an_entries.write_json = lambda path, obj: got.update(obj)
    an_entries.main()
    rep = json.loads((PIANO / "out/fugue_jp_piano.render.json").read_text())
    x = read(PIANO / "out/fugue_jp_piano.wav")
    last_up = max(nt["end"] for nt in midi_notes(PIANO / "out/fugue_jp.mid")) + 0.3
    fr = SR // 100
    n = len(x) // fr
    env = 10 * np.log10((x[: n * fr] ** 2).sum(axis=1).reshape(n, fr).mean(axis=1) + 1e-30)
    env -= env.max()
    i = int(last_up * 100)
    tail = env[i:]
    t = np.arange(len(tail)) / 100
    sel = (t > 0.3) & (tail > -70)
    from lib2 import click_scan
    notes = midi_notes(PIANO / "out/fugue_jp.mid")
    clicks = click_scan(x, protect=[nt["start"] + 0.3 for nt in notes], k=12.0)
    ups = np.array([nt["end"] + 0.3 for nt in notes])
    save("demo", {"clicks_away_from_onsets": clicks[:20], "clicks_within_30ms_after_a_keyup":
                  sum(1 for c in clicks if np.min(np.abs(ups - c["t"])) < 0.03),
                  "entries": got, "render": {k: rep[k] for k in ("duration_s", "hall", "normalise_gain_db", "measured",
                                                                 "stereo", "truncation_check", "warnings")},
                  "tail_after_last_keyup": {"file_ends_s_after_last_keyup": round(len(x) / SR - last_up, 2),
                                            "level_db_re_loudest_10ms": {f"{a:g}": round(float(tail[int(a * 100)]), 1)
                                                                         for a in (0.5, 1.0, 1.5, 2.0, 2.5) if a * 100 < len(tail)},
                                            "decay_db_per_s_above_-70": round(float(np.polyfit(t[sel], tail[sel], 1)[0]), 1) if sel.sum() > 10 else None}})


def main() -> None:
    P.mkdir(exist_ok=True)
    what = sys.argv[1:] or ["contract"]
    for w in what:
        globals()[w]()


if __name__ == "__main__":
    main()
