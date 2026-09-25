import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
from show import show
CS2 = parse(sys.argv[1] if len(sys.argv) > 1 else "r4 f''4 ees''4 des''8 c''8 | bes'4 c''4 des''4 ees''4 | des''4 c''4 ees''4 des''4 | c''2 bes'4. aes'8 | g'2")
show([CS2, CS1, octave(S1, -1)])
perms({'S1': S1, 'CS1': CS1, 'CS2': CS2}, 'cs2b')
