#!/usr/bin/env python3
"""Proposal-3 lab toolkit: spelled-pitch melodies, transforms, LilyPond writer, checker runner.

Time unit: quarter note (Fraction). 4/4 bars of 4 quarters. Pitches are spelled
(letter index + alteration) so transpositions keep correct flats/sharps.

  m = mel("bes'2. bes'8 a' | ...")          parse a LilyPond \\absolute fragment
  tr(m, '5')  / tr(m, -7, -12)                transpose by named interval or (steps, semis)
  inv(m, axis_lo, axis_hi)                    chromatic mirror (spelled diatonically)
  aug(m, 2), at(m, t)                         augmentation, time shift
  write_lab(path, header, {'soprano': [(t, m), ...], ...}, bars)
  check(path) -> (summary_dict, lines)        runs ricercar/tools/check.py with the ranges
"""
import os, re, subprocess, sys, tempfile
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, '..', '..', '..', 'tools', 'check.py')
RANGES = dict(soprano=(60, 84), alto=(53, 77), tenor=(48, 72), bass=(36, 62))
VOICES = ['soprano', 'alto', 'tenor', 'bass']
LET = 'cdefgab'
NAT = [0, 2, 4, 5, 7, 9, 11]
TOK = re.compile(r"(?P<n>[a-g](?:isis|eses|is|es)?[',]*|[rRs])(?P<d>\d+)?(?P<dot>\.*)(?:\*(?P<mult>\d+))?(?P<tie>~)?|\|")


class N:
    """note: start t, duration d (quarters), step (abs diatonic index, c'=28) and alter; step None = rest"""
    __slots__ = ('t', 'd', 'step', 'alt', 'tie')

    def __init__(s, t, d, step=None, alt=0, tie=False):
        s.t, s.d, s.step, s.alt, s.tie = F(t), F(d), step, alt, tie

    @property
    def midi(s):
        if s.step is None:
            return None
        o, l = divmod(s.step, 7)
        return 12 * (o + 1) + NAT[l] + s.alt

    def name(s):
        if s.step is None:
            return 'r'
        o, l = divmod(s.step, 7)
        acc = {0: '', 1: 'is', 2: 'isis', -1: 'es', -2: 'eses'}[s.alt]
        base = LET[l] + acc
        base = base.replace('ees', 'es').replace('aes', 'as') if False else base
        octs = o - 3
        return base + ("'" * octs if octs > 0 else "," * (-octs))

    def copy(s, **kw):
        n = N(s.t, s.d, s.step, s.alt, s.tie)
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    def __repr__(s):
        return f"{s.name()}@{float(s.t):g}/{float(s.d):g}"


def mel(src, t0=0):
    t, dur, out = F(t0), F(1), []
    tie = False
    for m in TOK.finditer(re.sub(r"%.*", "", src)):
        if m.group(0) == '|':
            continue
        n = m.group('n')
        if m.group('d'):
            dur = F(4, int(m.group('d')))
            add = dur
            for _ in m.group('dot'):
                add /= 2
                dur += add
        d = dur * (int(m.group('mult')) if m.group('mult') else 1)
        if n in ('r', 'R', 's'):
            out.append(N(t, d))
            tie = False
        else:
            acc = n[1:].rstrip("',")
            alt = {'': 0, 'is': 1, 'es': -1, 'isis': 2, 'eses': -2, 's': -1}[acc]
            octv = 3 + n.count("'") - n.count(",")
            step = LET.index(n[0]) + 7 * octv
            if tie and out and out[-1].step == step and out[-1].alt == alt:
                out[-1].d += d
            else:
                out.append(N(t, d, step, alt))
            tie = bool(m.group('tie'))
        t += d
    return out


IV = {'1': (0, 0), 'm2': (1, 1), '2': (1, 2), 'm3': (2, 3), '3': (2, 4), '4': (3, 5), 'a4': (3, 6),
      'd5': (4, 6), '5': (4, 7), 'm6': (5, 8), '6': (5, 9), 'm7': (6, 10), '7': (6, 11), '8': (7, 12),
      'm9': (8, 13), '9': (8, 14), 'm10': (9, 15), '10': (9, 16), '11': (10, 17), '12': (11, 19)}


