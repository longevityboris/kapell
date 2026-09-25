#!/usr/bin/env python3
"""Adversarial tests for tools/orchestrate.py: the integrity checker must catch broken output,
and the written MIDI must follow each renderer's contract.

usage: python3 test_orchestrate.py [SCORE.ly PLAN.json]      (default: the final-lab skeleton)
Writes results to orchestration/tests/results/orchestrate_tests.json; exit 1 on any failure.
"""
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

import mido

HERE = Path(__file__).resolve().parent
R = HERE.parent.parent
sys.path.insert(0, str(R / "tools"))
import orchestrate as O  # noqa: E402

SCORE = Path(sys.argv[1]) if len(sys.argv) > 2 else R / "design/final-lab/SK_final.ly"
PLAN = Path(sys.argv[2]) if len(sys.argv) > 2 else R / "design/final-lab/plan.json"
SPEC = R / "orchestration/quintet_skeleton.json"
results = {}


def run(spec_d, name):
    d = Path(tempfile.mkdtemp(prefix=f"orch_{name}_"))
    spec_d = copy.deepcopy(spec_d)
    frm = spec_d.get("marks", {}).get("from")
    if frm and not Path(frm).is_absolute():
        spec_d["marks"]["from"] = str((SPEC.parent / frm).resolve())
    sp = d / "spec.json"
    sp.write_text(json.dumps(spec_d))
    try:
        rep = O.build(SCORE, PLAN, sp, d / "out", quiet=True)
    except SystemExit as e:
        return d, {"ok": False, "errors": [f"SystemExit: {e}"]}
    return d, rep


def mutate(outdir, group, track, fn):
    p = outdir / f"{group}.mid"
    mid = mido.MidiFile(str(p))
    for tr in mid.tracks:
        if any(m.type == "track_name" and m.name == track for m in tr):
            fn(tr)
    mid.save(str(p))


def expect(name, cond, detail):
    results[name] = {"pass": bool(cond), "detail": detail}
    print(f"{'PASS' if cond else 'FAIL'}  {name}: {detail}")


base = json.loads(SPEC.read_text())
d, rep = run(base, "base")
out = d / "out"
expect("clean output passes", rep["ok"], rep["errors"][:3])


def first_note_on(tr):
    return next(i for i, m in enumerate(tr) if m.type == "note_on" and m.velocity > 0)


# 1. a wrong pitch (semitone) must be caught as missing + extra
work = Path(tempfile.mkdtemp())
shutil.copytree(out, work / "o")


def shift_first(tr, delta):
    """move the first note (on and its off) by `delta` semitones"""
    i = first_note_on(tr)
    key = tr[i].note
    tr[i].note = key + delta
    for m in tr[i + 1:]:
        if m.type in ("note_off", "note_on") and m.note == key and (m.type == "note_off" or m.velocity == 0):
            m.note = key + delta
            break


mutate(work / "o", "quartet", "Viola", lambda tr: shift_first(tr, 1))
r1 = O.check(SCORE, PLAN, SPEC, work / "o")
expect("semitone error caught", not r1["ok"] and any("va: 1 assigned note(s) missing" in e for e in r1["errors"])
       and any("va: 1 note(s) that no assignment" in e for e in r1["errors"]), r1["errors"][:3])

# 2. an undeclared octave shift of one note
work = Path(tempfile.mkdtemp())
shutil.copytree(out, work / "o")


def octave_up(tr):
    i = first_note_on(tr)
    key = tr[i].note
    tr[i].note = key + 12
    for m in tr[i + 1:]:
        if m.type in ("note_off", "note_on") and m.note == key and (m.type == "note_off" or m.velocity == 0):
            m.note = key + 12
            break


mutate(work / "o", "piano", "bass", lambda tr: shift_first(tr, 12))
r2 = O.check(SCORE, PLAN, SPEC, work / "o")
expect("undeclared octave caught", not r2["ok"] and any("bass" in e for e in r2["errors"]), r2["errors"][:3])

# 3. a dropped note
work = Path(tempfile.mkdtemp())
shutil.copytree(out, work / "o")


def drop(tr):
    i = first_note_on(tr)
    key = tr[i].note
    dt = tr[i].time
    del tr[i]
    tr[i].time += dt
    for j in range(i, len(tr)):
        m = tr[j]
        if m.type in ("note_off", "note_on") and m.note == key and (m.type == "note_off" or m.velocity == 0):
            t = m.time
            del tr[j]
            if j < len(tr):
                tr[j].time += t
            break


