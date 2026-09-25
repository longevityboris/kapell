"""4-voice stretto search for S1-family entries (proposal 3).
Entries enter one per voice at a fixed spacing d (quarters). Forms: S1 (bbm) and ANS (fm) and SUB (ebm),
rectus or inversus (tonal mirror), at any octave that fits the voice range.
Pairwise screening with check.py + strict.py (cached), then full 4-voice verification."""
import itertools, sys, os, tempfile
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from p3 import *
from mats import S1, ANS, S1I

SUB = tr(S1, '-5')                 # e-flat minor form (ees...)
SUBI = tmirror(SUB) if False else tr(S1I, '-5')
FORMS = {'S1': S1, 'ANS': ANS, 'SUB': SUB, 'S1I': S1I, 'ANSI': tr(S1I, '5'), 'SUBI': tr(S1I, '-5')}
RNG = dict(soprano=(60, 84), alto=(53, 77), tenor=(48, 72), bass=(36, 62))


def fits(m, v):
    ps = [n.midi for n in m if n.step is not None]
    lo, hi = RNG[v]
    return lo <= min(ps) and max(ps) <= hi


def placements(form, v):
    out = []
    for k in range(-4, 3):
        m = octs(FORMS[form], k)
        if fits(m, v):
            out.append(k)
    return out


def run_parts(parts, bars):
    fd, p = tempfile.mkstemp(suffix='.ly', dir='/tmp')
    os.close(fd)
    write_lab(p, 'x', parts, bars)
    s, _ = check(p)
    d, _ = strict(p)
    os.unlink(p)
    return s, d


cache = {}


def pair_ok(e1, e2, bars):
    key = (e1, e2)
    if key in cache:
        return cache[key]
    (f1, k1, t1, v1), (f2, k2, t2, v2) = e1, e2
    parts = {v1: [at(octs(FORMS[f1], k1), t1)], v2: [at(octs(FORMS[f2], k2), t2)]}
    s, d = run_parts(parts, bars)
    ok = bad(s) == 0 and d.get('clash', 1) == 0
    cache[key] = (ok, s, d)
    return cache[key]


def search(d, order, forms_allowed, first='S1', bars=8, limit=40):
    voices = order
    cands = []
    for fs in itertools.product(forms_allowed, repeat=3):
        fs = (first,) + fs
        pls = [placements(f, v) for f, v in zip(fs, voices)]
        if not all(pls):
            continue
        for ks in itertools.product(*pls):
            entries = tuple((f, k, F(d * i), v) for i, (f, k, v) in enumerate(zip(fs, ks, voices)))
            # pitch order must follow voice order at entry points (rough): mean pitch descending by voice
            means = [sum(n.midi for n in octs(FORMS[f], k) if n.step is not None) / 20 for f, k, _, _ in entries]
            vidx = [VOICES.index(v) for v in voices]
            srt = [m for _, m in sorted(zip(vidx, means))]
            if srt != sorted(srt, reverse=True):
                continue
            cands.append(entries)
    print(f"d={d} order={order}: {len(cands)} candidates", file=sys.stderr)
    # pairwise screen (parallel over unique pairs)
    pairs = {(a, b) for c in cands for a, b in itertools.combinations(c, 2)}
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda ab: pair_ok(ab[0], ab[1], bars), pairs))
    good = [c for c in cands if all(cache[(a, b)][0] for a, b in itertools.combinations(c, 2))]
    print(f"  pairwise-clean: {len(good)}", file=sys.stderr)
    res = []

    def full4(c):
        parts = {}
        for f, k, t, v in c:
            parts[v] = [at(octs(FORMS[f], k), t)]
        s, dd = run_parts(parts, bars)
        return (bad(s), dd.get('clash', 9), dd.get('acc2', 9), dd.get('xrel', 9), dd.get('acc', 9), s['d4'] + s['dir']), c

    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(full4, good[:400]))
    res.sort(key=lambda r: r[0])
    for key, c in res[:limit]:
        print(key, ' | '.join(f"{v[0].upper()}:{f}{k:+d}@{float(t):g}" for f, k, t, v in c))
    return res


if __name__ == '__main__':
    d = int(sys.argv[1])
    order = sys.argv[2].split(',')
    forms = sys.argv[3].split(',')
    search(d, order, forms, first=sys.argv[4] if len(sys.argv) > 4 else 'S1', limit=25)
