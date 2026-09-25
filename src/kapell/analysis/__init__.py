"""Counterpoint and harmony analysis (pure functions, no import-time side effects).

Stable entry points (other lanes import these; extend, do not rename):

    check.run(path, voices=None, bars=None, measure=None, ranges=None, src=None)
        -> {totals, violations, review, dissonances, lines}
    suspensions.count(path, voices=None, bars=None, measure=None, src=None) -> {strong, weak, items}
    strict.run(path, voices=None, bars=None, measure=None, src=None) -> {clash, xrel, acc, acc2, items}
    harmony.analyse(path, key=None, bars=None, voices=None, measure=None, src=None)
        -> {attacks: [{pos, bar, beat, bass, pcs, chord, roman}], stats}
    grid.rows(data, a, b, step, attacks)        spanmap.compute(plan, sections, voices)
    splice.check_section(section_path, skeleton, plan, base=None, voices=None, ranges=None)

Common flag vocabulary (see common.py helpers in each module):
    --voices s,a,t,b   --bars A-B   --measure 3/4   --key bes | 1-20=bb,21-30=f   --full
"""
from fractions import Fraction as F

DEFAULT_VOICES = ['soprano', 'alto', 'tenor', 'bass']


def parse_bars(spec):
    """'A-B' | 'A' | (A, B) | None -> (A, B) or None."""
    if spec is None or spec == '':
        return None
    if isinstance(spec, (tuple, list)):
        return (int(spec[0]), int(spec[1]))
    s = str(spec)
    if '-' in s:
        a, b = s.split('-', 1)
        return (int(a), int(b))
    return (int(s), int(s))


def parse_measure(spec):
    """'4/4' | '3/4' | '1' | Fraction | None -> bar length as a fraction of a whole note."""
    if spec is None or spec == '':
        return F(1)
    return F(spec) if not isinstance(spec, F) else spec


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
