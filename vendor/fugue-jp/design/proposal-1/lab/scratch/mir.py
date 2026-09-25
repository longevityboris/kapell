import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
from show import show
CS2 = parse("r4 f''4 ees''4 des''8 c''8 | bes'4 c''4 des''4 ees''4 | des''4 c''4 ees''4. des''8 | c''2 bes'4. aes'8 | g'2")
I1 = mirror(S1); IC1 = mirror(CS1); IC2 = mirror(CS2)
for n, l in (('I1', I1), ('IC1', IC1), ('IC2', IC2)):
    print(n, render(l))
perms({'I1': I1, 'IC1': IC1, 'IC2': IC2}, 'mir')
