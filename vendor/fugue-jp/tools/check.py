#!/usr/bin/env python3
"""Counterpoint checker for fugue.ly (voices written in \\absolute, 4/4).

usage: python3 check.py FILE.ly [--voices s,a,t,b] [--bars A-B] [--grid] [--quiet]
                        [--range name=lo-hi] [--measure 3/4]
Voices are \\absolute variables, listed highest first. Missing variables are skipped.
Reports: bar sums, ranges, parallel/antiparallel perfect intervals, accented
(beat-to-beat) perfects, direct perfects in outer voices, melodic problems,
voice crossing, and every dissonance with a heuristic justification.
"""
import re, sys
from fractions import Fraction as F
from bisect import bisect_right

_lyfiles = [a for a in sys.argv[1:] if a.endswith('.ly')]
SRC = open(_lyfiles[0] if _lyfiles else 'fugue.ly').read()
# --voices a,b,c : variable names, listed top (highest) to bottom (lowest)
_va = sys.argv[sys.argv.index('--voices') + 1] if '--voices' in sys.argv else 'soprano,alto,tenor,bass'
VOICES = _va.split(',')
ABBR = {v: (v[0].upper() if sum(w[0] == v[0] for w in VOICES) == 1 else v[:2].capitalize()) for v in VOICES}
# default ranges: piano keyboard A0-C8; override with --range name=lo-hi (MIDI numbers)
RANGE = {v: (21, 108) for v in VOICES}
for i, a in enumerate(sys.argv):
    if a == '--range':
        nm, lohi = sys.argv[i + 1].split('=')
        lo, hi = lohi.split('-')
        RANGE[nm] = (int(lo), int(hi))
# --measure N/D : bar length as a fraction of a whole note (default 1 = 4/4 or 2/2)
MEASURE = F(sys.argv[sys.argv.index('--measure') + 1]) if '--measure' in sys.argv else F(1)
PC = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)
LETTERS = 'cdefgab'

args = sys.argv[1:]
BARS = None
if '--bars' in args:
    a, b = args[args.index('--bars') + 1].split('-')
    BARS = (int(a), int(b))
GRID = '--grid' in args
QUIET = '--quiet' in args

TOK = re.compile(r"(?P<note>[a-g](?:isis|eses|is|es)?[',]*)(?P<dur>\d+)?(?P<dot>\.*)(?P<tie>~)?"
                 r"|(?P<rest>[rRs])(?P<rdur>\d+)?(?P<rdot>\.*)(?:\*(?P<mult>\d+))?"
                 r"|(?P<tie2>~)|(?P<bar>\|)|(?P<cmd>\\[a-zA-Z]+)|(?P<skip>[()\[\]\-^_!?.<>])")


class Note:
    def __init__(s, start, dur, midi, name, letter_abs):
        s.start, s.dur, s.midi, s.name, s.labs = start, dur, midi, name, letter_abs

    @property
    def end(s):
        return s.start + s.dur


