import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
sys.path.insert(0, '.')
from aug import test
S2D = transpose(S2M, 2, 3)      # D-flat major, ees''
CS3 = parse(sys.argv[1] if len(sys.argv) > 1 else "c'2 f'2 | ges'4 f'4 ees'4 f'4 | bes'2 aes'4 ges'4 | aes'4 bes'4 c''4 des''4 | c''2")
BS = parse(sys.argv[2] if len(sys.argv) > 2 else "c2 des2 | ges2 aes2 | ees2 f4 ges4 | aes2 c2 | aes2")
print(render(S2D))
test('cs3_S2_over_CS3.ly', dict(soprano=S2D, alto=CS3, bass=BS))
test('cs3_S2_over_CS3_nobass.ly', dict(soprano=S2D, alto=CS3))
test('cs3_CS3_over_S2.ly', dict(soprano=CS3 if False else octave(CS3, 1), alto=S2D, bass=BS))
test('cs3_CS3_over_S2lo.ly', dict(alto=CS3, tenor=octave(S2D, -1), bass=octave(BS, -1)))