def tr(m, steps, semis=None):
    """transpose; steps may be an interval name ('5', '-4', 'm3') or diatonic steps with semis"""
    if isinstance(steps, str):
        neg = steps.startswith('-')
        st, se = IV[steps.lstrip('-')]
        steps, semis = (-st, -se) if neg else (st, se)
    out = []
    for n in m:
        if n.step is None:
            out.append(n.copy())
            continue
        ns = n.step + steps
        o, l = divmod(ns, 7)
        target = n.midi + semis
        alt = target - (12 * (o + 1) + NAT[l])
        out.append(n.copy(step=ns, alt=alt))
    return out


def respell(m, fn):
    """fn(note) -> (step, alt) or None to keep"""
    out = []
    for n in m:
        r = fn(n) if n.step is not None else None
        out.append(n.copy(step=r[0], alt=r[1]) if r else n.copy())
    return out


def inv(m, axis_step, axis_midi2):
    """mirror: new_step = axis_step - step ; new_midi = axis_midi2 - midi (axis_midi2 = sum of the pair)"""
    out = []
    for n in m:
        if n.step is None:
            out.append(n.copy())
            continue
        ns = axis_step - n.step
        o, l = divmod(ns, 7)
        target = axis_midi2 - n.midi
        out.append(n.copy(step=ns, alt=target - (12 * (o + 1) + NAT[l])))
    return out


def aug(m, k=2):
    return [n.copy(t=n.t * k, d=n.d * k) for n in m]


def at(m, dt):
    return [n.copy(t=n.t + F(dt)) for n in m]


def setpitch(m, idx, name):
    """replace pitch of note idx with LilyPond name (keeps rhythm)"""
    x = mel(name + '4')[0]
    m = [n.copy() for n in m]
    m[idx].step, m[idx].alt = x.step, x.alt
    return m


def end(m):
    return max(n.t + n.d for n in m) if m else F(0)


# ---------------- LilyPond writer ----------------
DUR = [(F(4), '1'), (F(3), '2.'), (F(2), '2'), (F(3, 2), '4.'), (F(1), '4'), (F(3, 4), '8.'),
       (F(1, 2), '8'), (F(3, 8), '16.'), (F(1, 4), '16'), (F(1, 8), '32')]


def _pieces(t, d, bar=F(4)):
    """split [t, t+d) at barlines and half-bars where needed into notatable values"""
    out = []
    while d > 0:
        room = bar - (t % bar)
        seg = min(d, room)
        # greedy but keep dotted values aligned to their own grid
        for v, s in DUR:
            if v <= seg and (t % min(v, F(2)) == 0 or v <= F(1, 2) or (v == F(3, 2) and t % F(1, 2) == 0) or (v == F(2) and t % 1 == 0)
                             or (v == F(3) and t % bar == 0) or (v == F(3, 4) and t % F(1, 4) == 0)):
                out.append((t, v, s))
                t += v
                d -= v
                seg -= v
                break
        else:
            v, s = [(v, s) for v, s in DUR if v <= seg][0]
            out.append((t, v, s))
            t += v
            d -= v
    return out


def to_ly(m, total, t0=0, bar=F(4)):
    """voice string for notes m (absolute times) filling [t0, total) with rests"""
    toks, t = [], F(t0)
    items = sorted([n for n in m if n.t >= t0], key=lambda n: n.t)
    full = []
    for n in items:
        if n.t > t:
            full.append(N(t, n.t - t))
        full.append(n)
        t = n.t + n.d
    if t < total:
        full.append(N(t, total - t))
    out, cur = [], None
    for n in full:
        ps = _pieces(n.t, n.d, bar)
        for i, (pt, pv, ps_) in enumerate(ps):
            if pt % bar == 0 and pt > t0:
                out.append('|')
                if (pt - t0) % (bar * 4) == 0:
                    out.append('\n ')
            if n.step is None:
                if pv == bar and pt % bar == 0:
                    out.append('R1')
                else:
                    out.append('r' + ps_)
            else:
                out.append(n.name() + ps_ + ('~' if i < len(ps) - 1 else ''))
    out.append('|')
    return ' '.join(out).replace('| \n  ', '|\n  ')


