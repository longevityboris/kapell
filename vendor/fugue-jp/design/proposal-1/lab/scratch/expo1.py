import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from ricer import *
S = """
bes'2. bes'8 a' | bes'2. bes'8 a' | bes'4. c''8 c''4. ees''8 | ees''2. des''8 bes' |
c''2 des''2 | d''4. ees''8 f''4. g''8 | f''2. ees''4~ | ees''4 d''4 des''4 c''4 |
b'2 c''2~ | c''4 bes'4 a'2 |
bes'4 f''4 ees''4 des''8 c''8 | bes'4 c''4 des''4 ees''4 | des''4 c''4 ees''4. des''8 | c''2 bes'4. aes'8~ |
aes'4 r4 r2 | r2 c''2~ | c''4 bes'4 ees''2~ | ees''2 des''4 f''4~ |
f''2
"""
A = """
R1*4 |
f'2. f'8 e' | f'2. f'8 e' | f'4. g'8 g'4. bes'8 | bes'2. aes'8 f' |
g'2 e'2 | f'2 c'2 |
f'2 ges'2 | g'4. aes'8 bes'4. c''8 | bes'2. aes'4~ | aes'4 g'4 ges'4 f'4 |
r4 c''4 bes'4 aes'8 g'8 | f'4 g'4 aes'4 bes'4 | aes'4 g'4 bes'4. aes'8 | g'2 f'4. ees'8 |
d'2
"""
T = """
R1*10 |
bes2. bes8 a | bes2. bes8 a | bes4. c'8 c'4. ees'8 | ees'2. des'8 bes |
c'2 des'2 | d'4. ees'8 f'4. g'8 | f'2. ees'4~ | ees'4 d'4 des'4 c'4 |
b2
"""
B = """
R1*14 |
f2. f8 e | f2. f8 e | f4. g8 g4. bes8 | bes2. aes8 f |
g2
"""
p = lab('expo1.ly', dict(soprano=S, alto=A, tenor=T, bass=B), 'Exposition 1-19 v1')
out = check(p)
print('\n'.join(l for l in out.splitlines() if not l.startswith('DIS ')))
print('strict:'); print('\n'.join(strict(out)))
