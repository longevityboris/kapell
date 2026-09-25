export const meta = {
  name: 'ricercar-compose-and-render',
  description: 'Compose the ricercar section by section from BLUEPRINT.md with per-section review, join seams, whole-piece review panel, then engrave, perform and render on piano and string quartet',
  phases: [
    { title: 'Compose', detail: 'one composer per section, checker-clean, two reviewers, reviser' },
    { title: 'Join', detail: 'assemble, fix seams, whole-piece checker' },
    { title: 'Review', detail: 'whole-piece panel (rigor, arc, beauty, idiom), fixers per section, up to 2 rounds' },
    { title: 'Render', detail: 'four versions (Bach organ, Beethoven piano, symphonic, piano+quartet) plus bonus quartet, each with listening QA' },
    { title: 'Final', detail: 'completeness critic' },
  ],
}

// args: { sections: [{id, bars, summary}], meter: "...", measure: "1" }
const ROOT = '/Users/biobook/Music/llm-music/fugue-jp'
const R = ROOT + '/ricercar'
const SECS = args.sections
const MEASURE = args.measure || '1'

const GIT = `GIT: the repo ${ROOT} has no remote; never push. Other agents commit concurrently, so stage ONLY your own paths: \`git add <paths> && git commit -m "..." -- <paths>\`; on index.lock wait and retry. Commit after every verified step.`

const CONTEXT = `
PROJECT: ${R}. ${GIT}
We are composing "Ricercar on the Theme from Jurassic Park": a 4-voice double fugue in B-flat minor ending in a transfigured B-flat major apotheosis, 210-240 s, with the depth of Bach's Ricercar a 6 / Art of Fugue and the arc of late Beethoven. The user's standard: "a lot of reasoning, logic, layers, very high quality"; the previous attempt was judged shallow, "too happy", melody "off".
THE BLUEPRINT IS LAW: ${R}/design/BLUEPRINT.md, verified materials in ${R}/design/final-lab/ (materials.ly holds every subject/answer/countersubject/inversion/augmentation at reference pitch). Read the blueprint fully before writing a note. Meter/tempo: ${args.meter}.
Voices are \\absolute variables soprano, alto, tenor, bass (notes, rests, ties, bar checks only; Dutch accidentals; c' = middle C). Ranges (MIDI): soprano 60-84, alto 53-77, tenor 48-72, bass 36-62. Must be idiomatic on piano (upper staff S+A within an octave-plus reach, lower T+B) AND string quartet (vn1, vn2, va, vc).
TOOLS: checker \`python3 ${R}/tools/check.py FILE --voices soprano,alto,tenor,bass --measure ${MEASURE} [--bars A-B] [--grid] [--quiet]\` (0 PAR!, 0 BEAT, 0 DIS! required; justify every D4?/DIR by ear in a comment); harmony x-ray \`python3 ${R}/tools/harmony.py FILE --key ... --stats --measure ${MEASURE}\`; assembler \`cd ${R} && python3 tools/assemble.py --measure ${MEASURE}\` (reads score/sections/secNN*.ly, first line '% bars A-B').
QUALITY BAR, every bar: every voice is a real melody (no padding, no static held chord tones without purpose); dissonance prepared and resolved Bach-style; subjects enter exactly as the blueprint says at the stated pitch; harmonic rhythm alive; chromaticism and suspensions where the blueprint places them; each episode derives from subject cells.`

// listenable checkpoint for the user after each integration step
const PREVIEW = tag => `\nCHECKPOINT PREVIEW: after the piece is clean, render a listening preview so the user can check progress: \`cd ${R} && python3 tools/perform.py score/music-voices.ly design/final-lab/plan.json /tmp/${tag}_piano.mid --target piano && (cd audio/piano && python3 render_piano.py /tmp/${tag}_piano.mid -o ${R}/preview/${tag}_piano)\` and the same with --target strings through audio/strings/render_quartet.py to ${R}/preview/${tag}_quartet. Also engrave ${R}/preview/${tag}_score.pdf (piano layout). Report the three paths in your notes.`
const secFile = (i, s) => `${R}/score/sections/sec${String(i + 1).padStart(2, '0')}_${s.id.replace(/[^A-Za-z0-9]+/g, '_')}.ly`

