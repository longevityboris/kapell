import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
from show import show
S2u = transpose(S2, 4, 7)    # S2 a fifth higher (g'')
show([S2u, S1], ['S2@5', 'S1'])
run_perm(('S2u', 'S1'), {'S2u': S2u, 'S1': S1}, 'comb')
run_perm(('S1', 'S2u'), {'S2u': S2u, 'S1': S1}, 'comb')
# other transpositions of S2 against S1 at offset 0
for nm, tr in [('P1', (0, 0)), ('P4u', (3, 5)), ('M3d', (-2, -4)), ('m3u', (2, 3)), ('M6d', (-5, -9))]:
    L = {'S2x': transpose(S2, *tr), 'S1': S1}
    run_perm(('S2x', 'S1'), L, 'comb' + nm)
    run_perm(('S1', 'S2x'), L, 'comb' + nm)
