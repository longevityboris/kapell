import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from matrix import matrix
from fractions import Fraction as F
offs = [F(k, 4) for k in range(0, 9, 1)]
matrix(S2, CS2, 'S2 (bes minor) x CS2', offs)
matrix(S2, CS1, 'S2 (bes minor) x CS1', offs)
matrix(S2M, CS2, 'S2M x CS2', offs)
