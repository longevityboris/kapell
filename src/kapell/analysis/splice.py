"""Verify one composed section against the skeleton (from final-lab/splice_check.py and fl.py).

check_section(section, skeleton, plan, base=None, voices=None, ranges=None, measure=None) -> dict

The section file holds the voices (\\absolute) for exactly its bars and a comment '% bars A-B'.
  1. LENGTH    each voice is exactly B-A+1 bars long;
  2. BOUNDARY  every voice keeps the skeleton's first attack at A:1 and its last note of bar B
               (pitch, rest, tie-in/tie-out), so the proven joins stay valid;
  3. LOCK      notes inside plan roles subject/answer/cf are unchanged (start, duration, pitch);
               cs spans too, up to the role's 'landing_from'; plan "keep" items likewise;
  4. UNISON    two voices on one MIDI pitch with one attacking fail unless the skeleton has it;
  5. CHECK     the section is spliced into `base` (default: the skeleton) and check + strict run on
               bars A-1..B+1 (the joins included): 0 errors, parallels, beat-parallels, unjustified
               and 0 CLASH.
Boundaries and locks always compare against the skeleton, even when base is another score.
Returns {section, bars, checked, pass, failures, known_unisons, check, strict, lines}.

Bar-string helpers (from fl.py): read_bars, splice_bars, write_source, section_bars.
"""
import json
import re
from fractions import Fraction as F

from kapell.analysis import check as _check
from kapell.analysis import parse_measure, parse_voices, read_source
from kapell.analysis import strict as _strict
from kapell.analysis.lyparse import parse_voice


# ---- bar-string helpers (fl.py) ----------------------------------------------------------------

def _body(src, v):
    m = re.search(r"(?m)^" + re.escape(v) + r"\s*=\s*\\absolute\s*\{(.*?)^\}", src, re.S)
    return re.sub(r"%.*", "", m.group(1)) if m else None


def _split_bars(body):
    body = re.sub(r"R1\*(\d+)", lambda m: " | ".join(["r1"] * int(m.group(1))), body)
    return [p for p in (x.strip() for x in body.split('|')) if p]


def read_bars(src, voices=None):
    """-> {voice: [bar strings]}; missing voices become whole-bar rests."""
    voices = parse_voices(voices)
    sc, n = {}, 0
    for v in voices:
        b = _body(src, v)
        sc[v] = _split_bars(b) if b is not None else None
        if sc[v]:
            n = max(n, len(sc[v]))
    return {v: (sc[v] if sc[v] is not None else ['r1'] * n) for v in voices}


def nbars(sc):
    return max(len(x) for x in sc.values())


def splice_bars(base, part, first):
    sc = {v: list(base[v]) for v in base}
    for v in base:
        for i, bar in enumerate(part.get(v, [])):
            j = first - 1 + i
            while len(sc[v]) <= j:
                sc[v].append('r1')
            sc[v][j] = bar
    return sc


def write_source(sc, note='', first_bar=1, per_line=4):
    out = ['\\version "2.24.0"'] + ['% ' + line for line in note.strip().splitlines()]
    for v, bars in sc.items():
        out.append(f"{v} = \\absolute {{")
        for i in range(0, len(bars), per_line):
            out.append(f"  % {first_bar + i}")
            out.append("  " + " | ".join(bars[i:i + per_line]) + " |")
        out.append("}")
    return "\n".join(out) + "\n"


def section_bars(src):
    """(A, B) from the '% bars A-B' comment, or None."""
    m = re.search(r'%\s*bars\s+(\d+)\s*-\s*(\d+)', src)
    return (int(m.group(1)), int(m.group(2))) if m else None


# ---- the check ---------------------------------------------------------------------------------

def _plan_pos(s):
    bar, beat = s.split(':')
    return F(int(bar) - 1) + (F(beat) - 1) / 4


def _pos(t):
    b = int(t) + 1
    return f"{b}:{float((t - (b - 1)) * 4 + 1):g}"


def _sounding(ns, t):
    for n in ns:
        if n.start <= t < n.end:
            return n
    return None


def _unisons(src, voices, t0, t1, measure):
    data = {v: [n for n in (parse_voice(src, v, measure) or []) if n.midi is not None] for v in voices}
    out = set()
    for t in sorted({n.start for v in voices for n in data[v] if t0 <= n.start < t1}):
        snd = {v: _sounding(data[v], t) for v in voices}
        vs = [v for v in voices if snd[v] is not None]
        for i in range(len(vs)):
            for j in range(i + 1, len(vs)):
                a, b = snd[vs[i]], snd[vs[j]]
                if a.midi == b.midi and (a.start == t or b.start == t):
                    out.add((t, vs[i], vs[j], a.midi))
    return out


def spliced_source(section, base, voices=None, section_src=None, base_src=None):
    """-> (spliced LilyPond source, A, B, part) for a section file spliced into base."""
    voices = parse_voices(voices)
    ssrc = read_source(section, section_src)
    ab = section_bars(ssrc)
    if ab is None:
        raise ValueError("section file needs a comment line '% bars A-B'")
    part = read_bars(ssrc, voices)
    sc = splice_bars(read_bars(read_source(base, base_src), voices), part, ab[0])
    return write_source(sc, f"splice of {section} into {base}"), ab[0], ab[1], part


