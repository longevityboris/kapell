#!/usr/bin/env python3
"""combo4.py: search placements of thematic forms over a fixed bass, judged by the real checker.

Fixed bass: INV in augmentation from F2 (the Part IV dominant pedal), 38 beats.
Upper voices: each of S1 / INV / S2 (Bb-minor forms) may be placed in soprano/alto/tenor at an
offset (beats, step 2) and an octave; every candidate is written as a 4-voice lab and checked.
Score = 10*PAR + 6*BEAT + 6*DIS! + 2*D4? + 1*CROS + 4*cross-relations - 0.2*imperfect-consonance count.
"""
import sys, os, itertools, subprocess, tempfile
from fractions import Fraction as F
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p2 import parse, real, shift, aug, emit, length, S1, S2
from scan import INV, cross_rel

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, '../../../tools/check.py')
BASS = aug(real(parse(INV), -21, -36), 2)          # f'' -> f,  (F2), augmented
TOTAL = F(40)
RANGES = dict(soprano=(60, 84), alto=(53, 77), tenor=(48, 72), bass=(36, 62))


def place(form, off, semis, steps):
    return shift(real(parse(form), steps, semis), F(off))


def check(voices):
    with tempfile.NamedTemporaryFile('w', suffix='.ly', delete=False) as fh:
        fh.write('\\version "2.24.0"\n')
        for v in ['soprano', 'alto', 'tenor', 'bass']:
            ns = voices.get(v)
            body = emit(ns, total=TOTAL) if ns else "R1*10 |"
            fh.write(f"{v} = \\absolute {{\n  {body}\n}}\n")
        path = fh.name
    r = subprocess.run(['sh', os.path.join(HERE, 'chk.sh'), path], capture_output=True, text=True).stdout
    os.unlink(path)
    lines = r.strip().splitlines()
    c = lambda p: sum(l.startswith(p) for l in lines)
    sc = 10 * c('PAR!') + 6 * c('BEAT') + 6 * c('DIS!') + 2 * c('D4?') + 1 * c('CROS') + 8 * c('ERR')
    return sc, [l for l in lines if l[:4] in ('PAR!', 'BEAT', 'DIS!', 'D4? ', 'CROS', 'ERR ')]


def inrange(ns, v):
    lo, hi = RANGES[v]
    return all(lo <= n[2] <= hi for n in ns if n[2] is not None)


if __name__ == '__main__':
    # candidate registers (semitones, letter steps) relative to the written form
    REG = {
        'S1': {'tenor': [(-12, -7)], 'alto': [(0, 0)], 'soprano': [(0, 0), (12, 7)]},
        'INV': {'tenor': [(-12, -7)], 'alto': [(-12, -7)], 'soprano': [(0, 0)]},
        'S2': {'tenor': [(-12, -7)], 'alto': [(0, 0)], 'soprano': [(0, 0), (12, 7)]},
    }
    FORMSRC = {'S1': S1, 'INV': INV, 'S2': S2}
    which = sys.argv[1].split(',') if len(sys.argv) > 1 else ['S1', 'INV', 'S2']
    offs = range(0, int(os.environ.get("OMAX", 22)), int(os.environ.get("OSTEP", 2)))
    res = []
    voices_names = ['soprano', 'alto', 'tenor']
    for assign in itertools.permutations(voices_names, len(which)):
        for off in itertools.product(offs, repeat=len(which)):
            if min(off) != 0 and 0 not in off:
                pass
            for regs in itertools.product(*[REG[w][v] for w, v in zip(which, assign)]):
                vs = {'bass': BASS}
                ok = True
                for w, v, o, (se, st) in zip(which, assign, off, regs):
                    ns = place(FORMSRC[w], o, se, st)
                    if length(ns) > TOTAL or not inrange(ns, v):
                        ok = False
                        break
                    vs[v] = ns
                if not ok:
                    continue
                sc, iss = check(vs)
                ups = [vs[v] for v in voices_names if v in vs]
                cr = sum(cross_rel(a, b) for a, b in itertools.combinations(ups + [BASS], 2))
                sc += 4 * cr
                res.append((sc, assign, off, regs, iss, cr))
    res.sort(key=lambda r: r[0])
    for sc, assign, off, regs, iss, cr in res[:25]:
        print(f"score {sc:5.1f} cr {cr} ", ', '.join(f"{w}->{v}@{o}{'' if r == (0,0) else r}" for w, v, o, r in zip(which, assign, off, regs)))
        for i in iss[:5]:
            print('      ', i)
