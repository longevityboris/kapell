import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from show import show
# E4 at relative bars 1-4 (+5:1): B = A1 at F, ; T = CS1 answer level at c' ; A = CS2 answer level (down a 4th)
B = octave(A1, -2)
T = transpose(CS1, 4, 7)          # f' -> c'' ... then down an octave
T = octave(T, -1)
A = transpose(CS2, -3, -5)
show([A, T, B], ['A', 'T', 'B'])
print(render(A)); print(render(T)); print(render(B))
