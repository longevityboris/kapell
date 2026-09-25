#!/usr/bin/env python3
"""Build the skeleton from piece.py and verify it in one go.

usage: python3 verify.py [--bars A-B] [--grid A-B] [--no-build]

Prints: check.py summary and every flag (PAR!, BEAT, DIS!, D4?, DIR, MEL, CROS, range), strict.py
summary with CLASH/XREL (and ACC/ACC2 inside --bars), unisons and hollow four-voice sonorities,
suspensions, and the measured duration (piano and strings targets). Exit 1 if not clean.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
sys.path.insert(0, HERE)
import fl  # noqa: E402
import grid  # noqa: E402


def run(args):
    return subprocess.run(args, capture_output=True, text=True, cwd=HERE)


def main():
    args = sys.argv[1:]
    if '--no-build' not in args:
        r = run([sys.executable, 'build_sk.py'])
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode:
            sys.exit(1)
    sk = os.path.join(HERE, 'SK_final.ly')
    bars = args[args.index('--bars') + 1] if '--bars' in args else None
    lines, slines = fl.check(sk, bars=bars)
    ok = True
    for l in lines:
        tok = l.split()[0] if l.split() else ''
        if tok in ('PAR!', 'BEAT', 'DIS!', 'D4?', 'DIR', 'MEL', 'CROS', 'ERR') or 'range' in l.lower() or l.startswith('--'):
            print('  ' + l)
    if not re.search(r'errors 0, parallels 0, beat-par 0, unjustified 0', lines[-1] if lines else ''):
        ok = False
    s = run([sys.executable, 'strict.py', sk, '-v'] + (['--bars', bars] if bars else []))
    for l in s.stdout.splitlines():
        if l.startswith(('CLASH', 'XREL')) or l.startswith('strict') or (bars and l.startswith('ACC')):
            print('  ' + l)
    if 'clash 0' not in s.stdout:
        ok = False
    data = grid.load(sk)
    a, b = (map(int, bars.split('-'))) if bars else (None, None)
    uni, hol = [], []
    for t, cells, names, ch, flags in grid.rows(data, a, b, attacks=True):
        if 'UNI' in flags:
            uni.append(grid.pos(t))
        if 'HOL' in flags:
            hol.append(grid.pos(t))
    print('  unisons at:', ' '.join(uni) or 'none')
    print('  hollow 4-voice sonorities (<=2 pitch classes) at:', ' '.join(hol) or 'none')
    # plan audit: a hairpin needs attacks to be heard on the piano (loudness is set at note-on)
    import json
    from fractions import Fraction as F
    plan = json.load(open(os.path.join(HERE, 'plan.json')))
    pp = lambda x: F(int(x.split(':')[0]) - 1) + (F(x.split(':')[1]) - 1) / 4
    attacks = sorted({n.start for v in data for n in data[v] if n.midi is not None})
    gaps = []
    for d in plan['dynamics']:
        if 'until' not in d:
            continue
        a0, a1 = pp(d['at']), pp(d['until'])
        t = a0
        while t < a1:
            if not any(t <= x < min(t + F(1, 2), a1) for x in attacks):
                gaps.append(f"{grid.pos(t)}")
            t += F(1, 2)
    print('  hairpin half-bars without any attack:', ' '.join(gaps) or 'none')
    su = run([sys.executable, 'suspensions.py', sk])
    print('  ' + ' / '.join(su.stdout.strip().splitlines()))
    for tgt in ('piano', 'strings'):
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'perform.py'), sk, os.path.join(HERE, 'plan.json'),
                            f'/tmp/verify_{tgt}_{os.getpid()}.mid', '--target', tgt], capture_output=True, text=True)
        print(f'  duration {tgt}: ' + (p.stdout.strip().split(',')[-1].strip() if p.returncode == 0 else p.stderr.strip()[-200:]))
    if '--grid' in args:
        ga, gb = map(int, args[args.index('--grid') + 1].split('-'))
        for t, cells, names, ch, flags in grid.rows(data, ga, gb, attacks=True):
            print(f"{grid.pos(t):>7}  " + ' '.join(f"{c:>5}" for c in cells) + f"   {ch}" + (f"   [{' '.join(flags)}]" if flags else ''))
    print('CLEAN' if ok else 'NOT CLEAN')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
