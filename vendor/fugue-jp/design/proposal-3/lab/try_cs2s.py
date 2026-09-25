from gen import *
from shape import shape_pen
from p3 import show, quick, bad, to_ly
import itertools
cs1 = mel("r2 g2 | ges2 f2 | e2 f2 | ges2 f2")          # tenor octave
sync = [(F(1), F(2))] + [(F(1 + 2 * i), F(2)) for i in range(1, 7)] + [(F(15), F(1)), (F(16), F(2))]

def desc_pen(seq, p, t, d):
    s = shape_pen(seq, p, t, d, span_min=0)
    if seq:
        iv = p - seq[-1][2]
        if iv > 0:
            s += 0.8
        if iv == 0:
            s += 0.5
    return s

configs = {
    'bass':   dict(lo=38, hi=50, lowest=True),
    'middle': dict(lo=55, hi=69, lowest=False),
}
for name, cfg in configs.items():
    fixed = [S1, cs1] if name == 'bass' else [S1, tr(cs1, '-8')]
    res = generate(fixed, sync, cfg['lo'], cfg['hi'], lowest=cfg['lowest'], beam=800, top=80,
                   pcs_allowed={10, 0, 1, 3, 5, 6, 8, 9, 7}, pen_extra=desc_pen, finish={10, 1, 5})
    out = []
    for sc, m in res:
        if name == 'bass':
            parts = {'alto': [S1], 'tenor': [cs1], 'bass': [m]}
        else:
            parts = {'soprano': [tr(S1, '8')], 'alto': [m], 'tenor': [tr(cs1, '-8')] if False else [cs1]}
            parts = {'alto': [S1], 'tenor': [m], 'bass': [tr(cs1, '-8')]}
        s, lines = quick(parts, 5)
        strong = sum(1 for l in lines if l.startswith('DIS ') and ' strong ' in l)
        out.append((bad(s), s['d4'] + s['mel'] + s['cros'], strong, round(sc, 2), to_ly(m, 20)))
    out.sort()
    print('=====', name)
    for o in out[:12]:
        print(o[:4], o[4].replace('\n', ' '))
