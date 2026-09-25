export const meta = {
  name: 'ricercar-design-and-sound-v2',
  description: 'Resume the interrupted ricercar work: 4 designers finish proposals, judge panel, blueprint synthesis with adversarial critique; finish and QA the piano and string-quartet renderers',
  phases: [
    { title: 'Design', detail: '4 designers continue their existing proposals, proving every device with the checker' },
    { title: 'Judge', detail: '3 judges (rigor, beauty, execution) score all proposals' },
    { title: 'Synthesize', detail: 'merge the winner with grafted ideas into BLUEPRINT.md and verified final-lab' },
    { title: 'Critique', detail: 'two critics (contrapuntal and musical) per round, fixer, up to 2 rounds' },
    { title: 'Sound', detail: 'finish piano and quartet renderers, adversarial audio QA, fix loop' },
  ],
}

const ROOT = '/Users/biobook/Music/llm-music/fugue-jp'
const R = ROOT + '/ricercar'
const LIB = '/Users/biobook/Music/SampleLibraries'

const GIT = `GIT: the repo ${ROOT} has no remote; never push. Other agents commit concurrently in the same repo, so stage ONLY your own paths and commit with \`git add <your paths> && git commit -m "..." -- <your paths>\`; if you hit index.lock, wait a few seconds and retry. Commit after every meaningful verified step (not only at the end): a previous session was cut off by a usage limit and only committed work survived. Do not commit audio (.wav/.m4a) or sample libraries.`

const CONTEXT = `
PROJECT: ${R}. ${GIT}
The user wants a NEW piece: a deep, beautiful, "mathematically beautiful" 4-voice fugue / ricercar on John Williams's Theme from Jurassic Park, with the depth of Bach's Ricercar a 6 (Musical Offering) and the Art of Fugue, and the large-scale arc of late Beethoven (Op. 110 finale, Op. 131 No. 1, Hammerklavier fugue). Length 3.5-4 minutes (210-240 s). FULL CREATIVE LICENSE, including small tweaks to the tune to make it smoother and more beautiful, as long as it stays instantly recognisable. The user's complaints about the previous piece: "too happy", "melody seems off", shallow; they want "a lot of reasoning, logic, layers, very high quality".
Decisions already made: home key B-flat MINOR (theme's scale degree 3 lowered; see THEME.md), ending with the theme transfigured into B-flat MAJOR (apotheosis). 4 voices: soprano, alto, tenor, bass. It will be rendered with real samples on (a) a concert grand piano with real dynamics and (b) a string quartet (violin I, violin II, viola, cello), so every line must be idiomatic for both: ranges soprano 60-84 (C4-C6), alto 53-77, tenor 48-72, bass 36-62 (MIDI numbers, c'=60). Keep hand spans plausible for keyboard where practical (upper staff = S+A, lower = T+B).
Reference theme: ${R}/design/THEME.md (read it).
Previous attempt: ${ROOT}/fugue.ly and ${ROOT}/NOTES.md (B-flat major organ fugue, 37 bars). Its diagnosed flaws, which the new piece MUST fix:
 1. Subject = only theme bars 1-4 in halved note values: rushed, ended on the pickup notes, so every entry stopped mid-phrase; first bar one static tonic chord.
 2. Countersubject = generic 3rds/6ths filler; free voices = sustained chord padding.
 3. Harmony almost all diatonic major triads; little chromaticism, few suspensions, no harmonic surprise.
 4. No inversion, augmentation, combination of subjects; stretto only at the octave.
 5. Two-bar block form with no long-range tension, climax or release; flat dynamics.
TOOLS:
 - LilyPond 2.26 (\`lilypond\`). Voices are \\absolute variables named soprano, alto, tenor, bass containing ONLY notes, rests (r, R, s), ties (~) and bar checks (|); comments with %. Dutch accidentals (bes, ees, fis). c' = middle C.
 - Counterpoint checker: \`python3 ${R}/tools/check.py FILE.ly --voices soprano,alto,tenor,bass [--bars A-B] [--grid] [--quiet] [--measure 1]\` (missing voices are skipped, so 2-3 voice labs work). Reports bar-length errors, ranges, PAR! (parallel/antiparallel 5ths/8ves), BEAT (5ths/8ves on successive beats), MEL, CROS, DIR, and every dissonance (DIS = justified, DIS! = unjustified, D4? = 4th/tritone vs bass needing review). Anything claimed to work must have 0 PAR!, 0 BEAT, 0 DIS!; explain any D4?/DIR by ear.
 - Harmony x-ray: \`python3 ${R}/tools/harmony.py FILE.ly --key 1-20=bb,21-30=f --stats\` (Roman numerals, richness metrics).
 - Section assembler \`${R}/tools/assemble.py\`, performance engine \`${R}/tools/perform.py\` (score -> expressive multi-track MIDI), score templates ${R}/score/piano.ly and quartet.ly.
 - music21 and numpy are installed.
`

