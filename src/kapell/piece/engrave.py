"""Prepare printable reductions from absolute SATB voices and performance specs.

Routing uses the performance engine's attack rule: a tied note belongs to the
assignment containing its first attack, including its entire held duration.
The deliberately small notation reader rejects unsupported music instead of
silently losing it; in that case the templates print labelled unfiltered voices.
"""
import json
import re
from collections import defaultdict
from fractions import Fraction as F
from pathlib import Path

from kapell.analysis.lyparse import parse_voice

VOICES = ("soprano", "alto", "tenor", "bass")
FORCES = {"organ": "organ", "ensemble": "piano and string quartet",
          "orchestra": "orchestra"}
SPECS = {"organ": "bach_organ/bach_organ.json",
         "ensemble": "quintet/ricercar_quintet.json",
         "orchestra": "symphonic/symphonic.json"}
FAMILIES = {"Winds": {"fl", "ob", "cl", "bn"},
            "Brass": {"hn", "tpt", "tbn", "btbn", "tba"},
            "Strings": {"vn1", "vn2", "va", "vc", "cb"}}


def ly_string(value):
    """Escape the contents of a LilyPond quoted string (never music)."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


def position(value, measure, end):
    if value == "end":
        return end
    bar, beat = str(value).split(":")
    b, q = int(bar), F(beat)
    if b < 1 or not 1 <= q < measure * 4 + 1:
        raise ValueError(f"invalid position: {value}")
    return (b - 1) * measure + (q - 1) / 4


def read_voices(source, measure):
    """Guard the analysis parser: only plain notes, rests, ties and bar checks."""
    clean = re.sub(r"%[^\n]*", "", source)
    token = r"(?:[a-g](?:isis|eses|is|es)?[',]*\d*\.*|[rRs]\d*\.*(?:\*\d+)?|[\s|~])+"
    voices = {}
    for voice in VOICES:
        match = re.search(r"(?m)^" + voice + r"\s*=\s*\\absolute\s*\{([^{}]*)\}", clean)
        if not match or not re.fullmatch(token, match[1]):
            raise ValueError(f"{voice}: routing requires plain absolute notes/rests/ties")
        # parse_voice expects the closing brace on its own line.
        notes = parse_voice(f"{voice} = \\absolute {{\n{match[1]}\n}}", voice, measure)
        if not notes:
            raise ValueError(f"{voice}: empty voice")
        voices[voice] = notes
    if len({notes[-1].end for notes in voices.values()}) != 1:
        raise ValueError("voice durations differ")
    return voices


def pitch_name(note, octave=0):
    if octave % 12:
        raise ValueError("only whole-octave shifts are supported")
    match = re.fullmatch(r"([A-G])([#b]*)(-?\d+)", note.name)
    letter, accidental, octv = match.groups()
    shift = int(octv) + octave // 12 - 3
    return letter.lower() + accidental.replace("#", "is").replace("b", "es") + ("'" * shift if shift >= 0 else "," * -shift)


def route_notes(voices, assignments, parts, measure, end, *, octaves=True):
    """Return (start, end, LilyPond pitch) intervals, deduplicating doublings."""
    result = set()
    for route in assignments:
        if route["part"] not in parts:
            continue
        voice = route["voice"]
        if voice not in voices:
            raise ValueError(f"unknown voice: {voice}")
        start = position(route.get("at", "1:1"), measure, end)
        stop = position(route.get("until", "end"), measure, end)
        if not 0 <= start < stop <= end:
            raise ValueError(f"assignment outside score: {route}")
        for note in voices[voice]:
            if note.midi is not None and start <= note.start < stop:
                result.add((note.start, note.end, pitch_name(note, route.get("octave", 0) if octaves else 0)))
    return sorted(result)


def music_line(events, end, measure):
    """Notate intervals as notes/chords, splitting at bars and tying held pitches."""
    durations = sorted(((F(1, n) * (2 - F(1, 2**dots)), str(n) + "." * dots)
                        for n in (1, 2, 4, 8, 16, 32, 64, 128) for dots in range(3)), reverse=True)
    points = {F(0), end, *(x for a, b, _ in events for x in (a, b))}
    bar = measure
    while bar < end:
        points.add(bar)
        bar += measure
    points = sorted(points)
    tokens = []
    for start, stop in zip(points, points[1:]):
        active = [(a, b, p) for a, b, p in events if a <= start < b]
        t = start
        while t < stop:
            remaining = stop - t
            if not active and t % measure == 0 and remaining == measure:
                tokens.append(f"R1*{measure.numerator}/{measure.denominator}")
                t = stop
                continue
            pair = next(((d, s) for d, s in durations if d <= remaining), None)
            if pair is None:
                raise ValueError("routing needs durations shorter than 1/128")
            duration, suffix = pair
            pitches = sorted({p for _, _, p in active})
            held = {p for _, b, p in active if b > t + duration}
            if not pitches:
                tokens.append("r" + suffix)
            elif len(pitches) == 1:
                tokens.append(pitches[0] + suffix + ("~" if pitches[0] in held else ""))
            else:
                tokens.append("<" + " ".join(p + ("~" if p in held else "") for p in pitches) + ">" + suffix)
            t += duration
        if stop % measure == 0:
            tokens.append("|\n")
    return "\\absolute { " + " ".join(tokens) + " }"


def registration_music(spec, measure):
    """Group original division cues by bar; preserve exact beat labels in text."""
    reg = spec["groups"]["organ"]["options"]["registration"]
    bars = defaultdict(list)
    for change in reg.get("changes", []):
        pos = position(change["at"], measure, F(10**6))
        labels = [f"{div}: {change[div]}" for div in ("HW", "OW", "POS", "PED") if div in change]
        if labels:
            # One short line per division avoids forcing very wide systems.
            for label in labels:
                bars[int(pos // measure)].append(f"{change['at']}  {label}")
    for change in reg.get("manual_changes", []):
        pos = position(change["at"], measure, F(10**6))
        bars[int(pos // measure)].append(f"{change['at']}  {change['voice']} -> {change['division']}")
    tokens, cursor = [], F(0)
    for bar, labels in sorted(bars.items()):
        start = bar * measure
        if start > cursor:
            gap = start - cursor
            tokens.append(f"s1*{gap.numerator}/{gap.denominator}")
        lines = " ".join(f'"{ly_string(label)}"' for label in labels)
        tokens.append(f"s1*{measure.numerator}/{measure.denominator} ^\\markup \\fontsize #-3 \\column {{ {lines} }}")
        cursor = start + measure
    return "{ " + " ".join(tokens) + " }"


def prepare_layout(root: Path, cfg: dict, name: str, template: str):
    """Return filled template plus explicit reduction/fallback notes for the CLI."""
    piece, paths = cfg.get("piece", {}), cfg.get("paths", {})
    measure = F(piece.get("measure", "4/4"))
    if measure <= 0:
        raise ValueError("measure must be positive")
    notes, definitions = [], []
    subtitle = re.sub(r",?\s+for\s+[^,]+$", "", piece.get("subtitle", "")).strip()
    values = {"TITLE": piece.get("name", root.name),
              "SUBTITLE": f"{subtitle}, for {FORCES[name]}" if subtitle else f"For {FORCES[name]}"}
    spec_path = root / paths.get("performance", "performance") / SPECS[name]
    try:
        spec = json.loads(spec_path.read_text())
        if not isinstance(spec, dict):
            raise ValueError("expected a JSON object")
    except (OSError, ValueError) as exc:
        spec = None
        notes.append(f"Performance spec unavailable ({spec_path.name}): {exc}")

    if name == "organ":
        notes.append("Two-manual reduction: soprano + alto on I, tenor on II, bass on pedal. Original HW/OW/POS/PED registration cues are references, not a two-manual stop prescription.")
        values["NOTICE"] = "Two-manual reduction; registration cues refer to the original HW / OW / POS / PED divisions."
        registration = "{}"
        if spec:
            try:
                registration = registration_music(spec, measure)
            except (KeyError, TypeError, ValueError) as exc:
                notes.append(f"Registration cues unavailable: {exc}")
        definitions.append("registrationCues = " + registration)
    else:
        try:
            if not spec or not spec.get("assignments"):
                raise ValueError("no performance assignments")
            # Bar-position routing is intentionally limited to fixed meter.
            global_path = (root / paths.get("score", "score/music-voices.ly")).parent / "music-global.ly"
            global_text = re.sub(r"%[^\n]*", "", global_path.read_text())
            meters = re.findall(r"\\time\s+(\d+/\d+)", global_text)
            if any(F(m) != measure for m in meters) or re.search(r"\\(?:partial|compoundMeter|include)\b", global_text):
                raise ValueError("routing requires fixed meter without pickup")
            voices = read_voices((root / paths.get("score", "score/music-voices.ly")).read_text(), measure)
            end = voices["soprano"][-1].end
            assignments = spec["assignments"]
            if not isinstance(assignments, list) or any(not isinstance(a, dict) for a in assignments):
                raise ValueError("assignments must be a list of objects")
            if any(a.get("voice") not in VOICES or not isinstance(a.get("part"), str) for a in assignments):
                raise ValueError("assignment has an unknown voice or missing part")
            if name == "ensemble":
                lanes = {"pianoSoprano": {"soprano", "soprano_8va"}, "pianoAlto": {"alto"},
                         "pianoTenor": {"tenor"}, "pianoBass": {"bass", "bass_8vb"},
                         "violinOne": {"vn1"}, "violinTwo": {"vn2"}, "viola": {"va"}, "cello": {"vc"}}
                if {a["part"] for a in assignments} - set().union(*lanes.values()):
                    raise ValueError("unsupported ensemble part")
                for lane, parts in lanes.items():
                    events = route_notes(voices, assignments, parts, measure, end)
                    definitions.append(f"{lane} = " + music_line(events, end, measure))
                values["NOTICE"] = "Assignment score: rests and octave doublings from the quintet spec; added pedal points and performance nuances omitted."
                notes.append("Ensemble follows assignment attacks, rests, voice handoffs and octave doublings; added pedal points, damper pedal, articulation and level overrides are omitted. Shared score dynamics retained.")
            else:
                if {a["part"].split(".")[0] for a in assignments} - set().union(*FAMILIES.values(), {"timp"}):
                    raise ValueError("unsupported orchestra part")
                for family, prefixes in FAMILIES.items():
                    parts = {a["part"] for a in assignments if a["part"].split(".")[0] in prefixes}
                    for voice in VOICES:
                        events = route_notes(voices, [a for a in assignments if a["voice"] == voice], parts, measure, end, octaves=False)
                        definitions.append(f"{family.lower()}{voice.title()} = " + music_line(events, end, measure))
                values["NOTICE"] = "Condensed short score at source pitch: family assignments; unison / octave doubles collapsed; percussion and added pedals omitted."
                notes.append("Orchestra is a six-staff family short score at source pitch. Instrument doublings and octave shifts are collapsed; percussion, added pedal points, articulation and level overrides are omitted. Shared score dynamics retained.")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            definitions.clear()
            notes.append(f"Unfiltered fallback: all four voices printed; performance rests and doublings not derived ({exc}).")
            values["NOTICE"] = "Unfiltered study score: all voices printed; performance assignments, rests and doublings not applied."
            if name == "ensemble":
                mapping = dict(zip(("pianoSoprano", "pianoAlto", "pianoTenor", "pianoBass"), VOICES))
                mapping.update(dict(zip(("violinOne", "violinTwo", "viola", "cello"), VOICES)))
            else:
                mapping = {f"{family.lower()}{voice.title()}": voice for family in FAMILIES for voice in VOICES}
            definitions.extend(f"{lane} = \\{voice}" for lane, voice in mapping.items())

    template = re.sub(r"@(TITLE|SUBTITLE|NOTICE)@", lambda m: ly_string(values[m[1]]), template)
    return template.replace("@DEFINITIONS@", "\n".join(definitions)), notes
