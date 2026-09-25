from fractions import Fraction as F
from search import *
from mats import *

def mat(leader, fol, label, offs, rows=None):
    print(f"=== {label}   (penalty; '.'=0, cols = offset in quarters)")
    print("        " + ''.join(f"{str(int(o*4)):>4}" for o in offs))
    rows = rows or (list(REAL.items()) + [(f'd{d:+d}', d) for d in range(-15, 16) if d % 7 != 0])
    for name, amt in rows:
        kind = 'r' if name in REAL else 'd'
        cells = []
        for dt in offs:
            f = follower(fol, kind, amt, dt)
            lead_avg = sum(p[1] for s, d, p in leader if p) / len(leader)
            fol_avg = sum(p[1] for s, d, p in f if p) / len(f)
            U, L = (f, leader) if fol_avg >= lead_avg else (leader, f)
            pen, notes = evaluate(U, L)
            cells.append('   .' if pen == 0 else f"{pen:4.0f}" if pen < 100 else ' 99')
        print(f"{name:7} " + ''.join(cells))

import sys
w = sys.argv[1]
offs = [F(k, 4) for k in range(0, 33, 2)]
if w == 'aug':   # augmented S1 in the bass (leader, 2 octaves down), normal S1 above as follower
    mat(octave(S1aug, -2), S1, 'S1aug (bass) x S1', offs)
if w == 'augI':
    mat(octave(S1aug, -2), I1, 'S1aug (bass) x I1', offs)
if w == 'augS2':
    mat(octave(S1aug, -2), S2, 'S1aug (bass) x S2', offs)
if w == 'Maug':
    mat(octave(S1Maug, -2), THEMEM, 'S1Maug (bass) x THEME major', offs)
if w == 'A1aug':
    mat(octave(A1aug, -3), S1, 'A1aug (bass, F pedal) x S1', offs)
    mat(octave(A1aug, -3), I1, 'A1aug (bass, F pedal) x I1', offs)
    mat(octave(A1aug, -3), S2, 'A1aug (bass, F pedal) x S2', offs)