// ---------------- DESIGN ----------------
const ANGLES = [
  'BACH-STRICT: model the Ricercar a 6 and Art of Fugue. Maximise learned devices (invertible counterpoint at 8ve/10th/12th, mirror inversion, stretto at several intervals and distances, augmentation, combination of subjects), archaic dignity, alla breve gravity, every voice a real melody.',
  'BEETHOVEN-ARC: model the late-Beethoven fugues (Op. 110 finale with its inversion and radiant major return, Op. 131 No. 1, Hammerklavier). Motivic development of cells of the theme (the B-flat/A neighbour, the rising 2nd+3rd, the falling arpeggio), long-range tension, dramatic dominant preparation, climax, subito piano, and a transfigured major ending that feels earned.',
  'CHROMATIC-DEPTH: model Bach WTC I C-sharp minor and B minor fugues and the Musical Offering Royal Theme. Chromatic countersubjects (descending lament tetrachord, passus duriusculus), suspension chains, diminished sevenths, Neapolitan and augmented-sixth colour at structural points, dark minor-key gravity, harmonic surprise that still feels inevitable.',
  'MELODIC-BEAUTY: model Bach chorale fantasias and cantus-firmus fugues (Vor deinen Thron, Art of Fugue augmentation). Keep the tune beautiful and recognisable: consider the complete 8-bar theme as a cantus firmus in long notes in the final section while the other voices weave the subjects; singable lines, warm voice-leading, lyrical countersubjects, a luminous major apotheosis.',
]

const DESIGN_TASK = (k, angle) => `${CONTEXT}
YOUR ROLE: independent DESIGNER #${k}. Angle: ${angle}
RESUMING INTERRUPTED WORK: a previous designer #${k} with the same angle was cut off mid-task. Its files are in ${R}/design/proposal-${k}/ (lab .ly files, helper scripts such as mats.py/search tools, maybe a DESIGN.md skeleton). Read them first, re-run the checker on every existing lab file, keep what is verified and good, fix or discard the rest, and continue. Work ONLY inside ${R}/design/proposal-${k}/.
Produce a complete, concrete design a composer can execute bar by bar:
 A. SUBJECTS & MATERIALS in LilyPond: Subject I (from theme bars 1-4, at or near real rhythm; it must end on a strong degree or elide, not stop on a pickup), its answer (real or tonal, justified), Subject II (from theme bars 5-8), countersubject(s) with genuinely independent character (e.g. chromatic lament, suspension line, rhythmic motor), inversion(s), augmentation, any tune tweaks (justify each).
 B. PROOF: for every contrapuntal claim (S+CS invertibility at 8ve/10th/12th, answer+CS, inversion + CS, each planned stretto interval/distance, S1+S2 combination, augmentation against normal speed, the major apotheosis texture) keep a small lab .ly in proposal-${k}/lab/ and run the checker until clean. Record each final summary line.
 C. ARCHITECTURE: meter and tempo; total bars; duration arithmetic (must land 210-240 s); form table with bar numbers (exposition, counter-exposition, episodes, strettos, inversion, augmentation, combination, dominant pedal and climax, apotheosis/coda); tonal plan with the logic of each modulation; entry table (bar, voice, form, key, starting pitch); harmonic outline per section (bass or Roman numerals per half bar at least at entries, cadences, climax); dynamics arc (where the climax sits, subito effects); special harmonic events (diminished 7ths, Neapolitan, augmented 6th, deceptive cadences, pedal points, lament bass) placed where they matter.
 D. Write ${R}/design/proposal-${k}/DESIGN.md with all of the above (materials inline, proof table with lab file names and checker results, honest risks). Update and commit DESIGN.md incrementally as sections become solid, so partial progress survives an interruption.
Priorities if time runs short: materials + core proofs (S1/answer/CS, one stretto, S1+S2 combination, augmentation/cantus firmus against the subjects) and a complete form table beat exhaustive extras. Be ambitious about depth and beauty; be ruthless about verification. Design it; do not write the full piece.
Return the structured summary.`

