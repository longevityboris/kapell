#!/usr/bin/env python3
"""Measure an organ render against its MIDI: pitch and onset per note, dropped and stuck notes,
clicks, registration contrast (level and spectrum per section), voice balance.

usage: python3 qa/qa_organ.py IN.mid REPORT.json STEMS_DIR MIX.wav [-o QA.json]

REPORT.json is render_organ.py's --json report (lead-in, registration timeline, divisions);
STEMS_DIR its --stems output. Everything is measured on the audio files:

* pitch: per note on its voice's dry stem, the harmonic comb (analyze_organ.py) of multiples of
  f (the key's equal-tempered frequency; a 16' stop's even harmonics fall on it too), within
  +-60 cents, on the later part of the note (from max(120 ms, 45% of the note) after the onset to
  30 ms before the end, at most 1 s), where the previous note's release has decayed; only when
  that window holds at least 12 periods of f and 0.12 s. Notes whose key another voice already
  holds on the same division (shared pipes, heard in that voice's stem) are skipped. Error in
  cents from A440 equal temperament. Every note off by more than 5 cents is measured again on
  its own pipes rendered alone (same stops, key and duration), and on a 2.5 s note of those pipes.
* presence (dropped notes): the comb's peak over the median comb value on that segment, and the
  energy at the note's harmonics against the stem's energy just before the onset.
* onset: the time at which the energy in the note's harmonic bands (1st-3rd harmonic, +-35 cents;
  STFT 2048 samples, 4096 below C3, hop 64, energy read at the window centre, which is unbiased
  for a step) reaches 50% of its level 200-350 ms after the MIDI onset: "speech" time of the
  pipes (first sound is sample-accurate at the MIDI onset by construction).
* stuck notes: (a) every stem 2.5 s into each rest of its voice longer than 3 s, and 3 s after its
  last note-off, must be 50 dB below the stem's peak; (b) after each note-off, the note's
  harmonics (1-4, and f/2 with a 16' stop) that no other note of the voice shares during the next
  1.2 s (4 FFT bins apart at least) and that are within 15 dB of the note's strongest partial:
  their level 1.0 s after key-up re just before it. A stuck pipe stays near 0 dB; a note
  is flagged if it has not fallen by 6 dB (the recorded releases carry the Norrfjärden church,
  release T20 up to 3 s in the pedal, so 1 s after key-up is -20 to -60 dB).
* clicks: second difference of each dry stem over its running median (10 ms windows, 21-window
  median); candidates > 12x are classed as at a note boundary (45 ms before to 15 ms after a
  note-on, as keys are anticipated by up to 40 ms, or within 20 ms of a note-off) or not.
* registration contrast: for each registration segment (between changes), the mix's RMS level
  and spectral centroid while music sounds.
* whole-system decay (organ samples with their own church + the added church): at every cut-off
  (all keys up, nothing for 1 s), the mix's energy after the cut-off relative to the steady level
  before it is the Schroeder integral of the system's response, so C80 = 10 log10((1 - d80) / d80)
  with d80 the energy remaining 80 ms after the cut-off, and T20 from its -5..-25 dB slope;
  broadband and in the 1 kHz octave. (The render report's C80 counts only the added church.)
* balance: each voice's stem level while it sounds (K-weighted as in BS.1770, so a 16' octave
  counts as the ear hears it), per registration segment.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss
import soundfile as sf

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from analyze_organ import harmonic_comb  # noqa: E402
from render_organ import load_midi  # noqa: E402


def f_et(k):
    return 440.0 * 2 ** ((k - 69) / 12)


def kweight(x, sr):
    """BS.1770 K-weighting (shelf + high-pass), coefficients for 48 kHz."""
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
    return ss.lfilter(b2, a2, ss.lfilter(b1, a1, x))


def has16(rep, voice_div_tl, t):
    """True if the division the voice is on at time t has a 16' stop drawn."""
    div = voice_div_tl[0][1]
    for tt, d in voice_div_tl:
        if tt <= t:
            div = d
    regs = rep['registration'][div]
    cur = regs[0]['stops']
    for c in regs:
        if c['t'] <= t + 0.03:
            cur = c['stops']
    return any("16'" in s_ for s_ in cur), div


