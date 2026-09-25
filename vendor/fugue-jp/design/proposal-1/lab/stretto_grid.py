"""Verified stretto grid: every (leader, follower, interval, distance) combination is
written as a two-voice lab in lab/stretto/ and run through tools/check.py.

Cell codes:  #  = 0 PAR!/BEAT/DIS!/D4? and strict 0  (clean in alla-breve terms)
             +  = 0 PAR!/BEAT/DIS!/D4?, strict > 0  (checker-clean, accented dissonance to review)
             .  = fails (parallels / unjustified dissonance)
python3 stretto_grid.py  -> prints the tables (also written to stretto_grid.txt)
"""
import os
from fractions import Fraction as F
from ricer import *
from mats import *

os.makedirs('stretto', exist_ok=True)
FORMS = {'S1': S1, 'I1': I1}
# follower interval: name -> (diatonic steps, semitones); negative = below
IV = [('8ve below', -7, -12), ('5th below', -4, -7), ('4th below', -3, -5),
      ('unison', 0, 0), ('4th above', 3, 5), ('5th above', 4, 7), ('8ve above', 7, 12)]
DIST = list(range(1, 17))


def cell(lead, fol, iv, q):
    dia, semi = iv[1], iv[2]
    f = shift(transpose(FORMS[fol], dia, semi), F(q, 4))
    L = FORMS[lead]
    # place the higher line in alto and the lower in tenor (octave apart if needed)
    if semi >= 0:
        voices = dict(alto=f, tenor=octave(L, -1)) if semi > 0 else dict(alto=L, tenor=octave(f, -1))
    else:
        voices = dict(alto=L, tenor=octave(f, 0) if semi <= -7 else octave(f, -1))
    name = f"stretto/{lead}_{fol}_{iv[0].replace(' ', '')}_{q}q.ly"
    lab(name, voices, name)
    out = check(name)
    cnt, s, tot = summary(out)
    bad = cnt['PAR!'] + cnt['BEAT'] + cnt['DIS!'] + cnt['D4?']
    if bad:
        return '.'
    return '#' if not strict(out) else '+'


if __name__ == '__main__':
    lines = []
    for lead, fol in (('S1', 'S1'), ('I1', 'I1'), ('S1', 'I1'), ('I1', 'S1')):
        lines.append(f"\n{lead} leader, {fol} follower; columns = entry distance in quarter notes")
        lines.append(f"{'':11s}" + ''.join(f"{q:>3d}" for q in DIST))
        for iv in IV:
            lines.append(f"{iv[0]:11s}" + ''.join(f"{cell(lead, fol, iv, q):>3s}" for q in DIST))
    txt = '\n'.join(lines)
    print(txt)
    open('stretto_grid.txt', 'w').write(txt + '\n')