const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    dir: { type: 'string' },
    title: { type: 'string' },
    pitch: { type: 'string', description: 'one-paragraph description of the concept' },
    meter_tempo: { type: 'string' },
    bars: { type: 'number' },
    duration_sec: { type: 'number' },
    devices: { type: 'array', items: { type: 'string' } },
    verified: { type: 'array', items: { type: 'object', properties: { claim: { type: 'string' }, lab_file: { type: 'string' }, checker: { type: 'string' } }, required: ['claim', 'lab_file', 'checker'] } },
    risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['dir', 'title', 'pitch', 'meter_tempo', 'bars', 'duration_sec', 'devices', 'verified', 'risks'],
}

const JUDGE_LENSES = [
  { key: 'rigor', text: 'CONTRAPUNTAL RIGOR: re-run the checker on the lab files yourself; check that claimed combinations really work (invertibility, strettos, combination, augmentation), that the answer is correct, that dissonance treatment is Bach-grade. Penalise unverified or false claims heavily.' },
  { key: 'beauty', text: 'BEAUTY AND DEPTH: judge as a great composer and listener. Would this be profound, "mathematically beautiful", emotionally deep, with a Beethoven-grade arc and an earned major apotheosis? Is the theme instantly recognisable and are the tune tweaks improvements? Sing the materials in your head (you may render lab MIDI with lilypond and inspect it, but do not play audio).' },
  { key: 'execution', text: 'EXECUTION AND CLARITY: can this be composed bar by bar within 210-240 s without collapsing? Is the plan concrete (bar numbers, keys, entries, harmonic outline)? Will it sound clear on piano and on string quartet? Are ranges and textures practical?' },
]

const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    scores: { type: 'array', items: { type: 'object', properties: { proposal: { type: 'number' }, score: { type: 'number', description: '1-10' }, rationale: { type: 'string' } }, required: ['proposal', 'score', 'rationale'] } },
    winner: { type: 'number' },
    graft_ideas: { type: 'array', items: { type: 'object', properties: { from: { type: 'number' }, idea: { type: 'string' } }, required: ['from', 'idea'] } },
    fatal_issues: { type: 'array', items: { type: 'object', properties: { proposal: { type: 'number' }, issue: { type: 'string' } }, required: ['proposal', 'issue'] } },
  },
  required: ['scores', 'winner', 'graft_ideas', 'fatal_issues'],
}

const BLUEPRINT_SCHEMA = {
  type: 'object',
  properties: {
    blueprint_path: { type: 'string' },
    title: { type: 'string' },
    meter_tempo: { type: 'string' },
    bars: { type: 'number' },
    duration_sec: { type: 'number' },
    sections: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, bars: { type: 'string' }, summary: { type: 'string' } }, required: ['id', 'bars', 'summary'] } },
    open_risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['blueprint_path', 'title', 'meter_tempo', 'bars', 'duration_sec', 'sections', 'open_risks'],
}