def parse(voice):
    m = re.search(r"(?m)^" + voice + r"\s*=\s*\\absolute\s*\{(.*?)^\}", SRC, re.S | re.M)
    if not m:
        return None
    body = re.sub(r"%.*", "", m.group(1))
    t, dur, notes, tie_pending, barno, errs = F(0), F(1, 4), [], False, 1, []
    pos = 0
    body = body.strip()
    while pos < len(body):
        if body[pos].isspace():
            pos += 1
            continue
        mt = TOK.match(body, pos)
        if not mt:
            errs.append(f"{voice}: cannot parse near '{body[pos:pos+15]}'")
            pos += 1
            continue
        pos = mt.end()
        g = mt.groupdict()
        if g['note']:
            n = g['note']
            letter = n[0]
            acc = n[1:].rstrip("',")
            alter = {'': 0, 'is': 1, 'es': -1, 'isis': 2, 'eses': -2}[acc]
            octv = 3 + n.count("'") - n.count(",")
            midi = 12 * (octv + 1) + PC[letter] + alter
            if g['dur']:
                dur = F(1, int(g['dur']))
                d = dur
                for _ in g['dot']:
                    d = d / 2
                    dur += d
            name = letter.upper() + ('#' * alter if alter > 0 else 'b' * -alter) + str(octv)
            labs = LETTERS.index(letter) + 7 * octv
            if tie_pending and notes and notes[-1].midi == midi and notes[-1].end == t:
                notes[-1].dur += dur
            else:
                if tie_pending:
                    errs.append(f"{voice} bar {barno}: tie to different pitch {name}")
                notes.append(Note(t, dur, midi, name, labs))
            t += dur
            tie_pending = bool(g['tie'])
        elif g['rest']:
            if g['rdur']:
                dur = F(1, int(g['rdur']))
                d = dur
                for _ in g['rdot']:
                    d = d / 2
                    dur += d
            total = dur * (int(g['mult']) if g['mult'] else 1)
            notes.append(Note(t, total, None, '-', None))
            t += total
            tie_pending = False
        elif g['tie2']:
            tie_pending = True
        elif g['bar']:
            if t % MEASURE != 0:
                errs.append(f"{voice}: bar check failed at bar {barno} (pos {t})")
            barno = int(t / MEASURE) + 1
    return notes, t, errs


def at(notes, starts, t):
    i = bisect_right(starts, t) - 1
    if i < 0:
        return None
    n = notes[i]
    return n if n.start <= t < n.end and n.midi is not None else None


def neighbours(notes, n):
    i = notes.index(n)
    pv = notes[i - 1] if i > 0 and notes[i - 1].midi is not None and notes[i - 1].end == n.start else None
    nx = notes[i + 1] if i + 1 < len(notes) and notes[i + 1].midi is not None else None
    return pv, nx


def pos_str(t):
    bar = int(t / MEASURE) + 1
    beat = (t - (bar - 1) * MEASURE) * 4 + 1
    return f"{bar}:{float(beat):g}"


def inrange(t):
    if BARS is None:
        return True
    return BARS[0] <= int(t / MEASURE) + 1 <= BARS[1]


data, errors = {}, []
VOICES = [v for v in VOICES if parse(v) is not None]
pairs_all = None
for v in VOICES:
    notes, total, errs = parse(v)
    data[v] = (notes, [n.start for n in notes], total)
    errors += errs
totals = {v: data[v][2] for v in VOICES}
out = []
if len(set(totals.values())) != 1:
    errors.append(f"voice totals differ: { {v: str(x) for v, x in totals.items()} }")
END = max(totals.values())

# ranges and melodic checks
for v in VOICES:
    notes = [n for n in data[v][0] if n.midi is not None]
    lo, hi = RANGE[v]
    for n in notes:
        if not lo <= n.midi <= hi:
            errors.append(f"{v} {pos_str(n.start)} {n.name} out of range")
    for a, b in zip(data[v][0], data[v][0][1:]):
        if a.midi is None or b.midi is None or not inrange(b.start):
            continue
        semis, steps = b.midi - a.midi, b.labs - a.labs
        s, st = abs(semis), abs(steps)
        bad = None
        if st == 1 and s == 3: bad = 'aug2'
        elif st == 3 and s == 6: bad = 'aug4 leap'
        elif st == 4 and s == 6: bad = 'dim5 leap (resolve inward)'
        elif st == 3 and s == 4: bad = 'dim4 leap'
        elif st == 6: bad = '7th leap'
        elif s > 12: bad = 'leap > octave'
        elif st == 4 and s == 8: bad = 'aug5 leap'
        if bad:
            out.append(f"MEL  {ABBR[v]} {pos_str(b.start)} {a.name}->{b.name}: {bad}")

times = sorted({n.start for v in VOICES for n in data[v][0]})
def snd(v, t):
    return at(data[v][0], data[v][1], t)

