#!/usr/bin/env python3
"""Write ricercar_quintet.json, the piano-quintet scoring of "The Neighbour" (score/music-voices.ly).

usage: python3 performance/quintet/make_spec.py        (writes performance/quintet/ricercar_quintet.json)

The scoring is a table below (ASSIGN, PEDAL_POINTS); the one computed part is the piano's damper pedal.
The plan asks for "pedal each harmony" (30-35 and 55-66), which perform.py does not implement (it falls
back to every half bar, and a half-bar pedal holds the subject's neighbour eighths, B-flat with A, and
the lament's steps in the bass). Here the pedal is placed from the notes the piano actually plays: a
span starts on a piano attack and grows by eighths, up to a bar, while the pedal would not make two
notes a second apart ring together that the score does not sound together anyway (a pedal-created
second or seventh: pitch-class distance 1 or 2). Each span becomes one perform.py pedal press
{"at", "until", "every": "bar"} (down 30 ms after "at", up 5 ms before "until").

Model: Shostakovich, Piano Quintet Op. 57, ii (Fugue). Strings alone through the exposition, the
false dawn, Climax I and the arioso; the piano enters with the fuga inversa (35) and carries it,
the viola bringing the tenor's stretto entry (37); the cello returns with the augmented inversion
(46), violin II with S2 (48), violin I with the diminution heads (50:3); Climax II and the major
apotheosis are tutti with the piano's octave doublings; the coda thins to violin I's d'' over the
piano's tolling tonic pedal in octaves.
"""
import json
import sys
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parent.parent
sys.path.insert(0, str(R / "tools"))
from lyparse import parse_voice  # noqa: E402

SCORE = R / "score" / "music-voices.ly"
OUT = HERE / "ricercar_quintet.json"
VOICES = ["soprano", "alto", "tenor", "bass"]

