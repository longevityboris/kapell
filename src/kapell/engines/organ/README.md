# Pipe organ renderer (the Bach version)

Renders the ricercar's four voices (or any multi-voice MIDI file) on a sampled North German
baroque organ in a church. Input contract: `CONTRACT.md`. Nothing is ever played through the
speakers.

```
./setup_organ.sh                         # once: sample set, impulse response, pipe model
demo/render_demo.sh                      # skeleton -> out/skeleton_organ.wav/.m4a + QA
python3 render_organ.py IN.mid --registration REG.json -o OUT [--stems DIR] [--json REPORT]
python3 tests/contract_tests.py          # 19 pass/fail checks of CONTRACT.md, exit 1 on failure
python3 tests/loop_sweep.py              # every pipe held 5 s: loop wraps and release joins
```

## Instrument and room

* **Organ:** Norrfjärden Church (Grönlunds Orgelbyggeri 1997), a replica of the 1684 organ of
  the German Church in Stockholm. Hauptwerck (12 stops), Rückpositief (10), Oberwerck (7) and
  Pedahl (7): 36 stops, 1769 sample files, every pipe recorded separately in stereo (44.1 kHz,
  24-bit) with several loops and releases chosen by how long the key was held. Sample set by Lars
  Palo, version 20230618, **CC BY-SA 4.0** (familjenpalo.se). 1.9 GB in
  `/Users/biobook/Music/SampleLibraries/Organ/NorrfjardenChurch`.
* **Church:** OpenAIR impulse response, Lady Chapel, St Albans Cathedral, ORTF position A
  (University of York Audiolab), **CC BY 4.0**, added by convolution with its direct sound
  removed (the samples already carry the Norrfjärden church). Default level -4 dB relative to the
  dry organ (`--wet-db`).
* Both credits are written into the WAV and M4A tags. A published render must carry them; the
  CC BY-SA licence of the samples applies to the recordings made from them.

## How a note becomes sound

1. **Voices and divisions.** One voice per MIDI track (soprano, alto: Hauptwerck; tenor:
   Rückpositief; bass: Pedal, unless the registration sidecar says otherwise). A MIDI note is a
   key; each drawn stop sounds at its own footage (16' an octave down, 4' up, mixtures at their
   harmonics). Two voices on one key of one division play one set of pipes; a key handed from one
   voice to another is re-struck.
2. **Registration** is a timeline per division (`changes` in the sidecar, or `organ:` text events).
   Held keys follow the stops, as on a real organ: a stop drawn under a held key starts speaking at
   the change, a retired one releases there. Velocity is ignored, so dynamics are terraced by
   registration, as Bach's were.
3. **Pipes** (`pipe_engine.py`): the recorded pipe nearest in pitch is retuned from the organ's
   1/4-comma meantone at about a semitone above A440 to equal temperament at A440 (or Vallotti /
   Werckmeister III, `--temperament`). The sustain is the attack plus a loop that wraps cleanly
   (4 ms crossfade), resampled once so the retuning never breaks a loop. The release sample is
   joined at the best-matching phase, level-matched. The samples are spaced-pair recordings in
   which some pipes are nearly anti-phase between the channels; each pipe's right channel is
   delayed by its measured lag (at most 1.5 ms) so the organ does not thin out in mono.
4. **Anticipation.** Keys are played early by half the median speech time of the pipes they open
   (at most 40 ms), as an organist does, so slow bass pipes still speak on the beat.
5. **Mix:** dry sum, church convolution, one peak normalisation for the whole file (true peak
   -1 dBTP) so registration contrasts survive, 24-bit WAV and 256 kb/s AAC.

## The demo registration plan (`demo/skeleton_registration.json`)

The performance plan's hairpins become registration steps at phrase joins:

