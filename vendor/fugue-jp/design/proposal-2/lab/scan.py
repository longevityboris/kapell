#!/usr/bin/env python3
"""scan.py: brute-force 2-voice combination scan using the REAL checker (tools/check.py).

usage: scan.py LEADER FOLLOWER [--ivs P8,P5,...] [--dmax 16] [--step 0.5] [--aug-f 2] [--aug-l 2]
               [--follower-below | --follower-above] [--top 20] [--minover 8]
LEADER/FOLLOWER: names of forms in FORMS (or 'lilypond:...' literal). The follower is transposed by
each interval (relative to its written pitch) and delayed by d beats (negative d = follower first).
Each candidate is written as a 2-voice lab (alto/tenor so no bass-4th rule applies unless --bass)
and checked; with --bass the lower voice is written as the bass so 4ths against it count.
Score = 10*PAR + 6*BEAT + 6*DIS! + 2*D4? + 0.5*CROS ; overlap = beats both voices sound.
"""
import sys, os, subprocess, tempfile
from fractions import Fraction as F
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p2 import parse, real, shift, aug, mirror, emit, length, S1, S2

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, '../../../tools/check.py')

INV = "f''2. f''8 ges'' | f''2. f''8 ges'' | f''4. ees''8 ees''4. c''8 | c''2. des''8 f'' | ees''4. ges''8 bes''4"
ANS = "f''2. f''8 e'' | f''2. f''8 e'' | f''4. g''8 g''4. bes''8 | bes''2. aes''8 f'' | g''4. e''8 c''4"
S1M = "bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. d''8 bes' | c''4. a'8 f'4"
S2M = "c''4. a'8 f'4 d''8 bes' | c''2. f''8 bes' | ees''4. d''8 d''4. c''8 | c''1"
INVM = "f''2. f''8 g'' | f''2. f''8 g'' | f''4. ees''8 ees''4. c''8 | c''2. d''8 f'' | ees''4. g''8 bes''4"
FULLM = S1M.rsplit('|', 1)[0] + "| c''4. a'8 f'4 d''8 bes' | c''2. f''8 bes' | ees''4. d''8 d''4. c''8 | bes'1"
S1_DB = "des''2. des''8 c''8 | des''2. des''8 c''8 | des''4. ees''8 ees''4. ges''8 | ges''2. f''8 des''8 | ees''4. c''8 aes'4"
S1_GB = "ges'2. ges'8 f'8 | ges'2. ges'8 f'8 | ges'4. aes'8 aes'4. ces''8 | ces''2. bes'8 ges'8 | aes'4. f'8 des'4"
INVM2 = "f''2. f''8 ges''8 | f''2. f''8 ges''8 | f''4. ees''8 ees''4. c''8 | c''2. d''8 f''8 | ees''4. g''8 bes''4"
FORMS = dict(INVM2=INVM2, S1=S1, S2=S2, INV=INV, ANS=ANS, S1M=S1M, S2M=S2M, INVM=INVM, FULLM=FULLM, S1_DB=S1_DB, S1_GB=S1_GB)


def cross_rel(a, b):
    """count simultaneous same-letter/different-pitch-class pairs (e.g. E against E-flat)."""
    n = 0
    for x in a:
        if x[2] is None: continue
        for y in b:
            if y[2] is None: continue
            if x[0] < y[0] + y[1] and y[0] < x[0] + x[1]:
                if x[3] % 7 == y[3] % 7 and (x[2] - y[2]) % 12 != 0:
                    n += 1
    return n


def quality(a, b):
    """per quarter beat: imperfect consonance +1, perfect 0, 4th -0.5, dissonance on beat -1."""
    def at(ns, t):
        for n in ns:
            if n[2] is not None and n[0] <= t < n[0] + n[1]: return n
    q = 0
    t0 = max(min(n[0] for n in a if n[2]), min(n[0] for n in b if n[2]))
    t1 = min(max(n[0] + n[1] for n in a if n[2]), max(n[0] + n[1] for n in b if n[2]))
    t = F(int(t0))
    while t < t1:
        x, y = at(a, t), at(b, t)
        if x and y:
            ic = abs(x[2] - y[2]) % 12
            q += {3: 1, 4: 1, 8: 1, 9: 1, 0: 0, 7: 0, 5: -0.5}.get(ic, -1)
        t += 1
    return q