# (voice, part, at, until, extra options)
ASSIGN = [
    # ---- quartet ---------------------------------------------------------------------------
    # violin I: the tune alone (1-5:3), then CS1 over the answer. sec01 header, request (1): the
    # answer (alto, 5:1) must hold the ear; CS1 enters as a new, softer line, with a new bow at
    # 5:4 (it would otherwise slur out of the subject's last note F4), catching up with the global
    # p < mp by 10:1 (levels from the header: -1.09, -0.77, -0.26 steps at 5:4, 7:1, 9:1).
    ("soprano", "vn1", "1:1", "5:4", {}),
    ("soprano", "vn1", "5:4", "6:1", {"level": -1.0, "articulation": "detache"}),
    ("soprano", "vn1", "6:1", "7:1", {"level": -1.0}),
    ("soprano", "vn1", "7:1", "9:1", {"level": -0.6}),
    ("soprano", "vn1", "9:1", "10:1", {"level": -0.25}),
    ("soprano", "vn1", "10:1", "35:1", {}),
    # the soprano rests 46-50:2; violin I returns with the first diminution head (50:3)
    ("soprano", "vn1", "46:1", "59:1", {}),
    # the tune's second half and its peak (f'' at 60:4) over the bass's answer, which the plan brings
    # out as much as the tune (answer and subject both +0.7): violin I sings out from 59:1, through
    # c'' rising to d'' (63:1), the note that makes the tune major
    ("soprano", "vn1", "59:1", "65:1", {"level": 0.5}),
    ("soprano", "vn1", "65:1", "end", {}),
    # violin II: the answer and CS1; the viola takes the alto 9:4-12:4 (F3, F#3 below the violin's G3)
    ("alto", "vn2", "1:1", "9:4", {}),
    ("alto", "va", "9:4", "13:1", {}),
    ("alto", "vn2", "13:1", "30:1", {}),
    # arioso dolente: the pulsing eighths lightly separated (blueprint section 8)
    ("alto", "vn2", "30:1", "35:1", {"articulation": "detache"}),
    # rests through the fuga inversa (the piano has the alto); returns with S2 at 48:1
    ("alto", "vn2", "46:1", "end", {}),
    # viola: the tenor from its first entry (13:1)
    ("tenor", "va", "13:1", "30:1", {}),
    ("tenor", "va", "30:1", "30:4.5", {"articulation": "detache"}),
    # sec04 header: the tenor's lament 30:4.5-32:1 is the arioso's moving inner line (+0.4 over the pulse)
    ("tenor", "va", "30:4.5", "32:1", {"articulation": "detache", "level": 0.4}),
    ("tenor", "va", "32:1", "35:1", {"articulation": "detache"}),
    # the tenor's inverted stretto entry (37:1) is the first string sound after the piano's entry
    ("tenor", "va", "37:1", "43:1", {}),
    # sec05 header: the free tenor crosses above the alto's CS2 inv. 43:1-44:4.5; keep it under
    ("tenor", "va", "43:1", "45:1", {"level": -0.3}),
    # ... through the cadence and the lament lead-in over the pedal (46-47), then rests while the
    # piano has S1 (48:1), and rejoins it for the climb to Climax II (50:1)
    ("tenor", "va", "45:1", "48:1", {}),
    ("tenor", "va", "50:1", "end", {}),
    # cello: the bass from its entry (9:1). The exposition's p < mp hairpin rises 5.2 dB at this entry
    # in the master (the dry quartet +1.7 dB: the hall answers the cello's register), which is the
    # texture growing by its third voice; a -0.3 trim on 9:1-11:1 took only 0.5 dB off it and put
    # the subject's head B-flat under violin II's answer tail (-40.5 vs -39.1 LUFS in 9:1-9:4), so the
    # entry keeps the plan's level
    ("bass", "vc", "1:1", "30:2", {}),
    # sec04 header: the bass's S2 head 30:2-31:1 (+0.4, like the tenor's lament)
    ("bass", "vc", "30:2", "31:1", {"level": 0.4}),
    ("bass", "vc", "31:1", "35:1", {}),
    # rests through the fuga inversa; returns with the augmented inversion, the dominant pedal (46:1)
    ("bass", "vc", "46:1", "end", {}),
    # ---- piano -----------------------------------------------------------------------------
    # the fuga inversa: the piano enters alone with the inversion in the bass (35:1)
    ("soprano", "soprano", "35:1", "46:1", {}),
    ("alto", "alto", "35:1", "46:1", {}),
    ("bass", "bass", "35:1", "46:1", {}),
    # S1 in the tenor (48:1) is the piano's, S2 (alto) violin II's: the tune's two halves in two colours
    ("tenor", "tenor", "48:1", "55:1", {}),
    # Climax II: tutti from 50:1, the soprano's diminution heads doubled by the piano
    ("soprano", "soprano", "50:1", "52:1", {}),
    # ... and an octave higher from C major ("the light", 52:1) through the tune in major
    ("soprano", "soprano_8va", "52:1", "63:1", {"octave": 12, "level": -1.0}),
    # the coda: the d'' (63:1), the last V7 and the final chord at pitch
    ("soprano", "soprano", "63:1", "end", {}),
    ("alto", "alto", "50:1", "55:1", {}),
    # the apotheosis: violin I sings the tune, the others sotto voce (blueprint section 6). At the
    # plan's level the piano's CS2 (tenor) matched violin I (-36.3 / -36.8 LUFS in 55-58) and the
    # piano sat 4-5 dB over the tune; its inner voices go one step down (softer hammers), while
    # violin II and the viola keep them at full level
    ("alto", "alto", "55:1", "63:1", {"level": -1.0}),
    ("tenor", "tenor", "55:1", "63:1", {"level": -1.0}),
    ("alto", "alto", "63:1", "end", {}),
    ("tenor", "tenor", "63:1", "end", {}),
    ("bass", "bass", "50:1", "59:1", {}),
    # the bass's answer in major (59-62) under the tune's peak (f'' at 60:4): violin I leads. With
    # the piano's bass and its octave at the plan's level (answer role), cello + piano bass sat
    # 2-4.6 dB over the soprano (violin I + piano 8va) in 59-62 on the dry stems; the piano's two
    # bass lines go one step down, the cello keeps the answer
    ("bass", "bass", "59:1", "63:1", {"level": -1.0}),
    ("bass", "bass", "63:1", "end", {}),
    # bass octaves: Climax II and the hinge; the answer in major under the tune's peak (59-62);
    # the tonic pedal re-struck every bar (63-66), tolling
    ("bass", "bass_8vb", "50:1", "55:1", {"octave": -12, "level": -0.5}),
    # (at -1.0 the octave below was still the loudest bass line in bar 61: two steps down, a shadow)
    ("bass", "bass_8vb", "59:1", "63:1", {"octave": -12, "level": -2.0}),
    ("bass", "bass_8vb", "63:1", "end", {"octave": -12, "level": -1.0}),
]

# the dominant pedal: the piano holds the bass's F an octave down under the cello's augmented
# inversion and its G-flat neighbours (the blueprint's "sostenuto on F2 in 46-50"). One F1 struck
# at 46:1 decayed to 20-28 dB under the cello by bar 48, so the pedal is re-struck, a notch softer,
# at 48:1 with the piano's S1 entry (the key is let go under the cello's G-flat at 47:4)
PEDAL_POINTS = [
    {"voice": "bass", "part": "pedal_8vb", "at": "46:1", "until": "48:1", "octave": -12,
     "mode": "sustain", "bridge": 1, "min_beats": 4, "level": -0.5},
    {"voice": "bass", "part": "pedal_8vb", "at": "48:1", "until": "50:1", "octave": -12,
     "mode": "sustain", "bridge": 1, "min_beats": 4, "level": -1.0},
]

