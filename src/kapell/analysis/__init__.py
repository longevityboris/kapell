"""Counterpoint and harmony analysis (pure functions, no import-time side effects).

Stable entry points (other lanes import these; extend, do not rename):

    check.run(path, voices=None, bars=None, measure=None, ranges=None, src=None)
        -> {totals, violations, review, dissonances, lines}
    suspensions.count(path, voices=None, bars=None, measure=None, src=None) -> {strong, weak, items}
    strict.run(path, voices=None, bars=None, measure=None, src=None) -> {clash, xrel, acc, acc2, items}
    harmony.analyse(path, key=None, bars=None, voices=None, measure=None, src=None)
        -> {attacks: [{pos, bar, beat, bass, pcs, chord, roman}], stats}
    grid.grid(path, voices=None, bars=None, step='1/8', attacks=False) -> [{pos, cells, names, chord, flags}]
    spanmap.compute(plan, sections, voices=None) -> [{id, first, last, voices: {v: [{from, to, label}]}}]
    splice.check_section(section, skeleton, plan, base=None, voices=None, ranges=None)
        -> {section, bars, checked, pass, failures, known_unisons, check, strict, review, lines}
Every function also accepts src=<LilyPond text> instead of a path; each module has lines(result)
reproducing the original script's text output.

Common flag vocabulary (parsed by the helpers below):
    --voices s,a,t,b   --bars A-B   --measure 3/4   --key bes | 1-20=bb,21-30=f   --full
"""
from fractions import Fraction as F

DEFAULT_VOICES = ['soprano', 'alto', 'tenor', 'bass']


def parse_bars(spec):
    """'A-B' | 'A' | (A, B) | None -> (A, B) or None."""
    if spec is None or spec == '':
        return None
    try:
        parts = list(spec) if isinstance(spec, (tuple, list)) else str(spec).split('-')
        if len(parts) == 1:
            parts *= 2
        a, b = map(int, parts)
        if a < 1 or b < a:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("bars must satisfy 1 <= A <= B") from None
    return a, b


def parse_measure(spec):
    """'4/4' | '3/4' | '1' | Fraction | None -> bar length as a fraction of a whole note."""
    if spec is None or spec == '':
        return F(1)
    try:
        value = F(spec)
        if value <= 0:
            raise ValueError
    except (ValueError, ZeroDivisionError):
        raise ValueError('measure must be a positive fraction') from None
    return value


def parse_voices(spec):
    if spec is None or spec == '':
        return list(DEFAULT_VOICES)
    if isinstance(spec, (list, tuple)):
        return list(spec)
    return [v.strip() for v in str(spec).split(',') if v.strip()]


def read_source(path=None, src=None):
    if src is not None:
        return src
    with open(path) as fh:
        return fh.read()