const SEC_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' }, bars: { type: 'string' },
    checker_summary: { type: 'string' }, boundary_met: { type: 'boolean' },
    notes: { type: 'string', description: 'what you did, deviations from the blueprint and why' },
  },
  required: ['file', 'bars', 'checker_summary', 'boundary_met', 'notes'],
}
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    issues: { type: 'array', items: { type: 'object', properties: { severity: { type: 'string', enum: ['major', 'minor'] }, where: { type: 'string', description: 'file and bar:beat' }, issue: { type: 'string' }, fix: { type: 'string' } }, required: ['severity', 'where', 'issue', 'fix'] } },
    verdict: { type: 'string', enum: ['ready', 'needs-fixes'] },
  },
  required: ['issues', 'verdict'],
}
const fmtIssues = xs => xs.map((x, i) => `${i + 1}. [${x.severity}] ${x.where}: ${x.issue}\n   fix: ${x.fix}`).join('\n')

// ---------------- COMPOSE ----------------
phase('Compose')
const composed = await pipeline(SECS,
  (s, _o, i) => agent(`${CONTEXT}
ROLE: COMPOSER of section ${s.id} (bars ${s.bars}): ${s.summary}
Write ${secFile(i, s)} containing ONLY a first-line comment '% bars ${s.bars}' then the four voice variables covering exactly these bars, each as \`name = \\absolute {\` ... with the closing \`}\` alone at the START of a line (the assembler's regex needs it). Other sections are being written in parallel by other composers; you must not touch their files.
NEIGHBOURS: ${i > 0 ? `the previous section is ${SECS[i - 1].id} (bars ${SECS[i - 1].bars}): ${SECS[i - 1].summary}.` : 'this is the first section.'} ${i < SECS.length - 1 ? `The next section is ${SECS[i + 1].id} (bars ${SECS[i + 1].bars}): ${SECS[i + 1].summary}.` : 'This is the last section.'} Read the blueprint's boundary conditions on BOTH seams and compose toward them: your first attack must follow smoothly from the previous section's specified last notes (no parallels, no unprepared dissonance, no leap larger than the blueprint allows), and your last notes must lead smoothly into the next section's specified first attack. Honour the blueprint's spec and BOUNDARY CONDITIONS exactly. To test the seams, write a scratch file under /tmp that prepends the previous section's specified last chord and appends the next section's first chord, and run the checker on it. Use the verified materials verbatim at the blueprint's pitch levels (copy from final-lab/materials.ly and transpose exactly). Comment each subject entry and device inline (% S1 alto, B-flat minor; % CS2 inverted at the 10th ...).
Iterate with the checker until clean; also run the harmony x-ray and make sure harmonic events the blueprint places here actually sound. Commit the file. Return the summary.`,
    { label: `compose ${s.id}`, phase: 'Compose', schema: SEC_SCHEMA }),
  (res, s, i) => res && parallel([
    ['counterpoint', 'CONTRAPUNTAL RIGOR: run the checker; verify every entry is at the blueprint pitch and form (compare note by note with final-lab/materials.ly transposed), dissonance treatment, voice-leading, ranges, boundary conditions met exactly.'],
    ['music', 'MUSICAL QUALITY AND IDIOM: is every voice a singing line with its own shape? any padding, static or aimless bars, clumsy leaps, monotony? does the harmony do what the blueprint asks (surprise, suspensions, colour)? playable on piano (hand spans) and idiomatic on quartet?'],
  ].map(([k, lens]) => () => agent(`${CONTEXT}
ROLE: REVIEWER (${k}) of ${secFile(i, s)} (section ${s.id}, bars ${s.bars}; spec: ${s.summary}). Lens: ${lens}
Be demanding; report concrete, located issues with concrete fixes. Do not modify files.`,
    { label: `review ${k} ${s.id}`, phase: 'Compose', schema: REVIEW_SCHEMA }))).then(rs => ({ res, reviews: rs.filter(Boolean) })),
  (x, s, i) => {
    if (!x) return null
    const issues = x.reviews.flatMap(r => r.issues)
    if (!issues.length) return x.res
    return agent(`${CONTEXT}
ROLE: REVISER of ${secFile(i, s)} (section ${s.id}, bars ${s.bars}; spec: ${s.summary}). Resolve these review findings (major first) without breaking the boundary conditions; re-run the checker to clean; commit. If a finding is wrong, keep the music and explain in the notes.
${fmtIssues(issues)}`, { label: `revise ${s.id}`, phase: 'Compose', schema: SEC_SCHEMA }).then(r => r || x.res)
  })
