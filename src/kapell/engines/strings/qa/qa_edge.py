#!/usr/bin/env python3
"""Edge cases and articulation timing of render_quartet.py (tries to break it).

  python3 qa_edge.py

 slur_timing      two-note slurs (vn1, va, vc; 1 s notes, contiguous, CC1 88):
                  when does the new pitch overtake the old one, relative to the
                  second note-on?  (pitch-specific harmonic energy, 5 ms steps)
 cc21_order       sfizz alone: note A (CC21 = 11 -> 0.12 s) slurred into B; B's own
                  CC21 is sent at B's note-on, i.e. before A's note-off.  A's decay
                  after its note-off with B's CC21 = 11 / 58 / 127.
 cc21_chain       the same through render_quartet: a slur into a final note before a
                  rest (the final note gets a 0.5-1.1 s release); A's decay.
 cc20_input       a MIDI that carries CC20 (documented as optional input)
 names            tracks "Violin II", "Violin I", "Viola", "Cello" in that order; and
                  a lone "Violin II"
 map_malformed    --map "soprano:vn1"
 six_voices       perform.py-style names soprano alto tenor bass pedal + a 6th
 hanging          a note-on without note-off
 out_of_range     a soprano note at key 40 and one at 104 while every voice plays
 bend             pitch bend +8191 on a held note (bend_up = 200 cents)
 short_notes      10 ms and 40 ms notes (audible?)
 long_note        22 s notes (loop region) on vn1 / va / vc: level jumps, HF spikes
 fermata_cc_gaps  perform.py MIDI of the QA fugue: CC1 events more than 0.6 s apart
                  with a value change (render_quartet then holds and jumps in 60 ms)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import QA, QUARTET, SR, STRINGS, TMP, db, env_db, hz, load, midi_cc, pitch_spectral, render, save, state  # noqa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iowa_common import SFIZZ_RENDER  # noqa: E402

D = TMP / "edge"


def write_midi(path, tracks, tempo=500000, tpb=960):
    """tracks: list of (name, channel, program|None, [(sec, order, msg)])"""
    mf = mido.MidiFile(type=1, ticks_per_beat=tpb)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage("set_tempo", tempo=tempo))
    mf.tracks.append(t0)
    tps = tpb * 1e6 / tempo
    for name, ch, prog, ev in tracks:
        tr = mido.MidiTrack()
        if name is not None:
            tr.append(mido.MetaMessage("track_name", name=name))
        if prog is not None:
            tr.append(mido.Message("program_change", channel=ch, program=prog))
        ev = sorted(ev, key=lambda e: (e[0], e[1]))
        last = 0
        for s, _, m in ev:
            tk = int(round(s * tps))
            tr.append(m.copy(channel=ch, time=tk - last))
            last = tk
        mf.tracks.append(tr)
    mf.save(str(path))
    return path


def N(t, d, k, v=80):
    return [(t, 2, mido.Message("note_on", note=k, velocity=v)), (t + d, 1, mido.Message("note_off", note=k, velocity=0))]


def CC(t, c, v):
    return [(t, 0, mido.Message("control_change", control=c, value=v))]


def run(args):
    r = subprocess.run([sys.executable, str(STRINGS / "render_quartet.py"), *map(str, args)], capture_output=True,
                       text=True)
    return r.returncode, r.stdout[-2500:], r.stderr[-2500:]


def harm_energy(x, t, k, W):
    seg = x[int(t * SR) - W // 2: int(t * SR) + W // 2]
    n = len(seg)
    X = np.abs(np.fft.rfft(seg * np.hanning(n), 1 << 15)) ** 2
    df = SR / (1 << 15)
    e = 0.0
    for h in range(1, 5):
        f = h * hz(k)
        i0, i1 = int(f * 2 ** (-0.4 / 12) / df), int(f * 2 ** (0.4 / 12) / df) + 1
        e += X[i0:i1].sum()
    return 10 * np.log10(e + 1e-30)


def decay(x, k, t_off, W):
    """time after t_off at which note k's harmonic energy is 20 / 40 dB below its level at t_off - 50 ms"""
    ref = harm_energy(x, t_off - 0.05, k, W)
    t20 = t40 = None
    for t in np.arange(t_off, t_off + 2.5, 0.005):
        e = harm_energy(x, t, k, W)
        if t20 is None and e < ref - 20:
            t20 = t - t_off
        if e < ref - 40:
            t40 = t - t_off
            break
    return (None if t20 is None else round(1000 * t20, 1)), (None if t40 is None else round(1000 * t40, 1))


