#!/usr/bin/env python3
"""Contract tests for render_organ.py: small MIDI files that exercise CONTRACT.md, rendered and
measured. Writes tests/results.json (and prints a summary); renders go to /tmp.

usage: python3 tests/contract_tests.py [--keep]

1. registration ladder (HW, one held chord + a scale in the soprano): each named registration's
   K-weighted level and spectral centroid, plus the gain-matched share of energy above 2 kHz, so
   the registration changes timbre, not only level; the pedal ladder likewise.
2. swell box: CC11 127 -> 0 -> 127 on an enclosed division: level and centroid, open vs closed.
3. `organ:` text events change registration and move a voice; presets; custom stop lists;
   an unknown registration name is an error.
4. key sharing: soprano and alto on the same key play one set of pipes (level equal to one voice,
   not +6 dB); a hand-over is re-struck.
5. folding below the pedal compass (warning, count) and --no-fold (error); zero-length note.
6. stems: the stems sum to the dry mix (--no-reverb); lead-in and anticipation of the first sound;
   velocity has no effect; two renders are identical.

Each promise is then checked (`checks` in results.json, PASS/FAIL printed); the exit code is 1 if
any check fails.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import mido
import numpy as np
import scipy.signal as ss
import soundfile as sf

HERE = Path(__file__).resolve().parent.parent
REN = str(HERE / 'render_organ.py')
TMP = Path(tempfile.mkdtemp(prefix='organ_tests_'))
TPB = 480


def kweight(x, sr=48000):
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
    return ss.lfilter(b2, a2, ss.lfilter(b1, a1, x))


def midi(path, tracks, tempo=500000, texts=()):
    """tracks: {name: [(key, start_beats, dur_beats, vel)]} ; texts: [(beat, text)]; ccs in tracks as ('cc', beat, ctl, val)."""
    mf = mido.MidiFile(type=1, ticks_per_beat=TPB)
    t0 = mido.MidiTrack()
    t0.append(mido.MetaMessage('track_name', name='tempo', time=0))
    t0.append(mido.MetaMessage('set_tempo', tempo=tempo, time=0))
    last = 0
    for b, tx in sorted(texts):
        tick = int(b * TPB)
        t0.append(mido.MetaMessage('text', text=tx, time=tick - last))
        last = tick
    mf.tracks.append(t0)
    for ch, (name, notes) in enumerate(tracks.items()):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage('track_name', name=name, time=0))
        ev = []
        for n in notes:
            if n[0] == 'cc':
                ev.append((int(n[1] * TPB), 0, mido.Message('control_change', channel=ch, control=n[2], value=n[3])))
            else:
                k, s, d, v = n
                ev.append((int(s * TPB), 1, mido.Message('note_on', channel=ch, note=k, velocity=v)))
                ev.append((int((s + d) * TPB), 0, mido.Message('note_off', channel=ch, note=k, velocity=0)))
        ev.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for tick, _, m in ev:
            tr.append(m.copy(time=tick - last))
            last = tick
        mf.tracks.append(tr)
    mf.save(path)
    return path


def render(mid, out, *args, expect_fail=False):
    cmd = [sys.executable, REN, str(mid), '-o', str(out), '--no-m4a', '--json', str(out) + '.json', *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if expect_fail:
        return r
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    x, sr = sf.read(str(out) + '.wav', dtype='float64')
    return x, json.load(open(str(out) + '.json')), r


def level_centroid(x, a, b, sr=48000):
    s = x[int(a * sr):int(b * sr)].mean(axis=1)
    k = kweight(s)
    f, P = ss.welch(s, sr, nperseg=8192)
    return (20 * math.log10(np.sqrt(np.mean(k ** 2)) + 1e-12), float((f * P).sum() / P.sum()),
            10 * math.log10(P[f >= 2000].sum() / P.sum()))


def main():
    res = {}
    # 1. registration ladder -------------------------------------------------------------------
    chord = {'soprano': [(65, 0, 4, 90), (67, 4, 1, 90), (69, 5, 1, 90), (70, 6, 2, 90)],
             'alto': [(61, 0, 8, 90)], 'tenor': [(58, 0, 8, 90)], 'bass': [(46, 0, 8, 90)]}
    m1 = midi(TMP / 'ladder.mid', chord)
    ladder = {}
    for reg in ['flute8', 'flute8+4', 'principal8', 'principal8+4', 'principal8+4+2', 'plenum', 'plenum_reed']:
        side = TMP / f'reg_{reg}.json'
        json.dump({'manuals': {'soprano': 'HW', 'alto': 'HW', 'tenor': 'HW', 'bass': 'HW'},
                   'changes': [{'at': '1:1', 'HW': reg}]}, open(side, 'w'))
        x, rep, _ = render(m1, TMP / f'ladder_{reg}', '--registration', str(side), '--no-reverb', '--peak-db', '0')
        g = 10 ** (rep['normalisation_gain_db'] / 20)
        L, C, H = level_centroid(x / g, 0.5 + 0.5, 0.5 + 3.5)     # undo the normalisation: true levels
        ladder[reg] = {'k_level_db': round(L, 1), 'centroid_hz': round(C), 'energy_above_2k_db': round(H, 1)}
    pl = {}
    for reg in ['pedal8', 'pedal16', 'pedal16+8', 'pedal16+8+4', 'pedal_reed', 'pedal_plenum_reed']:
        side = TMP / f'preg_{reg}.json'
        json.dump({'changes': [{'at': '1:1', 'PED': reg, 'HW': 'off', 'POS': 'off'}]}, open(side, 'w'))
        x, rep, _ = render(m1, TMP / f'pladder_{reg}', '--registration', str(side), '--no-reverb', '--peak-db', '0')
        g = 10 ** (rep['normalisation_gain_db'] / 20)
        L, C, H = level_centroid(x / g, 1.0, 4.0)
        pl[reg] = {'k_level_db': round(L, 1), 'centroid_hz': round(C), 'energy_above_2k_db': round(H, 1)}
    res['registration_ladder_HW'] = ladder
    res['registration_ladder_PED'] = pl
    lv = [ladder[r]['k_level_db'] for r in ladder]
    res['ladder_levels_rise'] = all(b >= a - 0.5 for a, b in zip(lv, lv[1:]))
    res['ladder_brightness_rises_flute_to_plenum'] = ladder['plenum']['energy_above_2k_db'] > ladder['flute8']['energy_above_2k_db'] + 6

    # 2. swell box ------------------------------------------------------------------------------
    # CC11: open 0-2 s, closing 2-4 s, closed 4-6 s, opening 6-7 s, open 7-8 s (120 bpm: 2 beats/s)
    curve = [(0, 127), (4, 127)] + [(4 + i / 4, int(127 * (1 - i / 16))) for i in range(1, 17)] + \
            [(12, 0)] + [(12 + i / 8, int(127 * i / 16)) for i in range(1, 17)] + [(16, 127)]
    sw = {'soprano': [(65, 0, 16, 90)] + [('cc', b, 11, v) for b, v in curve]}
    m2 = midi(TMP / 'swell.mid', sw)
    side = TMP / 'swell.json'
    json.dump({'enclosed': ['HW'], 'changes': [{'at': '1:1', 'HW': 'principal8+4+2'}]}, open(side, 'w'))
    x, rep, _ = render(m2, TMP / 'swell', '--registration', str(side), '--no-reverb')
    open_ = level_centroid(x, 0.5 + 0.8, 0.5 + 1.9)
    closed = level_centroid(x, 0.5 + 4.3, 0.5 + 5.9)
    reopen = level_centroid(x, 0.5 + 7.1, 0.5 + 7.9)
    x2, _, _ = render(m2, TMP / 'swell_off', '--registration', str(TMP / 'reg_principal8+4+2.json'), '--no-reverb')
    res['swell'] = {'open_db': round(open_[0], 1), 'closed_db': round(closed[0], 1), 'reopened_db': round(reopen[0], 1),
                    'open_centroid': round(open_[1]), 'closed_centroid': round(closed[1]),
                    'open_above_2k_db': round(open_[2], 1), 'closed_above_2k_db': round(closed[2], 1),
                    'closed_minus_open_db': round(closed[0] - open_[0], 1),
                    'not_enclosed_level_change_db': round(level_centroid(x2, 0.5 + 4.3, 0.5 + 5.9)[0] - level_centroid(x2, 0.5 + 0.8, 0.5 + 1.9)[0], 1)}

    # 3. text events, presets, custom lists, unknown names ---------------------------------------
    m3 = midi(TMP / 'text.mid', {'soprano': [(65, 0, 2, 90), (67, 2, 2, 90)], 'tenor': [(53, 0, 2, 90), (55, 2, 2, 90)]},
              texts=[(2, 'organ: HW=plenum PED=pedal_plenum_reed'), (2, 'organ: tenor->HW')])
    _, rep, _ = render(m3, TMP / 'text', '--no-reverb')
    hw = rep['registration']['HW']
    res['text_events'] = {'HW_timeline': [(c['t'], len(c['stops'])) for c in hw],
                          'tenor_divisions': rep['voices']['tenor']['divisions'],
                          'ok': len(hw) == 2 and len(hw[1]['stops']) == 5 and rep['voices']['tenor']['divisions'][-1][1] == 'HW'}
    _, rep, _ = render(m3, TMP / 'preset', '--registration', 'plenum', '--no-reverb')
    res['preset_plenum_HW_stops'] = rep['registration']['HW'][0]['stops']
    side = TMP / 'custom.json'
    json.dump({'custom': {'my': ["Gedackt flott 8", "octava 4'"]}, 'changes': [{'at': '1:1', 'HW': 'my'}]}, open(side, 'w'))
    _, rep, _ = render(m3, TMP / 'custom', '--registration', str(side), '--no-reverb')
    res['custom_list_HW_stops'] = rep['registration']['HW'][0]['stops']
    side = TMP / 'bad.json'
    json.dump({'changes': [{'at': '1:1', 'HW': 'fortissimo'}]}, open(side, 'w'))
    r = render(m3, TMP / 'bad', '--registration', str(side), expect_fail=True)
    res['unknown_registration'] = {'exit_code': r.returncode, 'message': r.stderr.strip().splitlines()[-1][:160]}

    # 4. key sharing and hand-over ---------------------------------------------------------------
    one = midi(TMP / 'one.mid', {'soprano': [(65, 0, 4, 90)]})
    two = midi(TMP / 'two.mid', {'soprano': [(65, 0, 4, 90)], 'alto': [(65, 0.01, 4, 90)]})
    side = TMP / 'p8.json'
    json.dump({'changes': [{'at': '1:1', 'HW': 'principal8'}]}, open(side, 'w'))
    x1, r1, _ = render(one, TMP / 'one', '--registration', str(side), '--no-reverb', '--peak-db', '0')
    x2, r2, _ = render(two, TMP / 'two', '--registration', str(side), '--no-reverb', '--peak-db', '0')
    l1 = level_centroid(x1 / 10 ** (r1['normalisation_gain_db'] / 20), 1.0, 2.0)[0]
    l2 = level_centroid(x2 / 10 ** (r2['normalisation_gain_db'] / 20), 1.0, 2.0)[0]
    ho = midi(TMP / 'handover.mid', {'alto': [(65, 0, 2.01, 90)], 'soprano': [(65, 2.0, 2, 90)]})
    _, r3, _ = render(ho, TMP / 'handover', '--registration', str(side), '--no-reverb')
    res['key_sharing'] = {'shared_keys': r2['shared_keys'], 'pipe_events_one': r1['pipe_events'],
                          'pipe_events_two': r2['pipe_events'], 'level_two_minus_one_db': round(l2 - l1, 2),
                          'handover_restrikes': r3['handover_restrikes'], 'handover_pipe_events': r3['pipe_events']}

    # 5. folding and odd notes -------------------------------------------------------------------
    fo = midi(TMP / 'fold.mid', {'bass': [(30, 0, 2, 90), (40, 2, 0, 90)]})
    _, rep, r = render(fo, TMP / 'fold', '--no-reverb')
    rf = render(fo, TMP / 'fold2', '--no-fold', expect_fail=True)
    res['folding'] = {'folded': rep['folded_notes'], 'warnings': rep['warnings'],
                      'no_fold_exit_code': rf.returncode, 'no_fold_message': rf.stderr.strip().splitlines()[-1][:160]}

    # 6. stems, lead-in, velocity, determinism ---------------------------------------------------
    quartet = {'soprano': [(70, 0, 1, 90), (72, 1, 1, 90), (73, 2, 2, 90)], 'alto': [(65, 0, 4, 90)],
               'tenor': [(58, 0, 2, 90), (60, 2, 2, 90)], 'bass': [(46, 0, 4, 90)]}
    q = midi(TMP / 'q.mid', quartet)
    qv = midi(TMP / 'qv.mid', {k: [(n[0], n[1], n[2], 20) for n in v] for k, v in quartet.items()})
    xa, ra, _ = render(q, TMP / 'qa', '--no-reverb', '--stems', str(TMP / 'qa_stems'))
    xb, rb, _ = render(qv, TMP / 'qb', '--no-reverb')
    xc, rc, _ = render(q, TMP / 'qc', '--no-reverb')
    st = sum(sf.read(str(TMP / 'qa_stems' / f'{v}.wav'), dtype='float64')[0] for v in quartet)
    n = min(len(st), len(xa))
    env = np.abs(xa).max(axis=1)
    first = int(np.argmax(env > 10 ** (-60 / 20))) / 48000
    res['stems'] = {'max_abs_diff_sum_vs_mix_dbfs': round(20 * math.log10(np.abs(st[:n] - xa[:n]).max() + 1e-12), 1),
                    'first_sound_s': round(first, 4), 'lead_in_s': ra['lead_in_s'],
                    'anticipation_ms': ra['anticipation_ms']}
    res['velocity_ignored_identical'] = bool(np.array_equal(xa, xb))
    res['deterministic_identical'] = bool(np.array_equal(xa, xc))
    res['velocity_max_abs_diff'] = float(np.abs(xa - xb).max())
    res['determinism_max_abs_diff'] = float(np.abs(xa - xc).max())

    # verdicts: what CONTRACT.md promises, as pass/fail --------------------------------------------
    pv = [pl[r]['k_level_db'] for r in ('pedal8', 'pedal16+8', 'pedal16+8+4', 'pedal_plenum_reed')]
    sw_, ks, fo_, stm = res['swell'], res['key_sharing'], res['folding'], res['stems']
    checks = {
        'HW ladder: level never falls by more than 0.5 dB from flute8 to plenum_reed': res['ladder_levels_rise'],
        'HW ladder: plenum has >= 6 dB more energy above 2 kHz than flute8': res['ladder_brightness_rises_flute_to_plenum'],
        'PED ladder: pedal8 < pedal16+8 < pedal16+8+4 < pedal_plenum_reed': all(b > a for a, b in zip(pv, pv[1:])),
        'swell: closed is 15-24 dB below open': -24 <= sw_['closed_minus_open_db'] <= -15,
        'swell: closed is darker (lower centroid, less above 2 kHz)': sw_['closed_centroid'] < sw_['open_centroid']
        and sw_['closed_above_2k_db'] < sw_['open_above_2k_db'],
        'swell: reopened within 1.5 dB of open': abs(sw_['reopened_db'] - sw_['open_db']) <= 1.5,
        'swell: CC11 ignored on a division not enclosed (within 1 dB)': abs(sw_['not_enclosed_level_change_db']) <= 1.0,
        'organ: text events change registration and move a voice': res['text_events']['ok'],
        'preset plenum draws the HW plenum (5 stops with the Mixtur)': len(res['preset_plenum_HW_stops']) == 5
        and any('Mixtur' in s for s in res['preset_plenum_HW_stops']),
        'custom stop list resolves (accents, case, punctuation ignored)': res['custom_list_HW_stops'] == ["Gedackt flött 8'", "Octava 4'"],
        'unknown registration name is an error': res['unknown_registration']['exit_code'] != 0,
        'key sharing: one set of pipes (same events, level within 0.5 dB)': ks['shared_keys'] == 1
        and ks['pipe_events_two'] == ks['pipe_events_one'] and abs(ks['level_two_minus_one_db']) <= 0.5,
        'hand-over between voices is re-struck': ks['handover_restrikes'] == 1 and ks['handover_pipe_events'] == 2,
        'folding: out-of-compass key folded and counted; --no-fold is an error': fo_['folded'] == {'PED': 1}
        and fo_['no_fold_exit_code'] != 0,
        'zero-length note played as a touch, with a warning': any('zero-length' in w for w in fo_['warnings']),
        'stems sum to the dry mix (< -80 dBFS difference)': stm['max_abs_diff_sum_vs_mix_dbfs'] < -80,
        'first sound within 45 ms before the lead-in (anticipation only)': stm['lead_in_s'] - 0.045 <= stm['first_sound_s'] <= stm['lead_in_s'],
        'velocity ignored (bit-identical)': res['velocity_ignored_identical'],
        'deterministic (bit-identical)': res['deterministic_identical'],
    }
    res['checks'] = {k: bool(v) for k, v in checks.items()}
    res['all_pass'] = all(res['checks'].values())
    json.dump(res, open(HERE / 'tests' / 'results.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    for k, v in res['checks'].items():
        print(('PASS ' if v else 'FAIL ') + k)
    print('renders in', TMP)
    print('ALL PASS' if res['all_pass'] else 'SOME CHECKS FAILED')
    sys.exit(0 if res['all_pass'] else 1)


if __name__ == '__main__':
    main()
