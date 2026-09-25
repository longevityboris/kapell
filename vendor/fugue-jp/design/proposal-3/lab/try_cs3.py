from gen import *
from shape import shape_pen
from p3 import *
from mats import S2
import sys
rh = eighths(4, start_rest=F(1, 2))
sk = {F(0, 1) + 0: {5, 9}, F(2): {5, 0, 9}, F(4): {3, 6, 0}, F(6): {5, 9, 3}, F(8): {3, 6}, F(10): {1, 6, 10},
      F(12): {5, 9, 3}, F(14): {5, 9, 0}}
res = generate([S2], rh, 55, 68, skeleton=sk, lowest=None, beam=900, top=80,
               pcs_allowed={10, 0, 1, 3, 5, 6, 8, 9, 7}, pen_extra=lambda s, p, t, d: shape_pen(s, p, t, d, span_min=5),
               finish={10, 1, 5})
out = []
for sc, m in res:
    a = full({'soprano': [S2], 'alto': [m]}, 5)
    b = full({'alto': [octs(S2, -1)], 'tenor': [octs(m, -1)]}, 5)  # same order lower
    c = full({'soprano': [octs(m, 1)], 'alto': [S2]}, 5)          # inverted at the octave
    key = (bad(a[0]) + bad(c[0]), a[1]['clash'] + c[1]['clash'], a[1]['acc2'] + c[1]['acc2'], a[1]['acc'] + c[1]['acc'],
           a[0]['d4'] + c[0]['d4'] + a[0]['cros'] + c[0]['cros'], round(sc, 1))
    out.append((key, to_ly(m, 20).replace('\n', ' ')))
out.sort()
for k, l in out[:12]:
    print(k, l)
