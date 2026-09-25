"""Small toolkit for proposal-1 lab work.

Lines are lists of events (start, dur, pitch) on a whole-note timeline
(Fraction; one bar of 2/2 = 1).  pitch = (dia, midi) where dia is the absolute
diatonic step (letter index + 7*scientific octave) or None for a rest.

  parse(ly)            LilyPond \\absolute fragment -> line (starting at 0)
  render(line, bars)   line -> LilyPond text with bar checks, ties across bars
  shift/transpose/mirror/augment/concat/pad
  lab(path, voices, title, bars)  write a checkable + compilable lab file
  check(path, bars=None)          run tools/check.py with the fixed ranges
"""
import re, subprocess, os
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.normpath(os.path.join(HERE, '..', '..', '..', 'tools', 'check.py'))
RANGES = dict(soprano=(60, 84), alto=(53, 77), tenor=(48, 72), bass=(36, 62))
LET = 'cdefgab'
PC = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)
ACC = {'': 0, 'is': 1, 'es': -1, 'isis': 2, 'eses': -2}
ACCS = {0: '', 1: 'is', -1: 'es', 2: 'isis', -2: 'eses'}
TOK = re.compile(r"(?P<n>[a-g](?:isis|eses|is|es)?[',]*|[rsR])(?P<d>\d+)?(?P<dot>\.*)(?:\*(?P<mult>\d+))?(?P<tie>~)?|(?P<bar>\|)")


def pitch(name):
    letter, rest = name[0], name[1:]
    acc = rest.rstrip("',")
    octv = 3 + rest.count("'") - rest.count(",")
    dia = LET.index(letter) + 7 * octv
    midi = 12 * (octv + 1) + PC[letter] + ACC[acc]
    return (dia, midi)


def pname(p):
    dia, midi = p
    letter, octv = LET[dia % 7], dia // 7
    alter = midi - (12 * (octv + 1) + PC[letter])
    marks = octv - 3
    return letter + ACCS[alter] + ("'" * marks if marks > 0 else "," * (-marks))


def parse(ly, start=F(0)):
    """Parse notes/rests/ties/bar checks. Tied equal pitches are merged."""
    ly = re.sub(r"%.*", "", ly)
    t, dur, out, tie = start, F(1, 4), [], False
    for m in TOK.finditer(ly):
        if m.group('bar'):
            continue
        if m.group('d'):
            dur = F(1, int(m.group('d')))
            d = dur
            for _ in m.group('dot'):
                d /= 2
                dur += d
        n = m.group('n')
        p = None if n in ('r', 's', 'R') else pitch(n)
        if m.group('mult'):
            out.append((t, dur * int(m.group('mult')), None))
            t += dur * int(m.group('mult'))
            tie = False
            continue
        if tie and out and p is not None and out[-1][2] == p and out[-1][0] + out[-1][1] == t:
            s0, d0, _ = out[-1]
            out[-1] = (s0, d0 + dur, p)
        else:
            out.append((t, dur, p))
        t += dur
        tie = bool(m.group('tie'))
    return out


def length(line):
    return max(s + d for s, d, _ in line) if line else F(0)


def shift(line, dt):
    return [(s + dt, d, p) for s, d, p in line]


def transpose(line, dia, semis):
    return [(s, d, None if p is None else (p[0] + dia, p[1] + semis)) for s, d, p in line]


def octave(line, n):
    return transpose(line, 7 * n, 12 * n)


def augment(line, k=2, origin=None):
    o = line[0][0] if origin is None else origin
    return [(o + (s - o) * k, d * k, p) for s, d, p in line]


# harmonic minor on a tonic given as LilyPond name; mirror maps degree r -> axis - r
HMIN = [0, 2, 3, 5, 7, 8, 11]


