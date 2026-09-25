#!/usr/bin/env python3
"""proposal-2 material library: parse / transform / emit LilyPond fragments, write labs, run checker.

Notes are [start, dur, midi, labs] with start/dur in quarter beats (Fraction), labs = absolute
letter index (c4 = 28, i.e. 7*octave + letter), midi = MIDI number (rest: midi None).
"""
import re, subprocess, os
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
PC = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)
LET = 'cdefgab'
TOK = re.compile(r"([a-g](?:isis|eses|is|es)?[',]*)(\d+)?(\.*)(~)?|([rs])(\d+)?(\.*)|(\|)|(~)")


def parse(src, t0=0):
    t, dur, out, tie = F(t0), F(1), [], False
    src = re.sub(r"%.*", "", src)
    for m in TOK.finditer(src):
        n, d, dots, ti, r, rd, rdots, bar, tie2 = m.groups()
        if bar:
            continue
        if tie2:
            tie = True
            continue
        dd, dt = (d, dots) if n else (rd, rdots)
        if dd:
            dur = F(4, int(dd))
            x = dur
            for _ in dt:
                x /= 2
                dur += x
        if r:
            out.append([t, dur, None, None])
            t += dur
            tie = False
            continue
        letter = n[0]
        acc = n[1:].rstrip("',")
        alt = {'': 0, 'is': 1, 'es': -1, 'isis': 2, 'eses': -2}[acc]
        octv = 3 + n.count("'") - n.count(",")
        midi = 12 * (octv + 1) + PC[letter] + alt
        labs = LET.index(letter) + 7 * octv
        if tie and out and out[-1][2] == midi and out[-1][0] + out[-1][1] == t:
            out[-1][1] += dur
        else:
            out.append([t, dur, midi, labs])
        t += dur
        tie = bool(ti)
    return out


def length(notes):
    return max(n[0] + n[1] for n in notes) if notes else F(0)


def pname(midi, labs):
    letter = LET[labs % 7]
    octv = labs // 7
    alt = midi - (12 * (octv + 1) + PC[letter])
    s = letter + {0: '', 1: 'is', -1: 'es', 2: 'isis', -2: 'eses'}[alt]
    d = octv - 3
    return s + ("'" * d if d > 0 else "," * (-d))


DURS = [(F(4), '1'), (F(3), '2.'), (F(2), '2'), (F(3, 2), '4.'), (F(1), '4'), (F(3, 4), '8.'),
        (F(1, 2), '8'), (F(1, 4), '16')]


def split_dur(pos, d, bar=F(4)):
    """split a duration starting at pos (beats) into LilyPond values, never crossing a barline,
    preferring beat-aligned values."""
    out = []
    while d > 0:
        room = bar - (pos % bar)
        for val, s in DURS:
            if val <= d and val <= room:
                # avoid a half note starting on beat 2 or 4 unless it's all that's left in a syncope
                if val == 2 and (pos % 2) != 0 and d != val:
                    continue
                if val == 3 and (pos % 4) != 0:
                    continue
                out.append((val, s))
                pos += val
                d -= val
                break
        else:
            raise ValueError(f"cannot split {d} at {pos}")
    return out


def emit(notes, bar=F(4), total=None):
    """notes -> LilyPond string with bar checks; gaps become rests."""
    notes = sorted(notes, key=lambda n: n[0])
    out, t = [], F(0)
    items = []
    for n in notes:
        if n[0] > t:
            items.append([t, n[0] - t, None, None])
        items.append(n)
        t = n[0] + n[1]
    if total is not None and t < total:
        items.append([t, total - t, None, None])
    toks = []
    for s, d, m, l in items:
        parts = split_dur(s, d, bar)
        pos = s
        for i, (val, sym) in enumerate(parts):
            if pos % bar == 0 and pos > 0:
                toks.append('|')
            if m is None:
                toks.append('r' + sym)
            else:
                toks.append(pname(m, l) + sym + ('~' if i < len(parts) - 1 else ''))
            pos += val
    # rest merging not attempted; add final bar check
    return ' '.join(toks) + ' |'


def shift(notes, dt):
    return [[n[0] + dt, n[1], n[2], n[3]] for n in notes]


def real(notes, steps, semis):
    """real (chromatic) transposition by a spelled interval."""
    return [[n[0], n[1], None if n[2] is None else n[2] + semis, None if n[3] is None else n[3] + steps]
            for n in notes]


def aug(notes, k=2):
    return [[n[0] * k, n[1] * k, n[2], n[3]] for n in notes]


def cut(notes, t0, t1):
    """portion of notes in [t0, t1), clipped."""
    out = []
    for s, d, m, l in notes:
        e = s + d
        a, b = max(s, t0), min(e, t1)
        if a < b:
            out.append([a, b - a, m, l])
    return out


# tonal mirror in B-flat minor: B-flat <-> F, C <-> E-flat, D-flat <-> D-flat,
# A (#7) <-> G-flat (b6), A-flat (b7) <-> G (#6), E (#4) <-> C-flat (b2).
# Letter axis: bes (labs 27) <-> f' (labs 31) -> axis 29 (d').
_MIR = {10: 5, 5: 10, 0: 3, 3: 0, 1: 1, 9: 6, 6: 9, 8: 7, 7: 8, 4: 11, 11: 4, 2: 2}


def mirror(notes, axis_labs=58):
    """tonal inversion in B-flat minor. axis_labs = 2 * mirror letter; default maps bes <-> f'."""
    out = []
    for s, d, m, l in notes:
        if m is None:
            out.append([s, d, None, None])
            continue
        nl = axis_labs - l
        pc = _MIR[m % 12]
        octv = nl // 7
        base = 12 * (octv + 1) + PC[LET[nl % 7]]
        # choose the midi with pitch class pc nearest to the natural letter
        cand = min((base + k for k in range(-2, 3) if (base + k) % 12 == pc), key=lambda x: abs(x - base))
        out.append([s, d, cand, nl])
    return out


def write_lab(path, voices, comment='', bars=None):
    """voices: dict name -> LilyPond string or note list. Missing voices become full-bar rests."""
    names = ['soprano', 'alto', 'tenor', 'bass']
    strs = {}
    total = F(0)
    for v in names:
        x = voices.get(v)
        if isinstance(x, list):
            total = max(total, length(x))
        elif isinstance(x, str):
            total = max(total, length(parse(x)))
    if bars:
        total = F(bars * 4)
    nb = int(total / 4) + (1 if total % 4 else 0)
    total = F(nb * 4)
    for v in names:
        x = voices.get(v)
        if x is None:
            strs[v] = f"R1*{nb} |"
        elif isinstance(x, list):
            strs[v] = emit(x, total=total)
        else:
            strs[v] = x
    with open(path, 'w') as fh:
        fh.write('\\version "2.24.0"\n')
        for line in comment.strip().splitlines():
            fh.write('% ' + line + '\n')
        for v in names:
            fh.write(f"{v} = \\absolute {{\n  {strs[v]}\n}}\n")
    return path


def check(path, extra=()):
    r = subprocess.run(['sh', os.path.join(HERE, 'chk.sh'), path, *extra], capture_output=True, text=True)
    return r.stdout


def summary(path, extra=()):
    return check(path, extra).strip().splitlines()[-1]


# ---------------------------------------------------------------- materials (B-flat minor)
S1 = "bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes' | c''4. a'8 f'4"
S2 = "c''4. a'8 f'4 des''8 bes' | c''2. f''8 bes' | ees''4. des''8 des''4. c''8 | c''1"