# where the piano uses the damper: Climax II and the hinge (sec06 finding 8), the apotheosis and
# coda (plan.json: 55:1-66:4, each harmony). The fuga inversa stays dry, as in plan.json.
PEDAL_REGIONS = [("50:1", "55:1"), ("55:1", "66:4")]

QUARTET = ["vn1", "vn2", "va", "vc"]
PIANO = ["soprano", "alto", "tenor", "bass", "soprano_8va", "bass_8vb", "pedal_8vb"]


def pos(s: str) -> F:
    bar, beat = s.split(":")
    return (int(bar) - 1) + (F(beat) - 1) / 4


def fmt(x: F) -> str:
    bar = int(x) + 1
    beat = (x - (bar - 1)) * 4 + 1
    return f"{bar}:{float(beat):g}"


def piano_notes(score: dict, end: F) -> list:
    """(start, end, midi) of every note the piano plays under ASSIGN (pedal point excluded: it lies
    outside the pedal regions)."""
    out = []
    for v, part, a, u, opt in ASSIGN:
        if part not in PIANO:
            continue
        lo, hi = pos(a), end if u == "end" else pos(u)
        for n in score[v]:
            if lo <= n.start < hi:
                out.append((n.start, n.end, n.midi + opt.get("octave", 0)))
    return sorted(out)


def pcs_at(score: dict, t: F) -> set:
    """pitch classes the score (all four voices) sounds at t."""
    return {n.midi % 12 for v in VOICES for n in score[v] if n.start <= t < n.end}


def clashes(pn: list, score: dict, s: F, e: F) -> bool:
    """True if a pedal held over [s, e) keeps a released piano note ringing into a later piano attack
    a second (or seventh, ninth) away, while the score no longer sounds that note's pitch class at the
    attack (a passing note, a neighbour, a suspension held into its resolution, a change of harmony)."""
    caught = [n for n in pn if n[1] > s and n[0] < e]
    for n1 in caught:
        if n1[1] >= e:
            continue  # its key is still down at the lift: the pedal does not extend it
        for n2 in caught:
            if n2 is n1 or not (n1[1] <= n2[0] < e):
                continue
            if (n1[2] - n2[2]) % 12 in (1, 2, 10, 11) and n1[2] % 12 not in pcs_at(score, n2[0]):
                return True
    return False


def pedal_spans(pn: list, score: dict) -> list:
    spans = []
    onsets = sorted({n[0] for n in pn})
    step = F(1, 8)
    for ra, rb in PEDAL_REGIONS:
        a, b = pos(ra), pos(rb)
        s = a
        while s < b:
            nxt = [o for o in onsets if s <= o < b]
            if not nxt:
                break
            s = nxt[0]
            best, e = None, s + F(1, 4)
            while e <= min(b, s + 1) and not clashes(pn, score, s, e):
                best = e
                e += step
            if best is None:
                s += step
                continue
            spans.append({"at": fmt(s), "until": fmt(best), "every": "bar"})
            s = best
    return spans


def main():
    src = SCORE.read_text()
    score = {v: [n for n in parse_voice(src, v) if n.midi is not None] for v in VOICES}
    end = max(n.end for v in VOICES for n in score[v])
    pn = piano_notes(score, end)
    spans = pedal_spans(pn, score)
    assignments = []
    for v, part, a, u, opt in ASSIGN:
        x = {"voice": v, "part": part, "at": a, "until": u}
        x.update(opt)
        assignments.append(x)
    spec = {
        "title": "The Neighbour - ricercar a 4 on the Theme from Jurassic Park - piano quintet",
        "comment": (__doc__.split("Model:", 1)[1].strip().replace("\n", " ")
                    + " Written by performance/quintet/make_spec.py; the piano's pedal spans are computed there."),
        "marks": {"from": "../../design/final-lab/piece.py"},
        "groups": {
            "quartet": {"renderer": "quartet", "parts": QUARTET},
            "piano": {"renderer": "piano", "parts": PIANO, "options": {"pedal": spans}},
        },
        "assignments": assignments,
        "pedal_points": PEDAL_POINTS,
        "mix": {
            "lead_in": 0.5,
            "reference_group": "quartet",
            "groups": {
                "quartet": {"gain_db": 0.0, "hall_re_dry_db": 4.0,
                            "stage": {"vn1": {"az": 30, "depth": 0.0}, "vn2": {"az": 10, "depth": 0.4},
                                      "va": {"az": -10, "depth": 0.4}, "vc": {"az": -28, "depth": 0.0}}},
                "piano": {"gain_db": -1.0, "hall_re_dry_db": 4.0,
                          "stage": {"*": {"az": 0, "depth": 1.2, "width": 0.7}},
                          "render_args": ["--jobs", "2"]},
            },
        },
    }
    OUT.write_text(json.dumps(spec, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(R)}: {len(assignments)} windows, {len(spans)} pedal spans")
    for sp in spans:
        print(f"  pedal {sp['at']:>7} - {sp['until']}")


if __name__ == "__main__":
    main()
