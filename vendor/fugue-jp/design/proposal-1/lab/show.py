from fractions import Fraction as F
from ricer import *
from search import at

def show(lines, names=None):
    """Print simultaneities of several lines (top first)."""
    names = names or [f'v{i}' for i in range(len(lines))]
    times = sorted({s for l in lines for s, d, p in l})
    for t in times:
        row = []
        mids = []
        for l in lines:
            e = at(l, t)
            if e and e[2]:
                nm = pname(e[2]) + ('*' if e[0] == t else ' ')
                mids.append(e[2][1])
            else:
                nm = '-'
            row.append(f"{nm:9}")
        ivs = ''
        if len(mids) >= 2:
            ivs = ' '.join(str((mids[i] - mids[-1]) % 12) for i in range(len(mids) - 1))
        bar = int(t) + 1
        beat = (t - int(t)) * 4 + 1
        print(f"{bar}:{float(beat):<5g} " + ''.join(row) + '  | ' + ivs)
