import sys; sys.path.insert(0,'..'); sys.argv=[sys.argv[0]]
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
import skeleton as K
from mats import *
from ricer import *
from fractions import Fraction as F
base = list(K.STMT)
def run(tag, extra):
    K.STMT[:] = base + extra
    p = K.build(name=f'sk63_{tag}.ly')
    out = check(p, bars='59-68')
    cnt, s, tot = summary(out)
    st = strict(out)
    print(f"{tag:12s} PAR={cnt['PAR!']} BEAT={cnt['BEAT']} DIS!={cnt['DIS!']} D4?={cnt['D4?']} CROS={cnt['CROS']} strict={len(st)}")
    for l in out.splitlines():
        if l[:4] in ('PAR!','BEAT','DIS!','D4? ','CROS','DIR ','MEL '): print('   ', l)
    for l in st: print('    strict:', l)
tr = lambda l, s, d: transpose(l, d, s)
run('none', [])
run('S_S1', [('soprano', 63, 3, 'x', K.trim(S1, F(9, 2)))])
run('S_S1_T_I1', [('soprano', 63, 3, 'x', S1), ('tenor', 64, 1, 'x', octave(I1, -1))])
run('A_S1_S_I1', [('alto', 63, 3, 'x', S1), ('soprano', 64, 1, 'x', I1)])