def write_lab(path, header, parts, bars, extra=''):
    """parts: voice -> list of melodies (absolute times). Writes a 4-voice lab file."""
    total = F(bars) * 4
    lines = ['% ' + l for l in header.strip().split('\n')]
    lines.append(extra)
    for v in VOICES:
        m = [n for seg in parts.get(v, []) for n in seg]
        lines.append(f"{v} = \\absolute {{\n  {to_ly(m, total)}\n}}")
    open(path, 'w').write('\n'.join(lines) + '\n')


def check(path, bars=None, extra=()):
    cmd = [sys.executable, CHECK, path, '--voices', 'soprano,alto,tenor,bass']
    for v, (lo, hi) in RANGES.items():
        cmd += ['--range', f'{v}={lo}-{hi}']
    if bars:
        cmd += ['--bars', bars]
    cmd += list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = r.stdout.strip().split('\n')
    s = dict(err=0, par=0, beat=0, dis=0, d4=0, mel=0, cros=0, dir=0)
    for l in lines:
        for k, p in (('err', 'ERR'), ('par', 'PAR!'), ('beat', 'BEAT'), ('dis', 'DIS!'), ('d4', 'D4?'),
                     ('mel', 'MEL'), ('cros', 'CROS'), ('dir', 'DIR')):
            if l.startswith(p):
                s[k] += 1
    if r.returncode != 0:
        s['err'] += 1
        lines.append(r.stderr[-500:])
    return s, lines


def bad(s):
    return s['err'] + s['par'] + s['beat'] + s['dis']


def quick(parts, bars, name='tmp', extra=()):
    fd, p = tempfile.mkstemp(suffix='.ly', prefix=name, dir='/tmp')
    os.close(fd)
    write_lab(p, 'tmp', parts, bars)
    s, lines = check(p, extra=extra)
    os.unlink(p)
    return s, lines


# ---------------- materials (B-flat minor) ----------------
S1 = mel("bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 c'' | bes'2")