const CRITIC_SCHEMA = {
  type: 'object',
  properties: {
    major_issues: { type: 'array', items: { type: 'object', properties: { issue: { type: 'string' }, fix: { type: 'string' } }, required: ['issue', 'fix'] } },
    minor_issues: { type: 'array', items: { type: 'string' } },
    verdict: { type: 'string', enum: ['ready', 'needs-fixes'] },
  },
  required: ['major_issues', 'minor_issues', 'verdict'],
}

const CRITIC_LENSES = [
  { key: 'counterpoint', text: 'CONTRAPUNTAL AND STRUCTURAL: re-run the checker on everything in final-lab; hunt false contrapuntal claims, entries that cannot work in the stated keys/voices/ranges, duration arithmetic errors, boundary conditions between sections that cannot join, stretto/combination claims not actually proven at the stated pitch level, plans too vague to execute bar by bar.' },
  { key: 'musical', text: 'MUSICAL: as a great composer, hunt for a weak or unearned climax/apotheosis, sections with no real idea, monotony (same texture/key/rhythm too long), the theme not recognisable or distorted, the major ending sounding cheap or "happy" rather than transfigured, a harmonic plan without surprise, lines that will not sing on strings or lie badly on piano.' },
]

async function designFlow() {
  phase('Design')
  const proposals = await parallel(ANGLES.map((a, i) => () =>
    agent(DESIGN_TASK(i + 1, a), { label: `designer ${i + 1}`, phase: 'Design', schema: DESIGN_SCHEMA })))
  const ok = proposals.map((p, i) => p ? { ...p, k: i + 1 } : null).filter(Boolean)
  log(`${ok.length}/4 design proposals completed`)
  if (!ok.length) return { error: 'no proposals' }
  const summaries = ok.map(p => `Proposal ${p.k}: ${p.title} | ${p.meter_tempo} | ${p.bars} bars, ${p.duration_sec}s | dir ${p.dir}\n  ${p.pitch}\n  devices: ${p.devices.join('; ')}\n  verified: ${p.verified.length} claims; risks: ${p.risks.join('; ')}`).join('\n')

  phase('Judge')
  const judgments = await parallel(JUDGE_LENSES.map(l => () =>
    agent(`${CONTEXT}\nROLE: JUDGE (${l.key}). Evaluate ALL design proposals below by reading each DESIGN.md and its lab files under ${R}/design/proposal-K/. Lens: ${l.text}\nScore each 1-10 with a concrete rationale, pick a winner, list the best ideas worth grafting from the others, and any fatal issues. Do not modify files.\n\nPROPOSALS:\n${summaries}`,
      { label: `judge ${l.key}`, phase: 'Judge', schema: JUDGE_SCHEMA })))
  const js = judgments.map((j, i) => j ? { ...j, lens: JUDGE_LENSES[i].key } : null).filter(Boolean)
  const tally = {}
  js.forEach(j => j.scores.forEach(s => { tally[s.proposal] = (tally[s.proposal] || 0) + s.score }))
  const ranked = Object.entries(tally).sort((a, b) => b[1] - a[1])
  log(`Judge totals: ${ranked.map(([k, v]) => `#${k}=${v}`).join(', ')}`)
  const winner = ranked.length ? Number(ranked[0][0]) : ok[0].k
  const judgeText = js.map(j => `JUDGE ${j.lens}: winner #${j.winner}\n` +
    j.scores.map(s => `  #${s.proposal}: ${s.score} - ${s.rationale}`).join('\n') +
    `\n  grafts: ${j.graft_ideas.map(g => `[#${g.from}] ${g.idea}`).join(' | ')}\n  fatal: ${j.fatal_issues.map(f => `[#${f.proposal}] ${f.issue}`).join(' | ')}`).join('\n\n')

  phase('Synthesize')
  let bp = await agent(`${CONTEXT}\nROLE: SYNTHESIZER. Designers produced proposals (below) and judges scored them. Build the FINAL BLUEPRINT starting from the winning proposal #${winner}, grafting the best ideas from the others where they genuinely improve depth, beauty or rigor (never at the cost of verified correctness or the 210-240 s length).
Write ${R}/design/BLUEPRINT.md and put every material/combination snippet in ${R}/design/final-lab/ (re-verify each with the checker; record results). It must be executable by composers working section by section, IN PARALLEL, without seeing each other's work:
 - Materials: final Subject I, answer, Subject II (+ answer if used), all countersubjects, inversions, augmentation forms, tune tweaks, in LilyPond, with justifications. Also write them as a machine-readable file ${R}/design/final-lab/materials.ly (one \\absolute variable per material at its reference pitch).
 - Meter, tempo (with changes), total bars, duration arithmetic.
 - Form table with exact bar numbers, and for EACH SECTION a spec: bar range, entries (bar, voice, form, key, exact starting pitch), harmonic skeleton (bass or Roman numerals at least per half bar), what each non-subject voice does (which countersubject/motif), texture (active voices), dynamics and expressive marks, and BOUNDARY CONDITIONS: exact chord and each voice's exact pitch (or rest) on the first attack and on the last note of the section, so independently composed sections join without parallels or leaps.
 - A section list for composition: 7-10 sections of roughly 6-14 bars, each self-contained.
 - A performance sketch: tempo map, dynamics arc, where each subject entry must be brought out.
 - Proof table and open risks.
Commit when done.\n\nPROPOSALS:\n${summaries}\n\nJUDGEMENTS:\n${judgeText}`,
    { label: 'synthesizer', phase: 'Synthesize', schema: BLUEPRINT_SCHEMA })

  phase('Critique')
  const critLog = []
  for (let round = 1; round <= 2 && bp; round++) {
    const crits = (await parallel(CRITIC_LENSES.map(l => () =>
      agent(`${CONTEXT}\nROLE: ADVERSARIAL CRITIC (${l.key}, round ${round}). Read ${R}/design/BLUEPRINT.md and ${R}/design/final-lab/. Lens: ${l.text}\nDefault to reporting an issue if uncertain; give a concrete fix for each major issue. Do not modify files.`,
        { label: `critic ${l.key} r${round}`, phase: 'Critique', schema: CRITIC_SCHEMA })))).filter(Boolean)
    const major = crits.flatMap(c => c.major_issues)
    const minor = crits.flatMap(c => c.minor_issues)
    critLog.push({ round, major: major.length, minor: minor.length })
    log(`Critique round ${round}: ${major.length} major, ${minor.length} minor`)
    if (crits.length < CRITIC_LENSES.length) { critLog.push({ round, criticsFailed: CRITIC_LENSES.length - crits.length }); log(`Critique round ${round}: a critic failed; stopping without a verdict`); break }
    if (major.length === 0 && crits.every(c => c.verdict === 'ready')) break
    bp = await agent(`${CONTEXT}\nROLE: BLUEPRINT FIXER (round ${round}). Fix ${R}/design/BLUEPRINT.md and ${R}/design/final-lab/ to resolve these critic findings. Verify every fix with the checker, update the proof table, keep materials.ly in sync, commit. If you judge a finding wrong, say why in a "Critic responses" section of the blueprint instead of changing the music.\nMAJOR:\n${major.map((m, i) => `${i + 1}. ${m.issue}\n   suggested fix: ${m.fix}`).join('\n')}\nMINOR:\n${minor.map(m => `- ${m}`).join('\n')}`,
      { label: `fixer r${round}`, phase: 'Critique', schema: BLUEPRINT_SCHEMA }) || bp
  }
  return { winner, tally, critLog, blueprint: bp, proposals: ok.map(p => ({ k: p.k, title: p.title, bars: p.bars, duration: p.duration_sec, verified: p.verified.length })) }
}

// ---------------- SOUND ----------------
const SOUND_SCHEMA = {
  type: 'object',
  properties: {
    instrument: { type: 'string' },
    library: { type: 'string' },
    license: { type: 'string' },
    source_urls: { type: 'array', items: { type: 'string' } },
    renderer: { type: 'string' },
    render_script: { type: 'string' },
    usage: { type: 'string' },
    demo_files: { type: 'array', items: { type: 'string' } },
    dynamics: { type: 'string', description: 'how p/f and crescendo are achieved and the measured evidence' },
    quality_notes: { type: 'string' },
    problems: { type: 'array', items: { type: 'string' } },
  },
  required: ['instrument', 'library', 'license', 'source_urls', 'renderer', 'render_script', 'usage', 'demo_files', 'dynamics', 'quality_notes', 'problems'],
}

const QA_SCHEMA = {
  type: 'object',
  properties: {
    defects: { type: 'array', items: { type: 'object', properties: { severity: { type: 'string', enum: ['major', 'minor'] }, issue: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['severity', 'issue', 'evidence', 'fix'] } },
    verdict: { type: 'string', enum: ['ready', 'needs-fixes'] },
    measurements: { type: 'string' },
  },
  required: ['defects', 'verdict', 'measurements'],
}

const SOUND_COMMON = `
${GIT}
Samples live under ${LIB}/ (already downloaded: SalamanderGrandPiano, IowaMIS, VPO3, IR (impulse responses), tools (sfizz source + build), bin/sfizz_render (built)). The user authorised further downloads from reputable official sources only; record URLs and licences. fluidsynth, ffmpeg, lilypond are installed; Python has numpy, scipy, mido, soundfile, music21.
Renders: 48 kHz stereo, tasteful concert-hall convolution reverb, true-peak about -1 dBFS, WAV + 256 kb/s AAC .m4a (\`afconvert -f m4af -d aac -b 256000\`). NEVER play audio through the speakers.
INTEGRATION CONTRACT: the renderer takes the MIDI produced by ${R}/tools/perform.py (read its docstring and code: one track per voice named soprano/alto/tenor/bass with velocities and CC1/CC11/CC7 automation; --target piano|strings). The end-to-end chain must work: \`python3 ${R}/tools/perform.py SCORE.ly PLAN.json OUT.mid --target <t>\` then the renderer. If perform.py and the renderer disagree (track names, CC meaning, channels), fix the renderer side, or make a minimal backward-compatible fix in perform.py and say so. Demo input: the old fugue ${ROOT}/fugue.ly (voices soprano, alto, tenor, pedal or similar; inspect it) with a small plan JSON you write under your directory (pp opening, crescendo to f at the stretto, subject entries brought out).
Also prove with a dynamics test MIDI (same phrase at pp, mf, ff, plus a sustained crescendo/diminuendo) that dynamics change timbre and loudness, not just gain: measure RMS and spectral centroid per segment and report numbers.`

const PIANO_TASK = `ROLE: FINISH the concert-grand PIANO renderer at ${R}/audio/piano/. A previous agent built most of it and was cut off while writing the dynamics test generator: read render_piano.py, make_sfz.py, make_ir.py, piano_paths.py, analyse_dynamics.py, make_test_midi.py and out/*.json first. The docstring mentions setup_piano.sh: create it if missing (idempotent: fetch/verify samples, IR, build sfizz_render) so the setup is reproducible. Complete and verify the end-to-end chain, render the demo (old fugue via perform.py) and the dynamics test, and document usage.
${SOUND_COMMON}
Return the structured summary.`

const STRINGS_TASK = `ROLE: FINISH the STRING QUARTET renderer (violin I, violin II, viola, cello) at ${R}/audio/strings/. A previous agent was cut off mid-way: read render_quartet.py, iowa_build.py, iowa_common.py, iowa_analyze.py, hall.py, measure_dynamics.py, make_test_midi.py and out/ first. It had two candidate libraries in ${LIB}: University of Iowa MIS solo strings (IowaMIS, pp/mf/ff recordings) and Virtual Playing Orchestra 3 (VPO3, SFZ with solo-string performance patches). Evaluate both on the same dynamics test and a 4-voice excerpt, choose the better-sounding one that works reliably (or combine: e.g. Iowa for sustained tone, VPO3 for short notes), and explain why with measurements.
Requirements: sustained notes that can crescendo/diminuendo via CC1/CC11 (crossfade between dynamic layers, not just gain), smooth legato-ish connection for slow lines, clear short notes for fast figures, correct pitch (check tuning of every sample set; Iowa files are single notes that need trimming/normalising), no clicks at note boundaries, balanced quartet (the viola and second violin must not vanish). Optional cello-an-octave-lower bass doubling for tutti climaxes as a flag, off by default. Write setup_strings.sh (idempotent) for reproducibility.
${SOUND_COMMON}
Return the structured summary.`

const QA_TASK = (what, dir) => `ROLE: ADVERSARIAL AUDIO QA for the ${what} renderer in ${dir}. Try to break it. Do NOT modify its code; you may write scratch files under /tmp.
${SOUND_COMMON}
Check, with measurements (numpy/scipy on the rendered WAVs, mido on the MIDI):
 - end-to-end chain from perform.py MIDI works as documented; every note in the MIDI is audible at the right time (onset alignment within ~20 ms, no dropped or stuck notes, releases happen when keys lift);
 - pitch accuracy of every voice (sample tuning within ~5 cents; transpositions right);
 - dynamics: pp vs ff differ in loudness AND spectrum; crescendos are smooth (no steps or zipper noise); voicing a single voice is audible;
 - clicks/pops at note starts and ends, clipping, DC offset, noise floor, stereo sanity, reverb tail not cut, levels normalised;
 - balance between voices; fast 16th passages stay clear; low bass notes are not muddy;
 - documentation matches behaviour; setup script is idempotent.
Report every defect with evidence and a concrete fix. verdict=ready only if there are no major defects.`

async function soundLane(what, task, dir, label) {
  let res = await agent(task, { label: `${label} engine`, phase: 'Sound', schema: SOUND_SCHEMA })
  const qaLog = []
  for (let round = 1; round <= 2; round++) {
    const qa = await agent(QA_TASK(what, dir), { label: `${label} QA r${round}`, phase: 'Sound', schema: QA_SCHEMA })
    if (!qa) break
    const major = qa.defects.filter(d => d.severity === 'major')
    qaLog.push({ round, major: major.length, minor: qa.defects.length - major.length, verdict: qa.verdict })
    log(`${label} QA round ${round}: ${major.length} major, ${qa.defects.length - major.length} minor`)
    if (qa.verdict === 'ready' && major.length === 0 && round > 1) break
    if (qa.defects.length === 0) break
    res = await agent(`${task}\n\nFOLLOW-UP: an adversarial QA agent found these defects in your renderer. Fix them all (major first), re-render the demos, re-measure, commit.\n${qa.defects.map((d, i) => `${i + 1}. [${d.severity}] ${d.issue}\n   evidence: ${d.evidence}\n   suggested fix: ${d.fix}`).join('\n')}\nQA measurements: ${qa.measurements}`,
      { label: `${label} fix r${round}`, phase: 'Sound', schema: SOUND_SCHEMA }) || res
  }
  return { result: res, qaLog }
}

const [design, piano, strings] = await parallel([
  () => designFlow(),
  () => soundLane('concert-grand piano', PIANO_TASK, `${R}/audio/piano`, 'piano'),
  () => soundLane('string quartet', STRINGS_TASK, `${R}/audio/strings`, 'strings'),
])
return { design, piano, strings }