# ------------------------------------------------------------------ tests
def slur_timing(res):
    out = {}
    for name, k1, k2 in (("Violin I", 69, 71), ("Viola", 60, 62), ("Cello", 48, 50)):
        tag = {"Violin I": "vn1", "Viola": "va", "Cello": "vc"}[name]
        ev = CC(0, 1, 88) + CC(0, 11, 88) + N(1.0, 1.0, k1) + N(2.0, 1.0, k2)
        p = write_midi(D / f"slur_{tag}.mid", [(name, 0, None, ev)])
        rep = render(p, D / f"slur_{tag}", "--keep-start", "--hall", "none")
        x = load(D / f"slur_{tag}_stem_{tag}.wav")
        W = int(max(0.04 * SR, 4 * SR / hz(k1)))
        ts = np.arange(1.8, 2.3, 0.005)
        a = np.array([harm_energy(x, t, k1, W) for t in ts])
        b = np.array([harm_energy(x, t, k2, W) for t in ts])
        cross = ts[np.flatnonzero(b > a)[0]] if (b > a).any() else None
        bref = float(np.median([harm_energy(x, t, k2, W) for t in np.arange(2.4, 2.8, 0.05)]))
        b6 = ts[np.flatnonzero(b > bref - 6)[0]] if (b > bref - 6).any() else None
        tot = np.array([10 * np.log10(np.mean(x[int((t - 0.01) * SR): int((t + 0.01) * SR)] ** 2) + 1e-20) for t in ts])
        arts = rep["jobs"][0]["note_list"]
        out[tag] = dict(second_note_art=arts[1][4], first_note_rendered_off=arts[0][1],
                        crossover_ms_after_note_on=None if cross is None else round(1000 * (cross - 2.0), 1),
                        new_note_within_6db_ms=None if b6 is None else round(1000 * (b6 - 2.0), 1),
                        level_dip_db=round(float(np.median(tot[:20]) - tot.min()), 1))
    res["slur_timing"] = out
    print("slur_timing", out)


def cc21_order(res):
    out = {}
    for x_cc in (11, 58, 127):
        mf = mido.MidiFile(type=0, ticks_per_beat=960)
        tr = mido.MidiTrack()
        mf.tracks.append(tr)
        tr.append(mido.MetaMessage("set_tempo", tempo=500000))
        ev = [(0.4, mido.Message("control_change", control=1, value=88)),
              (0.45, mido.Message("control_change", control=20, value=0)),
              (0.45, mido.Message("control_change", control=21, value=11)),
              (0.5, mido.Message("note_on", note=69, velocity=90)),
              (1.5, mido.Message("control_change", control=20, value=80)),
              (1.5, mido.Message("control_change", control=21, value=x_cc)),
              (1.5, mido.Message("note_on", note=72, velocity=90)),
              (1.57, mido.Message("note_off", note=69, velocity=0)),
              (3.5, mido.Message("note_off", note=72, velocity=0))]
        last = 0
        for t, m in ev:
            tk = int(round(t * 1920))
            tr.append(m.copy(time=tk - last))
            last = tk
        mp, wav = D / f"cc21_{x_cc}.mid", D / f"cc21_{x_cc}.wav"
        mf.save(str(mp))
        subprocess.run([str(SFIZZ_RENDER), "--sfz", str(QUARTET / "violin.sfz"), "--midi", str(mp), "--wav", str(wav),
                        "-s", str(SR)], check=True, capture_output=True)
        x = load(wav)
        t20, t40 = decay(x, 69, 1.57, int(0.04 * SR))
        out[f"B_cc21={x_cc}"] = dict(A_minus20_ms=t20, A_minus40_ms=t40,
                                     B_release_s=round(0.03 + 1.2 * x_cc / 127, 3))
    res["cc21_order"] = out
    print("cc21_order", out)