| bars | Hauptwerck (S, A) | Rückpositief (T) | Pedal (B) | plan |
|---|---|---|---|---|
| 1-12 | Gedackt 8' | Flött 8' | Gedackter Bass 8' | p to mp, exposition |
| 13-19 | Principal 8' | Flött 8' + Principal 4' | 16' + 8' | mf |
| 20-23 | + Octava 4' | + Flött 4' | | building to f |
| 24-26 | + Octava 2' | + Octava 2' | + 4' | |
| 26:3-29 | plenum (Mixtur VI) | plenum (Cimbel III) | plenum + Posaune 16', Trompete 8' | ff, climax I |
| 30-34 | soprano solo on the Rückpositief Sesquialtera; alto and tenor on the Oberwerck Quintadena 8' | | Gedackter Bass 8' | pp arioso |
| 35-45 | flutes 8', 8'+4' from 39, principals from 41, + 4' at 43 | same | 8', 16'+8' from 39 | inverted fugue, pp to mf |
| 46-51 | flutes 8'+4', principals from 48, + 2' at 50 | | 16'+8', + 4' at 50 | p to f |
| 52-53 | plenum, then + Quintadena 16' + Trommeten 8' | plenum | plenum + reeds | fff, climax II |
| 54-58 | principals 8'+4', + 2' at 57 | principals | 16'+8', + 4' at 57 | f to p, rebuilding |
| 59-61:2 | plenum + Trommeten 8' | plenum | plenum + reeds | apotheosis |
| 61:3-66 | principals 8'+4'+2', then Principal 8' alone from 63 | | 16'+8'+4', then 16'+8' | mp to pp coda |

## Measurements (2026-09-25, on the current code)

**Contract tests** (`tests/results.json`): 19/19 pass. Hauptwerck ladder, K-weighted level and the
share of energy above 2 kHz: flute 8' -13.1 dB / -42.6 dB, principal 8' -8.8 / -31.0, 8'+4'+2'
-5.1 / -12.8, plenum -3.1 / -7.3, plenum + reed -1.7 / -8.7. Pedal: 8' alone -21.9 dB, 16'+8'
-15.5, 16'+8'+4' -13.7, plenum with reeds -11.1. Swell box (optional, `enclosed`): closed
-20.9 dB and darker (centroid 1255 to 870 Hz). Renders are bit-identical run to run.

**Every pipe** (`tests/loop_sweep.json`): 1653 stop/key combinations held 5 s: 0 clicks at loop
wraps, 0 at release joins; level steps between 20 ms windows p99 2.45 dB (the pipes' own
unsteadiness). One outlier, see Limits.

**The skeleton** (`demo/render_demo.sh`, 66 bars; `out/skeleton_organ.json`,
`qa/results/skeleton_qa.json`), measured on the audio:

* 703 notes, 701 key presses, 1495 pipe events on 322 pipes; 0 key presses without sound, 0
  missing pipes, 0 folded notes. The pedal's short-octave keys C, D, E borrow a neighbouring pipe
  retuned by about a semitone (47 pipe events).
* Pitch, 690 notes: median 0.01 cents from A440 equal temperament, p95 1.5 cents, 1 note over 5
  cents (a 0.34 s 16' pedal note measured at -6.5 c; the same pipes on a long note measure
  0.4 c: a short-window artefact).
* Stuck notes: none. Every rest longer than 3 s is at least 92 dB below the voice's peak, and all
  228 notes with partials no neighbour shares fall by more than 6 dB within 1 s of key-up (median
  -34 dB in the pedal, -46 to -48 dB on the manuals).
* Clicks: 14 candidates in the dry stems, all at note boundaries (attacks and key-ups), none
  elsewhere (inside held notes, where loop wraps and registration changes fall).