IVS = {'P1': (0, 0), 'P8u': (7, 12), 'P8d': (-7, -12), 'P15d': (-14, -24),
       'P5u': (4, 7), 'P5d': (-4, -7), 'P4u': (3, 5), 'P4d': (-3, -5),
       'P12d': (-11, -19), 'P11d': (-10, -17), 'P12u': (11, 19),
       'm3d': (-2, -3), 'M3d': (-2, -4), 'm3u': (2, 3), 'M3u': (2, 4),
       'm6d': (-5, -8), 'M6d': (-5, -9), 'm10d': (-9, -15), 'M10d': (-9, -16),
       'M2d': (-1, -2), 'M9d': (-8, -14), 'm7d': (-6, -10), 'M2u': (1, 2), 'P11u': (10, 17), 'P18u': (17, 29)}


def form(name):
    if name.startswith('lilypond:'):
        return parse(name[len('lilypond:'):])
    return parse(FORMS[name])


def run(up, lo, bass=False):
    tot = max(length(up), length(lo))
    nb = int((tot + 3) // 4)
    total = F(nb * 4)
    vu, vl = ('soprano', 'bass') if bass else ('alto', 'tenor')
    rng = []
    with tempfile.NamedTemporaryFile('w', suffix='.ly', delete=False) as fh:
        fh.write('\\version "2.24.0"\n')
        for v in ['soprano', 'alto', 'tenor', 'bass']:
            if v == vu:
                body = emit(up, total=total)
            elif v == vl:
                body = emit(lo, total=total)
            else:
                body = f"R1*{nb} |"
            fh.write(f"{v} = \\absolute {{\n  {body}\n}}\n")
        path = fh.name
    r = subprocess.run(['python3', CHECK, path, '--voices', 'soprano,alto,tenor,bass'],
                       capture_output=True, text=True).stdout
    os.unlink(path)
    lines = r.strip().splitlines()
    c = lambda p: sum(l.startswith(p) for l in lines)
    score = 10 * c('PAR!') + 6 * c('BEAT') + 6 * c('DIS!') + 2 * c('D4?') + 0.5 * c('CROS') + 5 * c('ERR')
    return score, [l for l in lines if l[:4] in ('PAR!', 'BEAT', 'DIS!', 'D4? ', 'CROS', 'ERR ')]


def overlap(a, b):
    sa = [(n[0], n[0] + n[1]) for n in a if n[2] is not None]
    sb = [(n[0], n[0] + n[1]) for n in b if n[2] is not None]
    lo = max(min(x for x, _ in sa), min(x for x, _ in sb))
    hi = min(max(y for _, y in sa), max(y for _, y in sb))
    return max(F(0), hi - lo)


if __name__ == '__main__':
    a = sys.argv[1:]
    L, Fo = a[0], a[1]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    ivs = opt('--ivs', ','.join(IVS)).split(',')
    dmax = F(opt('--dmax', '16'))
    dmin = F(opt('--dmin', '0'))
    step = F(opt('--step', '1/2'))
    top = int(opt('--top', '20'))
    minover = F(opt('--minover', '8'))
    bass = '--bass' in a
    lead = form(L)
    fol0 = form(Fo)
    if '--aug-f' in a:
        fol0 = aug(fol0, int(opt('--aug-f', 2)))
    if '--aug-l' in a:
        lead = aug(lead, int(opt('--aug-l', 2)))
    res = []
    d = dmin
    while d <= dmax:
        for iv in ivs:
            st, se = IVS[iv]
            fol = real(fol0, st, se)
            if d >= 0:
                l2, f2 = lead, shift(fol, d)
            else:
                l2, f2 = shift(lead, -d), fol
            ov = overlap(l2, f2)
            if ov < minover:
                continue
            # decide which is upper by mean pitch
            ml = sum(n[2] for n in l2 if n[2]) / len([n for n in l2 if n[2]])
            mf = sum(n[2] for n in f2 if n[2]) / len([n for n in f2 if n[2]])
            up, lo = (l2, f2) if ml >= mf else (f2, l2)
            sc, issues = run(up, lo, bass)
            cr = cross_rel(up, lo)
            ql = quality(up, lo)
            sc += 4 * cr
            if cr: issues = [f"CROSS-RELATIONS {cr}"] + issues
            res.append((sc - 0.3 * ql, -ov, iv, d, issues + [f"quality {ql}"]))
        d += step
    res.sort(key=lambda r: (r[0], r[1]))
    for sc, nov, iv, d, issues in res[:top]:
        print(f"score {sc:5.1f} overlap {float(-nov):5.1f}  follower {Fo} {iv:5} at +{float(d):g} beats")
        for i in issues[:6]:
            print('      ', i)
