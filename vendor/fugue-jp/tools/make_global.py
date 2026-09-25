#!/usr/bin/env python3
"""Write score/music-global.ly (\\global, \\marks, \\dynamicsLine) from the performance plan.

usage: cd ricercar && python3 tools/make_global.py [--plan design/final-lab/plan.json] [--out score/music-global.ly]

Single source: tempo, ramps, fermatas, breaths and dynamics are read from plan.json (the same file
perform.py plays), section starts from the '% bars A-B' line of score/sections/secNN*.ly. Only the
wording (tempo names, expressive words) and the key/double-bar table live here. Every variable is a
grid of spacer rests exactly as long as the piece, one bar check per bar, so it lines up with the voices
in piano.ly and quartet.ly.

  \\global        key, time, tempo marks and ramps, fermatas (on every staff), breaths/caesura, bar lines
  \\marks         boxed rehearsal numbers 1-7 at the section starts (= blueprint section numbers)
  \\dynamicsLine  dynamics and hairpins; spans longer than 5 bars become 'cresc./dim. poco a poco'
"""
import glob
import json
import os
import re
import sys
from fractions import Fraction as F

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
args = sys.argv[1:]
plan_path = args[args.index('--plan') + 1] if '--plan' in args else os.path.join(ROOT, 'design/final-lab/plan.json')
out_path = args[args.index('--out') + 1] if '--out' in args else os.path.join(ROOT, 'score/music-global.ly')
plan = json.load(open(plan_path))
BEATS = 4  # 4/4 throughout (blueprint section 3)

# ---- wording and notation choices (the numbers come from plan.json) ----
TEMPO_TEXT = {  # bar:beat of a plan 'bpm' entry -> tempo word
    '1:1': 'Grave e sostenuto',
    '30:1': 'Arioso dolente',
    '35:1': 'Fuga inversa',
    '54:1': 'Meno mosso',
    '55:1': 'Largamente',
}
RAMP_TEXT = {  # bar:beat of a plan 'until/to_bpm' entry -> ramp word
    '35:1': 'poi a poi di nuovo vivente',  # Op. 110's words for the inverted fugue's accelerando
}
KEYS = {1: r'\key bes \minor', 55: r'\key bes \major'}  # A minor (35-45) is the neighbour key, not a home key
DOUBLE_BARS = [30, 35, 46, 55]  # part starts after Op. 110: arioso, fuga inversa, pedal, apotheosis
EXPRESSIVE = {  # bar:beat -> (dynamic, custom script name) where the plan's level gets a word
    '30:1': ('pp', 'subPP'),
    '46:1': ('p', 'subPMist'),
    '55:1': ('p', 'pDolce'),
}
LEVELS = ['ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff']
TEXT_SPAN_BEATS = 20  # hairpins longer than this are written as words


def at(s):
    bar, beat = s.split(':')
    return F(int(bar) - 1) * BEATS + F(beat) - 1  # in beats from the start


def pos(t):
    return f"{int(t // BEATS) + 1}:{t % BEATS + 1}"


# ---- piece length and section starts from the section files ----
starts, total = [], 0
for f in sorted(glob.glob(os.path.join(ROOT, 'score/sections/sec[0-9]*.ly'))):
    m = re.search(r'%\s*bars\s+(\d+)\s*-\s*(\d+)', open(f).read())
    a, b = int(m.group(1)), int(m.group(2))
    starts.append(a)
    total = max(total, b)
END = F(total * BEATS)

# every event must sit on the grid
times = [at(e['at']) for k in ('tempo', 'fermatas', 'breaths', 'dynamics') for e in plan[k]]
times += [at(e['until']) for k in ('tempo', 'dynamics') for e in plan[k] if 'until' in e]
UNIT = F(1) if all(t.denominator == 1 for t in times) else F(1, 2)
assert all((t / UNIT).denominator == 1 for t in times), 'plan position off the eighth grid'


