#!/usr/bin/env python3
"""quick 2-4 voice trial: python3 try2.py NAME 'sop' 'alt' 'ten' 'bas' (use - for empty)"""
import sys
from p4 import *
nm = sys.argv[1]
vs = {}
for v, s in zip(VOICES, sys.argv[2:6]):
    if s != '-':
        vs[v] = ly(s)
p = write_lab(nm + '.ly', vs, title=nm)
out = check(p, grid='--grid' in sys.argv)
print(out)
