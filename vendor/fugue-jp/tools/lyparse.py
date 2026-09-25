"""Minimal parser for LilyPond \\absolute voice variables (notes, rests, ties, bar checks).

parse_voice(src, name, measure=Fraction(1)) -> list[Note]
Note fields: start, dur (whole-note units, Fraction), midi (None for rests), name, bar (1-based),
beat (1-based quarter beats within bar). Tied notes are merged. Commands (\\foo) are skipped.
"""
import re
from fractions import Fraction as F

PC = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)
TOK = re.compile(r"(?P<note>[a-g](?:isis|eses|is|es)?[',]*)(?P<dur>\d+)?(?P<dot>\.*)(?P<tie>~)?"
                 r"|(?P<rest>[rRs])(?P<rdur>\d+)?(?P<rdot>\.*)(?:\*(?P<mult>\d+))?"
                 r"|(?P<tie2>~)|(?P<bar>\|)|(?P<cmd>\\[a-zA-Z]+)|(?P<skip>[()\[\]\-^_!?.<>])")


class Note:
    __slots__ = ('start', 'dur', 'midi', 'name', 'bar', 'beat')

    def __init__(self, start, dur, midi, name, measure):
        self.start, self.dur, self.midi, self.name = start, dur, midi, name
        self.bar = int(start / measure) + 1
        self.beat = float((start - (self.bar - 1) * measure) * 4 + 1)

    @property
    def end(self):
        return self.start + self.dur

    def __repr__(self):
        return f"Note({self.name}@{self.bar}:{self.beat:g} dur={self.dur})"


def _dur(num, dots):
    d = F(1, int(num))
    total, add = d, d
    for _ in dots:
        add /= 2
        total += add
    return total


def parse_voice(src, name, measure=F(1)):
    m = re.search(r"(?m)^" + re.escape(name) + r"\s*=\s*\\absolute\s*\{(.*?)^\}", src, re.S)
    if not m:
        return None
    body = re.sub(r"%.*", "", m.group(1))
    t, dur, notes, tie = F(0), F(1, 4), [], False
    pos = 0
    while pos < len(body):
        if body[pos].isspace() or body[pos] in '{}':
            pos += 1
            continue
        mt = TOK.match(body, pos)
        if not mt:
            pos += 1
            continue
        pos = mt.end()
        g = mt.groupdict()
        if g['note']:
            n = g['note']
            acc = n[1:].rstrip("',")
            alter = {'': 0, 'is': 1, 'es': -1, 'isis': 2, 'eses': -2}[acc]
            octv = 3 + n.count("'") - n.count(",")
            midi = 12 * (octv + 1) + PC[n[0]] + alter
            if g['dur']:
                dur = _dur(g['dur'], g['dot'])
            nm = n[0].upper() + ('#' * alter if alter > 0 else 'b' * -alter) + str(octv)
            if tie and notes and notes[-1].midi == midi and notes[-1].end == t:
                notes[-1].dur += dur
            else:
                notes.append(Note(t, dur, midi, nm, measure))
            t += dur
            tie = bool(g['tie'])
        elif g['rest']:
            if g['rdur']:
                dur = _dur(g['rdur'], g['rdot'])
            total = dur * (int(g['mult']) if g['mult'] else 1)
            notes.append(Note(t, total, None, '-', measure))
            t += total
            tie = False
        elif g['tie2']:
            tie = True
    return notes
