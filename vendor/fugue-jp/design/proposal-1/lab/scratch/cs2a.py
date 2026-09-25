import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
from show import show
CS2 = parse("r4 des'4 c'4 ees'4~ | ees'4 des'4 c'4 f4 | ges2 f2 | aes2. f4 | c2")
show([S1, CS1, CS2])
perms({'S1': S1, 'CS1': CS1, 'CS2': CS2}, 'cs2a')
