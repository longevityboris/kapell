import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
import itertools, io, contextlib
S2Mu = transpose(S2M, 4, 7)    # S2 (major form) a fifth higher: F major, g''
def allperm(L, tag):
    for order in itertools.permutations(L):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_perm(order, L, tag)
        s = buf.getvalue(); head = s.splitlines()[0]
        print(head); print('\n'.join(l for l in s.splitlines()[1:] if 'strict' in l or l.strip()[:4] in ('PAR!','BEAT','DIS!','D4? ','DIR ')))
print(render(S2Mu))
allperm({'S1': S1, 'S2Mu': S2Mu}, 'c2')
allperm({'S1': S1, 'S2Mu': S2Mu, 'CS1': CS1}, 'c3a')
allperm({'S1': S1, 'S2Mu': S2Mu, 'CS2': CS2}, 'c3b')