def cc21_chain(res):
    # slur A (1 s) -> B (0.6 s) then a rest: B is the last note before a rest (release 0.5-1.1 s)
    out = {}
    for label, notes in (("slur_into_final", [(1.0, 1.0, 69), (2.0, 0.6, 72)]),
                         ("slur_into_slur", [(1.0, 1.0, 69), (2.0, 0.6, 72), (2.6, 0.6, 74)])):
        ev = CC(0, 1, 88) + CC(0, 11, 88)
        for t, d, k in notes:
            ev += N(t, d, k)
        p = write_midi(D / f"chain_{label}.mid", [("Violin I", 0, None, ev)])
        rep = render(p, D / f"chain_{label}", "--keep-start", "--hall", "none", keep_temp=True)
        tmp = Path(rep["temp"])
        x = load(tmp / "j0_vn1.wav")
        jm = mido.MidiFile(str(tmp / "j0_vn1.mid"))
        t = 0.0
        seq = []
        for m in jm:
            t += m.time
            if m.type in ("note_on", "note_off", "control_change") and (m.type != "control_change" or m.control == 21):
                seq.append((round(t, 3), m.type, getattr(m, "note", None), getattr(m, "value", None)))
        a_off = next(s[0] for s in seq if s[1] == "note_off" and s[2] == 69)
        t20, t40 = decay(x, 69, a_off, int(0.04 * SR))
        out[label] = dict(job_midi_events=seq, A_note_off_s=a_off, A_minus20_ms=t20, A_minus40_ms=t40)
        subprocess.run(["rm", "-rf", str(tmp)])
    res["cc21_chain"] = out
    print("cc21_chain", {k: {kk: v[kk] for kk in v if kk != "job_midi_events"} for k, v in out.items()})


def cc20_input(res):
    ev = CC(0, 1, 88) + CC(0.9, 20, 80) + N(1.0, 0.5, 69) + CC(1.45, 20, 112) + N(1.5, 0.2, 71) + N(1.7, 0.5, 72)
    p = write_midi(D / "cc20.mid", [("Violin I", 0, None, ev)])
    rc, so, se = run([p, "-o", D / "cc20", "--hall", "none"])
    ev2 = CC(0, 1, 88) + CC(0.9, 21, 100) + N(1.0, 0.5, 69) + N(1.6, 0.5, 71)
    p2 = write_midi(D / "cc21.mid", [("Violin I", 0, None, ev2)])
    rc2, so2, se2 = run([p2, "-o", D / "cc21", "--hall", "none"])
    res["cc20_input"] = dict(returncode=rc, stderr_tail=se[-600:], cc21_only_returncode=rc2,
                             cc21_stderr_tail=se2[-300:])
    print("cc20_input", rc, se[-300:], "| cc21 only:", rc2)


def names(res):
    out = {}
    base = [N(0.5, 1.0, 76), N(0.5, 1.0, 69), N(0.5, 1.0, 60), N(0.5, 1.0, 48)]
    for label, order in (("vn2_first", ["Violin II", "Violin I", "Viola", "Cello"]),
                         ("lone_violin_ii", ["Violin II"])):
        tr = []
        for i, nm in enumerate(order):
            k = {"Violin I": 76, "Violin II": 69, "Viola": 60, "Cello": 48}[nm]
            tr.append((nm, i, None, CC(0, 1, 88) + N(0.5, 1.0, k)))
        p = write_midi(D / f"names_{label}.mid", tr)
        rep = render(p, D / f"names_{label}", "--hall", "none")
        out[label] = {j["label"]: j["inst"] for j in rep["jobs"]}
    res["names"] = out
    print("names", out)
    del base


