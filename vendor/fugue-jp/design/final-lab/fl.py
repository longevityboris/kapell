#!/usr/bin/env python3
"""final-lab helpers: read/write bar-indexed four-voice LilyPond labs, splice, check.

A "score" here is a dict voice -> list of bar strings (bar 1 = index 0), each bar string holding
exactly one 4/4 bar of \\absolute LilyPond (notes, rests, ties). Ties across a barline are written
as a trailing '~' in the earlier bar.

  read(path)                 -> score (all four voices; missing voices become rests)
  write(path, score, note)   -> writes a checker/LilyPond-ready lab (bar numbers as comments)
  splice(base, part, first)  -> copy of base with part's bars pasted from bar `first`
  window(score, a, b)        -> bars a..b only (1-based, inclusive)
  check(path, bars=None)     -> (summary line of tools/check.py, strict summary line)
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VOICES = ['soprano', 'alto', 'tenor', 'bass']


def _body(src, v):
    m = re.search(r"(?m)^" + v + r"\s*=\s*\\absolute\s*\{(.*?)^\}", src, re.S)
    if not m:
        return None
    return re.sub(r"%.*", "", m.group(1))


def _split_bars(body):
    # expand R1*n into n bars, then split on bar checks
    body = re.sub(r"R1\*(\d+)", lambda m: " | ".join(["r1"] * int(m.group(1))), body)
    parts = [p.strip() for p in body.split('|')]
    return [p for p in parts if p]


def read(path):
    src = open(path).read()
    sc = {}
    n = 0
    for v in VOICES:
        b = _body(src, v)
        sc[v] = _split_bars(b) if b is not None else None
        if sc[v]:
            n = max(n, len(sc[v]))
    for v in VOICES:
        if sc[v] is None:
            sc[v] = ['r1'] * n
    return sc


def nbars(sc):
    return max(len(sc[v]) for v in VOICES)


def write(path, sc, note='', first_bar=1, per_line=4):
    out = ['\\version "2.24.0"']
    for line in note.strip().splitlines():
        out.append('% ' + line)
    for v in VOICES:
        out.append(f"{v} = \\absolute {{")
        bars = sc[v]
        for i in range(0, len(bars), per_line):
            chunk = bars[i:i + per_line]
            out.append(f"  % {first_bar + i}")
            out.append("  " + " | ".join(chunk) + " |")
        out.append("}")
    open(path, 'w').write("\n".join(out) + "\n")
    return path


def window(sc, a, b):
    return {v: sc[v][a - 1:b] for v in VOICES}


def splice(base, part, first):
    sc = {v: list(base[v]) for v in VOICES}
    for v in VOICES:
        for i, bar in enumerate(part[v]):
            j = first - 1 + i
            while len(sc[v]) <= j:
                sc[v].append('r1')
            sc[v][j] = bar
    return sc


def check(path, bars=None, first_bar=None):
    args = ['sh', os.path.join(HERE, 'ck.sh'), path, '--quiet']
    if bars:
        args += ['--bars', bars]
    r = subprocess.run(args, capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    s_args = [sys.executable, os.path.join(HERE, 'strict.py'), path]
    if bars:
        s_args += ['--bars', bars]
    s = subprocess.run(s_args, capture_output=True, text=True)
    slines = [l for l in s.stdout.splitlines() if l.strip()]
    return lines, slines


def report(path, bars=None, show=True):
    lines, slines = check(path, bars)
    flagged = [l for l in lines if l.split()[0] in ('PAR!', 'BEAT', 'DIS!', 'D4?', 'DIR', 'MEL', 'CROS', 'ERR', 'RANGE')
               or 'error' in l.lower() and not l.startswith('--')]
    if show:
        print(f"== {os.path.basename(path)}" + (f" bars {bars}" if bars else ''))
        for l in lines:
            if not l.startswith('DIS '):
                print('  ' + l)
        for l in slines:
            if not l.startswith('ACC '):
                print('  ' + l)
    return lines, slines



_NOTE = re.compile(r"(?<![a-zA-Z\\])([a-g](?:isis|eses|is|es)?)([',]*)(?=[\d~\s|.]|$)")


def octave(s, k):
    """shift every note of a LilyPond \\absolute string by k octaves."""
    def f(m):
        name, marks = m.group(1), m.group(2)
        n = marks.count("'") - marks.count(',') + k
        return name + ("'" * n if n > 0 else ',' * (-n))
    return _NOTE.sub(f, s)


def bars(s):
    return [b.strip() for b in s.replace('\n', ' ').split('|') if b.strip()]


def lab(voices, n=None):
    """voices: dict voice -> string (bars separated by |); missing voices become rests."""
    sc = {v: bars(voices[v]) if v in voices else None for v in VOICES}
    n = n or max(len(x) for x in sc.values() if x)
    return {v: (sc[v] if sc[v] else ['r1'] * n) for v in VOICES}


if __name__ == '__main__':
    for p in sys.argv[1:]:
        report(p)
