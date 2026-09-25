"""Per section and voice: which spans are LOCKED (subject/answer/cf), CS (countersubject, with its
landing window), KEEP (plan "keep") and FREE, derived from plan.json so a card's FREE claims can
never contradict a lock that splice enforces (from final-lab/spanmap.py).

compute(plan, sections, voices=None) -> [{id, first, last, voices: {v: [{from, to, label}]}}]
    plan      dict (plan.json: roles, keep) or a path to it
    sections  [{id, bars}] in order (first bars accumulate from 1) or [{id, first, bars}]
sections_from_dir(d) -> [{id, first, bars}] from the '% bars A-B' comment of every *.ly in d
lines(result) -> the original markdown-ish text
"""
import json
from fractions import Fraction as F
from pathlib import Path

from kapell.analysis import parse_voices

Q = F(1, 8)


def _pp(x):
    b, beat = x.split(':')
    return F(int(b) - 1) + (F(beat) - 1) / 4


def _pos(t):
    b = int(t) + 1
    return f"{b}:{float((t - (b - 1)) * 4 + 1):g}"


def sections_from_dir(d):
    from kapell.analysis.splice import section_bars
    out = []
    for f in sorted(Path(d).glob('*.ly')):
        ab = section_bars(f.read_text())
        if ab:
            out.append({'id': f.stem, 'first': ab[0], 'bars': ab[1] - ab[0] + 1})
    return out


def compute(plan, sections, voices=None):
    if not isinstance(plan, dict):
        with open(plan) as fh:
            plan = json.load(fh)
    voices = parse_voices(voices or plan.get('voices'))
    out, nxt = [], 1
    for s in sections:
        a = s.get('first', nxt)
        b = a + s['bars'] - 1
        nxt = b + 1
        sec = {'id': s['id'], 'first': a, 'last': b, 'voices': {}}
        for v in voices:
            t, t1, labels = F(a - 1), F(b), []
            while t < t1:
                lab = 'FREE'
                for r in plan.get('roles', []):
                    if r['voice'] != v:
                        continue
                    if _pp(r['at']) <= t < _pp(r['until']):
                        if r['role'] in ('subject', 'answer', 'cf'):
                            lab = f"LOCKED {r['role']}"
                        elif r['role'] == 'cs':
                            lab = 'CS landing (free)' if r.get('landing_from') and t >= _pp(r['landing_from']) else 'CS'
                        break
                if lab == 'FREE':
                    for k in plan.get('keep', []):
                        if k['voice'] == v and _pp(k['at']) <= t < _pp(k['until']):
                            lab = 'KEEP'
                            break
                labels.append((t, lab))
                t += Q
            runs = []
            for t, lab in labels:
                if runs and runs[-1][1] == lab:
                    runs[-1][2] = t + Q
                else:
                    runs.append([t, lab, t + Q])
            sec['voices'][v] = [{'from': _pos(r[0]), 'to': _pos(r[2]), 'label': r[1]} for r in runs]
        out.append(sec)
    return out


def lines(result):
    out = []
    for s in result:
        out += ['', f"{s['id']} (bars {s['first']}-{s['last']})"]
        for v, runs in s['voices'].items():
            out.append(f"  {v[0].upper()}: " + '; '.join(f"{r['from']}-{r['to']} {r['label']}" for r in runs))
    return out