def mirror(line, tonic="bes'", axis=4, scale=HMIN):
    """Diatonic mirror inversion.  r = diatonic distance from tonic; r -> axis - r.
    axis=4 maps 1^<->5^ above (Art of Fugue convention), 7^<->6^, 2^<->4^, 3^<->3^.
    Chromatic alterations relative to the scale are negated."""
    td, tm = pitch(tonic)

    def smidi(r):
        return tm + 12 * (r // 7) + scale[r % 7]

    out = []
    for s, d, p in line:
        if p is None:
            out.append((s, d, None))
            continue
        r = p[0] - td
        alt = p[1] - smidi(r)
        r2 = axis - r
        out.append((s, d, (td + r2, smidi(r2) - alt)))
    return out


def set_pitch(line, idx, name):
    s, d, _ = line[idx]
    line = list(line)
    line[idx] = (s, d, pitch(name))
    return line


def pad(line, total):
    """Fill gaps with rests from 0 to total."""
    out, t = [], F(0)
    for s, d, p in sorted(line, key=lambda e: e[0]):
        if s > t:
            out.append((t, s - t, None))
        out.append((s, d, p))
        t = s + d
    if t < total:
        out.append((t, total - t, None))
    return out


VALS = [F(1), F(3, 4), F(1, 2), F(3, 8), F(1, 4), F(3, 16), F(1, 8), F(1, 16)]
NAME = {F(1): '1', F(3, 4): '2.', F(1, 2): '2', F(3, 8): '4.', F(1, 4): '4',
        F(3, 16): '8.', F(1, 8): '8', F(1, 16): '16', F(7, 8): '2..'}


ALIGN = {F(1): F(1), F(3, 4): F(1, 4), F(1, 2): F(1, 4), F(3, 8): F(1, 8), F(1, 4): F(1, 8),
         F(3, 16): F(1, 16), F(1, 8): F(1, 16), F(1, 16): F(1, 16)}


def _pieces(start, dur):
    """Split [start, start+dur) at barlines into notatable values."""
    out, t, end = [], start, start + dur
    while t < end:
        bar_end = (t // 1 + 1)
        seg = min(end, bar_end) - t
        pos = t - t // 1
        for v in VALS:
            if v <= seg and pos % ALIGN[v] == 0:
                out.append((t, v))
                t += v
                break
        else:
            raise ValueError(f"cannot notate {dur} at {start}")
    return out


def render(line, total=None, per_line=1):
    total = total if total is not None else length(line)
    line = pad(line, total)
    toks, bars = [], []
    for s, d, p in line:
        pcs = _pieces(s, d)
        for k, (t, v) in enumerate(pcs):
            nm = 'r' if p is None else pname(p)
            tie = '~' if (p is not None and k < len(pcs) - 1) else ''
            toks.append((t, nm + NAME[v] + tie, t + v))
    out, cur, barno = [], [], 1
    for t, tk, e in toks:
        cur.append(tk)
        if e == barno:
            out.append(' '.join(cur) + ' |')
            cur = []
            barno += 1
    if cur:
        out.append(' '.join(cur))
    return '\n  '.join(out)


HEAD = r'''\version "2.24.0"
%% proposal-1 lab: {title}
\header {{ title = "{title}" tagline = ##f }}
global = {{ \key bes \minor \time 2/2 }}
'''
SCORE = r'''
\score {
  \new StaffGroup <<
    \new Staff \with { instrumentName = "S" } << \global \soprano >>
    \new Staff \with { instrumentName = "A" } << \global \alto >>
    \new Staff \with { instrumentName = "T" } << \global \clef "treble_8" \tenor >>
    \new Staff \with { instrumentName = "B" } << \global \clef bass \bass >>
  >>
  \layout { }
  \midi { \tempo 2 = 46 }
}
'''


def lab(path, voices, title, total=None, notes=''):
    """voices: dict name -> line (or LilyPond string).  Missing voices become rests."""
    lines = {}
    for v in ('soprano', 'alto', 'tenor', 'bass'):
        x = voices.get(v)
        if isinstance(x, str):
            x = parse(x)
        lines[v] = x or []
    total = total or max(length(l) for l in lines.values())
    import math
    total = F(math.ceil(total))
    txt = HEAD.format(title=title)
    if notes:
        txt += ''.join('% ' + l + '\n' for l in notes.strip().splitlines())
    for v in ('soprano', 'alto', 'tenor', 'bass'):
        body = render(lines[v], total) if lines[v] else ' '.join(['R1 |'] * int(total))
        txt += f"\n{v} = \\absolute {{\n  {body}\n}}\n"
    txt += SCORE
    with open(path, 'w') as f:
        f.write(txt)
    return path


def check(path, bars=None, extra=()):
    cmd = ['python3', CHECK, path, '--voices', 'soprano,alto,tenor,bass']
    for v, (lo, hi) in RANGES.items():
        cmd += ['--range', f'{v}={lo}-{hi}']
    if bars:
        cmd += ['--bars', bars]
    cmd += list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout + r.stderr


def summary(out):
    lines = out.strip().splitlines()
    tot = [l for l in lines if l.startswith('-- totals')]
    cnt = {k: sum(l.startswith(k) for l in lines) for k in ('PAR!', 'BEAT', 'DIS!', 'D4?', 'DIR', 'CROS', 'MEL', 'ERR', 'DIS ')}
    strong = sum(1 for l in lines if l.startswith('DIS') and ' strong ' in l)
    return cnt, strong, (tot[0] if tot else 'NO TOTALS: ' + out[-300:])


def compile_ly(path):
    d = os.path.dirname(os.path.abspath(path))
    r = subprocess.run(['lilypond', '-s', '-o', os.path.splitext(os.path.abspath(path))[0], path],
                       capture_output=True, text=True, cwd=d)
    return r.returncode, r.stderr[-2000:]


NMIN = [0, 2, 3, 5, 7, 8, 10]


def dtrans(line, steps, tonic="bes'", scale=NMIN):
    """Diatonic transposition inside the key (chromatic alterations kept)."""
    td, tm = pitch(tonic)

    def smidi(r):
        return tm + 12 * (r // 7) + scale[r % 7]

    out = []
    for s, d, p in line:
        if p is None:
            out.append((s, d, None)); continue
        r = p[0] - td
        alt = p[1] - smidi(r)
        out.append((s, d, (td + r + steps, smidi(r + steps) + alt)))
    return out


def strict(out):
    """Stile-antico filter: dissonances on the half-note beats (beats 1 and 3)
    that are NOT suspensions/retardations (i.e. accented passing notes,
    appoggiaturas, escapes, anticipations).  These pass tools/check.py but
    must be reviewed by ear; the design keeps them rare and deliberate."""
    bad = []
    for l in out.splitlines():
        if l.startswith('DIS ') and ' strong ' in l:
            just = l[l.index('[') + 1:l.index(']')]
            if not any(k in just for k in ('SUS', 'RET')):
                bad.append(l)
    return bad