# parallels
pairs = [(VOICES[i], VOICES[j]) for i in range(4) for j in range(i + 1, 4)]
for x, y in pairs:
    tl = sorted({n.start for n in data[x][0]} | {n.start for n in data[y][0]})
    for t1, t2 in zip(tl, tl[1:]):
        if not inrange(t2):
            continue
        a1, a2, b1, b2 = snd(x, t1), snd(x, t2), snd(y, t1), snd(y, t2)
        if None in (a1, a2, b1, b2):
            continue
        if a1.midi == a2.midi or b1.midi == b2.midi:
            continue
        i1, i2 = abs(a1.midi - b1.midi) % 12, abs(a2.midi - b2.midi) % 12
        if i1 == i2 and i1 in (0, 7):
            kind = 'P8/P1' if i1 == 0 else 'P5'
            same = (a2.midi - a1.midi) * (b2.midi - b1.midi) > 0
            out.append(f"PAR! {ABBR[x]}{ABBR[y]} {pos_str(t1)}->{pos_str(t2)} {kind} "
                       f"{'parallel' if same else 'contrary'} {a1.name}/{b1.name} -> {a2.name}/{b2.name}")
    # accented: beat to beat
    beats = [F(k, 4) for k in range(int(END * 4))]
    for t1, t2 in zip(beats, beats[1:]):
        if not inrange(t2):
            continue
        a1, a2, b1, b2 = snd(x, t1), snd(x, t2), snd(y, t1), snd(y, t2)
        if None in (a1, a2, b1, b2) or a1.midi == a2.midi or b1.midi == b2.midi:
            continue
        if a2.start != t2 and b2.start != t2:
            continue
        i1, i2 = abs(a1.midi - b1.midi) % 12, abs(a2.midi - b2.midi) % 12
        if i1 == i2 and i1 in (0, 7):
            # skip if already adjacent (reported above)
            tl_between = [t for t in tl if t1 < t < t2]
            if tl_between:
                out.append(f"BEAT {ABBR[x]}{ABBR[y]} {pos_str(t1)}->{pos_str(t2)} "
                           f"{'P8' if i1 == 0 else 'P5'} on successive beats {a1.name}/{b1.name} -> {a2.name}/{b2.name}")

# direct perfects in outer voices, crossing, dissonances
def lowest(t):
    s = [(snd(v, t).midi, v) for v in VOICES if snd(v, t)]
    return min(s) if s else None