const missing = SECS.filter((s, i) => !composed[i]).map(s => s.id)
if (missing.length) log(`WARNING: sections not composed: ${missing.join(', ')}`)

// ---------------- JOIN ----------------
phase('Join')
const JOIN_SCHEMA = {
  type: 'object',
  properties: { total_bars: { type: 'number' }, checker_summary: { type: 'string' }, seam_fixes: { type: 'array', items: { type: 'string' } }, remaining: { type: 'array', items: { type: 'string' } } },
  required: ['total_bars', 'checker_summary', 'seam_fixes', 'remaining'],
}
let join = await agent(`${CONTEXT}
ROLE: INTEGRATOR. ${missing.length ? `Sections ${missing.join(', ')} are MISSING: compose them first from the blueprint spec. ` : ''}Run the assembler (cd ${R} && python3 tools/assemble.py --measure ${MEASURE}), which writes score/music-voices.ly; fix any length/header errors. Run the checker on the assembled file for the whole piece and specifically across every seam (2 bars either side of each section boundary): fix parallels, bad leaps, unresolved dissonances, broken ties and unmet boundary conditions by editing the section files minimally near the seam. Re-assemble and re-check until the whole piece is clean. Also create ${R}/score/music-global.ly defining \\global (key, time, tempo marks per the blueprint), \\marks (rehearsal marks at section starts) and \\dynamicsLine (dynamics and hairpins per the blueprint's dynamic arc, as spacer rests with dynamics) so that ${R}/score/piano.ly and quartet.ly compile; compile both with lilypond (output into ${R}/score/out/) and fix errors. Commit.${PREVIEW('draft1_composed')}`,
  { label: 'integrator', phase: 'Join', schema: JOIN_SCHEMA })
log(`Joined: ${join ? join.total_bars + ' bars; ' + join.checker_summary : 'integrator failed'}`)

// ---------------- REVIEW ----------------
phase('Review')
const PANEL = [
  ['bach', 'LEARNED COUNTERPOINT (Bach): audit every device the blueprint promises (each entry, inversion, stretto, augmentation, combination, invertible counterpoint) against the actual notes; list any promised device missing or botched. Run the checker on the whole piece.'],
  ['arc', 'LARGE-SCALE ARC (Beethoven): tension curve, key plan, harmonic richness (run harmony.py --stats per section), climax placement and force, dominant preparation, subito effects, whether the major apotheosis is earned and transfigured rather than "happy". Point to the weakest 8 bars in the piece and say how to fix them.'],
  ['theme', 'THE THEME AND BEAUTY: is the Jurassic Park theme instantly recognisable at its main appearances (compare with THEME.md)? any place where the tune sounds "off" (wrong note, rhythm, accent)? do lines sing? is anything mechanical, aimless or monotonous?'],
  ['idiom', 'PERFORMANCE IDIOM: playable on piano (spans, hand distribution S+A / T+B, crossing), idiomatic on string quartet (ranges, string crossings, sustained lines, clarity of fast notes), texture clarity (can a listener hear each entry?).'],
]
for (let round = 1; round <= 2; round++) {
  const reviews = (await parallel(PANEL.map(([k, lens]) => () => agent(`${CONTEXT}
ROLE: WHOLE-PIECE REVIEWER (${k}, round ${round}). The assembled piece is ${R}/score/music-voices.ly (sources: ${R}/score/sections/). Lens: ${lens}
Every issue must name the SECTION FILE and bar:beat. Report only issues that matter for quality. Do not modify files.`,
    { label: `panel ${k} r${round}`, phase: 'Review', schema: REVIEW_SCHEMA })))).filter(Boolean)
  const issues = reviews.flatMap(r => r.issues)
  const major = issues.filter(x => x.severity === 'major')
  log(`Review round ${round}: ${major.length} major, ${issues.length - major.length} minor`)
  if (!major.length && reviews.every(r => r.verdict === 'ready')) break
  // group by section file; fixers own one file each so they can run in parallel
  const bySec = SECS.map((s, i) => ({ s, i, file: secFile(i, s), xs: issues.filter(x => x.where.includes(secFile(i, s).split('/').pop().replace('.ly', ''))) })).filter(g => g.xs.length)
  const unplaced = issues.filter(x => !bySec.some(g => g.xs.includes(x)))
  await parallel(bySec.map(g => () => agent(`${CONTEXT}
ROLE: SECTION FIXER (round ${round}) for ${g.file} (section ${g.s.id}, bars ${g.s.bars}). Resolve these whole-piece review findings, editing ONLY this file; keep the first and last beat of each voice unchanged unless a finding requires it (then note it). Checker-clean, commit.
${fmtIssues(g.xs)}`, { label: `fix ${g.s.id} r${round}`, phase: 'Review', schema: SEC_SCHEMA })))
  join = await agent(`${CONTEXT}
ROLE: INTEGRATOR (round ${round}). Section fixers just edited section files. Re-assemble, re-check the whole piece and every seam, fix seam problems minimally, recompile piano.ly and quartet.ly into ${R}/score/out/, commit.${PREVIEW('draft' + (round + 1) + '_review' + round)}${unplaced.length ? `\nAlso resolve these findings that were not tied to one section:\n${fmtIssues(unplaced)}` : ''}`,
    { label: `integrator r${round}`, phase: 'Review', schema: JOIN_SCHEMA }) || join
}

