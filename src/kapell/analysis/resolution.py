"""Tendency-tone resolution: chordal sevenths (DIS7) and leading tones of dominant sevenths (LT).

A seventh chord is recognised from the spelled notes sounding at an attack (LilyPond spelling is
kept by lyparse): the letters must stack in thirds on one root (letters 0, 2, 4, 6 above it, the
fifth optional, the third required) with a third of 3-4, a fifth of 6-8 and a seventh of 9-11
semitones. Non-chord tones break the stack, so passing sonorities are not read as chords.

DIS7  the seventh of a seventh chord must resolve by step down (1-2 semitones) when its voice leaves
      it. It also counts as resolved when
        - the voice reaches the step below through one intervening note within 2 beats
          (ornamented resolution);
        - another voice takes the step below in the same register as the seventh leaves (hand-off
          of the resolution);
        - another voice holds or re-strikes the same seventh (same letter and pitch class) and that
          voice steps down within `beats` beats (hand-off of the seventh);
        - the harmony is unchanged when the voice leaves and another voice still sounds the seventh
          (the obligation moves to that voice, which is checked on its own);
        - the seventh rises by step while the bass rises by step (the V4/3-I6 tenths licence);
        - the "seventh" rises a semitone while the root falls a semitone in the bass (a German
          sixth spelled as a dominant seventh, resolving outward).
      A minor seventh chord with its third in the bass is read as an added-sixth chord and skipped.
      Re-strikes and short returning neighbour notes (E F E) continue the seventh while the chord
      keeps its root; a seventh carried into a new harmony that way is no longer checked.
      Only sevenths on a quarter-beat attack or at least a quarter long are checked; bass notes held
      a whole bar or more are pedal points and are skipped.
LT    the third of a dominant seventh (Mm7) in the top sounding voice must rise a semitone when the
      next harmony's root lies a fifth below (V7-I), unless another voice takes the tonic in the
      same register.

Findings: {code, at, voice, note, chord, to, message}, "bar:beat" 1-based quarter beats.
"""
from bisect import bisect_right
from fractions import Fraction as F

from kapell.analysis.coverage import load_voices, pos

LETTERS = "CDEFGAB"
QUALITY = {(4, 7, 10): "Mm7", (4, None, 10): "Mm7", (3, 7, 10): "m7", (3, None, 10): "m7",
           (3, 6, 10): "half-dim7", (3, 6, 9): "dim7", (3, None, 9): "dim7", (4, 7, 11): "M7",
           (4, None, 11): "M7", (3, 7, 11): "mM7"}


def _letter(n):
    return LETTERS.index(n.name[0])


def seventh_chord(notes):
    """notes: Note objects sounding together. -> (root_letter, root_pc, seventh (letter, pc), quality) | None"""
    tones = {(_letter(n), n.midi % 12) for n in notes}
    if len(tones) < 3:
        return None
    for rl, rpc in tones:
        rel = {}
        ok = True
        for L, pc in tones:
            d = (L - rl) % 7
            if d not in (0, 2, 4, 6) or (d in rel and rel[d] != (pc - rpc) % 12):
                ok = False
                break
            rel[d] = (pc - rpc) % 12
        if not ok or 2 not in rel or 6 not in rel or rel.get(0) != 0:
            continue
        q = QUALITY.get((rel[2], rel.get(4), rel[6]))
        if q:
            return rl, rpc, ((rl + 6) % 7, (rpc + rel[6]) % 12), q, ((rl + 2) % 7, (rpc + rel[2]) % 12)
    return None


class _Score:
    def __init__(self, voices: dict, measure):
        self.v = {k: [n for n in ns] for k, ns in voices.items()}
        self.starts = {k: [n.start for n in ns] for k, ns in self.v.items()}
        self.measure = measure
        self.order = list(voices)          # top to bottom
        self.times = sorted({n.start for ns in self.v.values() for n in ns if n.midi is not None})

    def at(self, v, t):
        ns, st = self.v[v], self.starts[v]
        i = bisect_right(st, t) - 1
        if i < 0:
            return None, -1
        n = ns[i]
        return (n if n.start <= t < n.end and n.midi is not None else None), i

    def sounding(self, t):
        out = []
        for v in self.order:
            n, _ = self.at(v, t)
            if n:
                out.append((v, n))
        return out

    def after(self, v, i, t_limit):
        """Notes of voice v after index i starting before t_limit (rests included)."""
        out = []
        for n in self.v[v][i + 1:]:
            if n.start >= t_limit:
                break
            out.append(n)
        return out


