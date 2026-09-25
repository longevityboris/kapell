import sys; sys.path.insert(0, '..')
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
from mats import *
from cssearch import *
C = S2M   # c'' level, B-flat major
names = "c'' d'' ees'' f'' g'' a'' bes'' c''' d'''".split()
tpls = {
 'a': "x2. x4~ | x4 x4 x4 x4 | x2 x4 x4 | x4 x4 x4 x4 | x2",
 'b': "x2 x4 x4 | x2. x4 | x4. x8 x4 x4 | x2 x2 | x2",
 'c': "x2. x4~ | x4 x4 x2 | x4 x4 x4. x8 | x4 x4 x4 x4 | x2",
 'd': "r4 x4 x4 x4 | x2. x4~ | x4 x4 x4 x4 | x2 x4 x4 | x2",
}
for k, t in tpls.items():
    res = cs_search(C, t, names, above=True, width=600, keep=4)
    for seq, cost in res:
        print(k, round(cost, 1), to_ly(seq))
