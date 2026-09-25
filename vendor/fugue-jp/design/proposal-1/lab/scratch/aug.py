import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
from fractions import Fraction as F
def test(name, voices, total=None, show_all=False):
    p = lab(name, voices, name, total)
    out = check(p)
    cnt, s, tot = summary(out)
    st = strict(out)
    print(f"{name:30s} PAR={cnt['PAR!']} BEAT={cnt['BEAT']} DIS!={cnt['DIS!']} D4?={cnt['D4?']} DIR={cnt['DIR']} CROS={cnt['CROS']} ERR={cnt['ERR']} strict={len(st)}")
    for l in out.splitlines():
        if l[:4] in ('PAR!','BEAT','DIS!','D4? ','DIR ','CROS','ERR ') or (show_all and l[:3]=='DIS'): print('   ', l)
    for l in st: print('    strict:', l)
if __name__ == '__main__':
  B = octave(A1aug, -2)
  print(render(B))
  # two-voice: bass A1aug with S1 / I1 at various offsets (quarters)
  for q in range(0, 20, 2):
      test(f"augS1_{q}.ly", dict(alto=shift(S1, F(q, 4)), bass=B))
  for q in range(0, 20, 2):
      test(f"augI1_{q}.ly", dict(soprano=shift(I1, F(q, 4)), bass=B))
  print('--- 3/4 voice climax combos')
  test("clim_a.ly", dict(soprano=I1, alto=S1, bass=B))
  test("clim_b.ly", dict(soprano=I1, alto=S1, tenor=octave(CS1, -1), bass=B))
  test("clim_c.ly", dict(soprano=I1, alto=S1, tenor=octave(CS2, -1), bass=B))
  test("clim_d.ly", dict(soprano=I1, alto=S1, tenor=octave(IC1, -2), bass=B))
  test("clim_e.ly", dict(soprano=I1, alto=S1, tenor=octave(IC2, -1), bass=B))
  # second wave at +4 bars: S1 in soprano? I1 in tenor?
  test("clim_f.ly", dict(soprano=I1 + shift(octave(S1, 0), F(4)), alto=S1, bass=B))
  print('--- climax v2 (S1 in tenor, I1 soprano, bass F,)')
  B2 = octave(A1aug, -3)
  test("clim2_a.ly", dict(soprano=I1, tenor=octave(S1, -1), bass=B2))
  test("clim2_b.ly", dict(soprano=I1, alto=CS1, tenor=octave(S1, -1), bass=B2))
  test("clim2_c.ly", dict(soprano=I1, alto=CS2, tenor=octave(S1, -1), bass=B2))
  test("clim2_d.ly", dict(soprano=I1, alto=octave(IC1, -1), tenor=octave(S1, -1), bass=B2))
  test("clim2_e.ly", dict(soprano=I1, alto=octave(IC2, 0), tenor=octave(S1, -1), bass=B2))
  test("clim2_f.ly", dict(soprano=octave(IC1,-1), alto=I1, tenor=octave(S1, -1), bass=B2))
