import sys
from fractions import Fraction as F
from search import *

def matrix(leader, fol, label, offs, names=None):
    print(f"=== {label}   (penalty; '.'=0, cols = offset in quarters)")
    print("        " + ''.join(f"{str(int(o*4)):>4}" for o in offs))
    rows = list(REAL.items()) + [(f'd{d:+d}', d) for d in range(-15, 16) if d % 7 != 0]
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

if __name__ == '__main__':
    offs = [F(k, 4) for k in range(0, 17)]
    w = sys.argv[1]
    if w == 'stretto': matrix(S1, S1, 'S1 x S1', offs[1:])
    if w == 'mirror':
        matrix(S1, I1, 'S1 leader x I1 follower', offs)
        matrix(I1, S1, 'I1 leader x S1 follower', offs[1:])
    if w == 'inv': matrix(I1, I1, 'I1 x I1', offs[1:])
    if w == 's1s2':
        matrix(S1, S2, 'S1 leader x S2 follower', offs + [F(k,4) for k in range(17,21)])
        matrix(S2, S1, 'S2 leader x S1 follower', offs[1:])