mutate(work / "o", "quartet", "Cello", drop)
r3 = O.check(SCORE, PLAN, SPEC, work / "o")
expect("dropped note caught", not r3["ok"] and any("missing" in e for e in r3["errors"]), r3["errors"][:3])

# 4. an added note (a pitch no voice has there)
work = Path(tempfile.mkdtemp())
shutil.copytree(out, work / "o")


def add(tr):
    i = first_note_on(tr)
    tr.insert(i + 1, mido.Message("note_on", channel=tr[i].channel, note=99, velocity=60, time=0))
    tr.insert(i + 2, mido.Message("note_off", channel=tr[i].channel, note=99, velocity=0, time=10))
    tr[i + 3].time = max(0, tr[i + 3].time - 10)


mutate(work / "o", "quartet", "Violin I", add)
r4 = O.check(SCORE, PLAN, SPEC, work / "o")
expect("added note caught", not r4["ok"] and any("no assignment" in e for e in r4["errors"]), r4["errors"][:3])

# 5. a hanging note (note-off removed)
work = Path(tempfile.mkdtemp())
shutil.copytree(out, work / "o")


def hang(tr):
    i = first_note_on(tr)
    key = tr[i].note
    for j in range(i + 1, len(tr)):
        m = tr[j]
        if m.type == "note_off" and m.note == key:
            t = m.time
            del tr[j]
            tr[j].time += t
            break


mutate(work / "o", "piano", "alto", hang)
r5 = O.check(SCORE, PLAN, SPEC, work / "o")
expect("hanging note caught", not r5["ok"] and any("without note-off" in e for e in r5["errors"]), r5["errors"][:3])

# 6. tempo map mismatch between groups
work = Path(tempfile.mkdtemp())
shutil.copytree(out, work / "o")
mid = mido.MidiFile(str(work / "o/piano.mid"))
for m in mid.tracks[0]:
    if m.type == "set_tempo":
        m.tempo += 1000
        break
mid.save(str(work / "o/piano.mid"))
r6 = O.check(SCORE, PLAN, SPEC, work / "o")
expect("tempo mismatch caught", not r6["ok"] and any("tempo" in e for e in r6["errors"]), r6["errors"][:3])

# 7. a spec that leaves the tenor unplayed in 44-46 must fail coverage
s7 = copy.deepcopy(base)
s7["assignments"] = [a for a in s7["assignments"] if not (a["voice"] == "tenor" and a["part"] == "tenor")]
s7["assignments"].append({"voice": "tenor", "part": "tenor", "at": "pedal_climax+4", "until": "end"})
_, r7 = run(s7, "uncovered")
expect("uncovered score notes caught", not r7["ok"] and any("played by no part" in e for e in r7["errors"]),
       r7["errors"][:3])
s7["allow_uncovered"] = [{"voice": "tenor", "at": "pedal_climax+2", "until": "pedal_climax+4"}]
_, r7b = run(s7, "allowed")
expect("declared gap accepted", r7b["ok"], r7b["errors"][:3])

# 8. spec validation: overlapping windows on one part, bad octave, unknown voice, timing override
for nm, mut in [
    ("overlap", lambda s: s["assignments"].append({"voice": "alto", "part": "vn1", "at": "2:1", "until": "3:1"})),
    ("octave7", lambda s: s["assignments"].append({"voice": "alto", "part": "soprano", "at": "2:1", "until": "3:1",
                                                    "octave": 7})),
    ("voice", lambda s: s["assignments"].append({"voice": "quintus", "part": "soprano", "at": "2:1", "until": "3:1"})),
    ("tempo_override", lambda s: s["groups"]["piano"].__setitem__("plan_overrides", {"tempo": []})),
]:
    s = copy.deepcopy(base)
    mut(s)
    _, r = run(s, nm)
    expect(f"spec rejected: {nm}", not r["ok"] and "SystemExit" in r["errors"][0], r["errors"][:1])

# 9. pedal point on a pitch the voice does not hold (explicit pitch F#) must be rejected
s9 = copy.deepcopy(base)
s9["pedal_points"][0]["pitch"] = 43      # G2: the bass sounds F2 and G-flat2 in 42-45, never G2
_, r9 = run(s9, "badpedal")
expect("pedal pitch the voice never sounds rejected", not r9["ok"], r9["errors"][:1])

# 10. pedal checker: a pedal note stretched over bars where the bass moves away must fail
work = Path(tempfile.mkdtemp())
shutil.copytree(out, work / "o")


