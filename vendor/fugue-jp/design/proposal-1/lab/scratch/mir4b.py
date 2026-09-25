import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from perm import *
CS2 = parse("r4 f''4 ees''4 des''8 c''8 | bes'4 c''4 des''4 ees''4 | des''4 c''4 ees''4. des''8 | c''2 bes'4. aes'8 | g'2")
I1 = mirror(S1)
IC1 = parse("bes''2 a''2 | aes''4. g''8 f''4. ees''8 | f''2. ges''8 g''8~ | g''4 aes''4 a''4 bes''4 | ces'''2")
IC2 = mirror(CS2)
import itertools
which = sys.argv[1]
L = {k: v for k, v in dict(S1=S1, CS1=CS1, CS2=CS2, I1=I1, IC1=IC1, IC2=IC2).items() if k in which.split(',')}
import io, contextlib
for order in itertools.permutations(L):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_perm(order, L, 'q' + str(len(L)))
    s = buf.getvalue()
    head = s.splitlines()[0]
    if 'PAR=0 BEAT=0 DIS!=0 D4?=0' in head:
        print(head)
    else:
        print('  x ' + head[:40] + ' ' + ' | '.join(l.strip()[:60] for l in s.splitlines()[1:] if l.strip()[:4] in ('PAR!','BEAT','DIS!','D4? ','ERR ')))
