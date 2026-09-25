"""Version pipelines: score + performance plan (+ scoring spec) -> MIDI -> an engine -> audio.

This is the kit's replacement for the per-version render.sh scripts of fugue-jp
(performance/<version>/render.sh). The steps and their order are those scripts'; the only
differences are where things go (renders_dir(piece)/<version>/, never the project) and the
optional bar range.

Version kinds (the engine family a version renders on):
    piano      plan.json only                  perform.py --target piano -> render_piano.py
    organ      spec with one "organ" group     orchestrate.py -> articulate.py -> check -> render_organ.py
    quartet    spec with one "quartet" group   orchestrate.py -> bowing.py, swell.py -> check -> mix.py
    orchestra  spec with an "orchestra" group  orchestrate.py -> check -> mix.py
    ensemble   spec with several groups        orchestrate.py -> check -> mix.py

A version is a folder performance/<name>/ in the project. `--version` takes either that folder
name or a kind; a kind resolves to the one folder of that kind listed in kapell.toml
[versions].render (else found under performance/).

Per-version helper arguments (bowing breaths, swell exclusions) are read from kapell.toml
[render.<folder>] (keys "bowing" and "swell": argument lists), else from the helper lines of the
version's legacy render.sh, so the fixture renders exactly as its own script did.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import mido

from kapell.commands import KapellError
from kapell.config import renders_dir
from kapell.engines import ENGINES

KIT = ENGINES.parent                       # src/kapell
PERFORM = KIT / "perform" / "perform.py"
ARTICULATE = KIT / "perform" / "articulate.py"
BOWING = KIT / "perform" / "bowing.py"
SWELL = KIT / "perform" / "swell.py"
ORCHESTRATE = KIT / "mix" / "orchestrate.py"
MIX = KIT / "mix" / "mix.py"
RENDER_PIANO = ENGINES / "piano" / "render_piano.py"
RENDER_ORGAN = ENGINES / "organ" / "render_organ.py"
KINDS = ("organ", "piano", "quartet", "orchestra", "ensemble")
REPORT_SUFFIXES = (".mix.json", ".render.json", ".qa.json", ".integrity.json", ".orchestration.json",
                   ".levels.json", ".presence.json")


# ------------------------------------------------------------------------------ project side
def piece_slug(root: Path, cfg: dict) -> str:
    name = (cfg.get("piece") or {}).get("name") or root.name
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or root.name


def _spec_files(folder: Path) -> list[Path]:
    out = []
    for f in sorted(folder.glob("*.json")):
        if f.name == "plan.json" or f.name.endswith(REPORT_SUFFIXES):
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and isinstance(d.get("groups"), dict) and "assignments" in d:
            out.append(f)
    return out


def kind_of(folder: Path) -> tuple[str, Path | None]:
    """(kind, spec path or None) of a version folder."""
    specs = _spec_files(folder)
    if not specs:
        if (folder / "plan.json").is_file():
            return "piano", None
        raise KapellError("no_version_spec", f"{folder} has neither a scoring spec nor a plan.json",
                          "a version folder needs plan.json (piano) or a spec with groups and assignments")
    spec = specs[0]
    renderers = {g.get("renderer", k) for k, g in json.loads(spec.read_text())["groups"].items()}
    if len(renderers) > 1:
        return "ensemble", spec
    if not renderers:
        raise KapellError("bad_spec", f"{spec}: groups must not be empty", exit_code=3)
    r = renderers.pop()
    return {"organ": "organ", "quartet": "quartet", "orchestra": "orchestra", "piano": "piano"}.get(r, "ensemble"), spec


def performance_dir(root: Path, cfg: dict) -> Path:
    return root / (cfg.get("paths") or {}).get("performance", "performance")


def resolve_version(root: Path, cfg: dict, version: str) -> dict:
    pdir = performance_dir(root, cfg)
    if (pdir / version).is_dir():
        folder = pdir / version
    elif version in KINDS:
        listed = [pdir / v for v in (cfg.get("versions") or {}).get("render", []) if (pdir / v).is_dir()]
        cands = listed or (sorted(p for p in pdir.iterdir() if p.is_dir()) if pdir.is_dir() else [])
        hits = []
        for c in cands:
            try:
                if kind_of(c)[0] == version:
                    hits.append(c)
            except KapellError:
                continue
        if len(hits) != 1:
            raise KapellError("version_ambiguous" if hits else "version_not_found",
                              f"{len(hits)} version folders of kind {version!r} under {pdir}: {[h.name for h in hits]}",
                              "pass the folder name, e.g. --version " + (hits[0].name if hits else "bach_organ"))
        folder = hits[0]
    else:
        have = sorted(p.name for p in pdir.iterdir() if p.is_dir()) if pdir.is_dir() else []
        raise KapellError("version_not_found", f"no version {version!r}", f"one of {list(KINDS)} or a folder: {have}")
    kind, spec = kind_of(folder)
    plan = folder / "plan.json"
    if not plan.is_file():
        plan = root / (cfg.get("paths") or {}).get("plan", "design/final-lab/plan.json")
    score = root / (cfg.get("paths") or {}).get("score", "score/music-voices.ly")
    for p in (plan, score):
        if not p.is_file():
            raise KapellError("missing_input", f"missing {p}", "check [paths] in kapell.toml")
    return {"name": folder.name, "kind": kind, "folder": folder, "spec": spec, "plan": plan, "score": score}


def helper_args(root: Path, cfg: dict, v: dict, helper: str, build: Path) -> list[str] | None:
    """Arguments after the MIDI path for bowing.py / swell.py: kapell.toml, else the legacy render.sh."""
    conf = ((cfg.get("render") or {}).get(v["name"]) or {}).get(helper)
    if conf is not None:
        return [str(x) for x in conf]
    sh = v["folder"] / "render.sh"
    if not sh.is_file():
        return None
    text = sh.read_text().replace("\\\n", " ")
    for line in text.splitlines():
        if f"{helper}.py" not in line or line.lstrip().startswith("#"):
            continue
        toks = shlex.split(line.split(";")[0].split("&&")[0].split("||")[0])
        i = next(i for i, x in enumerate(toks) if x.endswith(f"{helper}.py"))
        toks = toks[i + 2:]                            # drop the script and the MIDI path
        return [x.replace("${D}/build", str(build)).replace("$D/build", str(build)) for x in toks]
    return None


# ------------------------------------------------------------------------------ MIDI helpers
def parse_bars(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", s)
    if not m:
        raise KapellError("bad_bars", f"--bars {s!r} is not A-B", "e.g. --bars 1-8")
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if a < 1 or b < a:
        raise KapellError("bad_bars", f"--bars {s!r}: need 1 <= A <= B", "e.g. --bars 1-8")
    return a, b


def note_counts(midi: Path) -> dict:
    m = mido.MidiFile(str(midi))
    out = {}
    for i, t in enumerate(m.tracks):
        n = sum(1 for x in t if x.type == "note_on" and x.velocity > 0)
        if n:
            out[t.name or f"track{i}"] = out.get(t.name or f"track{i}", 0) + n
    return out


def crop_bars(src: Path, dst: Path, bars: tuple[int, int], measure_whole: float = 1.0) -> dict:
    """Keep the notes that start in bars A..B, with every tempo, CC and meta event up to one bar
    after the last kept release. Nothing is shifted in time, so bar-anchored sidecars (organ
    registration, orchestration windows) stay valid. A note is in range if its onset lies within a
    32nd of the bar lines (humanised onsets land a few ms early)."""
    m = mido.MidiFile(str(src))
    bar_t = 4 * m.ticks_per_beat * measure_whole
    tol = m.ticks_per_beat / 8
    lo, hi = (bars[0] - 1) * bar_t - tol, bars[1] * bar_t - tol
    kept, last_off, tracks = 0, 0, []
    for tr in m.tracks:
        t, active, out = 0, {}, []
        for msg in tr:
            t += msg.time
            key = (getattr(msg, "channel", None), getattr(msg, "note", None))
            if msg.type == "note_on" and msg.velocity > 0:
                keep = lo <= t < hi
                active.setdefault(key, []).append(keep)
                if keep:
                    kept += 1
                    out.append((t, msg, True))
            elif msg.type in ("note_off", "note_on"):
                stack = active.get(key)
                if stack and stack.pop(0):
                    last_off = max(last_off, t)
                    out.append((t, msg, True))
            elif msg.type != "end_of_track":
                out.append((t, msg, False))
        tracks.append(out)
    cutoff = max(last_off, hi) + bar_t
    for ti, out in enumerate(tracks):
        new, prev = mido.MidiTrack(), 0
        for t, msg, is_note in out:
            if not is_note and t > cutoff:
                continue
            new.append(msg.copy(time=int(t - prev)))
            prev = t
        m.tracks[ti] = new
    m.save(str(dst))
    return {"notes_kept": kept, "start_tick": max(0, int(lo + tol))}


def seconds_at_tick(midi: Path, tick: int) -> float:
    m = mido.MidiFile(str(midi))
    tempo, t, s = 500000, 0, 0.0
    evs = sorted((sum(x.time for x in tr[:i + 1]), x.tempo) for tr in m.tracks for i, x in enumerate(tr)
                 if x.type == "set_tempo")
    for et, tp in evs:
        if et >= tick:
            break
        s += mido.tick2second(et - t, m.ticks_per_beat, tempo)
        t, tempo = et, tp
    return s + mido.tick2second(tick - t, m.ticks_per_beat, tempo)


def trim_front(wav: Path, seconds: float) -> None:
    """Drop the silent span before the first kept bar (sample 0 = MIDI time -lead_in, by contract)."""
    if seconds <= 0 or not wav.is_file():
        return
    import soundfile as sf
    x, sr = sf.read(str(wav), always_2d=True)
    info = sf.info(str(wav))
    sf.write(str(wav), x[int(round(seconds * sr)):], sr, subtype=info.subtype)
    m4a = wav.with_suffix(".m4a")
    if m4a.exists():
        from kapell.engines.encoding import encode_aac
        encode_aac(wav, m4a)


# ------------------------------------------------------------------------------ running steps
class Steps:
    def __init__(self, log: Path):
        self.log = log
        self.done: list[dict] = []
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("")

    def run(self, name: str, cmd: list, cwd: Path | None = None, timeout: float = 3600) -> None:
        t0 = time.time()
        with open(self.log, "a") as fh:
            fh.write(f"\n$ {' '.join(map(str, cmd))}\n")
            fh.flush()
            r = subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
        self.done.append({"step": name, "s": round(time.time() - t0, 1), "rc": r.returncode})
        if r.returncode:
            tail = self.log.read_text().strip().splitlines()[-6:]
            raise KapellError("step_failed", f"{name} failed (exit {r.returncode}): {' | '.join(tail)[-600:]}",
                              f"full log: {self.log}", exit_code=2 if any(marker in " ".join(tail) for marker in
                                                 ("No such file", "ModuleNotFoundError", "PermissionError",
                                                  "encoder_unavailable", "install ffmpeg", "Permission denied",
                                                  "run ./setup_", "run setup_", "kapell setup")) else 1)


def outdir(root: Path, cfg: dict, v: dict) -> Path:
    return renders_dir(piece_slug(root, cfg)) / v["name"]


def perform_version(root: Path, cfg: dict, v: dict, steps: Steps, build: Path) -> dict:
    """Score + plan (+ spec) -> the version's performance MIDI in build/. Returns {midi, sidecar, manifest}."""
    py = sys.executable
    build.mkdir(parents=True, exist_ok=True)
    kind = v["kind"]
    if kind == "piano":
        mid = build / "piano.mid"
        steps.run("perform", [py, PERFORM, v["score"], v["plan"], mid, "--target", "piano", "--cues"])
        return {"midi": mid}
    steps.run("orchestrate", [py, ORCHESTRATE, v["score"], v["plan"], v["spec"], build, "--quiet"])
    if kind == "organ":
        mid = build / "organ.mid"
        raw = build / "organ_perform.mid"
        shutil.copyfile(mid, raw)
        steps.run("articulate", [py, ARTICULATE, v["score"], v["plan"], raw, mid, "--json", build / "articulation.json"])
        raw.unlink(missing_ok=True)
        steps.run("check", [py, ORCHESTRATE, v["score"], v["plan"], v["spec"], build, "--check", "--quiet"])
        return {"midi": mid, "sidecar": build / "organ.registration.json"}
    if kind == "quartet":
        mid = build / "quartet.mid"
        b = helper_args(root, cfg, v, "bowing", build)
        if b is not None:
            if "--orchestration" not in b:
                b = ["--orchestration", str(build / "orchestration.json")] + b
            steps.run("bowing", [py, BOWING, mid, *b])
        s = helper_args(root, cfg, v, "swell", build)
        if s is not None:
            steps.run("swell", [py, SWELL, mid, *s])
        if b is not None or s is not None:
            steps.run("check", [py, ORCHESTRATE, v["score"], v["plan"], v["spec"], build, "--check", "--quiet"])
    return {"manifest": build / "manifest.json"}