def _name(rl, rpc):
    nat = {0: 0, 1: 2, 2: 4, 3: 5, 4: 7, 5: 9, 6: 11}[rl]
    alt = (rpc - nat + 6) % 12 - 6
    return LETTERS[rl] + ("#" * alt if alt > 0 else "b" * -alt)


def check(src: str, voices, measure=F(1), beats: int = 4, bars=None) -> list:
    sc = _Score(load_voices(src, voices, measure), measure)
    win = F(beats, 4)
    out, seen = [], set()
    bass = sc.order[-1] if sc.order else None
    for t in sc.times:
        snd = sc.sounding(t)
        ch = seventh_chord([n for _, n in snd])
        if not ch:
            continue
        rl, rpc, sev, q, third = ch
        low = snd[-1][1]
        if q == "m7" and (_letter(low), low.midi % 12) == third:
            continue                        # added-sixth chord (C E G A over C), not A m7
        cname = f"{_name(rl, rpc)} {q}"
        b = int(t / measure) + 1
        if bars and not (bars[0] <= b <= bars[1]):
            continue
        for v, n in snd:
            if (_letter(n), n.midi % 12) != sev or (v, n.start) in seen:
                continue
            seen.add((v, n.start))
            _, i0 = sc.at(v, n.start)
            for x in sc.v[v][i0 + 1:]:          # re-strikes of the same seventh are one event
                if x.midi != n.midi:
                    break
                seen.add((v, x.start))
            on_grid = ((n.start * 4) % 1 == 0)
            if not (on_grid or n.dur >= F(1, 4)):
                continue
            if v == bass and n.dur >= measure:
                continue
            f = _seventh(sc, v, n, (rl, rpc), sev, win, bass)
            if f:
                f.update(code="DIS7", at=pos(n.start, measure), voice=v, note=n.name, chord=cname)
                f["message"] = f"{cname} at {pos(t, measure)}: seventh {n.name} ({v}) {f.pop('how')}"
                out.append(f)
        # leading tone of V7 in the top voice
        if q == "Mm7" and snd and (snd[0][0], snd[0][1].start) not in seen:
            v, n = snd[0]
            if (_letter(n), n.midi % 12) == third:
                seen.add((v, n.start))
                f = _leading(sc, v, n, (rl, rpc), win)
                if f:
                    f.update(code="LT", at=pos(n.start, measure), voice=v, note=n.name, chord=cname)
                    f["message"] = f"{cname} to {f.pop('next')}: leading tone {n.name} ({v}) {f.pop('how')}"
                    out.append(f)
    return out


def _departure(sc, v, n, root=None):
    """Follow same-pitch re-strikes and short neighbour notes that return (E F E: the E goes on)
    while the harmony keeps its root. Returns (last note, next note or None, index of last,
    absorbed); absorbed is True when the note was carried into a new harmony, where it is no
    longer the seventh of the chord it was checked in."""
    _, i = sc.at(v, n.start)
    cur = n
    ns = sc.v[v]
    while i + 1 < len(ns) and ns[i + 1].start == cur.end and ns[i + 1].midi is not None:
        a = ns[i + 1]
        b = ns[i + 2] if i + 2 < len(ns) else None
        if a.midi == cur.midi:
            step, x = 1, a
        elif (abs(a.midi - cur.midi) <= 2 and a.dur <= F(1, 4) and b is not None
              and b.start == a.end and b.midi == cur.midi):
            step, x = 2, b
        else:
            break
        if root is not None:
            ch = seventh_chord([y for _, y in sc.sounding(x.start)])
            if not ch or (ch[0], ch[1]) != root:
                return x, None, i + step, True
        i += step
        cur = x
    nxt = ns[i + 1] if i + 1 < len(ns) and ns[i + 1].start == cur.end else None
    if nxt is not None and nxt.midi is None:
        nxt = None
    return cur, nxt, i, False