def map_malformed(res):
    ev = CC(0, 1, 88) + N(0.5, 1.0, 69)
    p = write_midi(D / "map.mid", [("soprano", 0, None, ev)])
    rc, so, se = run([p, "-o", D / "map", "--map", "soprano:vn1", "--hall", "none"])
    rc2, so2, se2 = run([p, "-o", D / "map2", "--map", "soprano=viola", "--hall", "none"])
    res["map_malformed"] = dict(colon_returncode=rc, colon_stderr=se[-300:], bad_inst_returncode=rc2,
                                bad_inst_stderr=se2[-200:])
    print("map_malformed", rc, se[-200:], "|", rc2, se2[-150:])


def six_voices(res):
    nm = ["soprano", "alto", "tenor", "bass", "pedal", "extra"]
    keys = [79, 72, 64, 52, 40, 60]
    tr = [(n, i, [40, 40, 41, 42, 43, 42][i], CC(0, 1, 88) + N(0.5, 1.5, k)) for i, (n, k) in enumerate(zip(nm, keys))]
    p = write_midi(D / "six.mid", tr)
    rep = render(p, D / "six", "--hall", "none")
    res["six_voices"] = dict(mapping={j["label"]: j["inst"] for j in rep["jobs"]}, notes=rep["notes"])
    print("six_voices", res["six_voices"])


def hanging(res):
    ev = CC(0, 1, 88) + N(0.5, 0.5, 69) + [(1.2, 2, mido.Message("note_on", note=72, velocity=80))]
    p = write_midi(D / "hanging.mid", [("Violin I", 0, None, ev)])
    rep = render(p, D / "hanging", "--hall", "none")
    res["hanging"] = dict(notes_rendered=rep["jobs"][0]["notes"], log=rep["notes"],
                          duration_s=round(rep["duration_s"], 2))
    print("hanging", res["hanging"])


def out_of_range(res):
    tr = [("soprano", 0, None, CC(0, 1, 88) + N(0.5, 1.0, 40) + N(2.0, 1.0, 104)),
          ("alto", 1, None, CC(0, 1, 88) + N(0.5, 2.5, 60)),
          ("tenor", 2, None, CC(0, 1, 88) + N(0.5, 2.5, 52)),
          ("bass", 3, None, CC(0, 1, 88) + N(0.5, 2.5, 40))]
    p = write_midi(D / "range.mid", tr)
    rep = render(p, D / "range", "--hall", "none")
    sop = next(j for j in rep["jobs"] if j["label"] == "soprano")
    res["out_of_range"] = dict(soprano_rendered_keys=[n[2] for n in sop["note_list"]], log=rep["notes"],
                               stdout=rep["stdout"][-600:])
    print("out_of_range", res["out_of_range"]["soprano_rendered_keys"], rep["notes"])


def bend(res):
    ev = CC(0, 1, 88) + N(0.5, 3.0, 69) + [(2.0, 0, mido.Message("pitchwheel", pitch=8191))]
    p = write_midi(D / "bend.mid", [("Violin I", 0, None, ev)])
    rep = render(p, D / "bend", "--keep-start", "--hall", "none")
    x = load(D / "bend_stem_vn1.wav")
    m1, _ = pitch_spectral(x[int(1.0 * SR): int(1.9 * SR)], 69, span=3)
    m2, _ = pitch_spectral(x[int(2.3 * SR): int(3.3 * SR)], 71, span=3)
    res["bend"] = dict(before_cents_re_69=round(100 * (m1 - 69), 1), after_cents_re_69=round(100 * (m2 - 69), 1))
    print("bend", res["bend"])


