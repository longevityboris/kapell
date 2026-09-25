#!/usr/bin/env python3
"""Proposal-4 lab kit: exact subject transformations + lab-file writer + checker runner.

Pitches keep their spelling: (letter 0..6 = c..b, lily octave (3 = no ticks, c' = 4), alter).
Events are (pitch | None, duration in whole notes as Fraction).
"""
import os
import re
import subprocess
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
P4 = os.path.dirname(HERE)
LAB = os.path.join(P4, 'lab')
CHECK = os.path.abspath(os.path.join(P4, '..', '..', 'tools', 'check.py'))
LETTERS = 'cdefgab'
PC = [0, 2, 4, 5, 7, 9, 11]
ACC = {-2: 'eses', -1: 'es', 0: '', 1: 'is', 2: 'isis'}
RANGES = dict(soprano=(60, 84), alto=(53, 77), tenor=(48, 72), bass=(36, 62))
VOICES = ['soprano', 'alto', 'tenor', 'bass']

KEYS = {  # key signatures: letter -> alter
    'bes-minor': dict(b=-1, e=-1, a=-1, d=-1, g=-1),
    'bes-harm': dict(b=-1, e=-1, a=0, d=-1, g=-1),   # harmonic minor: A natural is diatonic
    'f-harm': dict(b=-1, e=0, a=-1, d=-1),
    'bes-major': dict(b=-1, e=-1),
    'f-minor': dict(b=-1, e=-1, a=-1, d=-1),
    'des-major': dict(b=-1, e=-1, a=-1, d=-1, g=-1),
    'ges-major': dict(b=-1, e=-1, a=-1, d=-1, g=-1, c=-1),
    'ees-minor': dict(b=-1, e=-1, a=-1, d=-1, g=-1, c=-1),
    'aes-major': dict(b=-1, e=-1, a=-1, d=-1),
    'ees-major': dict(b=-1, e=-1, a=-1),
    'c-minor': dict(b=-1, e=-1, a=-1),
}


def midi(p):
    l, o, a = p
    return 12 * (o + 1) + PC[l] + a


def dn(p):
    return p[0] + 7 * p[1]


def from_dn(d, m):
    """pitch with diatonic number d spelled to sound as midi m"""
    l, o = d % 7, d // 7
    a = m - (12 * (o + 1) + PC[l])
    return (l, o, a)


def name(p):
    l, o, a = p
    s = LETTERS[l] + ACC[a]
    return s + ("'" * (o - 3) if o >= 3 else ',' * (3 - o))


TOK = re.compile(r"(?P<note>[a-g](?:isis|eses|is|es)?[',]*)(?P<dur>\d+)?(?P<dot>\.*)(?P<tie>~)?"
                 r"|(?P<rest>[rRs])(?P<rdur>\d+)?(?P<rdot>\.*)(?:\*(?P<mult>\d+))?|(?P<tie2>~)|(?P<bar>\|)")


def _d(num, dots):
    d = F(1, int(num))
    tot, add = d, d
    for _ in dots:
        add /= 2
        tot += add
    return tot


def ly(s):
    """parse an \\absolute LilyPond fragment into events (ties merged)"""
    s = re.sub(r'%.*', '', s)
    ev, dur, tie, pos = [], F(1, 4), False, 0
    while pos < len(s):
        if s[pos].isspace():
            pos += 1
            continue
        m = TOK.match(s, pos)
        if not m:
            raise ValueError('parse error near ' + s[pos:pos + 20])
        pos = m.end()
        g = m.groupdict()
        if g['note']:
            n = g['note']
            acc = n[1:].rstrip("',")
            a = {'': 0, 'is': 1, 'es': -1, 'isis': 2, 'eses': -2}[acc]
            o = 3 + n.count("'") - n.count(',')
            p = (LETTERS.index(n[0]), o, a)
            if g['dur']:
                dur = _d(g['dur'], g['dot'])
            if tie and ev and ev[-1][0] == p:
                ev[-1] = (p, ev[-1][1] + dur)
            else:
                ev.append((p, dur))
            tie = bool(g['tie'])
        elif g['rest']:
            if g['rdur']:
                dur = _d(g['rdur'], g['rdot'])
            ev.append((None, dur * (int(g['mult']) if g['mult'] else 1)))
            tie = False
        elif g['tie2']:
            tie = True
    return ev


def length(ev):
    return sum(d for _, d in ev)


def rest(d):
    return [(None, F(d))]


def cat(*evs):
    out = []
    for e in evs:
        out += e
    return out


def aug(ev, k):
    return [(p, d * F(k)) for p, d in ev]


def real(ev, steps, semis):
    """exact (chromatic) transposition: diatonic steps for spelling, semitones for pitch"""
    return [(from_dn(dn(p) + steps, midi(p) + semis) if p else None, d) for p, d in ev]


