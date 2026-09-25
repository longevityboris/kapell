#!/usr/bin/env python3
"""Verify one composed section against the final skeleton, so sections can be composed in parallel.

usage: python3 splice_check.py SECTION.ly [--base OTHER_FULL_SCORE.ly]

SECTION.ly holds the four voices (soprano, alto, tenor, bass as \\absolute) for exactly its bars and
a comment line '% bars A-B'. The script
  1. checks each voice is exactly B-A+1 bars long;
  2. BOUNDARY: every voice keeps the skeleton's first attack at A:1 (pitch, rest, tie-in) and its
     last note (pitch, tie-out), so the joins proven in SK_final.ly stay valid;
  3. LOCK: notes inside the thematic spans of plan.json (roles subject, answer, cf) are unchanged
     (start, duration, pitch);
     CS: notes inside countersubject spans (role cs) are unchanged too, except from the role's
     'landing_from' position on (the landing note, which may change); any other change FAILS;
     KEEP: the items listed under plan.json "keep" (pivot notes, lead-ins, wedge pitches, cadence
     notes the blueprint says to keep) are checked like LOCK;
  4. UNISON: two voices on the same MIDI pitch at the same moment (one of them attacking) FAIL
     unless the skeleton has the same unison at the same place (those are listed as known);
  5. splices the section into the base (default SK_final.ly) and runs tools/check.py and strict.py
     on bars A-1..B+1 (the joins included).
Exit status 0 only if 1-5 pass with 0 PAR!, 0 BEAT, 0 DIS! and no CLASH.
"""
import json
import os
import re
import sys
import tempfile
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools'))
import fl  # noqa: E402
from lyparse import parse_voice  # noqa: E402


def notes_of(src, v):
    return [n for n in parse_voice(src, v)]


def sounding(ns, t):
    for n in ns:
        if n.start <= t < n.end:
            return n
    return None


def plan_pos(s):
    bar, beat = s.split(':')
    return F(int(bar) - 1) + (F(beat) - 1) / 4


def pos(t):
    b = int(t) + 1
    return f"{b}:{float((t - (b - 1)) * 4 + 1):g}"


def unisons(src, t0, t1):
    """set of (time, voice1, voice2, midi) where two voices share a MIDI pitch and one attacks."""
    data = {v: [n for n in notes_of(src, v) if n.midi is not None] for v in fl.VOICES}
    out = set()
    times = sorted({n.start for v in fl.VOICES for n in data[v] if t0 <= n.start < t1})
    for t in times:
        snd = {v: sounding(data[v], t) for v in fl.VOICES}
        vs = [v for v in fl.VOICES if snd[v] is not None]
        for i in range(len(vs)):
            for j in range(i + 1, len(vs)):
                a, b = snd[vs[i]], snd[vs[j]]
                if a.midi == b.midi and (a.start == t or b.start == t):
                    out.add((t, vs[i], vs[j], a.midi))
    return out


def main():
    args = sys.argv[1:]
    sec_path = args[0]
    base_path = args[args.index('--base') + 1] if '--base' in args else os.path.join(HERE, 'SK_final.ly')
    src = open(sec_path).read()
    m = re.search(r'%\s*bars\s+(\d+)\s*-\s*(\d+)', src)
    if not m:
        sys.exit("section file needs a comment line '% bars A-B'")
    a, b = int(m.group(1)), int(m.group(2))
    ok = True
    part = fl.read(sec_path)
    for v in fl.VOICES:
        if len(part[v]) != b - a + 1:
            print(f"ERR {v}: {len(part[v])} bars, expected {b - a + 1}")
            ok = False
    base = fl.read(base_path)
    spliced = fl.splice(base, part, a)
    tmp = os.path.join(tempfile.gettempdir(), f'splice_check_tmp_{os.getpid()}.ly')
    fl.write(tmp, spliced, f'splice of {os.path.basename(sec_path)} into {os.path.basename(base_path)}')
    sk_src = open(os.path.join(HERE, 'SK_final.ly')).read()
    new_src = open(tmp).read()
    t0, t1 = F(a - 1), F(b)
    # 2. boundaries
    for v in fl.VOICES:
        old, new = notes_of(sk_src, v), notes_of(new_src, v)
        o0, n0 = sounding(old, t0), sounding(new, t0)
        desc = lambda n: 'rest' if n is None or n.midi is None else f"{n.name}{' (tied in)' if n.start < t0 else ''}"
        if desc(o0) != desc(n0):
            print(f"BOUNDARY {v} first attack at {a}:1: skeleton {desc(o0)}, section {desc(n0)}")
            ok = False
        ol = [n for n in old if n.start < t1][-1]
        nl = [n for n in new if n.start < t1][-1]
        dl = lambda n: 'rest' if n.midi is None else f"{n.name}{' (tied out)' if n.end > t1 else ''}"
        if dl(ol) != dl(nl):
            print(f"BOUNDARY {v} last note of bar {b}: skeleton {dl(ol)}, section {dl(nl)}")
            ok = False
    # 3. locks, countersubjects, keeps
    plan = json.load(open(os.path.join(HERE, 'plan.json')))
    spans = [(r, r['role']) for r in plan.get('roles', [])] + [(k, 'keep') for k in plan.get('keep', [])]
    for r, role in spans:
        r0, r1 = plan_pos(r['at']), plan_pos(r['until'])
        if role == 'cs' and r.get('landing_from'):
            r1 = min(r1, plan_pos(r['landing_from']))
        if role not in ('subject', 'answer', 'cf', 'cs', 'keep'):
            continue
        lo, hi = max(r0, t0), min(r1, t1)
        if lo >= hi:
            continue
        v = r['voice']
        pick = lambda s: [(n.start, n.dur, n.midi) for n in notes_of(s, v) if lo <= n.start < hi]
        if pick(sk_src) != pick(new_src):
            what = {'subject': 'thematic notes', 'answer': 'thematic notes', 'cf': 'thematic notes',
                    'cs': 'countersubject notes (outside the landing window)',
                    'keep': f"kept notes ({r.get('what', 'see BLUEPRINT')})"}[role]
            print(f"LOCK {v} {role} {r['at']}-{r['until']}: {what} changed")
            ok = False
    # 4. unisons
    known = unisons(sk_src, t0, t1)
    for u in sorted(unisons(new_src, t0, t1)):
        t, v1, v2, midi = u
        if u in known:
            print(f"  UNI  {pos(t)} {v1}/{v2} (skeleton, documented)")
        else:
            print(f"UNISON {pos(t)} {v1}/{v2} on the same pitch (new): merges two voices")
            ok = False
    # 5. counterpoint checks with the joins
    bars = f"{max(1, a - 1)}-{min(fl.nbars(spliced), b + 1)}"
    lines, slines = fl.check(tmp, bars=bars)
    for l in lines:
        if not l.startswith('DIS '):
            print('  ' + l)
    for l in slines:
        if not l.startswith('ACC'):
            print('  ' + l)
    summ = lines[-1] if lines else ''
    if not re.search(r'errors 0, parallels 0, beat-par 0, unjustified 0', summ):
        ok = False
    if slines and not slines[-1].startswith('strict: clash 0'):
        ok = False
    try:
        os.remove(tmp)
    except OSError:
        pass
    print('PASS' if ok else 'FAIL', f"section bars {a}-{b} (checked {bars})")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
