import sys; sys.path.insert(0,'..'); sys.argv=[sys.argv[0]]
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
import skeleton as K
from mats import *
from ricer import *
from fractions import Fraction as F
base = list(K.STMT)
altoM1 = parse("ees'2 d'2 | ees'2. d'4 | c'2 b4. d'8 | d'2. ees'4")
sopM2 = parse("aes''2 g''2~ | g''2 f''4. e''8 | f''2 e''2 | f''4 g''4 bes''4 aes''4")
bass27 = parse("des2")
extra = [('alto', 19, 3, 'free alto M1', shift(altoM1, F(0))[1:] if False else parse("d'2 | ees'2. c'4~ | c'2 b4. d'8 | f'2. ees'4")),
         ('soprano', 23, 1, 'free soprano M2', sopM2)]
K.STMT[:] = base + extra
p = K.build(name='mirror_full.ly')
out = check(p, bars='18-27')
cnt, s, tot = summary(out)
print(tot)
for l in out.splitlines():
    if l[:4] in ('PAR!','BEAT','DIS!','D4? ','CROS','DIR ','MEL '): print('   ', l)
for l in strict(out): print('    strict:', l)
print('--- + soprano CS1 over the chain (27-31) and bass des at 27:1')
K.STMT[:] = base + extra + [('soprano', 27, 1, 'CS1 over S1', K.drop_landing(octave(CS1, 1))), ('bass', 27, 1, 'des', parse("des2"))]
p = K.build(name='mirror_full2.ly')
out = check(p, bars='26-33')
cnt, s, tot = summary(out)
print(tot)
for l in out.splitlines():
    if l[:4] in ('PAR!','BEAT','DIS!','D4? ','CROS','DIR ','MEL '): print('   ', l)
for l in strict(out): print('    strict:', l)
