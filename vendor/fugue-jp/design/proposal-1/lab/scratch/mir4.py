import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
CS2 = parse("r4 f''4 ees''4 des''8 c''8 | bes'4 c''4 des''4 ees''4 | des''4 c''4 ees''4. des''8 | c''2 bes'4. aes'8 | g'2")
I1 = mirror(S1); IC1 = mirror(CS1); IC2 = mirror(CS2)
L = dict(S1=S1, CS1=CS1, CS2=CS2, I1=I1, IC1=IC1, IC2=IC2)
import itertools
for a, b in itertools.combinations(L, 2):
    if {a, b} in ({'S1','CS1'},{'S1','CS2'},{'CS1','CS2'},{'I1','IC1'},{'I1','IC2'},{'IC1','IC2'}):
        continue
    for order in ((a, b), (b, a)):
        run_perm(order, L, 'pair')
