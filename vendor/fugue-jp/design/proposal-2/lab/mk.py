#!/usr/bin/env python3
"""mk.py OUT.ly [--grid] [--all] <<< 'S: ...\nA: ...\nT: ...\nB: ...'  (one line per voice, '%' comments ok)
Writes a 4-voice lab (missing voices = rests of the right length) and runs the checker."""
import sys, re, subprocess, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p2 import parse, length
from fractions import Fraction as F
out = sys.argv[1]
src = sys.stdin.read()
v = {}
comments = []
key = {'S': 'soprano', 'A': 'alto', 'T': 'tenor', 'B': 'bass'}
for line in src.splitlines():
    if line.startswith('#'):
        comments.append(line[1:].strip()); continue
    m = re.match(r"\s*([SATB])\s*:(.*)", line)
    if m:
        v.setdefault(key[m.group(1)], []).append(m.group(2).strip())
    elif line.strip() and v:
        last = list(v)[-1]; v[last].append(line.strip())
tot = max(length(parse(' '.join(x))) for x in v.values())
nb = int((tot + 3) // 4)
with open(out, 'w') as fh:
    fh.write('\\version "2.24.0"\n')
    for c in comments: fh.write('% ' + c + '\n')
    for name in ['soprano', 'alto', 'tenor', 'bass']:
        body = '\n  '.join(v[name]) if name in v else f"R1*{nb} |"
        fh.write(f"{name} = \\absolute {{\n  {body}\n}}\n")
here = os.path.dirname(os.path.abspath(__file__))
r = subprocess.run(['sh', os.path.join(here, 'chk.sh'), out] + [a for a in sys.argv[2:] if a.startswith('--bars') or re.match(r'\d+-\d+', a)], capture_output=True, text=True).stdout
lines = r.strip().splitlines()
show_all = '--all' in sys.argv
for l in lines:
    if show_all or not l.startswith('DIS '):
        print(l)
if '--grid' in sys.argv:
    g = subprocess.run(['python3', os.path.join(here, '../../../tools/check.py'), out, '--grid', '--quiet'], capture_output=True, text=True).stdout
    for l in g.splitlines():
        if re.match(r'^\d+:', l): print(l)