def stretch(tr):
    for m in tr:
        if m.type == "note_off":
            m.time += 4 * 4 * 960       # four more bars: over 46-49, where the bass leaves F
            break


mutate(work / "o", "piano", "pedal_8vb", stretch)
r10 = O.check(SCORE, PLAN, SPEC, work / "o")
expect("pedal note held past the pedal caught", not r10["ok"] and any("pedal" in e for e in r10["errors"]),
       r10["errors"][:2])

# 11. marks: an unknown mark and a section list that disagrees with the score are refused
s11 = copy.deepcopy(base)
s11["assignments"].append({"voice": "alto", "part": "soprano_8va", "at": "nowhere+2", "until": "end"})
_, r11 = run(s11, "badmark")
expect("unknown mark rejected", not r11["ok"] and "marks:" in r11["errors"][0], r11["errors"][:1])
bad_secs = Path(tempfile.mkdtemp()) / "secs.json"
bad_secs.write_text(json.dumps([{"id": "sec01_all", "bars": 10}]))
s12 = copy.deepcopy(base)
s12["marks"] = {"from": str(bad_secs)}
_, r12 = run(s12, "badsecs")
expect("section list that disagrees with the score rejected", not r12["ok"] and "disagree" in r12["errors"][0],
       r12["errors"][:1])
res = json.loads((out / "orchestration.json").read_text())
expect("marks resolved from piece.py", res["marks"]["inversa"]["at"] == "35:1" and "pedal_climax" in res["marks"],
       {k: v["at"] for k, v in res["marks"].items() if not k.startswith("sec")})