def band_env(x, sr, freqs, hop, n=4096):
    """energy in narrow bands (+-35 cents) around freqs, per hop, via STFT."""
    f, t, Z = ss.stft(x, sr, nperseg=n, noverlap=n - hop, boundary=None, padded=False)
    P = np.abs(Z) ** 2
    m = np.zeros(len(f), bool)
    for fr in freqs:
        half = max(fr * (2 ** (35 / 1200) - 1), sr / n)       # +-35 cents, at least one bin
        m |= np.abs(f - fr) <= half
    return t, P[m].sum(axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('midi')
    ap.add_argument('report')
    ap.add_argument('stems')
    ap.add_argument('mix')
    ap.add_argument('-o')
    a = ap.parse_args()
    rep = json.load(open(a.report))
    lead = rep['lead_in_s']
    voices, tmap, _ = load_midi(a.midi, lambda m: None)
    out = {'pitch': {}, 'onset': {}, 'presence': {}, 'stuck': {}, 'clicks': {}, 'balance': {}}
    all_err, all_on, weak, outliers = [], [], [], []
    shared_skipped = 0

    def shared(v, n, div):
        for w, dw in voices.items():
            if w == v:
                continue
            for o in dw['notes']:
                # the renderer's rule: one set of pipes while both hold the key, unless the first
                # voice lets go within 50 ms (a hand-over, re-struck)
                if (o['key'] == n['key'] and o['on'] <= n['on'] + 1e-6 and o['off'] > n['on'] + 1e-6
                        and not (o['off'] - n['on'] < 0.05 and n['on'] - o['on'] > 0.05)):
                    if has16(rep, rep['voices'][w]['divisions'], o['on'])[1] == div:
                        return True
        return False
    stems = {}
    for v, d in voices.items():
        x, sr = sf.read(str(Path(a.stems) / f'{v}.wav'), dtype='float64')
        m = x.mean(axis=1)
        stems[v] = m
        errs, ons = [], []
        notes = d['notes']
        for i, n in enumerate(notes):
            on, off = n['on'] + lead, n['off'] + lead
            f = f_et(n['key'])
            # pitch + presence
            h16, _div = has16(rep, rep['voices'][v]['divisions'], n['on'])
            if shared(v, n, _div):
                shared_skipped += 1
                continue
            s0 = int((on + max(0.12, 0.45 * (off - on))) * sr)
            s1 = int(min(off - 0.03, s0 / sr + 1.0) * sr)
            if (s1 - s0) / sr >= max(0.12, 12.0 / f):
                seg = x[s0:s1]
                f8, peak = harmonic_comb(seg, sr, f, span_cents=60, base_ratio=1.0)
                e = 1200 * math.log2(f8 / f)
                errs.append(e)
                if abs(e) > 5:
                    outliers.append({'voice': v, 't_s': round(n['on'], 2), 'key': n['key'],
                                     'dur_s': round(off - on, 2), 'cents': round(e, 1), 'comb_peak': round(peak, 2),
                                     'division': _div, 'h16': h16})
                if peak < 1.5:
                    weak.append({'voice': v, 'bar_s': round(n['on'], 2), 'key': n['key'], 'comb_peak': round(peak, 2)})
            # onset
            nfft = 4096 if n['key'] < 48 else 2048
            w0 = int((on - 0.15) * sr) - nfft // 2
            w1 = int((on + 0.4) * sr) + nfft // 2
            if w0 > 0 and off - on >= 0.4:
                t_, env = band_env(m[w0:w1], sr, [f, 2 * f, 3 * f], 64, n=nfft)
                t_ = t_ - (on - w0 / sr)                      # time re the MIDI onset (window centre)
                ref_i = (t_ >= 0.2) & (t_ <= 0.35)
                pre_i = (t_ >= -0.12) & (t_ <= -0.06)
                if ref_i.any() and pre_i.any():
                    ref = env[ref_i].mean()
                    base = env[pre_i].mean()
                    if ref > 4 * base:                        # the note stands out from what precedes it
                        i10 = np.nonzero((env >= base + 0.1 * (ref - base)) & (t_ >= -0.08))[0]
                        i50 = np.nonzero((env >= base + 0.5 * (ref - base)) & (t_ >= -0.08))[0]
                        if len(i10) and len(i50):
                            ons.append((float(t_[i10[0]]) * 1000, float(t_[i50[0]]) * 1000, _div))
        out['pitch'][v] = {'notes_measured': len(errs), 'median_cents': round(float(np.median(errs)), 2),
                           'p95_abs_cents': round(float(np.percentile(np.abs(errs), 95)), 2),
                           'max_abs_cents': round(float(np.max(np.abs(errs))), 2),
                           'over_5c': int(np.sum(np.abs(errs) > 5))}
        o10 = np.array([o[0] for o in ons]) if ons else np.zeros(1)
        o50 = np.array([o[1] for o in ons]) if ons else np.zeros(1)
        out['onset'][v] = {'notes_measured': len(ons),
                           'energy10_median_ms': round(float(np.median(o10)), 1),
                           'energy10_p95_abs_ms': round(float(np.percentile(np.abs(o10), 95)), 1),
                           'energy50_median_ms': round(float(np.median(o50)), 1),
                           'energy50_p95_abs_ms': round(float(np.percentile(np.abs(o50), 95)), 1)}
        all_err += errs
        all_on += ons
        # stuck (a): silence well into rests and after the last note
        pk = np.abs(m).max()
        spans = sorted((n['on'] + lead, n['off'] + lead) for n in notes)
        gaps, end_ = [], spans[0][1]
        for a_, b_ in spans[1:]:
            if a_ - end_ > 3.0:
                gaps.append((end_ + 2.5, a_ - 0.05))
            end_ = max(end_, b_)
        gaps.append((end_ + 3.0, len(m) / sr))
        worst = -200.0
        for a_, b_ in gaps:
            seg = m[int(a_ * sr):int(b_ * sr)]
            if len(seg):
                worst = max(worst, 20 * math.log10(np.abs(seg).max() / pk + 1e-12))
        out['stuck'][v] = {'rests_checked': len(gaps), 'max_level_in_rests_db_re_peak': round(worst, 1)}
        # stuck (b): unshared harmonics of each note decay after key-up
        bad_rel, checked, worst_rel, decays, flagged = 0, 0, -200.0, [], []
        for n in notes:
            if n['off'] - n['on'] < 0.2:
                continue
            off = n['off'] + lead
            f = f_et(n['key'])
            h16, _ = has16(rep, rep['voices'][v]['divisions'], n['on'])
            cand = [f * h for h in (1, 2, 3, 4)] + ([f / 2] if h16 else [])
            others = [o for o in notes if o is not n and o['on'] + lead < off + 1.2 and o['off'] + lead > off - 0.02]
            oh = []
            for o in others:
                fo = f_et(o['key'])
                oh += [fo / 2 * h for h in range(1, 25)]     # 16' and 8' partials up to the 12th of 8'
            for w, dw in voices.items():                      # shared keys: another voice's note may sound here
                if w != v:
                    for o in dw['notes']:
                        if o['key'] == n['key'] and o['on'] + lead < off + 1.2 and o['off'] + lead > off - 0.02:
                            oh += [f_et(o['key']) / 2 * h for h in range(1, 25)]
            nfft = 8192 if f < 150 else 4096
            tol = lambda c: max(c * (2 ** (60 / 1200) - 1), 4.0 * sr / nfft)   # noqa: E731
            free = [c for c in cand if all(abs(c - x_) > tol(c) for x_ in oh)]
            if not free:
                continue
            s0 = int((off - 0.25) * sr)
            # keep only partials the note really has (a stopped flute has almost no even harmonics)
            strength = []
            for c in cand:
                t_, e_ = band_env(m[s0:int((off - 0.03) * sr)], sr, [c], 256, n=nfft)
                strength.append(e_.mean() if len(e_) else 0.0)
            top = max(strength) + 1e-30
            free = [c for c in free if strength[cand.index(c)] > top * 10 ** (-15 / 10)]
            if not free:
                continue
            t_, env = band_env(m[s0:int((off + 1.1) * sr)], sr, free, 256, n=nfft)
            t_ = t_ - 0.25
            before = env[(t_ >= -0.2) & (t_ <= -0.05)].mean()
            after = env[(t_ >= 0.95)].mean() if (t_ >= 0.95).any() else env[-1]
            checked += 1
            d = 10 * math.log10(after / (before + 1e-20) + 1e-20)
            worst_rel = max(worst_rel, d)
            decays.append(d)
            if d > -6:
                bad_rel += 1
                flagged.append({'t_off_s': round(n['off'], 3), 'key': n['key'], 'decay_db': round(d, 1),
                                'bands_hz': [round(c, 1) for c in free]})
        out['stuck'][v].update({'notes_checked': checked, 'not_6db_down_1s_after_keyup': bad_rel,
                                'median_decay_db_at_1s': round(float(np.median(decays)), 1) if decays else None,
                                'slowest_decay_db_at_1s': round(worst_rel, 1), 'flagged': flagged})
        # clicks
        d2 = np.diff(m, 2)
        win = int(0.01 * sr)
        rms = np.sqrt(np.convolve(d2 ** 2, np.ones(win) / win, 'same')) + 1e-12
        med = ss.medfilt(rms[::win], 21)
        med = np.repeat(med, win)[:len(rms)] + 1e-9
        idx = np.nonzero(np.abs(d2) / med > 12)[0]
        groups = []
        for i in idx:
            if not groups or i - groups[-1] > int(0.005 * sr):
                groups.append(i)
        ons_ = np.array([n['on'] + lead for n in notes])
        offs_ = np.array([n['off'] + lead for n in notes])
        at_b, off_b = [], []
        for g in groups:
            t = g / sr
            near = np.any((t >= ons_ - 0.045) & (t <= ons_ + 0.015)) or np.any(np.abs(t - offs_) <= 0.02)
            (at_b if near else off_b).append(round(t, 3))
        out['clicks'][v] = {'candidates': len(groups), 'at_note_boundaries': len(at_b),
                            'elsewhere': len(off_b), 'elsewhere_times_s': off_b[:20]}
    out['pitch']['all'] = {'notes': len(all_err), 'shared_keys_skipped': shared_skipped,
                           'median_cents': round(float(np.median(all_err)), 2),
                           'p95_abs_cents': round(float(np.percentile(np.abs(all_err), 95)), 2),
                           'max_abs_cents': round(float(np.max(np.abs(all_err))), 2),
                           'over_5c': int(np.sum(np.abs(np.array(all_err)) > 5))}
    for key, idx in (('energy10', 0), ('energy50', 1)):
        arr = np.array([o[idx] for o in all_on])
        out['onset'][f'all_{key}'] = {'notes': len(arr), 'median_ms': round(float(np.median(arr)), 1),
                                      'p95_abs_ms': round(float(np.percentile(np.abs(arr), 95)), 1),
                                      'max_abs_ms': round(float(np.max(np.abs(arr))), 1)}
        for dv in sorted({o[2] for o in all_on}):
            arr = np.array([o[idx] for o in all_on if o[2] == dv])
            out['onset'][f'{dv}_{key}'] = {'notes': len(arr), 'median_ms': round(float(np.median(arr)), 1),
                                           'p95_abs_ms': round(float(np.percentile(np.abs(arr), 95)), 1)}
    out['presence'] = {'weak_comb_notes': weak, 'n_weak': len(weak)}
    # re-measure every pitch outlier on the same pipes rendered alone (same stops, key, duration)
    from pipe_engine import PipeBank, ReleaseCache, SampleCache, render_event
    bank = PipeBank(rep.get('temperament', 'equal'), rep.get('a4', 440.0))
    sc = SampleCache()
    rc = ReleaseCache(sc)
    name2key = {(st['division'], st['name']): k for k, st in bank.stops.items()}
    for o in outliers:
        stops = next(c['stops'] for c in reversed(rep['registration'][o['division']]) if c['t'] <= o['t_s'] + 0.03)
        y = None
        for sname in stops:
            pc = bank.choose(name2key[(o['division'], sname)], o['key'])
            if pc is None:
                continue
            z, _ = render_event(bank, pc, o['dur_s'], sc, rc, np.random.default_rng(0))
            y = z if y is None else (np.pad(y, ((0, max(0, len(z) - len(y))), (0, 0))) +
                                     np.pad(z, ((0, max(0, len(y) - len(z))), (0, 0))))
        seg = y[int(max(0.12, 0.45 * o['dur_s']) * 48000):int((o['dur_s'] - 0.03) * 48000)]
        f = f_et(o['key'])
        f8, _ = harmonic_comb(seg, 48000, f, span_cents=60, base_ratio=1.0)
        o['isolated_same_window_cents'] = round(1200 * math.log2(f8 / f), 2)
        y = None
        for sname in stops:
            pc = bank.choose(name2key[(o['division'], sname)], o['key'])
            if pc is None:
                continue
            z, _ = render_event(bank, pc, 2.5, sc, rc, np.random.default_rng(0))
            z = z[:int(2.5 * 48000)]
            y = z if y is None else y[:len(z)] + z[:len(y)]
        f8, _ = harmonic_comb(y[int(1.0 * 48000):int(2.45 * 48000)], 48000, f, span_cents=60, base_ratio=1.0)
        o['isolated_long_note_cents'] = round(1200 * math.log2(f8 / f), 2)
    out['pitch']['outliers'] = outliers
    # registration segments
    kstems = {v: kweight(st, 48000) for v, st in stems.items()}
    mix, sr = sf.read(a.mix, dtype='float64')
    mm = mix.mean(axis=1)
    times = sorted({round(c['t'], 3) for d in rep['registration'].values() for c in d})
    times = [t for t in times if t >= 0] + [len(mm) / sr - lead]
    segs = []
    for i in range(len(times) - 1):
        t0, t1 = times[i] + lead, times[i + 1] + lead
        if t1 - t0 < 1.0:
            continue
        s = mm[int(t0 * sr):int(t1 * sr)]
        if len(s) < sr:
            continue
        f, P = ss.welch(s, sr, nperseg=8192)
        cen = float((f * P).sum() / P.sum())
        regs = {d: next((c['stops'] for c in reversed(rep['registration'][d]) if c['t'] <= times[i] + 1e-3), [])
                for d in rep['registration']}
        bal = {}
        for v, st in kstems.items():
            sv = st[int(t0 * sr):int(t1 * sr)]
            act = np.abs(stems[v][int(t0 * sr):int(t1 * sr)]) > 1e-4
            if act.mean() > 0.2:
                bal[v] = round(20 * math.log10(np.sqrt(np.mean(sv[act] ** 2)) + 1e-12), 1)
        segs.append({'from_s': round(times[i], 2), 'to_s': round(times[i + 1], 2),
                     'rms_dbfs': round(20 * math.log10(np.sqrt(np.mean(s ** 2)) + 1e-12), 1),
                     'k_dbfs': round(20 * math.log10(np.sqrt(np.mean(kweight(s, sr) ** 2)) + 1e-12), 1),
                     'centroid_hz': round(cen), 'voices_rms_dbfs': bal,
                     'HW': len(regs.get('HW', [])), 'POS': len(regs.get('POS', [])),
                     'PED': len(regs.get('PED', []))})
    out['registration_segments'] = segs
    # whole-system decay at cut-offs
    allnotes = sorted((n['on'] + lead, n['off'] + lead) for d in voices.values() for n in d['notes'])
    cuts = []
    for i, (on_, off_) in enumerate(allnotes):
        end_ = max(o for _, o in allnotes[:i + 1])
        nxt = allnotes[i + 1][0] if i + 1 < len(allnotes) else 1e9
        if off_ >= end_ - 1e-9 and nxt - end_ >= 1.0 and end_ - on_ > 0.6:
            cuts.append((end_, min(nxt, len(mm) / sr)))
    dec = []
    sos1k = ss.butter(4, [707, 1414], 'bandpass', fs=sr, output='sos')
    for c0, c1 in sorted(set(cuts)):
        row = {'cutoff_s': round(c0 - lead, 2), 'gap_s': round(c1 - c0, 2)}
        for name, sig in (('broadband', mm), ('1k', ss.sosfiltfilt(sos1k, mm))):
            e = sig ** 2
            steady = e[int((c0 - 0.5) * sr):int((c0 - 0.1) * sr)].mean()
            # power after the cut-off (centred 20 ms mean) over the steady power = the share of the
            # system response's energy that arrives later than t (its Schroeder curve)
            w = int(0.020 * sr)
            n_post = int((c1 - c0) * sr)
            segp = e[int(c0 * sr) - w // 2:int(c0 * sr) + n_post + w // 2]
            d = np.convolve(segp, np.ones(w) / w, 'valid')[:n_post] / steady
            db = 10 * np.log10(d + 1e-12)
            i80 = int(0.080 * sr)
            d80 = float(d[i80])
            start = int(0.010 * sr)
            i5 = start + int(np.argmax(db[start:] <= -5)) if np.any(db[start:] <= -5) else 0
            i25 = start + int(np.argmax(db[start:] <= -25)) if np.any(db[start:] <= -25) else 0
            t20 = None
            if i25 > i5 > 0:
                tt = np.arange(i5, i25) / sr
                t20 = round(float(-60 / np.polyfit(tt, db[i5:i25], 1)[0]), 2)
            row[name] = {'level_80ms_db': round(10 * math.log10(d80), 1),
                         'C80_db': round(10 * math.log10(max(1e-9, 1 - d80) / d80), 1) if d80 < 1 else None,
                         'T20_s': t20}
        dec.append(row)
    out['system_decay_at_cutoffs'] = dec
    if a.o:
        Path(a.o).parent.mkdir(parents=True, exist_ok=True)
        json.dump(out, open(a.o, 'w'), indent=1)
    print('pitch (all):', out['pitch']['all'])
    for k_, v_ in out['onset'].items():
        if k_.startswith(('all', 'HW', 'POS', 'OW', 'PED')):
            print('onset', k_, v_)
    print('weak notes:', len(weak))
    for r_ in out['system_decay_at_cutoffs']:
        print('cut-off', r_)
    for o in outliers:
        print('pitch outlier', o)
    for v in voices:
        print(v, 'stuck', out['stuck'][v], 'clicks', {k: out['clicks'][v][k] for k in ('candidates', 'at_note_boundaries', 'elsewhere')})
    for s in segs:
        print(f"{s['from_s']:7.1f}-{s['to_s']:7.1f}s  rms {s['rms_dbfs']:6.1f} K {s['k_dbfs']:6.1f} dBFS  centroid {s['centroid_hz']:5d} Hz  HW {s['HW']} POS {s['POS']} PED {s['PED']}  {s['voices_rms_dbfs']}")


if __name__ == '__main__':
    main()