def _seventh(sc, v, n, root, sev, win, bass):
    cur, nxt, i, absorbed = _departure(sc, v, n, root)
    if absorbed:
        return None
    t = cur.end
    res = {cur.midi - 1, cur.midi - 2}
    if nxt is not None and nxt.midi in res:
        return None
    # same harmony, the seventh still sounds elsewhere: the obligation moves to that voice
    snd = sc.sounding(t)
    ch = seventh_chord([x for _, x in snd]) if snd else None
    if ch and (ch[0], ch[1]) == root and any(w != v and (_letter(x), x.midi % 12) == sev for w, x in snd):
        return None
    # ornamented resolution in the same voice: one intervening note, step below within 2 beats
    orn = [x for x in sc.after(v, i, t + F(1, 2))][:2]
    if len(orn) == 2 and orn[1].midi in res and orn[0].midi is not None:
        return None
    # enharmonic augmented sixth (German sixth spelled as a dominant seventh): the "seventh"
    # rises a semitone while the root falls a semitone in the bass
    if nxt is not None and nxt.midi - cur.midi == 1:
        bn, _ = sc.at(bass, t - F(1, 64))
        ba, _ = sc.at(bass, t)
        if bn and ba and bn.midi % 12 == root[1] and ba.midi - bn.midi == -1:
            return None
    for w in sc.order:
        if w == v:
            continue
        x, j = sc.at(w, t)
        # hand-off of the resolution in the same register
        if x is not None and x.start == t and x.midi in res:
            return None
        # hand-off of the seventh itself, then a step down in that voice
        if x is not None and (_letter(x), x.midi % 12) == sev:
            xc, xn, _, _ = _departure(sc, w, x)
            if xn is not None and xn.midi - xc.midi in (-1, -2) and xc.end <= t + win:
                return None
    # V4/3-I6 licence: seventh and bass rise by step together
    if nxt is not None and v != bass and nxt.midi - cur.midi in (1, 2):
        bn, _ = sc.at(bass, t - F(1, 64))
        ba, _ = sc.at(bass, t)
        if bn and ba and ba.start == t and ba.midi - bn.midi in (1, 2):
            return None
    if nxt is None:
        how = f"is left by a rest at {pos(t, sc.measure)}, unresolved within {int(win * 4)} beats"
        to = None
    else:
        how = f"moves {nxt.midi - cur.midi:+d} to {nxt.name} at {pos(t, sc.measure)}, no step-down resolution within {int(win * 4)} beats"
        to = nxt.name
    return {"to": to, "how": how}


def _leading(sc, v, n, root, win):
    cur, nxt, _, _ = _departure(sc, v, n)
    t = cur.end
    snd = sc.sounding(t)
    ch = seventh_chord([x for _, x in snd]) if snd else None
    if ch and (ch[0], ch[1]) == root:
        return None                        # harmony unchanged: not a cadence yet
    # next harmony root: the bass note at t
    bn = snd[-1][1] if snd else None
    if bn is None or (bn.midi - root[1]) % 12 != 5:
        return None                        # not V-I root motion
    tonic = cur.midi + 1
    if nxt is not None and nxt.midi == tonic:
        return None
    if any(x.start == t and x.midi == tonic for _, x in snd):
        return None
    where = f"{nxt.name}" if nxt is not None else "a rest"
    return {"to": nxt.name if nxt is not None else None, "next": bn.name,
            "how": f"goes to {where} at {pos(t, sc.measure)} instead of rising a semitone"}


def run_project(root, cfg: dict, score=None, bars=None) -> dict:
    from pathlib import Path
    from kapell.analysis.coverage import measure_of
    paths = cfg.get("paths") or {}
    score = Path(score) if score else Path(root) / paths.get("score", "score/music-voices.ly")
    voices = (cfg.get("piece") or {}).get("voices") or ["soprano", "alto", "tenor", "bass"]
    beats = int(((cfg.get("checks") or {}).get("resolution_beats")) or 4)
    found = check(score.read_text(), voices, measure_of(cfg), beats, bars)
    counts = {}
    for f in found:
        counts[f["code"]] = counts.get(f["code"], 0) + 1
    return dict(beats=beats, counts=counts, ok=not found, violations=found)
