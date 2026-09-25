"""Counterpoint checker for \\absolute LilyPond voices (refactored from fugue-jp tools/check.py).

run(path, voices=None, bars=None, measure=None, ranges=None, src=None, quiet=False) -> dict

Reports bar sums, ranges, parallel/antiparallel perfect intervals, accented (beat-to-beat)
perfects, direct perfects in the outer voices, melodic problems, voice crossing, and every
dissonance with a heuristic justification. Behaviour and line texts match the original script.

Returned dict:
  totals       {voices: {abbr: length}, errors, parallels, beat_parallels, unjustified,
                crossings, directs, melodic, d4, dissonances}
  violations   items that fail a check (ERR, PAR!, BEAT, DIS!), each {kind, pos, line}
  review       items for a human ear (CROS, DIR, MEL, D4?), same shape
  dissonances  justified dissonances (DIS), same shape plus {strong, just}
  lines        the original script's text output, in its order (summary last)
"""
import re
from bisect import bisect_right
from fractions import Fraction as F

from kapell.analysis import parse_bars, parse_measure, parse_voices, read_source

PC = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)
LETTERS = 'cdefgab'
VIOLATION_KINDS = ('ERR', 'PAR!', 'BEAT', 'DIS!')
REVIEW_KINDS = ('CROS', 'DIR', 'MEL', 'D4?')

TOK = re.compile(r"(?P<note>[a-g](?:isis|eses|is|es)?[',]*)(?P<dur>\d+)?(?P<dot>\.*)(?P<tie>~)?"
                 r"|(?P<rest>[rRs])(?P<rdur>\d+)?(?P<rdot>\.*)(?:\*(?P<mult>\d+))?"
                 r"|(?P<tie2>~)|(?P<bar>\|)|(?P<cmd>\\[a-zA-Z]+)|(?P<skip>[()\[\]\-^_!?.<>])")


class Note:
    __slots__ = ('start', 'dur', 'midi', 'name', 'labs')

    def __init__(s, start, dur, midi, name, letter_abs):
        s.start, s.dur, s.midi, s.name, s.labs = start, dur, midi, name, letter_abs

    @property
    def end(s):
        return s.start + s.dur


def _dur(num, dots):
    dur = F(1, int(num))
    d = dur
    for _ in dots:
        d = d / 2
        dur += d
    return dur


def parse(src, voice, measure=F(1)):
    """-> (notes, total, errors) or None if the variable is missing. Keeps check.py's error reports."""
    m = re.search(r"(?m)^" + re.escape(voice) + r"\s*=\s*\\absolute\s*\{(.*?)^\}", src, re.S | re.M)
    if not m:
        return None
    body = re.sub(r"%.*", "", m.group(1)).strip()
    t, dur, notes, tie_pending, barno, errs = F(0), F(1, 4), [], False, 1, []
    pos = 0
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
                dur = _dur(g['dur'], g['dot'])
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
                dur = _dur(g['rdur'], g['rdot'])
            total = dur * (int(g['mult']) if g['mult'] else 1)
            notes.append(Note(t, total, None, '-', None))
            t += total
            tie_pending = False
        elif g['tie2']:
            tie_pending = True
        elif g['bar']:
            if t % measure != 0:
                errs.append(f"{voice}: bar check failed at bar {barno} (pos {t})")
            barno = int(t / measure) + 1
    return notes, t, errs


