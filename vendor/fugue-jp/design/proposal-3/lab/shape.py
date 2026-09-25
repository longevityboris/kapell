"""melodic-shape penalties for gen.generate (pen_extra)"""
SCALE_BBM = {10, 0, 1, 3, 5, 6, 8}


def shape_pen(seq, p, t, d, scale=SCALE_BBM, chrom_ok=(9,), span_min=5):
    s = 0.0
    ps = [x[2] for x in seq] + [p]
    if p % 12 not in scale and p % 12 not in chrom_ok:
        s += 1.2
    if len(ps) >= 3:
        a, b, c = ps[-3:]
        if a == c and a != b:
            s += 1.0
        d1, d2 = b - a, c - b
        if d1 * d2 > 0 and abs(d1) <= 2 and abs(d2) <= 2:
            s -= 0.35
    if len(ps) >= 5:
        if ps[-1] == ps[-3] == ps[-5]:
            s += 3
    if len(ps) >= 8:
        w = ps[-8:]
        if max(w) - min(w) < span_min:
            s += 1.5
    if len(ps) >= 2 and abs(ps[-1] - ps[-2]) == 1 and (ps[-1] % 12 not in scale or ps[-2] % 12 not in scale):
        s += 0.3
    return s
