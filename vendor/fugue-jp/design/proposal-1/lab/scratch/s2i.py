import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from matrix import matrix
from fractions import Fraction as F
print(render(I1M)); print(render(S1M))
offs = [F(k, 4) for k in range(0, 17, 2)]
matrix(S2M, I1M, 'S2M leader x I1M follower', offs)
matrix(S2M, S1M, 'S2M leader x S1M follower', offs)
