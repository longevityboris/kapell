#!/usr/bin/env python3
"""Exploration tool for proposal 3: two-voice fit tables (stretto / combination / invertibility).

Not the verifier (check.py is). This only ranks candidate pairings quickly so the good ones
can be written out as lab .ly files.

Melodies are LilyPond \\absolute strings (notes, rests, ties). Time unit = quarter note, 4/4.
"""
import re, sys
from fractions import Fraction as F

PC = dict(c=0, d=2, e=4, f=5, g=7, a=9, b=11)
TOK = re.compile(r"(?P<n>[a-g](?:isis|eses|is|es)?[',]*|r|s)(?P<d>\d+)?(?P<dot>\.*)(?P<tie>~)?|\|")


def parse(src):
    """-> list of [start, dur, midi or None, step] (step = diatonic index)"""
    t, dur, out, tie = F(0), F(1), [], False
    for m in TOK.finditer(re.sub(r"%.*", "", src)):
        if m.group(0) == '|':
            continue
        n = m.group('n')
        if m.group('d'):
            dur = F(4, int(m.group('d')))
            add = dur
            for _ in m.group('dot'):
                add /= 2
                dur += add
        if n in ('r', 's'):
            out.append([t, dur, None, None])
            tie = False
        else:
            acc = n[1:].rstrip("',")
            alt = {'': 0, 'is': 1, 'es': -1, 'isis': 2, 'eses': -2}[acc]
            octv = 3 + n.count("'") - n.count(",")
            midi = 12 * (octv + 1) + PC[n[0]] + alt
            step = 'cdefgab'.index(n[0]) + 7 * octv
            if tie and out and out[-1][2] == midi:
                out[-1][1] += dur
            else:
                out.append([t, dur, midi, step])
            tie = bool(m.group('tie'))
        t += dur
    return out


def shift(mel, dt=0, semis=0, steps=0):
    return [[s + dt, d, (m + semis if m is not None else None), (st + steps if st is not None else None)]
            for s, d, m, st in mel]


def augment(mel, k=2):
    return [[s * k, d * k, m, st] for s, d, m, st in mel]


def at(mel, t):
    for i, (s, d, m, st) in enumerate(mel):
        if s <= t < s + d:
            return i if m is not None else None
    return None


def fit(up, lo, four_ok=False, strong_every=2, verbose=False):
    """Score upper voice `up` against lower voice `lo`. Lower is better."""
    times = sorted({n[0] for n in up} | {n[0] for n in lo})
    pen, notes = 0, []
    prev = None
    for t in times:
        iu, il = at(up, t), at(lo, t)
        if iu is None or il is None:
            prev = None
            continue
        u, l = up[iu], lo[il]
        diff = u[2] - l[2]
        if diff < 0:
            pen += 3
            notes.append(f"{t}: crossing")
        ic = diff % 12
        strong = (t % strong_every == 0)
        diss = ic in (1, 2, 6, 10, 11) or (ic == 5 and not four_ok)
        if diss:
            ok = False
            for mine, other, mel, idx in ((u, l, up, iu), (l, u, lo, il)):
                pv = mel[idx - 1] if idx > 0 and mel[idx - 1][2] is not None and mel[idx - 1][0] + mel[idx - 1][1] == mine[0] else None
                nx = mel[idx + 1] if idx + 1 < len(mel) and mel[idx + 1][2] is not None else None
                if mine[0] == t:  # mover
                    si = pv is not None and 1 <= abs(mine[2] - pv[2]) <= 2
                    so = nx is not None and 1 <= abs(nx[2] - mine[2]) <= 2
                    if si and so and not strong:
                        ok = True
                    elif si and so and strong:
                        pen += 2  # accented passing tone
                        ok = True
                        notes.append(f"{t}: accented passing {ic}")
                    elif so and not strong and other[0] < t:
                        pen += 1
                        ok = True
                else:  # held: suspension if it resolves down by step
                    if nx is not None and 1 <= mine[2] - nx[2] <= 2 and other[0] == t:
                        ok = True
            if not ok:
                pen += 6 if strong else 3
                notes.append(f"{t}: bad diss ic={ic}{' strong' if strong else ''}")
        # parallels between consecutive simultaneities where both move
        if prev is not None:
            pu, pl, pic = prev
            if u[2] != pu and l[2] != pl and ic == pic and ic in (0, 7):
                pen += 10
                notes.append(f"{t}: parallel {'8' if ic == 0 else '5'}")
        prev = (u[2], l[2], ic)
    return pen, notes


def table(a, b, dts, semis_list, label, four_ok=True, show=8):
    res = []
    for dt in dts:
        for k in semis_list:
            bb = shift(b, dt, k)
            # decide which is upper by mean pitch in overlap
            ov = [(n[2]) for n in bb if n[2] is not None]
            oa = [(n[2]) for n in a if n[2] is not None]
            if sum(ov) / len(ov) >= sum(oa) / len(oa):
                p, n = fit(bb, a, four_ok)
            else:
                p, n = fit(a, bb, four_ok)
            res.append((p, dt, k, n))
    res.sort(key=lambda r: r[0])
    print(f"== {label}")
    for p, dt, k, n in res[:show]:
        print(f"  pen {p:3}  delay {float(dt):5g} q  transp {k:+d}  {'; '.join(n[:6])}")


if __name__ == '__main__':
    pass


NAMES = ['c', 'des', 'd', 'ees', 'e', 'f', 'ges', 'g', 'aes', 'a', 'bes', 'b']
IVN = {0: '8', 1: 'm2', 2: 'M2', 3: 'm3', 4: 'M3', 5: 'P4', 6: 'TT', 7: 'P5', 8: 'm6', 9: 'M6', 10: 'm7', 11: 'M7'}


def nm(m):
    return NAMES[m % 12] + str(m // 12 - 1)


def grid(*mels):
    times = sorted({n[0] for mel in mels for n in mel if n[2] is not None})
    for t in times:
        row, ms = [], []
        for mel in mels:
            i = at(mel, t)
            if i is None:
                row.append('   -    ')
                ms.append(None)
            else:
                n = mel[i]
                row.append(f"{nm(n[2]):5}{'*' if n[0] == t else ' '}  ")
                ms.append(n[2])
        ivs = []
        for j in range(len(ms) - 1):
            if ms[j] is not None and ms[j + 1] is not None:
                ivs.append(IVN[(ms[j] - ms[j + 1]) % 12])
            else:
                ivs.append('.')
        bar, beat = divmod(t, 4)
        print(f"{int(bar)+1}:{float(beat)+1:<5g}" + ''.join(row) + '  ' + ' '.join(ivs))
