# every key of each string part held 3 s at mf, stacked vs each recording alone:
#   python3 sweep_strings.py vn1,vn2,va,vc,cb stack,vsco,vpo3   (renders into out/test/; prints level, range, drift)
import json, sys, subprocess
sys.path.insert(0, '/Users/biobook/Music/llm-music/fugue-jp/ricercar/audio/orchestra')
import mido, numpy as np, soundfile as sf
import orch_measure as M
from orch_common import PARTS, midi_name
H = '/Users/biobook/Music/llm-music/fugue-jp/ricercar/audio/orchestra'
parts = sys.argv[1].split(',')
sets = sys.argv[2].split(',')   # 'stack' or set names
TPQ = 480
mid = mido.MidiFile(type=1, ticks_per_beat=TPQ)
tt = mido.MidiTrack(); tt.append(mido.MetaMessage('set_tempo', tempo=1_000_000)); mid.tracks.append(tt)
plan = {}
for p in parts:
    tr = mido.MidiTrack(); tr.append(mido.MetaMessage('track_name', name=p))
    tr.append(mido.Message('control_change', control=1, value=88)); tr.append(mido.Message('control_change', control=20, value=0))
    t = 0.5; last = 0; plan[p] = []
    for k in range(PARTS[p]['lo'], PARTS[p]['hi'] + 1):
        on, off = t, t + 3.0
        a, b = int(on * TPQ), int(off * TPQ)
        tr.append(mido.Message('note_on', note=k, velocity=64, time=a - last)); last = a
        tr.append(mido.Message('note_off', note=k, velocity=0, time=b - last)); last = b
        plan[p].append((on, off, k)); t += 3.5
    mid.tracks.append(tr)
mid.save(f'{H}/out/test/sweep.mid')
res = {}
for s in sets:
    out = f'{H}/out/test/sweep_{s}'
    cmd = [sys.executable, f'{H}/render_orchestra.py', f'{H}/out/test/sweep.mid', '-o', out, '--stems', '--keep-start', '--no-reverb']
    if s != 'stack':
        cmd += ['--force-set', ','.join(f'{p}={s}' for p in parts)]
    subprocess.run(cmd, check=True, capture_output=True)
    rep = json.load(open(out + '.json'))
    dep = {}
    for j in rep['jobs']: dep.setdefault(j['label'].split('/')[0], j['seat_depth_m'])
    for p in parts:
        x, _ = sf.read(f'{out}.stems/{p}.wav', always_2d=True); m = x.mean(1); m = np.concatenate([m, np.zeros(48000 * 400)]); d = dep[p] / 343
        for on, off, k in plan[p]:
            e, _ = M.env_db(m[int((on + d + 0.4) * 48000): int((off + d - 0.1) * 48000)], 0.1, 0.05)
            lv = M.k_level_db(m[int((on + d + 0.4) * 48000): int((off + d - 0.1) * 48000)])
            res.setdefault(p, {}).setdefault(k, {})[s] = (round(lv, 1), round(float(e.max() - e.min()), 1),
                                                          round(float(np.mean(e[-8:]) - np.mean(e[:8])), 1))
for p in parts:
    print(p)
    for k, r in res[p].items():
        row = '  '.join(f"{s}: {r[s][0]:6.1f} rng {r[s][1]:4.1f} drift {r[s][2]:+5.1f}" for s in sets)
        flag = ' <<' if any(r[s][1] > 8 or abs(r[s][2]) > 4 or r[s][0] < -80 for s in sets) else ''
        print(f'  {midi_name(k):4s} {row}{flag}')
json.dump({p: {str(k): v for k, v in r.items()} for p, r in res.items()}, open(f'{H}/out/test/sweep.json', 'w'))