* Release joins: phase correlation median 0.9985; key-up moved by at most 14 ms (half a period of
  the lowest 16' pipe).
* Terraces: mix level while sounding -30 dBFS / centroid 470 Hz in the 8' flute exposition,
  -22 dBFS with principals, -16 dBFS / 870-1170 Hz with plenum and reeds; in the arioso the
  Sesquialtera solo is 10 dB above its accompaniment. Integrated -17.5 LUFS, loudness range
  14.5 LU, true peak -1.0 dBTP.
* Church: added reverberation -4 dB re the dry organ, its own C80 +8.2 dB. Whole system (the
  samples' church plus the added one) at the final cut-off: C80 +2.9 dB broadband and +6.7 dB at
  1 kHz, T20 2.65 s: a resonant church in which the lines stay distinct.
* Stereo, dry sum: L/R correlation 0.81, mono fold-down -0.43 dB (worst 1 s window -1.1 dB). With
  the per-pipe alignment switched off the same render measures 0.47 and -1.33 dB, and the alto
  loses 11.3 dB in mono in its worst second: the alignment is kept.
* Speed: the 232 s piece renders in about 20 s (8 threads); the whole demo with QA in about 30 s.

**The assembled score** (`score/music-voices.ly` at 09:08 on 2026-09-25, 66 bars, 748 notes),
rendered read-only with the same plan and registration as a check for the final renders: no
warnings, 0 key presses without sound, pitch p95 1.5 cents (the same single short 16' pedal note
over 5 cents), no stuck notes, no clicks away from note boundaries, whole-system C80 +1.7 dB
broadband / +7.3 dB at 1 kHz, T20 2.7 s, -18.4 LUFS, LRA 14.2 LU.

The skeleton's QA lists 25 bass notes whose harmonic comb is weak (`presence.weak_comb_notes`). They sound:
checked on the bass stem, two are a repeated key re-struck after 50 ms (the same pitch before and
after), three share a partial with the previous note (e.g. C#2's 16' third harmonic is G#2's
fundamental), and the rest rise 8-53 dB at their fundamental and third harmonic after the onset.
The comb metric struggles with stopped pipes (odd harmonics only) in short windows.

## Limits

* **Not modelled:** couplers, tremulant, wind sag, and dynamics within a note (by contract: velocity
  is ignored; the swell box exists only as an option, the real organ has none).
* **Oberwerck Spitzquinten 1 1/2', keys 82-85:** the recorded pipes beat, up to 7.8 dB between
  20 ms windows (key 84). Only the Oberwerck `plenum` and `plenum_reed` draw this stop; the demo
  plan does not.
* The stereo lag is measured on each pipe's main sample and also applied to its attack
  alternates. The bass stem's worst 1 s mono fold-down is -3.3 dB (overall -0.3 dB).
* **With `tools/mix.py`:** the organ's stems carry the render's normalisation gain (CONTRACT.md
  section 6; `normalisation_gain_db` in the report, -14 dB for the skeleton). mix.py's
  `raw_scale_db` currently treats organ stems as pre-normalisation, so in an ensemble mix the
  organ's level would be off by the difference between the piece's and the calibration chorale's
  normalisation gains; the fix belongs in mix.py (undo `normalisation_gain_db` for the organ, as it
  does for the quartet). The organ rendered alone (the Bach version) is not affected.

## Files

| file | what |
|---|---|
| `CONTRACT.md` | MIDI and registration input contract |
| `render_organ.py` | the renderer (MIDI, registration timeline, keys, mix, report) |
| `pipe_engine.py` | one pipe event: choice, retuning, loops, stereo alignment, release |
| `odf.py`, `analyze_organ.py` | GrandOrgue ODF parser; per-pipe measurement -> `data/norrfjarden_pipes.json` |
| `registrations.json` | named registrations per division, defaults and presets |
| `setup_organ.sh`, `organ_paths.py` | idempotent setup (checksummed downloads), paths |
| `demo/` | skeleton registration plan and the one-command demo |
| `tests/` | contract tests and the all-pipes loop sweep, with their results |
| `qa/` | measurement QA of a render against its MIDI, and the skeleton's results |
| `out/` | renders (audio and MIDI are not committed; the report is) |
