"""Search chromatic-descending CS1 lines against S1 (bbm). Both orientations checked with the real checker.
Rhythm templates are lists of (start, dur) in quarters; pitches descend by 1 or 2 semitones per note."""
import itertools, sys
from concurrent.futures import ThreadPoolExecutor
from p3 import *

FLATS = {0: ('c', 0), 1: ('d', -1), 2: ('d', 0), 3: ('e', -1), 4: ('e', 0), 5: ('f', 0), 6: ('g', -1),
         7: ('g', 0), 8: ('a', -1), 9: ('a', 0), 10: ('b', -1), 11: ('c', -1)}   # 11 as ces (Neapolitan)


def mk(midis, rhythm):
    out = []
    for m, (t, d) in zip(midis, rhythm):
        l, a = FLATS[m % 12]
        o = m // 12 - 1
        if l == 'c' and a == -1:
            o += 1
        out.append(N(t, d, LET.index(l) + 7 * o, a))
    return out


RHY = {
    'halves': [(2 * i, 2) for i in range(8)],
    'rest+halves': [(2 * i, 2) for i in range(1, 8)] + [(16, 2)],
    'sync': [(1, 2)] + [(1 + 2 * i, 2) for i in range(1, 7)] + [(15, 1)],
}


def run(job):
    name, midis = job
    rh = RHY[name]
    cs = mk(midis, rh)
    s1, l1 = quick({'alto': [S1], 'tenor': [cs]}, 5)
    s2, l2 = quick({'soprano': [tr(cs, '8')], 'alto': [S1]}, 5)
    strong = sum(1 for l in l1 + l2 if l.startswith('DIS ') and ' strong ' in l)
    return (bad(s1) + bad(s2), s1['d4'] + s2['d4'] + s1['mel'] + s2['mel'] + s1['cros'] + s2['cros'], strong,
            name, [n.name() for n in cs], s1, s2)


if __name__ == '__main__':
    jobs = []
    for name, rh in RHY.items():
        n = len(rh)
        for start in range(52, 68):
            for steps in itertools.product((1, 2), repeat=n - 1):
                if sum(1 for s in steps if s == 1) < 3:
                    continue
                midis = [start]
                for s in steps:
                    midis.append(midis[-1] - s)
                if midis[-1] < 48:
                    continue
                jobs.append((name, midis))
    print(len(jobs), 'jobs', file=sys.stderr)
    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(run, jobs))
    res.sort(key=lambda r: (r[0], r[1], r[2]))
    for r in res[:60]:
        print(r[0], r[1], r[2], r[3], ' '.join(r[4]))