# ---- contract checks on the clean output
pm = mido.MidiFile(str(out / "piano.mid"))
qm = mido.MidiFile(str(out / "quartet.mid"))
texts = lambda m: [x.text for x in m.tracks[0] if x.type == "text"]  # noqa: E731
expect("piano marker", "perform.py target=piano" in texts(pm), texts(pm))
expect("quartet marker", "perform.py target=strings" in texts(qm), texts(qm))
names = [next(x.name for x in t if x.type == "track_name") for t in qm.tracks[1:]]
expect("quartet track names", names == ["Violin I", "Violin II", "Viola", "Cello"], names)
# pedal only where the piano plays (35-62), never in the arioso (30-34, where the plan pedals)
tm = O.TempoMap(O.tempo_list(pm))
ped = [(t, m.value) for tr in pm.tracks for t, m in O.abs_events(tr) if m.type == "control_change" and m.control == 64]
bars = sorted({t // (4 * 960) + 1 for t, v in ped if v >= 64})
expect("piano pedal only where it plays", ped and min(bars) >= 46, f"pedal-down bars {bars[:3]}..{bars[-3:]}")
# CC20 on every vn2 note once an articulation hint is given; 'detache' (32) inside 30-35
vn2 = qm.tracks[2]
ev = list(O.abs_events(vn2))
ons = [t for t, m in ev if m.type == "note_on" and m.velocity > 0]
cc20 = {t: m.value for t, m in ev if m.type == "control_change" and m.control == 20}
expect("CC20 before every vn2 note", all(t in cc20 for t in ons), f"{sum(t in cc20 for t in ons)}/{len(ons)}")
det = [cc20[t] for t in ons if 29 * 3840 <= t < 34 * 3840]
expect("detache window = 32", det and set(det) == {32}, sorted(set(det)))
# the viola's CC1 follows the alto 9:4-13 and the tenor after 13 (the envelopes differ by role_level)
perf = O.read_perform(sorted((out / "perform").glob("perform_strings_*.mid"))[0], O.perform.Plan(json.loads(PLAN.read_text())),
                      {v: O.parse_voice(SCORE.read_text(), v) for v in ["soprano", "alto", "tenor", "bass"]})
va = qm.tracks[3]
cc1 = {}
for t, m in O.abs_events(va):
    if m.type == "control_change" and m.control == 1:
        cc1[t] = m.value


def val_at(d, t):
    ks = [k for k in d if k <= t]
    return d[max(ks)] if ks else None


alto = dict(perf["voices"]["alto"]["cc"][1])
ten = dict(perf["voices"]["tenor"]["cc"][1])
probe = [t for t in sorted(alto) if 8 * 3840 + 3 * 960 <= t < 12 * 3840][::4]     # 9:4 - 13:1
ok_a = all(val_at(cc1, t) == alto[t] for t in probe)
probe_t = [t for t in sorted(ten) if 12 * 3840 <= t < 34 * 3840][::8]              # 13:1 - 35:1
ok_t = all(val_at(cc1, t) == ten[t] for t in probe_t)
expect("viola CC1 = alto envelope in 9:4-13, tenor envelope in 14-29", ok_a and ok_t, f"alto {ok_a}, tenor {ok_t}")
# the piano's 8va doubling is one dynamic step softer (level -1) than the notes it doubles
vel = {}
for tr in pm.tracks[1:]:
    nm = next(x.name for x in tr if x.type == "track_name")
    vel[nm] = {t: m.velocity for t, m in O.abs_events(tr) if m.type == "note_on" and m.velocity > 0}
pv = dict(((t), v) for t, v in [(n.on, n.vel) for n in O.read_perform(sorted((out / "perform").glob("perform_piano_*.mid"))[0],
          O.perform.Plan(json.loads(PLAN.read_text())),
          {v: O.parse_voice(SCORE.read_text(), v) for v in ["soprano", "alto", "tenor", "bass"]})["voices"]["soprano"]["notes"]])
diffs = [vel["soprano_8va"][t] - pv[t] for t in vel["soprano_8va"]]
expect("level -1 lowers piano velocity by one dynamic step (8-16 perform units)",
       all(-17 <= x <= -7 for x in diffs), f"velocity change {min(diffs)}..{max(diffs)}")
# doubled notes start on the same tick in both groups
qon = {m.note: [] for m in []}
q_s = [t for t, m in O.abs_events(qm.tracks[1]) if m.type == "note_on" and m.velocity > 0]
p_s = [t for t, m in O.abs_events(pm.tracks[5]) if m.type == "note_on" and m.velocity > 0]   # soprano_8va
common = sorted(set(q_s) & set(p_s))
expect("vn1 and piano soprano 8va share onset ticks where they double (51-58)",
       len([t for t in p_s if 50 * 3840 <= t < 58 * 3840 and t in q_s]) == len([t for t in p_s if 50 * 3840 <= t < 58 * 3840]),
       f"{len(common)} shared onsets")

# a full symphony orchestra: more than 15 tracks in one group (MIDI has 16 channels; the orchestra
# contract gives channels no meaning, so they are reused; the committed code once raised StopIteration)
sym_path = R / "audio/orchestra/specs/skeleton_symphonic.json"
sym = json.loads(sym_path.read_text())
sym["marks"]["from"] = str((sym_path.parent / sym["marks"]["from"]).resolve())
sym17 = copy.deepcopy(sym)
sym17["groups"]["orchestra"]["parts"]["vc.2"] = {}
sym17["assignments"] += [dict(x, part="vc.2") for x in sym["assignments"] if x["part"] == "vc"]
d17, rep17 = run(sym17, "sym17")
m17 = mido.MidiFile(str(d17 / "out" / "orchestra.mid")) if (d17 / "out" / "orchestra.mid").exists() else None
n17 = len([tr for tr in m17.tracks if any(x.type == "note_on" for x in tr)]) if m17 else 0
expect("an orchestra group with 17 parts builds, 17 note tracks, integrity OK",
       rep17["ok"] and n17 == 17, f"ok {rep17['ok']}, {n17} note tracks, errors {rep17['errors'][:2]}")
# notes outside an orchestra part's compass: the renderer would move them an octave, so they are
# errors unless the spec accepts the move for that part (allow_octave_shift)
low = copy.deepcopy(sym)
low["assignments"] = [x for x in low["assignments"] if not (x["voice"] == "alto" and x["part"] in ("vn2", "va"))]
low["assignments"].append({"voice": "alto", "part": "vn2"})        # the alto reaches F3, vn2 stops at G3
_, rep_low = run(low, "compass")
expect("alto on vn2 throughout: notes below the vn2 compass fail the integrity check",
       not rep_low["ok"] and any(e.startswith("vn2:") and "compass" in e for e in rep_low["errors"]),
       [e[:90] for e in rep_low["errors"]][:2])
low["allow_octave_shift"] = ["vn2"]
_, rep_allow = run(low, "compass_allowed")
expect("allow_octave_shift turns them into warnings",
       rep_allow["ok"] and any(w.startswith("vn2:") and "compass" in w for w in rep_allow["warnings"]),
       rep_allow["errors"][:2] or [w[:90] for w in rep_allow["warnings"] if "compass" in w])

out_json = HERE / "results" / "orchestrate_tests.json"
out_json.parent.mkdir(exist_ok=True)
out_json.write_text(json.dumps(results, indent=1))
fails = [k for k, v in results.items() if not v["pass"]]
print(f"{len(results) - len(fails)}/{len(results)} passed" + (f"; failed: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