def render_version(root: Path, cfg: dict, v: dict, bars: tuple[int, int] | None, stems: bool) -> dict:
    out_dir = outdir(root, cfg, v)
    build = out_dir / "build"
    steps = Steps(out_dir / "render.log")
    tag = v["name"] + (f"_b{bars[0]}-{bars[1]}" if bars else "")
    out = out_dir / tag
    perf = perform_version(root, cfg, v, steps, build)
    measure = eval_fraction(json.loads(v["plan"].read_text()).get("measure", "1"))   # bar in whole notes
    py = sys.executable
    digest: dict = {"version": v["name"], "kind": v["kind"], "bars": f"{bars[0]}-{bars[1]}" if bars else "all"}
    front = 0.0
    if v["kind"] in ("piano", "organ"):
        mid = perf["midi"]
        if bars:
            cropped = build / f"{mid.stem}.{tag}.mid"
            crop_bars(mid, cropped, bars, measure)
            front = seconds_at_tick(mid, int((bars[0] - 1) * 4 * mido.MidiFile(str(mid)).ticks_per_beat * measure))
            mid = cropped
        report = out.with_suffix(".render.json")
        if v["kind"] == "piano":
            cmd = [py, RENDER_PIANO, mid, "-o", out, "--wet-db", "-1", "--json", report]
            if stems:
                cmd += ["--stems", out_dir / "stems"]
            steps.run("render_piano", cmd, cwd=ENGINES / "piano")
        else:
            cmd = [py, RENDER_ORGAN, mid, "--registration", perf["sidecar"], "-o", out, "--json", report]
            if stems:
                cmd += ["--stems", out_dir / "stems"]
            steps.run("render_organ", cmd, cwd=ENGINES / "organ")
        trim_front(out.with_suffix(".wav"), front)
        rep = json.loads(report.read_text())
        midi_n = note_counts(mid)
        audio_n = {k: d.get("notes") for k, d in rep.get("voices", {}).items()}   # both engines report voices.<v>.notes
        digest.update(notes_midi=sum(midi_n.values()), notes_rendered=sum(x or 0 for x in audio_n.values()),
                      notes_match=midi_n == {k: v2 for k, v2 in audio_n.items() if v2},
                      per_voice={k: [midi_n.get(k, 0), audio_n.get(k)] for k in sorted(set(midi_n) | set(audio_n))},
                      duration_s=rep.get("duration_s"), warnings=len(rep.get("warnings") or []),
                      report=str(report))
    else:
        man = perf["manifest"]
        if bars:
            m = json.loads(man.read_text())
            first, silent = None, []
            for g, gd in m["groups"].items():
                p = build / gd["midi"]
                first = first or p
                if crop_bars(p, p, bars, measure)["notes_kept"] == 0:
                    silent.append(g)          # a group that has not entered yet (the quintet's piano before bar 35)
            if len(silent) == len(m["groups"]):
                raise KapellError("no_notes", f"no notes start in bars {bars[0]}-{bars[1]}", "pick bars where the music plays")
            for g in silent:
                del m["groups"][g]
            if m.get("reference_group") in silent:
                m["reference_group"] = next(iter(m["groups"]))
            man = build / f"manifest.{tag}.json"
            man.write_text(json.dumps(m, indent=1))
            digest["groups_silent"] = silent
            front = seconds_at_tick(first, int((bars[0] - 1) * 4 * mido.MidiFile(str(first)).ticks_per_beat * measure))
        cmd = [py, MIX, man, "--out", out]
        if stems:
            cmd.append("--keep-stems")
        steps.run("mix", cmd, timeout=4 * 3600)
        trim_front(out.with_suffix(".wav"), front)
        mixrep = out.with_suffix(".mix.json")
        rep = json.loads(mixrep.read_text()) if mixrep.exists() else {}
        m = json.loads(man.read_text())
        midi_n = {g: sum(note_counts(build / gd["midi"]).values()) for g, gd in m["groups"].items()}
        digest.update(notes_midi=sum(midi_n.values()), per_group=midi_n, alignment_ok=rep.get("alignment_ok"),
                      report=str(mixrep))
    digest.update(wav=str(out.with_suffix(".wav")), m4a=str(out.with_suffix(".m4a")) if out.with_suffix(".m4a").exists() else None,
                  steps=steps.done, log=str(steps.log))
    meta = {"kit": _kit_version(), "score": str(v["score"]), "plan": str(v["plan"]),
            "spec": str(v["spec"]) if v["spec"] else None, **digest}
    out.with_suffix(".kapell.json").write_text(json.dumps(meta, indent=1))
    return digest


def eval_fraction(x) -> float:
    from fractions import Fraction
    return float(Fraction(str(x)))


def _kit_version() -> str:
    try:
        from importlib.metadata import version
        return version("kapell")
    except Exception:
        return "0.1.0"