// ---------------- RENDER ----------------
// Four versions requested by the user (all from the same 4-voice score), plus the quartet as a bonus.
phase('Render')
const RENDER_SCHEMA = {
  type: 'object',
  properties: { version: { type: 'string' }, specs: { type: 'array', items: { type: 'string' } }, wav: { type: 'string' }, m4a: { type: 'string' }, duration_sec: { type: 'number' }, notes: { type: 'string' } },
  required: ['version', 'specs', 'wav', 'm4a', 'duration_sec', 'notes'],
}
const CHAIN = `ENGINES (read each one's docstring/README/CONTRACT.md first): piano ${R}/audio/piano/render_piano.py; string quartet ${R}/audio/strings/render_quartet.py; pipe organ ${R}/audio/organ/ (render_organ.py, registration plans); orchestra ${R}/audio/orchestra/ (render_orchestra.py); orchestration + ensemble mixing ${R}/tools/orchestrate.py and ${R}/tools/mix.py (spec format in ${R}/tools/ORCHESTRATION.md; demo specs for the skeleton in ${R}/orchestration/). Performance logic: ${R}/tools/perform.py.`
const VERSIONS = [
  { key: 'bach_organ', text: 'BACH: pipe organ. Write the performance plan and a REGISTRATION plan (terraced: registration changes at section joins, not hairpins; distinct manuals so the voices separate; pedal 16+8 for the bass, plenum with pedal reed for the climax and apotheosis; tempo a touch steadier, baroque articulation: slight detachment of repeated notes and leaps, legato stepwise lines).' },
  { key: 'beethoven_piano', text: 'BEETHOVEN: solo piano, performed like the fugue of Op. 110 which this design follows: wide dynamic arc, bring out every subject entry (roles), expressive rubato at the arioso, sudden pianos, the long crescendo into the climax, a glowing, broadening major apotheosis with light pedal only where the texture is chordal.' },
  { key: 'beethoven_quartet', text: 'BONUS: string quartet (Grosse Fuge / Op. 131 spirit): the same interpretation for vn1, vn2, va, vc; sustained swells on long notes, clear detache on fast notes.' },
  { key: 'symphonic', text: 'SYMPHONIC: orchestra. Write a real ORCHESTRATION spec (Webern Ricercar-style colour hand-offs at phrase joins in the fugue, strings as the backbone, woodwind choir in the lament/arioso, horns on pedal points, brass and timpani saved for the climax and the apotheosis, octave doublings only in tuttis so the counterpoint stays clear) and a performance plan; render through orchestrate.py + mix.py.' },
  { key: 'quintet', text: 'ENSEMBLE: piano + string quartet (Shostakovich Op. 57 fugue as a model): strings alone for the exposition and lament, piano entering for the inverted fugue, both together with doublings for the climax and the major apotheosis. Write the orchestration spec and performance plan; render through orchestrate.py + mix.py.' },
]
const renderVersion = async v => {
  let r = await agent(`${CONTEXT}
${CHAIN}
ROLE: PERFORMER/ORCHESTRATOR for the ${v.key} version. ${v.text}
Base everything on the final score ${R}/score/music-voices.ly (and the entry comments in ${R}/score/sections/), the blueprint's performance sketch, and "measure": "${MEASURE}". Write your specs under ${R}/performance/${v.key}/ (plan JSON, plus registration or orchestration spec as needed), render to ${R}/performance/${v.key}/ricercar_${v.key}.wav and .m4a, and copy the m4a to ${R}/preview/final_${v.key}.m4a. Check the duration is 210-250 s and that every note of the score is present in the render chain (for orchestrated versions, run the integrity check of orchestrate.py). Never play audio. Commit specs, not audio.`,
    { label: `render ${v.key}`, phase: 'Render', schema: RENDER_SCHEMA })
  for (let round = 1; round <= 2 && r; round++) {
    const qa = await agent(`${CONTEXT}
${CHAIN}
ROLE: LISTENING QA (${v.key}, round ${round}) for ${r.wav} (specs: ${r.specs.join(', ')}). ${v.text}
You cannot hear, so measure: loudness envelope vs the planned arc (is the climax the loudest point? are subito pianos audible? does the apotheosis bloom rather than just get louder?), per-part/voice balance (stems), whether subject entries stand out, clarity of the four lines in tuttis (masking by doublings), onset timing, tuning, clipping, clicks, stuck notes, duration. Check that the version's concept is realised (e.g. organ registration really terraced; orchestral colours as specified). Report defects with evidence and concrete fixes in the specs or render options. Do not modify files.`,
      { label: `listen ${v.key} r${round}`, phase: 'Render', schema: REVIEW_SCHEMA })
    if (!qa || !qa.issues.length || (qa.verdict === 'ready' && !qa.issues.some(x => x.severity === 'major'))) break
    r = await agent(`${CONTEXT}
${CHAIN}
ROLE: PERFORMER/ORCHESTRATOR (${v.key}) revision ${round}. Fix these listening-QA findings in your specs under ${R}/performance/${v.key}/ or render options, re-render to the same outputs (and ${R}/preview/final_${v.key}.m4a), commit specs.
${fmtIssues(qa.issues)}`, { label: `render ${v.key} r${round}`, phase: 'Render', schema: RENDER_SCHEMA }) || r
  }
  return r
}
const renders = await parallel(VERSIONS.map(v => () => renderVersion(v)))
// ---------------- FINAL ----------------
phase('Final')
const final = await agent(`${CONTEXT}
ROLE: COMPLETENESS CRITIC. Compare the finished work (score/music-voices.ly, score/out/*.pdf, performance/*/ specs and the five renders: Bach organ, Beethoven piano, bonus quartet, symphonic, piano+quartet) against BLUEPRINT.md and the user's request. What is missing or unverified: a device promised but absent, a section below the quality bar, a render defect, missing analysis notes? Also write ${R}/NOTES.md: a concise analytical guide for the listener (form table with bar numbers and timings in the piano render, a short paragraph on each of the four versions and what to listen for in it, each device and where to hear it, the tune tweaks and why), in plain English. Commit NOTES.md. Return the list of remaining gaps (empty if none).`,
  { label: 'completeness critic', phase: 'Final', schema: { type: 'object', properties: { gaps: { type: 'array', items: { type: 'string' } }, notes_path: { type: 'string' } }, required: ['gaps', 'notes_path'] } })
return { composed: composed.map((c, i) => c ? { sec: SECS[i].id, checker: c.checker_summary } : null), join, renders: renders.map((r, i) => r ? { version: VERSIONS[i].key, m4a: r.m4a, duration: r.duration_sec } : null), final }
