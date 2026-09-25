"""Harmonic x-ray: the sonority at every attack, with Roman numerals in a key (from tools/harmony.py).

analyse(path, key=None, bars=None, voices=None, measure=None, src=None)
    -> {attacks: [{pos, bar, beat, bass, pcs, chord, roman, key}], stats}

key accepts "bes" (whole piece), "bes minor" / "F major" (kapell.toml style), or ranges
"1-20=bb,21-30=f". Lowercase first letter = minor, uppercase = major (LilyPond or English
accidentals: bes, bb, fis, f#). music21 is imported lazily so importing this module is cheap.
stats: attacks, seventh-type, dim7 and chromatic-to-key shares, distinct labels.
"""
from bisect import bisect_right

from kapell.analysis import parse_bars, parse_measure, parse_voices, read_source
from kapell.analysis.lyparse import parse_voice


def _tonic(k):
    if len(k) > 1:
        return k[0].upper() + k[1:].replace('is', '#').replace('es', '-').replace('s', '-')
    return k.upper()


def parse_key(spec):
    """-> list of (lo, hi, name, mode); lo/hi None = every bar. Raises ValueError on bad input."""
    if not spec:
        return []
    out = []
    for part in str(spec).split(','):
        part = part.strip()
        if '=' in part:
            rng, k = part.split('=', 1)
            lo, hi = parse_bars(rng.strip())
        else:
            lo = hi = None
            k = part
        words = k.split()
        name = words[0]
        if len(words) > 1:
            mode = words[1].lower()
            if mode not in ('major', 'minor'):
                raise ValueError(f"bad key mode {words[1]!r}")
        else:
            mode = 'minor' if name[0].islower() else 'major'
        if name[0].lower() not in 'abcdefg':
            raise ValueError(f"bad key {k!r}")
        out.append((lo, hi, _tonic(name), mode))  # bb/Bb/bes -> B-flat, fis/f# -> F-sharp
    return out


def analyse(path=None, key=None, bars=None, voices=None, measure=None, src=None):
    from music21 import chord, key as m21key, roman, pitch

    src = read_source(path, src)
    measure = parse_measure(measure)
    bars = parse_bars(bars)
    keymap = parse_key(key)
    cache = {}

    def key_for(bar):
        for lo, hi, tonic, mode in keymap:
            if lo is None or lo <= bar <= hi:
                if (tonic, mode) not in cache:
                    cache[(tonic, mode)] = m21key.Key(tonic, mode)
                return cache[(tonic, mode)]
        return None

    data = {}
    for v in parse_voices(voices):
        n = parse_voice(src, v, measure)
        if n:
            data[v] = (n, [x.start for x in n])

    def at(v, t):
        notes, starts = data[v]
        i = bisect_right(starts, t) - 1
        if i < 0:
            return None
        x = notes[i]
        return x if x.start <= t < x.end and x.midi is not None else None

    times = sorted({x.start for v in data for x in data[v][0]})
    stats = dict(attacks=0, seventh=0, dim7=0, chromatic=0)
    names, attacks = set(), []
    for t in times:
        b = int(t / measure) + 1
        if bars and not (bars[0] <= b <= bars[1]):
            continue
        snd = [x for x in (at(v, t) for v in data) if x]
        if not snd:
            continue
        mids = sorted(x.midi for x in snd)
        c = chord.Chord([pitch.Pitch(midi=m) for m in mids])
        k = key_for(b)
        rn = ''
        if k is not None:
            try:
                rn = roman.romanNumeralFromChord(c, k).figure
            except Exception:
                rn = '?'
        beat = float((t - (b - 1) * measure) * 4 + 1)
        name = c.pitchedCommonName
        attacks.append(dict(pos=f"{b}:{beat:g}", bar=b, beat=beat, bass=pitch.Pitch(midi=mids[0]).name,
                            pcs=sorted({m % 12 for m in mids}), chord=name, roman=rn,
                            key=(f"{k.tonic.name} {k.mode}" if k is not None else None)))
        stats['attacks'] += 1
        names.add(rn or name)
        if c.isSeventh() or c.isDominantSeventh() or c.isHalfDiminishedSeventh():
            stats['seventh'] += 1
        if c.isDiminishedSeventh():
            stats['dim7'] += 1
        if k is not None:
            sc_p = k.getScale().getPitches()
            sc = {p.name for p in sc_p} | {sc_p[6].transpose('A1').name if k.mode == 'minor' else ''}
            if any(p.name not in sc for p in c.pitches):
                stats['chromatic'] += 1
    n = stats['attacks'] or 1
    stats.update(distinct=len(names), seventh_share=round(stats['seventh'] / n, 3),
                 dim7_share=round(stats['dim7'] / n, 3), chromatic_share=round(stats['chromatic'] / n, 3))
    return {'attacks': attacks, 'stats': stats}


def lines(result, stats=False):
    """The original script's text output."""
    out, line, cur = [], [], None
    for a in result['attacks']:
        if a['bar'] != cur:
            if line:
                out.append(' | '.join(line))
            line, cur = [f"{a['bar']:3d}:"], a['bar']
        line.append(f"{a['beat']:g} {a['bass']} {a['roman'] or a['chord']}")
    if line:
        out.append(' | '.join(line))
    s = result['stats']
    if stats and s['attacks']:
        n = s['attacks']
        out.append(f"\nattacks {n}; seventh-type {s['seventh']/n:.0%}; dim7 {s['dim7']/n:.0%}; "
                   f"chromatic-to-key {s['chromatic']/n:.0%}; distinct labels {s['distinct']}")
    return out