def run(path=None, voices=None, bars=None, measure=None, ranges=None, src=None, quiet=False):
    src = read_source(path, src)
    voices = parse_voices(voices)
    measure = parse_measure(measure)
    bars = parse_bars(bars)
    abbr = {v: (v[0].upper() if sum(w[0] == v[0] for w in voices) == 1 else v[:2].capitalize()) for v in voices}
    rng = {v: (21, 108) for v in voices}
    for k, lohi in (ranges or {}).items():
        if isinstance(lohi, str):
            lo, hi = lohi.split('-')
            lohi = (lo, hi)
        rng[k] = (int(lohi[0]), int(lohi[1]))

    def pos_str(t):
        bar = int(t / measure) + 1
        beat = (t - (bar - 1) * measure) * 4 + 1
        return f"{bar}:{float(beat):g}"

    def inrange(t):
        return bars is None or bars[0] <= int(t / measure) + 1 <= bars[1]

    parsed = {v: parse(src, v, measure) for v in voices}
    voices = [v for v in voices if parsed[v] is not None]
    if not voices:
        return {'totals': {'voices': {}, 'errors': 1, 'parallels': 0, 'beat_parallels': 0, 'unjustified': 0},
                'violations': [{'kind': 'ERR', 'pos': None, 'line': 'ERR  no voices found'}],
                'review': [], 'dissonances': [], 'lines': ['ERR  no voices found']}
    data, errors = {}, []
    for v in voices:
        notes, total, errs = parsed[v]
        data[v] = (notes, [n.start for n in notes], total)
        errors += errs
    index = {v: {id(n): i for i, n in enumerate(data[v][0])} for v in voices}
    totals = {v: data[v][2] for v in voices}
    out = []  # (kind, pos, line, extra)
    if len(set(totals.values())) != 1:
        errors.append(f"voice totals differ: { {v: str(x) for v, x in totals.items()} }")
    END = max(totals.values())

    def item(kind, t, line, **extra):
        out.append(dict(kind=kind, pos=pos_str(t) if t is not None else None, line=line, **extra))

    # ranges and melodic checks
    for v in voices:
        lo, hi = rng.get(v, (21, 108))
        for n in data[v][0]:
            if n.midi is not None and not lo <= n.midi <= hi:
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
                item('MEL', b.start, f"MEL  {abbr[v]} {pos_str(b.start)} {a.name}->{b.name}: {bad}")

    times = sorted({n.start for v in voices for n in data[v][0]})

    def snd(v, t):
        notes, starts, _ = data[v]
        i = bisect_right(starts, t) - 1
        if i < 0:
            return None
        n = notes[i]
        return n if n.start <= t < n.end and n.midi is not None else None

    # parallels
    nv = len(voices)
    pairs = [(voices[i], voices[j]) for i in range(nv) for j in range(i + 1, nv)]
    beats = [F(k, 4) for k in range(int(END * 4))]
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
                item('PAR!', t1, f"PAR! {abbr[x]}{abbr[y]} {pos_str(t1)}->{pos_str(t2)} {kind} "
                     f"{'parallel' if same else 'contrary'} {a1.name}/{b1.name} -> {a2.name}/{b2.name}")
        # accented: beat to beat
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
                if any(t1 < t < t2 for t in tl):  # adjacent ones were reported above
                    item('BEAT', t1, f"BEAT {abbr[x]}{abbr[y]} {pos_str(t1)}->{pos_str(t2)} "
                         f"{'P8' if i1 == 0 else 'P5'} on successive beats {a1.name}/{b1.name} -> {a2.name}/{b2.name}")

    def lowest(t):
        s = [(snd(v, t).midi, v) for v in voices if snd(v, t)]
        return min(s) if s else None

    def neighbours(v, n):
        notes = data[v][0]
        i = index[v][id(n)]
        pv = notes[i - 1] if i > 0 and notes[i - 1].midi is not None and notes[i - 1].end == n.start else None
        nx = notes[i + 1] if i + 1 < len(notes) and notes[i + 1].midi is not None else None
        return pv, nx

    top = voices[0]
    prev_t = None
    for t in times:
        if not inrange(t) or t >= END:
            prev_t = t
            continue
        sounding = {v: snd(v, t) for v in voices if snd(v, t)}
        order = [v for v in voices if v in sounding]
        for hi_v, lo_v in zip(order, order[1:]):
            if sounding[hi_v].midi < sounding[lo_v].midi:
                item('CROS', t, f"CROS {pos_str(t)} {abbr[hi_v]} {sounding[hi_v].name} below "
                     f"{abbr[lo_v]} {sounding[lo_v].name}")
        # direct perfects (top voice vs lowest)
        if prev_t is not None and top in sounding:
            lw, lwp, s0 = lowest(t), lowest(prev_t), snd(top, prev_t)
            if lw and lwp and s0 and lw[1] == lwp[1] and lw[1] != top:
                b0, b1 = snd(lw[1], prev_t), sounding[lw[1]]
                sm, bm = sounding[top].midi - s0.midi, b1.midi - b0.midi
                iv = (sounding[top].midi - b1.midi) % 12
                if sm * bm > 0 and iv in (0, 7) and abs(sm) > 2 and sounding[top].start == t:
                    item('DIR', t, f"DIR  {pos_str(t)} {abbr[top]}/{abbr[lw[1]]} direct "
                         f"{'8ve' if iv == 0 else '5th'} ({abbr[top]} leaps {s0.name}->{sounding[top].name})")
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
                    pv, nxt = neighbours(v, n)
                    si = pv is not None and 1 <= abs(n.midi - pv.midi) <= 2
                    so = nxt is not None and 1 <= abs(nxt.midi - n.midi) <= 2
                    held = n.start < t or (pv is not None and pv.midi == n.midi)
                    i_n = index[v][id(n)]
                    nx2 = data[v][0][i_n + 2] if i_n + 2 < len(data[v][0]) else None
                    restep = (nxt is not None and nxt.midi == n.midi and nx2 is not None
                              and nx2.midi is not None and 1 <= n.midi - nx2.midi <= 2)
                    if si and so and n.start == t:
                        just.append(f"{abbr[v]}:PT/NT")
                    elif held and nxt is not None and nxt.midi < n.midi and so:
                        just.append(f"{abbr[v]}:SUS")
                    elif held and nxt is not None and nxt.midi == n.midi + 1 and so:
                        just.append(f"{abbr[v]}:RET")
                    elif n.start == t and so:
                        just.append(f"{abbr[v]}:APP" if not si else f"{abbr[v]}:APT")
                    elif held and restep:
                        just.append(f"{abbr[v]}:SUS(re)")
                    elif n.start == t and nxt is not None and nxt.midi == n.midi and si:
                        just.append(f"{abbr[v]}:ANT")
                    elif n.start == t and restep:
                        just.append(f"{abbr[v]}:ANT7")
                    elif n.start == t and si and not so:
                        just.append(f"{abbr[v]}:ESC?")
                strong = (t * 4) % 2 == 0
                tag = 'DIS ' if just else 'DIS!'
                if kind in ('P4/bass', 'TT/bass') and not just:
                    tag = 'D4? '
                if quiet and just and not strong:
                    continue
                item(tag.strip(), t, f"{tag} {pos_str(t)} {'strong' if strong else 'weak  '} {abbr[x]}{abbr[y]} "
                     f"{kind:7} {nx_.name}/{ny_.name}  [{', '.join(just) or 'UNJUSTIFIED'}]",
                     strong=bool(strong), interval=kind, just=just)
        prev_t = t

    err_items = [dict(kind='ERR', pos=None, line=f"ERR  {e}") for e in errors]
    count = lambda k: sum(o['kind'] == k for o in out)
    summary = (f"-- totals: { {abbr[v]: str(x) for v, x in totals.items()} }; "
               f"errors {len(errors)}, parallels {count('PAR!')}, "
               f"beat-par {count('BEAT')}, unjustified {count('DIS!')}")
    return {
        'totals': {'voices': {abbr[v]: str(x) for v, x in totals.items()},
                   'errors': len(errors), 'parallels': count('PAR!'), 'beat_parallels': count('BEAT'),
                   'unjustified': count('DIS!'), 'crossings': count('CROS'), 'directs': count('DIR'),
                   'melodic': count('MEL'), 'd4': count('D4?'), 'dissonances': count('DIS')},
        'violations': err_items + [o for o in out if o['kind'] in VIOLATION_KINDS],
        'review': [o for o in out if o['kind'] in REVIEW_KINDS],
        'dissonances': [o for o in out if o['kind'] == 'DIS'],
        'lines': [o['line'] for o in err_items + out] + [summary],
    }


def ok(result):
    """True when the result would pass splice_check: no errors, parallels, beat-parallels, unjustified."""
    t = result['totals']
    return t['errors'] == 0 and t['parallels'] == 0 and t['beat_parallels'] == 0 and t['unjustified'] == 0