def inkey(ev, steps, key_from, key_to=None):
    """diatonic transposition inside a key signature; accidentals relative to the signature kept"""
    k1, k2 = KEYS[key_from], KEYS[key_to or key_from]
    out = []
    for p, d in ev:
        if p is None:
            out.append((None, d))
            continue
        l, o, a = p
        rel = a - k1.get(LETTERS[l], 0)
        nd = dn(p) + steps
        nl = nd % 7
        out.append(((nl, nd // 7, k2.get(LETTERS[nl], 0) + rel), d))
    return out


def mirror(ev, axis, mode='real', key=None):
    """inversion around axis pitch (a pitch tuple). real = exact semitones; key = diatonic in key"""
    ad, am = dn(axis), midi(axis)
    out = []
    for p, d in ev:
        if p is None:
            out.append((None, d))
            continue
        nd = 2 * ad - dn(p)
        if mode == 'real':
            out.append((from_dn(nd, 2 * am - midi(p)), d))
        else:
            k = KEYS[key]
            l = p[0]
            rel = p[2] - k.get(LETTERS[l], 0)
            nl = nd % 7
            out.append(((nl, nd // 7, k.get(LETTERS[nl], 0) - rel), d))
    return out


def setnote(ev, idx, pitch_str):
    """replace pitch of the idx-th event (tweaks)"""
    e = list(ev)
    p = ly(pitch_str + '4')[0][0]
    e[idx] = (p, e[idx][1])
    return e


STD = [F(1), F(3, 4), F(1, 2), F(3, 8), F(1, 4), F(3, 16), F(1, 8), F(1, 16), F(1, 32)]
DUR_NAME = {F(1): '1', F(3, 4): '2.', F(1, 2): '2', F(3, 8): '4.', F(1, 4): '4', F(3, 16): '8.',
            F(1, 8): '8', F(1, 16): '16', F(1, 32): '32'}


def split(d, pos, measure):
    """decompose duration d starting at pos (within bar) into standard durations"""
    out = []
    while d > 0:
        for s in STD:
            if s <= d:
                # prefer values that start on a multiple of themselves (beat alignment) when possible
                grid = s if s in (F(1), F(1, 2), F(1, 4), F(1, 8), F(1, 16)) else s / 3
                if (pos % grid == 0) or s <= F(1, 16):
                    out.append(s)
                    pos += s
                    d -= s
                    break
        else:
            out.append(d)
            d = 0
    return out


def to_ly(ev, measure=F(1)):
    toks, t = [], F(0)
    bar_tokens = []
    for p, d in ev:
        remaining = d
        first = True
        while remaining > 0:
            pos = t % measure
            room = measure - pos
            seg = min(room, remaining)
            parts = split(seg, pos, measure)
            for i, s in enumerate(parts):
                if p is None:
                    bar_tokens.append('r' + DUR_NAME.get(s, '4'))
                else:
                    bar_tokens.append(name(p) + DUR_NAME[s])
                t += s
                last_piece = (remaining - s <= 0)
                remaining -= s
                if p is not None and not last_piece:
                    bar_tokens[-1] += '~'
            if t % measure == 0:
                toks.append(' '.join(bar_tokens) + ' |')
                bar_tokens = []
    if bar_tokens:
        toks.append(' '.join(bar_tokens))
    return toks


def fill(ev, total):
    L = length(ev)
    if L < total:
        return ev + rest(total - L)
    return ev


def write_lab(fname, voices, title='', comment='', measure=F(1), total=None, tempo=84):
    total = total or max(length(v) for v in voices.values())
    lines = [f'% {title}', ]
    for c in comment.strip().splitlines():
        lines.append('% ' + c)
    lines.append('\\version "2.24.0"')
    for v in VOICES:
        ev = fill(voices.get(v, []), total)
        body = to_ly(ev, measure)
        lines.append(f'{v} = \\absolute {{')
        for i, b in enumerate(body):
            lines.append(f'  {b}   % {i + 1}')
        lines.append('}')
    lines.append('\\score {\n  <<\n' + ''.join(
        f'    \\new Staff \\with {{ instrumentName = "{v[:1].upper()}" }} {{ \\clef "{c}" \\key bes \\minor \\{v} }}\n'
        for v, c in zip(VOICES, ['treble', 'treble', 'treble_8', 'bass']) if v in voices) +
        f'  >>\n  \\layout {{ }}\n  \\midi {{ \\tempo 4 = {tempo} }}\n}}')
    path = os.path.join(LAB, fname)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return path


def check(path, bars=None, grid=False, quiet=False):
    cmd = ['python3', CHECK, path, '--voices', ','.join(VOICES)]
    for v, (lo, hi) in RANGES.items():
        cmd += ['--range', f'{v}={lo}-{hi}']
    if bars:
        cmd += ['--bars', bars]
    if grid:
        cmd.append('--grid')
    if quiet:
        cmd.append('--quiet')
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout + r.stderr


def summary(out):
    lines = out.strip().splitlines()
    return lines[-1] if lines else ''


def score(out):
    """(errors, par, beat, dis!, d4?, dir, cros, mel) counts"""
    L = out.splitlines()
    c = lambda pre: sum(l.startswith(pre) for l in L)
    return dict(err=c('ERR'), par=c('PAR!'), beat=c('BEAT'), dis=c('DIS!'), d4=c('D4?'),
                dir=c('DIR'), cros=c('CROS'), mel=c('MEL'))


if __name__ == '__main__':
    print(to_ly(ly("bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes' | c''2")))