def short_notes(res):
    ev = CC(0, 1, 88) + N(0.5, 0.01, 69) + N(1.5, 0.04, 69) + N(2.5, 0.1, 69) + N(3.5, 0.5, 69)
    p = write_midi(D / "short.mid", [("Violin I", 0, None, ev)])
    rep = render(p, D / "short", "--keep-start", "--hall", "none")
    x = load(D / "short_stem_vn1.wav")
    lv = {}
    for t, d in ((0.5, 0.01), (1.5, 0.04), (2.5, 0.1), (3.5, 0.5)):
        seg = x[int(t * SR): int((t + 0.3) * SR)]
        e, _ = env_db(seg, 0.01, 0.002)
        lv[f"{int(d * 1000)}ms"] = round(float(e.max()), 1)
    res["short_notes"] = dict(peak_level_db=lv, rendered=[n[:3] for n in rep["jobs"][0]["note_list"]])
    print("short_notes", res["short_notes"])


def long_note(res):
    out = {}
    for name, k in (("Violin I", 69), ("Viola", 60), ("Cello", 48)):
        tag = {"Violin I": "vn1", "Viola": "va", "Cello": "vc"}[name]
        ev = CC(0, 1, 75) + CC(0, 11, 100) + N(0.5, 22.0, k)
        p = write_midi(D / f"long_{tag}.mid", [(name, 0, None, ev)])
        render(p, D / f"long_{tag}", "--keep-start", "--hall", "none")
        x = load(D / f"long_{tag}_stem_{tag}.wav")
        seg = x[int(1.5 * SR): int(22.0 * SR)]
        hop = int(0.05 * SR)
        n = len(seg) // hop
        lv = 10 * np.log10(np.mean(seg[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20)
        d = np.diff(lv)
        # HF (>6 kHz) 1 ms spikes vs the 50 ms median around them
        from scipy.signal import butter, sosfilt
        from scipy.ndimage import median_filter
        h = sosfilt(butter(4, 6000, "highpass", fs=SR, output="sos"), seg)
        m = len(h) // 48
        e = 10 * np.log10(np.mean(h[: m * 48].reshape(m, 48) ** 2, axis=1) + 1e-20)
        med = median_filter(e, size=51, mode="nearest")
        spikes = np.flatnonzero(e > med + 12)
        out[tag] = dict(level_std_db=round(float(lv.std()), 2), p2p_db=round(float(lv.max() - lv.min()), 2),
                        max_50ms_jump_db=round(float(np.abs(d).max()), 2),
                        jump_times_s=[round(1.5 + float(i) * 0.05, 2) for i in np.argsort(-np.abs(d))[:4]],
                        hf_spikes_over_12db=len(spikes),
                        spike_times_s=[round(1.5 + float(i) / 1000, 3) for i in spikes[:6]],
                        level_first_vs_last_5s_db=round(float(lv[: 100].mean() - lv[-100:].mean()), 2))
    res["long_note"] = out
    print("long_note", out)


def fermata_cc_gaps(res):
    cc = midi_cc(TMP / "fugue_qa.mid")
    gaps = []
    for ch, d in cc.items():
        ev = d.get(1, [])
        for (t0, v0), (t1, v1) in zip(ev, ev[1:]):
            if t1 - t0 > 0.6 and v1 != v0:
                gaps.append(dict(channel=ch, t0=round(t0, 2), t1=round(t1, 2), v0=v0, v1=v1))
    res["fermata_cc_gaps"] = gaps
    print("fermata_cc_gaps", gaps)


def main():
    D.mkdir(parents=True, exist_ok=True)
    res = dict(state=state())
    only = sys.argv[1:]
    for f in (slur_timing, cc21_order, cc21_chain, cc20_input, names, map_malformed, six_voices, hanging,
              out_of_range, bend, short_notes, long_note, fermata_cc_gaps):
        if only and f.__name__ not in only:
            continue
        try:
            f(res)
        except Exception as e:                      # a crash of the harness is itself a finding to look at
            res[f.__name__] = dict(harness_error=repr(e)[:800])
            print(f.__name__, "HARNESS ERROR", repr(e)[:800])
    p = save("edge.json" if not only else f"edge_{'_'.join(only)}.json", res)
    print("->", p)


if __name__ == "__main__":
    main()