prev_t = None
for t in times:
    if not inrange(t) or t >= END:
        prev_t = t
        continue
    sounding = {v: snd(v, t) for v in VOICES if snd(v, t)}
    # crossing
    order = [v for v in VOICES if v in sounding]
    for hi_v, lo_v in zip(order, order[1:]):
        if sounding[hi_v].midi < sounding[lo_v].midi:
            out.append(f"CROS {pos_str(t)} {ABBR[hi_v]} {sounding[hi_v].name} below {ABBR[lo_v]} {sounding[lo_v].name}")
    # direct perfects (soprano vs lowest)
    if prev_t is not None and 'soprano' in sounding:
        lw = lowest(t)
        lwp = lowest(prev_t)
        s0 = snd('soprano', prev_t)
        if lw and lwp and s0 and lw[1] == lwp[1] and lw[1] != 'soprano':
            b0, b1 = snd(lw[1], prev_t), sounding[lw[1]]
            sm, bm = sounding['soprano'].midi - s0.midi, b1.midi - b0.midi
            iv = (sounding['soprano'].midi - b1.midi) % 12
            if sm * bm > 0 and iv in (0, 7) and abs(sm) > 2 and sounding['soprano'].start == t:
                out.append(f"DIR  {pos_str(t)} S/{ABBR[lw[1]]} direct {'8ve' if iv == 0 else '5th'} (S leaps {s0.name}->{sounding['soprano'].name})")
    # dissonances
    lw = lowest(t)
    vs = list(sounding)
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            x, y = vs[i], vs[j]
            nx_, ny_ = sounding[x], sounding[y]
            if nx_.start != t and ny_.start != t:
                continue
            iv = abs(nx_.midi - ny_.midi) % 12
            low = min((nx_, x), (ny_, y), key=lambda p: p[0].midi)
            if iv in (1, 2, 10, 11):
                kind = {1: 'm2/m9', 2: 'M2/M9', 10: 'm7', 11: 'M7'}[iv]
            elif iv == 5 and low[0].midi == lw[0]:
                kind = 'P4/bass'
            elif iv == 6 and low[0].midi == lw[0]:
                kind = 'TT/bass'
            else:
                continue
            just = []
            for v in (x, y):
                n = sounding[v]
                pv, nxt = neighbours(data[v][0], n)
                si = pv is not None and 1 <= abs(n.midi - pv.midi) <= 2
                so = nxt is not None and 1 <= abs(nxt.midi - n.midi) <= 2
                held = n.start < t or (pv is not None and pv.midi == n.midi)
                i_n = data[v][0].index(n)
                nx2 = data[v][0][i_n + 2] if i_n + 2 < len(data[v][0]) else None
                restep = (nxt is not None and nxt.midi == n.midi and nx2 is not None
                          and nx2.midi is not None and 1 <= n.midi - nx2.midi <= 2)
                if si and so and n.start == t:
                    just.append(f"{ABBR[v]}:PT/NT")
                elif held and nxt is not None and nxt.midi < n.midi and so:
                    just.append(f"{ABBR[v]}:SUS")
                elif held and nxt is not None and nxt.midi == n.midi + 1 and so:
                    just.append(f"{ABBR[v]}:RET")
                elif n.start == t and so:
                    just.append(f"{ABBR[v]}:APP" if not si else f"{ABBR[v]}:APT")
                elif held and restep:
                    just.append(f"{ABBR[v]}:SUS(re)")
                elif n.start == t and nxt is not None and nxt.midi == n.midi and si:
                    just.append(f"{ABBR[v]}:ANT")
                elif n.start == t and restep:
                    just.append(f"{ABBR[v]}:ANT7")
                elif n.start == t and si and not so:
                    just.append(f"{ABBR[v]}:ESC?")
            strong = (t * 4) % 2 == 0
            tag = 'DIS ' if just else 'DIS!'
            if kind in ('P4/bass', 'TT/bass') and not just:
                tag = 'D4? '
            if QUIET and just and not strong:
                continue
            out.append(f"{tag} {pos_str(t)} {'strong' if strong else 'weak  '} {ABBR[x]}{ABBR[y]} {kind:7} "
                       f"{nx_.name}/{ny_.name}  [{', '.join(just) or 'UNJUSTIFIED'}]")
    prev_t = t

if GRID:
    for t in times:
        if not inrange(t) or t >= END:
            continue
        row = []
        for v in VOICES:
            n = snd(v, t)
            row.append(f"{ABBR[v]} {(n.name + ('*' if n.start == t else ' ')) if n else '  -  ':6}")
        lw = lowest(t)
        pcs = []
        for v in reversed(VOICES):
            n = snd(v, t)
            if n and n.name[:-1] not in pcs:
                pcs.append(n.name[:-1])
        print(f"{pos_str(t):7} " + '  '.join(row) + '   | ' + ' '.join(pcs))

for e in errors:
    print('ERR ', e)
for o in out:
    print(o)
print(f"-- totals: { {ABBR[v]: str(x) for v, x in totals.items()} }; "
      f"errors {len(errors)}, parallels {sum(o.startswith('PAR!') for o in out)}, "
      f"beat-par {sum(o.startswith('BEAT') for o in out)}, unjustified {sum(o.startswith('DIS!') for o in out)}")