class Line:
    """events keyed by time: 'pre' (zero-duration commands before the spacer), 'post' (attached to it),
    'bar' (commands just before the bar check that ends the previous bar)."""

    def __init__(self):
        self.ev = {}

    def add(self, t, kind, s):
        self.ev.setdefault(t, {'pre': [], 'post': [], 'bar': []})[kind].append(s)

    def render(self):
        def dur(n):  # n units -> spacer
            q = n * UNIT
            names = {F(4): 's1', F(3): 's2.', F(2): 's2', F(3, 2): 's4.', F(1): 's4', F(1, 2): 's8'}
            return names.get(q, f's4*{q}' if q.denominator == 1 else f's8*{q * 2}')

        out, t = [], F(0)
        cuts = sorted(set(self.ev) | {F(b * BEATS) for b in range(total + 1)})
        cuts = [c for c in cuts if c <= END]
        for i, c in enumerate(cuts[:-1]):
            e = self.ev.get(c, {'pre': [], 'post': [], 'bar': []})
            if c % BEATS == 0:
                bar = int(c // BEATS) + 1
                if bar > 1:
                    out.append('|\n')
                out.append(f'  %{bar}\n  ' if bar % 4 == 1 or e['pre'] or e['post'] else '  ')
            out.extend(p + ' ' for p in e['pre'])
            out.append(dur((cuts[i + 1] - c) / UNIT) + ''.join(e['post']) + ' ')
            nxt = self.ev.get(cuts[i + 1])
            if nxt and nxt['bar']:
                out.extend(p + ' ' for p in nxt['bar'])
        fin = self.ev.get(END)
        if fin:  # its 'bar' commands were written after the last spacer above
            out.extend(p + ' ' for p in fin['pre'])
        return ''.join(out).rstrip() + '\n'


# ---- \global ----
g = Line()
g.add(F(0), 'pre', r'\time 4/4')
for bar, k in KEYS.items():
    g.add(F((bar - 1) * BEATS), 'pre', k)
for bar in DOUBLE_BARS:
    g.add(F((bar - 1) * BEATS), 'bar', r'\bar "||"')
tempo_at = {}
for e in plan['tempo']:
    tempo_at.setdefault(e['at'], []).append(e)
for s, es in tempo_at.items():
    bpm = next((e['bpm'] for e in es if 'bpm' in e), None)
    ramp = next((e for e in es if 'to_bpm' in e), None)
    word = TEMPO_TEXT.get(s)
    rw = None
    if ramp:
        rw = RAMP_TEXT.get(s, 'rit.' if (bpm or 999) >= ramp['to_bpm'] or bpm is None else 'accel.')
    parts = []
    if word:
        parts.append(f'"{word}"')
    if rw:
        parts.append(rf'\normal-text \italic "{rw}"')
    text = (r'\markup { ' + ' '.join(parts) + ' }') if parts else ''
    metr = f' 4 = {bpm}' if bpm else ''
    g.add(at(s), 'pre', rf'\tempo {text}{metr}'.replace('  ', ' ').replace(r'\tempo  ', r'\tempo '))
for e in plan['fermatas']:
    g.add(at(e['at']), 'post', r'^\markup { \musicglyph "scripts.ufermata" }')
for e in plan['breaths']:
    t = at(e['at'])
    if e['ms'] >= 1000:  # general pause after the fermata chord: a caesura
        g.add(t, 'bar', r'\once \override BreathingSign.text = \markup { \musicglyph "scripts.caesura.straight" } \breathe')
    else:
        g.add(t, 'bar', r'\breathe')
g.add(END, 'bar', r'\bar "|."')

# ---- \marks ----
mk = Line()
mk.add(F(0), 'pre', r'\set Score.rehearsalMarkFormatter = #format-mark-box-numbers')
for b in starts:
    mk.add(F((b - 1) * BEATS), 'pre', r'\mark \default')

# ---- \dynamicsLine ----
d = Line()
cur = None
placed = {}  # time -> dynamic already written there
for e in plan['dynamics']:
    t = at(e['at'])
    if 'level' in e:
        lv = e['level']
        if placed.get(t) == lv or (lv == cur and e['at'] not in EXPRESSIVE):
            cur = lv
            continue
        name = EXPRESSIVE[e['at']][1] if e['at'] in EXPRESSIVE and EXPRESSIVE[e['at']][0] == lv else lv
        if placed.get(t):  # a hairpin already ended here on another level: keep the plan's level
            d.ev[t]['post'] = [p for p in d.ev[t]['post'] if p != '\\' + placed[t]]
        d.add(t, 'post', '\\' + name)
        placed[t] = lv
        cur = lv
    if 'until' in e:
        t1, to = at(e['until']), e['to']
        up = LEVELS.index(to) > LEVELS.index(cur)
        if t1 - t > TEXT_SPAN_BEATS:
            d.add(t, 'post', r'\crescPoco' if up else r'\dimPoco')
        else:
            d.add(t, 'post', r'\<' if up else r'\>')
        if e['until'] in EXPRESSIVE and EXPRESSIVE[e['until']][0] == to:
            d.add(t1, 'post', '\\' + EXPRESSIVE[e['until']][1])
        else:
            d.add(t1, 'post', '\\' + to)
        placed[t1] = to
        cur = to
# the plan's level at a hairpin's start must come before the hairpin on the same spacer
for t, e in d.ev.items():
    dyn = [p for p in e['post'] if p.lstrip('\\') in LEVELS or p.lstrip('\\') in {v[1] for v in EXPRESSIVE.values()}]
    rest = [p for p in e['post'] if p not in dyn]
    e['post'] = dyn + rest

HEAD = r'''%% GENERATED by tools/make_global.py from design/final-lab/plan.json and score/sections/ -- do not edit by hand.
%% \global: key, time, tempo marks and ramps, fermatas, breaths; \marks: rehearsal numbers = blueprint
%% section numbers; \dynamicsLine: the plan's dynamics and hairpins as spacer rests (%(n)d bars).

subPP = #(make-dynamic-script #{ \markup { \normal-text \italic "subito" \dynamic pp } #})
subPMist = #(make-dynamic-script #{ \markup { \normal-text \italic "subito" \dynamic p \normal-text \italic "misterioso" } #})
pDolce = #(make-dynamic-script #{ \markup { \dynamic p \normal-text \italic "dolce" } #})
crescPoco = #(make-music 'CrescendoEvent 'span-direction START 'span-type 'text 'span-text "cresc. poco a poco")
dimPoco = #(make-music 'DecrescendoEvent 'span-direction START 'span-type 'text 'span-text "dim. poco a poco")

''' % {'n': total}

with open(out_path, 'w') as fh:
    fh.write(HEAD)
    fh.write('global = {\n' + g.render() + '}\n\n')
    fh.write('marks = {\n' + mk.render() + '}\n\n')
    fh.write('dynamicsLine = {\n' + d.render() + '}\n')
print(f'wrote {out_path}: {total} bars, sections at {starts}, grid {UNIT} beat')