# ---------------- search ----------------
def pair_search(A, B, dts, ivs, va='alto', vb='soprano', bars=None, extra_parts=None, show=15, keep=None):
    """A fixed in voice va; B shifted by dt (quarters) and transposed by each interval in ivs, in voice vb.
    Runs the real checker on each combination; prints the clean ones ranked."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = []
    for dt in dts:
        for iv in ivs:
            b = at(tr(B, iv), dt)
            nb = bars or int((max(end(A), end(b)) + 3) // 4)
            parts = {va: [A], vb: [b]}
            if extra_parts:
                for k, v in extra_parts.items():
                    parts.setdefault(k, []).extend(v)
            jobs.append((dt, iv, parts, nb))

    def run(j):
        dt, iv, parts, nb = j
        s, lines = quick(parts, nb)
        strong = sum(1 for l in lines if l.startswith('DIS ') and ' strong ' in l)
        return (bad(s), s['d4'] + s['mel'] + s['cros'], strong, dt, iv, s, lines)

    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(run, jobs))
    res.sort(key=lambda r: (r[0], r[1], r[2]))
    for r in res[:show]:
        b_, soft, strong, dt, iv, s, lines = r
        print(f"bad {b_:2} soft {soft:2} strongdis {strong:2}  dt {float(dt):5g}q  iv {iv:>4}  "
              + ' '.join(f"{k}={v}" for k, v in s.items() if v))
    return res


def show(parts, bars, grid=True, quiet=False, path='/tmp/p3show.ly'):
    write_lab(path, 'show', parts, bars)
    ex = (['--grid'] if grid else []) + (['--quiet'] if quiet else [])
    s, lines = check(path, extra=ex)
    print('\n'.join(lines))
    return s


IVS_DOWN = ['-1', '-m2', '-2', '-m3', '-3', '-4', '-5', '-m6', '-6', '-m7', '-7', '-8', '-m9', '-9', '-m10', '-10', '-11', '-12']


def octs(m, k):
    return tr(m, 7 * k, 12 * k)


def perms3(lines, names, bars, voice_sets=(('soprano', 'alto', 'tenor'), ('alto', 'tenor', 'bass')), verbose=False):
    """Triple-counterpoint test: every vertical order of three lines, octave-placed without crossing
    (smallest spread), checked with the real checker. lines: dict name -> melody."""
    import itertools
    res = []
    for order in itertools.permutations(names):
        best = None
        base = lines[order[0]]
        for k1 in range(-4, 2):
            for k2 in range(-5, 1):
                mid = octs(lines[order[1]], k1)
                low = octs(lines[order[2]], k2)
                # no crossing: sampled at every onset
                ok = True
                ts = sorted({n.t for m in (base, mid, low) for n in m})
                spread = 0
                for t in ts:
                    a, b, c = [next((n.midi for n in m if n.step is not None and n.t <= t < n.t + n.d), None) for m in (base, mid, low)]
                    if a is not None and b is not None and b > a: ok = False
                    if b is not None and c is not None and c > b: ok = False
                    if a is not None and c is not None and c > a: ok = False
                    if a is not None and c is not None:
                        spread = max(spread, a - c)
                if ok and (best is None or spread < best[0]):
                    best = (spread, k1, k2, mid, low)
        if best is None:
            res.append((order, None, 'no placement'))
            continue
        spread, k1, k2, mid, low = best
        # shift whole block so that it sits in ranges: try both voice sets
        out = []
        for vs in voice_sets:
            for sh in range(-3, 3):
                parts = {vs[0]: [octs(base, sh)], vs[1]: [octs(mid, sh)], vs[2]: [octs(low, sh)]}
                s, lines_ = quick(parts, bars)
                if s['err'] == 0:
                    out.append((bad(s), s['d4'], vs, sh, s, lines_))
        out.sort(key=lambda x: (x[0], x[1]))
        res.append((order, (k1, k2, spread), out[0] if out else 'no range fit'))
    for order, pl, r in res:
        if isinstance(r, str) or r is None:
            print(order, pl, r)
            continue
        b_, d4, vs, sh, s, lines_ = r
        print(' > '.join(order), f"oct {pl}", f"voices {vs} shift {sh}", f"bad {b_} d4 {d4}",
              ' '.join(f"{k}={v}" for k, v in s.items() if v))
        if verbose:
            print('\n'.join('     ' + l for l in lines_ if not l.startswith('DIS ') or 'D4' in l))
    return res


def place(lines_in_order, kmin=-5, kmax=3):
    """octave-place lines (top->bottom) without crossing, minimal spread; returns list of octave shifts"""
    import itertools
    base = lines_in_order[0]
    ts = sorted({n.t for m in lines_in_order for n in m})

    def val(m, t):
        return next((n.midi for n in m if n.step is not None and n.t <= t < n.t + n.d), None)
    best = None
    for ks in itertools.product(range(kmin, kmax), repeat=len(lines_in_order) - 1):
        ms = [base] + [octs(m, k) for m, k in zip(lines_in_order[1:], ks)]
        ok, spread = True, 0
        for t in ts:
            vals = [val(m, t) for m in ms]
            pres = [v for v in vals if v is not None]
            if pres != sorted(pres, reverse=True):
                ok = False
                break
            if len(pres) >= 2:
                spread = max(spread, pres[0] - pres[-1])
        if ok and (best is None or spread < best[0]):
            best = (spread, ks, ms)
    return best


def permsN(lines, names, bars, show_all=False, voices=VOICES):
    import itertools
    res = []
    for order in itertools.permutations(names):
        b = place([lines[n] for n in order])
        if b is None:
            res.append((order, None))
            continue
        spread, ks, ms = b
        n = len(order)
        best = None
        vsets = [tuple(voices[i:i + n]) for i in range(0, len(voices) - n + 1)]
        for vs in vsets:
            for sh in range(-3, 3):
                parts = {v: [octs(m, sh)] for v, m in zip(vs, ms)}
                s, ls = quick(parts, bars)
                if s['err'] == 0:
                    key = (bad(s), s['d4'], s['dir'])
                    if best is None or key < best[0]:
                        best = (key, vs, sh, s, ls, ks)
        res.append((order, best))
    ok = 0
    for order, best in res:
        if best is None:
            print(' > '.join(order), '-- no placement/range fit')
            continue
        key, vs, sh, s, ls, ks = best
        ok += key[0] == 0
        if show_all or key[0] == 0:
            print(' > '.join(order), f"oct{ks} sh{sh}", f"bad {key[0]} d4 {key[1]} dir {key[2]}")
    print(f"clean orders: {ok}/{len(res)}")
    return res


def strict(path, extra=()):
    r = subprocess.run([sys.executable, os.path.join(HERE, 'strict.py'), path, '-v'] + list(extra),
                       capture_output=True, text=True)
    lines = r.stdout.strip().split('\n')
    last = lines[-1]
    import re as _re
    m = _re.search(r"clash (\d+), xrel (\d+), acc (\d+), acc2 (\d+)", last)
    d = dict(zip(('clash', 'xrel', 'acc', 'acc2'), map(int, m.groups()))) if m else {}
    return d, lines


def full(parts, bars, path='/tmp/p3full.ly'):
    write_lab(path, 'full', parts, bars)
    s, l1 = check(path)
    d, l2 = strict(path)
    return s, d, l1, l2


def pair_search2(A, B, dts, ivs, va='alto', vb='soprano', bars=None, extra_parts=None, show=15):
    """like pair_search but also runs strict.py; ranks by (bad, clash, acc2, xrel, acc, soft)"""
    from concurrent.futures import ThreadPoolExecutor
    jobs = []
    for dt in dts:
        for iv in ivs:
            b = at(tr(B, iv), dt)
            nb = bars or int((max(end(A), end(b)) + 3) // 4)
            parts = {va: [A], vb: [b]}
            if extra_parts:
                for k, v in extra_parts.items():
                    parts.setdefault(k, []).extend(v)
            jobs.append((dt, iv, parts, nb))

    def run(j):
        dt, iv, parts, nb = j
        fd, p = tempfile.mkstemp(suffix='.ly', dir='/tmp')
        os.close(fd)
        write_lab(p, 'x', parts, nb)
        s, _ = check(p)
        d, _ = strict(p)
        os.unlink(p)
        key = (bad(s), d.get('clash', 9), d.get('acc2', 9), d.get('xrel', 9), d.get('acc', 9), s['d4'] + s['mel'] + s['cros'] + s['dir'])
        return key, dt, iv, s, d

    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(run, jobs))
    res.sort(key=lambda r: r[0])
    for key, dt, iv, s, d in res[:show]:
        print(f"key {key}  dt {float(dt):5g}q  iv {iv:>4}")
    return res


# tonal mirror in B-flat harmonic minor about des (degree 2): bes<->f, c<->ees, des<->des, a<->ges, g<->aes, e<->ces
_HM = [('b', -1), ('c', 0), ('d', -1), ('e', -1), ('f', 0), ('g', -1), ('a', 0)]   # bes c des ees f ges a


def tmirror(m, axis_oct_shift=0):
    """tonal mirror about des (B-flat harmonic minor scale degrees d -> 4 - d, alterations flipped).
    Octave: bes' <-> f' (i.e. the mirror of bes' is f')."""
    out = []
    for n in m:
        if n.step is None:
            out.append(n.copy())
            continue
        # degree relative to bes (scale index from the letter), octave-aware via diatonic step
        # diatonic step of bes' = 34 (b=6 + 7*4); degree = step - 34 (+ octave multiples)
        deg = n.step - 34
        letter_idx = n.step % 7
        # base alteration of this letter in harmonic minor
        base = {6: -1, 0: 0, 1: -1, 2: -1, 3: 0, 4: -1, 5: 0}[letter_idx]
        dev = n.alt - base
        nd = 4 - deg + 34 - 4  # mirror: degree d -> 4 - d, anchored so bes'(34) -> f'(34+4-4... )
        # anchor: bes' (deg 0) -> f' (step 31: f=3 + 7*4 = 31)
        nstep = 31 - deg
        nl = nstep % 7
        nbase = {6: -1, 0: 0, 1: -1, 2: -1, 3: 0, 4: -1, 5: 0}[nl]
        out.append(n.copy(step=nstep + 7 * axis_oct_shift, alt=nbase - dev))
    return out