def check_section(section, skeleton, plan, base=None, voices=None, ranges=None, measure=None,
                  section_src=None, skeleton_src=None):
    voices = parse_voices(voices)
    measure = parse_measure(measure)
    sk_src = read_source(skeleton, skeleton_src)
    base_src = sk_src if base is None else read_source(base)
    new_src, a, b, part = spliced_source(section, base or skeleton, voices, section_src, base_src)
    if isinstance(plan, (str, bytes)) or hasattr(plan, 'read_text'):
        with open(plan) as fh:
            plan = json.load(fh)
    plan = plan or {}
    failures, lines = [], []

    def fail(kind, line, show=True):
        failures.append(dict(kind=kind, line=line))
        if show:
            lines.append(line)

    # 1. length
    for v in voices:
        if len(part[v]) != b - a + 1:
            fail('LENGTH', f"ERR {v}: {len(part[v])} bars, expected {b - a + 1}")
    t0, t1 = F(a - 1), F(b)
    # 2. boundaries
    for v in voices:
        old, new = parse_voice(sk_src, v, measure) or [], parse_voice(new_src, v, measure) or []
        desc = lambda n: 'rest' if n is None or n.midi is None else f"{n.name}{' (tied in)' if n.start < t0 else ''}"
        o0, n0 = _sounding(old, t0), _sounding(new, t0)
        if desc(o0) != desc(n0):
            fail('BOUNDARY', f"BOUNDARY {v} first attack at {a}:1: skeleton {desc(o0)}, section {desc(n0)}")
        ol = [n for n in old if n.start < t1]
        nl = [n for n in new if n.start < t1]
        dl = lambda n: 'rest' if n.midi is None else f"{n.name}{' (tied out)' if n.end > t1 else ''}"
        if ol and nl and dl(ol[-1]) != dl(nl[-1]):
            fail('BOUNDARY', f"BOUNDARY {v} last note of bar {b}: skeleton {dl(ol[-1])}, section {dl(nl[-1])}")
    # 3. locks, countersubjects, keeps
    spans = [(r, r['role']) for r in plan.get('roles', [])] + [(k, 'keep') for k in plan.get('keep', [])]
    what_for = {'subject': 'thematic notes', 'answer': 'thematic notes', 'cf': 'thematic notes',
                'cs': 'countersubject notes (outside the landing window)'}
    for r, role in spans:
        if role not in ('subject', 'answer', 'cf', 'cs', 'keep'):
            continue
        r0, r1 = _plan_pos(r['at']), _plan_pos(r['until'])
        if role == 'cs' and r.get('landing_from'):
            r1 = min(r1, _plan_pos(r['landing_from']))
        lo, hi = max(r0, t0), min(r1, t1)
        if lo >= hi or r['voice'] not in voices:
            continue
        v = r['voice']
        pick = lambda s: [(n.start, n.dur, n.midi) for n in (parse_voice(s, v, measure) or []) if lo <= n.start < hi]
        if pick(sk_src) != pick(new_src):
            what = what_for.get(role) or f"kept notes ({r.get('what', 'see BLUEPRINT')})"
            fail('LOCK', f"LOCK {v} {role} {r['at']}-{r['until']}: {what} changed")
    # 4. unisons
    known = _unisons(sk_src, voices, t0, t1, measure)
    known_list = []
    for u in sorted(_unisons(new_src, voices, t0, t1, measure)):
        t, v1, v2, _ = u
        if u in known:
            known_list.append(f"{_pos(t)} {v1}/{v2}")
            lines.append(f"  UNI  {_pos(t)} {v1}/{v2} (skeleton, documented)")
        else:
            fail('UNISON', f"UNISON {_pos(t)} {v1}/{v2} on the same pitch (new): merges two voices")
    # 5. counterpoint with the joins
    total_bars = nbars(read_bars(new_src, voices))
    window = (max(1, a - 1), min(total_bars, b + 1))
    ck = _check.run(src=new_src, voices=voices, bars=window, measure=measure, ranges=ranges, quiet=True)
    st = _strict.run(src=new_src, voices=voices, bars=window, measure=measure)
    for item in ck['violations']:
        fail(item['kind'], item['line'], show=False)
    for item in st['items']:
        if item['kind'] == 'CLASH':
            fail('CLASH', item['line'], show=False)
    lines += ['  ' + l for l in ck['lines'] if not l.startswith('DIS ')]
    lines += ['  ' + l for l in _strict.lines(st) if not l.startswith('ACC')]
    ok = not failures
    lines.append(f"{'PASS' if ok else 'FAIL'} section bars {a}-{b} (checked {window[0]}-{window[1]})")
    return {
        'section': str(section), 'bars': [a, b], 'checked': f"{window[0]}-{window[1]}", 'pass': ok,
        'failures': failures, 'known_unisons': known_list,
        'check': {k: ck['totals'][k] for k in ('errors', 'parallels', 'beat_parallels', 'unjustified',
                                               'crossings', 'directs', 'melodic', 'd4')},
        'strict': {k: st[k] for k in ('clash', 'xrel', 'acc', 'acc2')},
        'review': [i['line'] for i in ck['review']] + [i['line'] for i in st['items'] if i['kind'] in ('XREL', 'ACC2')],
        'lines': lines,
    }
