export const meta = {
  name: 'ricercar-continue',
  description: 'Continue the ricercar after the session-limit crash: fix the blueprint from the round-1 critique and re-critique; compose, join and review the piece; in parallel build organ, orchestra and mix engines and finish strings QA; then render the four versions (Bach organ, Beethoven piano, symphonic, piano+quartet) plus the quartet',
  phases: [
    { title: 'Blueprint', detail: 'apply the 11 major + minor round-1 critic findings, then critique/fix up to 2 more rounds' },
    { title: 'Compose', detail: 'one composer per section from the verified starters, two reviewers, reviser' },
    { title: 'Join', detail: 'assemble, seams, whole-piece checks, listenable preview' },
    { title: 'Review', detail: 'whole-piece panel, section fixers, integrator + preview, up to 2 rounds' },
    { title: 'Engines', detail: 'organ (Bach), orchestra (symphonic), orchestration+mix tools, each with adversarial audio QA' },
    { title: 'Polish', detail: 'finish string-quartet QA round 2 and fix' },
    { title: 'Demo', detail: 'latest music in every version through the shared chain' },
    { title: 'Render', detail: 'final five renders with listening QA' },
    { title: 'Final', detail: 'completeness critic and listener notes' },
  ],
}

// args (all optional): { skip: ['blueprint','compose','review','engines','polish','demo','render','final'], sections: [...] }
const A_ = args || {}
const SKIP = new Set(A_.skip || [])
const ROOT = '/Users/biobook/Music/llm-music/fugue-jp'
const R = ROOT + '/ricercar'
const LIB = '/Users/biobook/Music/SampleLibraries'
const MEASURE = '1'

// ---- global concurrency limiter: the user allows at most 6 workers at once ----
const MAX = 6
let active = 0
const waiters = []
async function A(prompt, opts) {
  while (active >= MAX) await new Promise(r => waiters.push(r))
  active++
  try { return await agent(prompt, opts) } finally { active--; const w = waiters.shift(); if (w) w() }
}

const GIT = `GIT: the repo ${ROOT} has no remote; never push. Other agents commit concurrently: stage ONLY your own paths and commit with \`git add <paths> && git commit -m "<why>" -- <paths>\` (retry on index.lock). Commit after every verified step: runs of this project have twice been killed by usage limits and only committed work survived. If you find output from an interrupted earlier run of your task, verify it and continue from it instead of starting over.`

const CONTEXT = `
PROJECT: ${R}. ${GIT}
We are making "The Neighbour", a ricercar a 4 (double fugue) on John Williams's Theme from Jurassic Park: B-flat minor to a transfigured B-flat major apotheosis, 210-240 s, with the depth of Bach's Ricercar a 6 / Art of Fugue and the arc of late Beethoven (Op. 110 frame). The user's standard: "a lot of reasoning, logic, layers, very high quality"; the previous attempt was judged shallow, "too happy", melody "off".
THE BLUEPRINT IS LAW: ${R}/design/BLUEPRINT.md, verified materials and tools in ${R}/design/final-lab/ (materials.ly, SK_final.ly = verified skeleton of the whole piece, sections/ = verified per-section starters, splice_check.py, strict.py, suspensions.py, plan.json = performance plan). Read the blueprint fully before touching notes.
Voices are \\absolute variables soprano, alto, tenor, bass (notes, rests, ties, bar checks only; Dutch accidentals; c' = middle C; closing } of each variable alone at the start of a line). Ranges (MIDI): S 60-84, A 53-77, T 48-72, B 36-62. Idiomatic on piano (S+A upper staff, T+B lower) and on string quartet.
TOOLS: \`python3 ${R}/tools/check.py FILE --voices soprano,alto,tenor,bass --measure ${MEASURE} [--bars A-B] [--quiet]\`; \`python3 ${R}/design/final-lab/splice_check.py FILE\`; \`python3 ${R}/design/final-lab/strict.py FILE -v\`; \`python3 ${R}/tools/harmony.py FILE --key ... --stats\`; assembler \`cd ${R} && python3 tools/assemble.py --measure ${MEASURE}\` (reads score/sections/secNN*.ly, writes score/music-voices.ly); \`python3 ${R}/tools/perform.py SCORE PLAN OUT.mid --target piano|strings\`.`

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    issues: { type: 'array', items: { type: 'object', properties: { severity: { type: 'string', enum: ['major', 'minor'] }, where: { type: 'string', description: 'file and bar:beat' }, issue: { type: 'string' }, fix: { type: 'string' } }, required: ['severity', 'where', 'issue', 'fix'] } },
    verdict: { type: 'string', enum: ['ready', 'needs-fixes'] },
  },
  required: ['issues', 'verdict'],
}
const fmtIssues = xs => xs.map((x, i) => `${i + 1}. [${x.severity}] ${x.where}: ${x.issue}\n   fix: ${x.fix}`).join('\n')

// =====================================================================================
// BLUEPRINT
// =====================================================================================
const BLUEPRINT_SCHEMA = {
  type: 'object',
  properties: {
    blueprint_path: { type: 'string' },
    title: { type: 'string' },
    meter_tempo: { type: 'string' },
    bars: { type: 'number' },
    duration_sec: { type: 'number' },
    sections: { type: 'array', items: { type: 'object', properties: { id: { type: 'string', description: 'starter file stem, e.g. sec01_expo' }, bars: { type: 'string' }, summary: { type: 'string' } }, required: ['id', 'bars', 'summary'] } },
    open_risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['blueprint_path', 'title', 'meter_tempo', 'bars', 'duration_sec', 'sections', 'open_risks'],
}
const CRITIC_LENSES = [
  { key: 'counterpoint', text: 'CONTRAPUNTAL AND STRUCTURAL: re-run check.py, strict.py and splice_check.py on SK_final.ly, every lab and every starter; hunt false contrapuntal claims (devices the text promises that the notes do not contain), entries that cannot work at the stated pitch, duration arithmetic errors, boundary conditions that cannot join, starters out of sync with SK_final.ly, plans too vague to execute.' },
  { key: 'musical', text: 'MUSICAL: as a great composer, hunt for a weak or unearned climax or apotheosis, sections with no real idea, monotony of key, texture or rhythm, the theme not recognisable, the major ending sounding "happy" rather than transfigured, a harmonic plan without surprise, lines that will not sing on strings or lie badly on piano. Listen in your head through SK_final.ly bar by bar.' },
]
const DEFAULT_SECTIONS = [
  { id: 'sec01_expo', bars: '1-12', summary: 'Exposition entries 1-3' },
  { id: 'sec02_entry4_episode', bars: '13-19', summary: 'Entry 4 and Episode 1' },
  { id: 'sec03_stretto_liquidation', bars: '20-29', summary: 'Stretto, liquidation, Climax I' },
  { id: 'sec04_arioso', bars: '30-34', summary: 'Arioso dolente' },
  { id: 'sec05_inversa', bars: '35-41', summary: 'Fuga inversa' },
  { id: 'sec06_pedal_climax', bars: '42-50', summary: 'Pedal, combination, Climax II' },
  { id: 'sec07_apotheosis_coda', bars: '51-62', summary: 'Apotheosis and coda' },
]

async function blueprintFlow() {
  if (SKIP.has('blueprint')) return { skipped: true, sections: A_.sections || DEFAULT_SECTIONS }
  const FIX_RULES = `Everything must stay verified after your changes: SK_final.ly checker-clean (0 PAR!, 0 BEAT, 0 DIS!) and strict-clean (0 CLASH), every lab re-verified (proofs.txt), the starters in final-lab/sections/ regenerated to match SK_final.ly exactly (splice_check.py PASS on each), materials.ly in sync, plan.json re-measured (210-240 s; you may add bars). Update BLUEPRINT.md throughout (idea, form table, entry table, section list and specs with exact boundary tables, performance sketch, proof table, risks) and add or extend a "Critique responses" section mapping every finding to what changed (or why it was rejected, with musical reasons). Commit after each verified change.`
  // args.blueprintFrom === 'critique': the round-1 fix is already committed; start at the round-2 critique
  let bp = A_.blueprintFrom === 'critique' ? { sections: A_.sections || DEFAULT_SECTIONS } : await A(`${CONTEXT}
ROLE: BLUEPRINT FIXER (round 1). Two critics reviewed the blueprint and found 11 major and many minor problems; their full findings are in ${R}/design/critique_r1.json (read all of it). The previous fixer was killed by a usage limit before changing anything. Resolve every finding. Many are DESIGN-LEVEL (the apotheosis thin and static and entered by deflation; climax II not earned by thematic content; bars 1-29 never leaving B-flat minor; A minor, the concept's large-scale neighbour, never established as a key; climax I never sounding the E dim7 it claims; the combination of subjects only nominal; bar 20 a static first bar; episode instruction not executable; splice_check only warning on countersubject changes). Solve them musically, not cosmetically: you may restructure (e.g. a real A-minor region with cadence, a longer fuga inversa, a recomposed apotheosis with genuine counterpoint around the cantus firmus, a thematic climax II), within 210-240 s. Make splice_check.py FAIL (not WARN) on changed locked or countersubject notes.
${FIX_RULES}
Return the final blueprint summary (sections = starter file stems with bar ranges and a one-paragraph spec each).`,
    { label: 'blueprint fixer r1', phase: 'Blueprint', schema: BLUEPRINT_SCHEMA })
  const critLog = []
  for (let round = 2; round <= 3 && bp; round++) {
    const crits = (await parallel(CRITIC_LENSES.map(l => () => A(`${CONTEXT}
ROLE: ADVERSARIAL CRITIC (${l.key}, round ${round}). The blueprint was just revised to answer an earlier critique (${R}/design/critique_r1.json; see the blueprint's "Critique responses"). Verify each earlier finding is really resolved in the NOTES (not just the text), and find new problems. Lens: ${l.text}
Default to reporting an issue if uncertain; give a concrete fix for each major issue. Do not modify files.`,
      { label: `critic ${l.key} r${round}`, phase: 'Blueprint', schema: REVIEW_SCHEMA })))).filter(Boolean)
    if (crits.length < CRITIC_LENSES.length) { log(`Blueprint critique r${round}: a critic failed; continuing with the current blueprint`); critLog.push({ round, criticsFailed: true }); break }
    const issues = crits.flatMap(c => c.issues)
    const major = issues.filter(x => x.severity === 'major')
    critLog.push({ round, major: major.length, minor: issues.length - major.length })
    log(`Blueprint critique r${round}: ${major.length} major, ${issues.length - major.length} minor`)
    if (!major.length && crits.every(c => c.verdict === 'ready')) break
    bp = await A(`${CONTEXT}
ROLE: BLUEPRINT FIXER (round ${round}). Resolve these critic findings (major first); if a finding is wrong, answer it in "Critique responses" with reasons instead of changing the music.
${FIX_RULES}
FINDINGS:
${fmtIssues(issues)}`, { label: `blueprint fixer r${round}`, phase: 'Blueprint', schema: BLUEPRINT_SCHEMA }) || bp
  }
  return { bp, critLog, sections: (bp && bp.sections && bp.sections.length) ? bp.sections : DEFAULT_SECTIONS }
}

// =====================================================================================
// COMPOSE + JOIN + REVIEW
// =====================================================================================
const SEC_SCHEMA = {
  type: 'object',
  properties: { file: { type: 'string' }, bars: { type: 'string' }, splice_check: { type: 'string' }, suspensions: { type: 'number' }, notes: { type: 'string' } },
  required: ['file', 'bars', 'splice_check', 'suspensions', 'notes'],
}
const JOIN_SCHEMA = {
  type: 'object',
  properties: { total_bars: { type: 'number' }, duration_sec: { type: 'number' }, checker_summary: { type: 'string' }, previews: { type: 'array', items: { type: 'string' } }, seam_fixes: { type: 'array', items: { type: 'string' } }, remaining: { type: 'array', items: { type: 'string' } } },
  required: ['total_bars', 'duration_sec', 'checker_summary', 'previews', 'seam_fixes', 'remaining'],
}
const PREVIEW = tag => `\nCHECKPOINT PREVIEW for the user (they listen along): once the piece is clean, render \`cd ${R} && python3 tools/perform.py score/music-voices.ly design/final-lab/plan.json /tmp/${tag}_piano.mid --target piano && (cd audio/piano && python3 render_piano.py /tmp/${tag}_piano.mid -o ${R}/preview/${tag}_piano)\`, the same with --target strings through audio/strings/render_quartet.py to ${R}/preview/${tag}_quartet, and engrave ${R}/preview/${tag}_score.pdf (compile ${R}/score/piano.ly with -o). Return the three paths in previews.`

async function composeFlow(SECS) {
  const secFile = s => `${R}/score/sections/${s.id}.ly`
  let composed = SECS.map(() => null)
  if (!SKIP.has('compose')) {
    phase('Compose')
    composed = await pipeline(SECS,
      (s, _o, i) => A(`${CONTEXT}
ROLE: COMPOSER of section ${s.id} (bars ${s.bars}): ${s.summary}
Follow blueprint section 7 ("Global rules for composers") to the letter: start from the verified starter ${R}/design/final-lab/sections/${s.id}.ly and deliver ${secFile(s)} (same name, keep the '% bars' line). Never change locked spans; keep every boundary entry; enrich the free voices into real melodies (motives from the head neighbour, its mirror sigh, cell b, CS1's tetrachord, CS2's turns), add prepared suspensions (the whole piece needs at least 30), no chordal padding, keep the deliberately thin places thin, no dynamics in the voices. Other composers are writing the other sections in parallel; touch only your file.
NEIGHBOURS: ${i > 0 ? `previous ${SECS[i - 1].id} (bars ${SECS[i - 1].bars}): ${SECS[i - 1].summary}` : 'first section'}. ${i < SECS.length - 1 ? `Next ${SECS[i + 1].id} (bars ${SECS[i + 1].bars}): ${SECS[i + 1].summary}` : 'Last section.'}
Verify: splice_check.py must PASS (joins included); explain every new D4?/DIR/MEL/XREL in a comment at the top; every new ACC2 in strict.py must be a suspension, pedal licence or chord seventh; count suspensions with suspensions.py. Iterate until it passes and sings. Commit your file. Return the summary.`,
        { label: `compose ${s.id}`, phase: 'Compose', schema: SEC_SCHEMA }),
      (res, s) => res && parallel([
        ['counterpoint', 'CONTRAPUNTAL RIGOR: run splice_check.py and strict.py; verify locked spans and boundary entries are intact, dissonance treatment Bach-grade, suspensions properly prepared and resolved, ranges, spacing.'],
        ['music', 'MUSICAL QUALITY AND IDIOM: is every voice a singing line with its own shape and rhythm complementary to the others? any padding, aimless or static bars, clumsy leaps, monotony, parallel thirds/sixths for too long? does the section realise the blueprint\'s expressive intent? playable on piano (spans) and idiomatic on quartet?'],
      ].map(([k, lens]) => () => A(`${CONTEXT}
ROLE: REVIEWER (${k}) of ${secFile(s)} (section ${s.id}, bars ${s.bars}; spec: ${s.summary}). Lens: ${lens}
Be demanding; report concrete, located issues (${s.id} bar:beat) with concrete fixes. Do not modify files.`,
        { label: `review ${k} ${s.id}`, phase: 'Compose', schema: REVIEW_SCHEMA }))).then(rs => ({ res, reviews: rs.filter(Boolean) })),
      (x, s) => {
        if (!x) return null
        const issues = x.reviews.flatMap(r => r.issues)
        if (!issues.length) return x.res
        return A(`${CONTEXT}
ROLE: REVISER of ${secFile(s)} (section ${s.id}, bars ${s.bars}; spec: ${s.summary}). Resolve these review findings (major first) under the blueprint's section-7 rules; splice_check.py must PASS; commit. If a finding is wrong, keep the music and explain in notes.
${fmtIssues(issues)}`, { label: `revise ${s.id}`, phase: 'Compose', schema: SEC_SCHEMA }).then(r => r || x.res)
      })
    const missing = SECS.filter((s, i) => !composed[i]).map(s => s.id)
    if (missing.length) log(`WARNING: sections not composed: ${missing.join(', ')}`)
  }

  let join = null
  if (!SKIP.has('review')) {
    phase('Join')
    join = await A(`${CONTEXT}
ROLE: INTEGRATOR. Every section should now exist in ${R}/score/sections/ (if one is missing, copy its starter from design/final-lab/sections/ and enrich it under the section-7 rules). Assemble; run check.py and strict.py on score/music-voices.ly and splice_check.py on every section; fix seam problems minimally. Re-measure duration with perform.py (210-240 s). Create ${R}/score/music-global.ly defining \\global (key, time, tempo marks), \\marks (rehearsal marks at section starts) and \\dynamicsLine (dynamics and hairpins from design/final-lab/plan.json as spacer rests) so ${R}/score/piano.ly and quartet.ly compile; compile both into ${R}/score/out/. Commit.${PREVIEW('draft1_composed')}`,
      { label: 'integrator', phase: 'Join', schema: JOIN_SCHEMA })
    log(`Joined: ${join ? `${join.total_bars} bars, ${join.duration_sec} s; ${join.checker_summary}; previews ${join.previews.join(', ')}` : 'integrator failed'}`)

    phase('Review')
    const PANEL = [
      ['bach', 'LEARNED COUNTERPOINT (Bach): audit every device the blueprint promises (each entry, inversion, stretto, augmentation, combination, invertible counterpoint, the dim7 liquidation) against the actual notes; list any promised device missing or botched. Run check.py and strict.py on the whole piece.'],
      ['arc', 'LARGE-SCALE ARC (Beethoven): tension curve, key plan, harmonic richness (harmony.py --stats per section), climax placement and force, dominant preparation, subito effects, whether the B-flat major apotheosis is earned and transfigured rather than "happy". Name the weakest 8 bars and how to fix them.'],
      ['theme', 'THE THEME AND BEAUTY: is the Jurassic Park theme instantly recognisable at its main appearances (compare THEME.md)? any place it sounds "off" (wrong note, rhythm, accent)? do the lines sing? anything mechanical, aimless or monotonous?'],
      ['idiom', 'PERFORMANCE IDIOM: piano (spans, hand distribution, crossings), string quartet (ranges, sustained lines, clarity of fast notes), organ (manual/pedal split: can the bass be a pedal line?), orchestra (can each line be given a colour?), and textural clarity (can a listener hear each entry?).'],
    ]
    for (let round = 1; round <= 2; round++) {
      const reviews = (await parallel(PANEL.map(([k, lens]) => () => A(`${CONTEXT}
ROLE: WHOLE-PIECE REVIEWER (${k}, round ${round}). The assembled piece is ${R}/score/music-voices.ly (sources ${R}/score/sections/). Lens: ${lens}
Every issue's "where" must start with the SECTION FILE STEM (e.g. sec03_stretto_liquidation) then bar:beat. Report only issues that matter for quality. Do not modify files.`,
        { label: `panel ${k} r${round}`, phase: 'Review', schema: REVIEW_SCHEMA })))).filter(Boolean)
      const issues = reviews.flatMap(r => r.issues)
      const major = issues.filter(x => x.severity === 'major')
      log(`Review round ${round}: ${major.length} major, ${issues.length - major.length} minor`)
      if (!major.length && reviews.length === PANEL.length && reviews.every(r => r.verdict === 'ready')) break
      const groups = SECS.map(s => ({ s, xs: issues.filter(x => x.where.includes(s.id)) })).filter(g => g.xs.length)
      const unplaced = issues.filter(x => !groups.some(g => g.xs.includes(x)))
      await parallel(groups.map(g => () => A(`${CONTEXT}
ROLE: SECTION FIXER (round ${round}) for ${secFile(g.s)} (bars ${g.s.bars}). Resolve these whole-piece review findings editing ONLY this file, under the section-7 rules (boundaries and locks intact; splice_check.py PASS). Commit.
${fmtIssues(g.xs)}`, { label: `fix ${g.s.id} r${round}`, phase: 'Review', schema: SEC_SCHEMA })))
      join = await A(`${CONTEXT}
ROLE: INTEGRATOR (review round ${round}). Section fixers just edited section files. Re-assemble, re-check the whole piece (check.py, strict.py, splice_check.py per section), fix seams minimally, re-measure duration, recompile piano.ly and quartet.ly into ${R}/score/out/, commit.${unplaced.length ? `\nAlso resolve these findings not tied to one section:\n${fmtIssues(unplaced)}` : ''}${PREVIEW(`draft${round + 1}_review${round}`)}`,
        { label: `integrator r${round}`, phase: 'Review', schema: JOIN_SCHEMA }) || join
      if (join) log(`After review round ${round}: ${join.checker_summary}; previews ${join.previews.join(', ')}`)
    }
  }
  return { composed: composed.map((c, i) => c ? { sec: SECS[i].id, check: c.splice_check, susp: c.suspensions } : null), join }
}

// =====================================================================================
// ENGINES (organ, orchestra, mix tools) + POLISH (strings)
// =====================================================================================
const ENGINE_SCHEMA = {
  type: 'object',
  properties: {
    engine: { type: 'string' },
    libraries: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, url: { type: 'string' }, license: { type: 'string' } }, required: ['name', 'url', 'license'] } },
    scripts: { type: 'array', items: { type: 'string' } },
    contract: { type: 'string' },
    demo_files: { type: 'array', items: { type: 'string' } },
    evidence: { type: 'string' },
    problems: { type: 'array', items: { type: 'string' } },
  },
  required: ['engine', 'libraries', 'scripts', 'contract', 'demo_files', 'evidence', 'problems'],
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
const SOUND = `
PROJECT: ${R}. ${GIT} Never commit audio or samples.
THE FOUR VERSIONS the user asked for, all from the same 4-voice score (voices soprano, alto, tenor, bass; MIDI ranges S 60-84, A 53-77, T 48-72, B 36-62): (1) BACH: pipe organ (manuals + pedal, registration instead of dynamics); (2) BEETHOVEN: solo piano (built: ${R}/audio/piano/render_piano.py), plus the string quartet as a bonus (built: ${R}/audio/strings/render_quartet.py); (3) SYMPHONIC: orchestra; (4) ENSEMBLE: piano + string quartet together (cf. Shostakovich Op. 57 II Fugue), scoring changing across the piece.
TEST MUSIC: the verified skeleton ${R}/design/final-lab/SK_final.ly with ${R}/design/final-lab/plan.json (both may be revised while you work; the composed score will later appear as ${R}/score/music-voices.ly).
CHAIN: \`python3 ${R}/tools/perform.py SCORE.ly PLAN.json OUT.mid --target piano|strings\` (read its docstring) feeds the renderers. Do NOT modify ${R}/audio/piano/ or ${R}/tools/perform.py (finished; call or import them); report needed changes in "problems".
SAMPLES in ${LIB}/: SalamanderGrandPiano, IowaMIS (quartet SFZ in IowaMIS/quartet), VPO3 (Virtual Playing Orchestra 3: Strings, Woodwinds, Brass, Percussion, bundled VSCO2-CE, SSO, NoBudgetOrch, Iowa, Mattias-Westlund; no organ), IR (Detmold Konzerthaus hall IR used by piano and quartet, DetmoldSRIR, 3D-MARCo), bin/sfizz_render. Downloads allowed from reputable official sources (project sites, GitHub releases, archive.org uploads by authors, OpenAIR, freepats); record URLs and licences. DISK IS TIGHT (~46 GB free): under 6 GB of new downloads per engine, delete archives after extracting, check \`df -h ~\` first.
RENDER STANDARD: 48 kHz stereo 24-bit WAV + 256 kb/s AAC m4a (\`afconvert -f m4af -d aac -b 256000\`), true peak about -1 dBTP, convolution reverb. NEVER play audio through the speakers. Prove quality by measurement (numpy/scipy/soundfile/mido): pitch per note, onsets vs MIDI, no dropped/stuck notes, no clicks/loop artefacts, dynamics changing timbre not only gain, balance, four lines followable.`
const CONTRACT_NOTE = dir => `Within your FIRST steps write ${dir}/CONTRACT.md (exact MIDI input contract: track names, channels, CC/velocity/program-change meanings, sidecar files, time base, how a caller selects instruments or registrations) and commit it: the orchestration tool is being written in parallel against it.`
const ENGINE_TASKS = {
  organ: `${SOUND}
ROLE: build the BACH version's engine: a realistic sampled PIPE ORGAN renderer in ${R}/audio/organ/ (samples under ${LIB}/Organ/). ${CONTRACT_NOTE(`${R}/audio/organ`)}
 - A real, freely licensed pipe-organ sample set with per-pipe samples, loops and release tails, ideally a North German / Silbermann-type instrument suited to Bach (evaluate free GrandOrgue sample sets from reputable producers, SFZ organs, freepats). Convert to SFZ for sfizz_render respecting loops and releases (GrandOrgue ODF maps pipes to WAVs), or use another reliable headless renderer. If nothing convincing works, say so and fall back to the best harpsichord you can make work; do not ship a bad organ.
 - Two or more manuals plus pedal; the caller assigns voices to manuals (e.g. S+A on Hauptwerk, T on Positiv, B on pedal 16'+8') so the four lines separate.
 - REGISTRATION instead of dynamics: named registrations (flute8, principal8, principal8+4, plenum with mixture, pedal16+8, pedal plenum with reed) switched at bar:beat positions via a documented sidecar JSON or MIDI events; optional swell box via CC11. Pipes in tune with each other; no loop clicks; natural chiff and release.
 - A church/cathedral IR from a freely licensed source (e.g. OpenAIR), RT60 ~2.5-4 s, counterpoint still clear (report C80).
 - render_organ.py IN.mid [--registration REG.json] -o OUT (+ --stems DIR, --no-reverb, --lead-in), usage docstring; setup_organ.sh idempotent.
 - Demo: the skeleton via perform.py --target piano (tracks soprano/alto/tenor/bass) with a registration plan in ${R}/audio/organ/demo/ (quiet 8' exposition, principals building, plenum + pedal reed for the climax and apotheosis) -> ${R}/audio/organ/out/skeleton_organ.wav/.m4a.
Return the structured summary.`,
  orchestra: `${SOUND}
ROLE: build the SYMPHONIC version's engine: an ORCHESTRA renderer in ${R}/audio/orchestra/ (extra samples under ${LIB}/Orchestra/). ${CONTRACT_NOTE(`${R}/audio/orchestra`)}
 - Roster (romantic orchestra): flute, oboe, clarinet, bassoon, 4 horns (solo and a2), trumpet, tenor and bass trombone, tuba, timpani (at least B-flat and F, rolls), string sections vn1, vn2, va, vc, cb. Stable documented part IDs (fl, ob, cl, bn, hn, tpt, tbn, btbn, tba, timp, vn1, vn2, va, vc, cb).
 - Best free samples per instrument (VPO3 SOLO/SEC, PERF/sustain/staccato, mod-wheel crossfade patches; bundled VSCO2-CE/SSO/NoBudgetOrch; Iowa MIS winds/brass if worthwhile), chosen by measurement on the same test phrase.
 - Dynamics via CC1 layer crossfade + CC11 expression, velocity for accents; swells on long notes; short strokes for fast notes; legato for slurred lines.
 - Seating/depth: per-instrument stereo placement and distance, in the same Detmold Konzerthaus hall as piano and quartet (DetmoldSRIR positions if useful); tuttis stay clear. Tune everything to A=440 (measure every sample set).
 - render_orchestra.py IN.mid -o OUT (+ --stems, --no-reverb, --lead-in), usage docstring; setup_orchestra.sh idempotent.
 - Demo: per-instrument pp/mf/ff test, a tutti chord, a crescendo, and the skeleton with a simple mapping (strings carry the voices, winds double at section changes, brass + timpani only in the climax and apotheosis) -> ${R}/audio/orchestra/out/skeleton_orchestra.wav/.m4a.
Return the structured summary.`,
  mix: `${SOUND}
ROLE: build the shared ORCHESTRATION + ENSEMBLE MIX tools for the SYMPHONIC and ENSEMBLE versions (and optionally the organ). You own ONLY: ${R}/tools/orchestrate.py, ${R}/tools/mix.py, ${R}/tools/ORCHESTRATION.md, ${R}/orchestration/.
1. ORCH spec (JSON, documented in ORCHESTRATION.md): assignments {voice, part, at "bar:beat", until "bar:beat", octave 0/-12/+12, level, articulation hints}; supports doubling, octave doubling, Webern-style hand-offs, rests, a derived sustained pedal part (timpani roll or horn on a pedal point); no pitches beyond the score's voices and their octave doublings; per-group options (organ registration sidecar, piano pedal).
2. orchestrate.py SCORE.ly PLAN.json ORCH.json OUTDIR: one MIDI per renderer group (piano, quartet, orchestra, organ) in that renderer's native contract (piano/quartet docs in ${R}/audio/piano and ${R}/audio/strings; organ/orchestra contracts appear as ${R}/audio/organ/CONTRACT.md and ${R}/audio/orchestra/CONTRACT.md while you work: build and test piano+quartet first, add organ and orchestra as they land), all sharing one tempo map and time zero, reusing perform.py's logic by import. Include an integrity checker: every part's notes are exactly its assigned voice's notes, transposed only by the declared octave.
3. mix.py MANIFEST: render each group (dry stems where available), align sample-accurately (verify by cross-correlation; inter-group error < 5 ms), place groups in the same Detmold hall with position/width/wet per group, balance, master to -1 dBTP, WAV + m4a.
4. Demo: ${R}/orchestration/quintet_skeleton.json (quartet alone for exposition and lament, piano entering for the inverted fugue, both with doublings for the climax and apotheosis) -> ${R}/orchestration/out/skeleton_quintet.wav/.m4a.
Usage docstrings. Return the structured summary.`,
}
const ENGINE_WHAT = { organ: ['pipe-organ renderer (Bach version)', `${R}/audio/organ`], orchestra: ['orchestra renderer (symphonic version)', `${R}/audio/orchestra`], mix: ['orchestration and ensemble mix tools', `${R}/tools/orchestrate.py, mix.py and ${R}/orchestration`] }
const QA_TASK = (what, dir) => `${SOUND}
ROLE: ADVERSARIAL AUDIO QA for the ${what} in ${dir}. Try to break it. Do NOT modify its code; scratch files in /tmp only.
Measure: the documented chain works end to end on the skeleton; every MIDI note audible at the right time and pitch (onset ~20 ms, tuning ~5 cents, no dropped/stuck notes, releases); dynamics/registration changes audible in level AND spectrum and smooth where intended; no clicks, loop artefacts, clipping, DC, cut tails; balance and clarity of four lines (per-stem levels); licences recorded; docs match behaviour; setup idempotent. For the mix tool also: sample-accurate group alignment and the note-for-note integrity check.
Report every defect with evidence and a concrete fix. verdict=ready only with no major defects.`

async function engineLane(key) {
  const task = ENGINE_TASKS[key]
  const [what, dir] = ENGINE_WHAT[key]
  let res = await A(task, { label: `${key} build`, phase: 'Engines', schema: ENGINE_SCHEMA })
  const qaLog = []
  for (let round = 1; round <= 2 && res; round++) {
    const qa = await A(QA_TASK(what, dir), { label: `${key} QA r${round}`, phase: 'Engines', schema: QA_SCHEMA })
    if (!qa) break
    const major = qa.defects.filter(d => d.severity === 'major').length
    qaLog.push({ round, major, minor: qa.defects.length - major })
    log(`${key} QA r${round}: ${major} major, ${qa.defects.length - major} minor`)
    if (!qa.defects.length || (qa.verdict === 'ready' && !major)) break
    res = await A(`${task}\n\nFOLLOW-UP (round ${round}): adversarial QA found these defects. Fix them (major first), re-render demos, re-measure, commit.\n${qa.defects.map((d, i) => `${i + 1}. [${d.severity}] ${d.issue}\n   evidence: ${d.evidence}\n   fix: ${d.fix}`).join('\n')}\nQA measurements: ${qa.measurements}`,
      { label: `${key} fix r${round}`, phase: 'Engines', schema: ENGINE_SCHEMA }) || res
  }
  return { res, qaLog }
}

async function stringsPolish() {
  if (SKIP.has('polish')) return { skipped: true }
  const qa = await A(`${SOUND}
ROLE: ADVERSARIAL AUDIO QA round 2 for the STRING QUARTET renderer in ${R}/audio/strings/ (render_quartet.py, Iowa MIS SFZ). A previous round-2 QA agent was killed by a usage limit after committing much of its harness and results under ${R}/audio/strings/qa/round2/ (read them, rerun what is incomplete, do not redo finished measurements). Round-1 defects and the round-1 fixes are in the git log (git log -- ricercar/audio/strings). Verify the round-1 fixes held (notably: interference between recorded dynamic layers making held notes swell and fade 5-8 dB) and find what remains. Do NOT modify the renderer; you may commit your QA harness and results under qa/round2/.
Report every defect with evidence and a concrete fix. verdict=ready only with no major defects.`,
    { label: 'strings QA r2', phase: 'Polish', schema: QA_SCHEMA })
  if (!qa || !qa.defects.length) return { qa }
  const fix = await A(`${SOUND}
ROLE: fix the STRING QUARTET renderer in ${R}/audio/strings/ (you may modify it). Adversarial QA round 2 found these defects; fix them (major first), re-render the demos, re-measure with the QA harness in qa/round2/, update the README, commit.
${qa.defects.map((d, i) => `${i + 1}. [${d.severity}] ${d.issue}\n   evidence: ${d.evidence}\n   fix: ${d.fix}`).join('\n')}
QA measurements: ${qa.measurements}`, { label: 'strings fix r2', phase: 'Polish', schema: ENGINE_SCHEMA })
  return { qa: { verdict: qa.verdict, defects: qa.defects.length }, fix }
}

async function enginesFlow() {
  if (SKIP.has('engines')) return { skipped: true }
  const [organ, orchestra, mix] = await parallel(['organ', 'orchestra', 'mix'].map(k => () => engineLane(k)))
  let demo = null
  if (!SKIP.has('demo')) {
    demo = await A(`${SOUND}
ROLE: FOUR-VERSION DEMO INTEGRATOR. Engines: organ ${R}/audio/organ, orchestra ${R}/audio/orchestra, orchestration + mix ${R}/tools/orchestrate.py, mix.py, ORCHESTRATION.md, plus piano and quartet. Use the most advanced music available: ${R}/score/music-voices.ly if it exists and check.py reports 0 errors/0 PAR!/0 DIS! on it, else the skeleton ${R}/design/final-lab/SK_final.ly; plan ${R}/design/final-lab/plan.json. Using ONLY the documented chains, render into ${R}/preview/: sound_bach_organ.m4a (registration plan), sound_beethoven_piano.m4a, sound_beethoven_quartet.m4a, sound_symphonic.m4a (write ${R}/orchestration/symphonic_demo.json: colour hand-offs, woodwind choir in the lament, brass and timpani reserved for climax and apotheosis, strings as backbone), sound_quintet.m4a (${R}/orchestration/quintet_demo.json). Fix small integration bugs in files you may touch (orchestration/ specs); report the rest. Measure each render (duration, loudness, true peak, section-wise loudness curve) and list section timestamps. Commit specs. Return a short report: which music was used, paths, durations, measurements, remaining problems.`,
      { label: 'four-version demo', phase: 'Demo' })
    log(`Demo: ${demo ? demo.slice(0, 300) : 'failed'}`)
  }
  return { organ, orchestra, mix, demo }
}

// =====================================================================================
// RUN: blueprint -> compose/review  ||  engines -> demo  ||  strings polish ; then render
// =====================================================================================
const [music, engines, polish] = await parallel([
  async () => { phase('Blueprint'); const b = await blueprintFlow(); const c = await composeFlow(b.sections); return { blueprint: { critLog: b.critLog, bars: b.bp && b.bp.bars, duration: b.bp && b.bp.duration_sec, sections: b.sections.map(s => `${s.id} ${s.bars}`) }, ...c } },
  () => enginesFlow(),
  () => stringsPolish(),
])

// ---------------- RENDER ----------------
const RENDER_SCHEMA = {
  type: 'object',
  properties: { version: { type: 'string' }, specs: { type: 'array', items: { type: 'string' } }, wav: { type: 'string' }, m4a: { type: 'string' }, duration_sec: { type: 'number' }, notes: { type: 'string' } },
  required: ['version', 'specs', 'wav', 'm4a', 'duration_sec', 'notes'],
}
const CHAIN = `ENGINES (read each one's docstring/README/CONTRACT.md first): piano ${R}/audio/piano/render_piano.py; string quartet ${R}/audio/strings/render_quartet.py; pipe organ ${R}/audio/organ/; orchestra ${R}/audio/orchestra/; orchestration + ensemble mixing ${R}/tools/orchestrate.py, ${R}/tools/mix.py (spec format ${R}/tools/ORCHESTRATION.md; demo specs in ${R}/orchestration/). Performance logic ${R}/tools/perform.py.`
const VERSIONS = [
  { key: 'bach_organ', text: 'BACH: pipe organ. Performance plan + REGISTRATION plan (terraced changes at section joins, not hairpins; distinct manuals so the voices separate; pedal 16+8 for the bass, plenum with pedal reed for the climax and apotheosis; steadier tempo; baroque articulation: slight detachment of repeated notes and leaps, legato stepwise lines).' },
  { key: 'beethoven_piano', text: 'BEETHOVEN: solo piano, played like the fugue of Op. 110 which this design follows: wide dynamic arc, every subject entry brought out (roles), rubato in the arioso, subito pianos, long crescendo into the climax, a glowing, broadening major apotheosis with light pedal only where chordal.' },
  { key: 'beethoven_quartet', text: 'BONUS: string quartet (Grosse Fuge / Op. 131 spirit): the same interpretation for vn1, vn2, va, vc; swells on long notes, clear detache on fast notes.' },
  { key: 'symphonic', text: 'SYMPHONIC: orchestra. A real ORCHESTRATION spec (Webern Ricercar-style colour hand-offs at phrase joins, strings as backbone, woodwind choir in the lament/arioso, horns on pedal points, brass and timpani saved for the climax and apotheosis, octave doublings only in tuttis) and a performance plan; orchestrate.py + mix.py.' },
  { key: 'quintet', text: 'ENSEMBLE: piano + string quartet (Shostakovich Op. 57 fugue as model): strings alone for the exposition and lament, piano entering for the inverted fugue, both with doublings for the climax and the major apotheosis; orchestrate.py + mix.py.' },
]
async function renderVersion(v) {
  let r = await A(`${CONTEXT}
${CHAIN}
ROLE: PERFORMER/ORCHESTRATOR for the ${v.key} version. ${v.text}
Base everything on the final score ${R}/score/music-voices.ly (entry comments in ${R}/score/sections/), the blueprint's performance sketch and design/final-lab/plan.json ("measure": "${MEASURE}"). Write specs under ${R}/performance/${v.key}/, render to ${R}/performance/${v.key}/ricercar_${v.key}.wav/.m4a and copy the m4a to ${R}/preview/final_${v.key}.m4a. Duration 210-250 s; every score note present (for orchestrated versions run orchestrate.py's integrity check). Never play audio. Commit specs, not audio.`,
    { label: `render ${v.key}`, phase: 'Render', schema: RENDER_SCHEMA })
  for (let round = 1; round <= 2 && r; round++) {
    const qa = await A(`${CONTEXT}
${CHAIN}
ROLE: LISTENING QA (${v.key}, round ${round}) for ${r.wav} (specs ${r.specs.join(', ')}). ${v.text}
You cannot hear, so measure: loudness envelope vs the planned arc (climax loudest? subito pianos audible? apotheosis blooming?), per-part balance (stems), subject entries standing out, clarity of the four lines in tuttis, onset timing, tuning, clipping, clicks, stuck notes, duration; and whether the version's concept is realised. Report defects with evidence and concrete fixes in specs or render options. Do not modify files.`,
      { label: `listen ${v.key} r${round}`, phase: 'Render', schema: REVIEW_SCHEMA })
    if (!qa || !qa.issues.length || (qa.verdict === 'ready' && !qa.issues.some(x => x.severity === 'major'))) break
    r = await A(`${CONTEXT}
${CHAIN}
ROLE: PERFORMER/ORCHESTRATOR (${v.key}) revision ${round}. Fix these listening-QA findings in ${R}/performance/${v.key}/ specs or render options, re-render to the same outputs and ${R}/preview/final_${v.key}.m4a, commit specs.
${fmtIssues(qa.issues)}`, { label: `render ${v.key} r${round}`, phase: 'Render', schema: RENDER_SCHEMA }) || r
  }
  return r
}
let renders = []
if (!SKIP.has('render')) {
  phase('Render')
  renders = await parallel(VERSIONS.map(v => () => renderVersion(v)))
}

let final = null
if (!SKIP.has('final')) {
  phase('Final')
  final = await A(`${CONTEXT}
ROLE: COMPLETENESS CRITIC. Compare the finished work (score/music-voices.ly, score/out/*.pdf, performance/*/ specs, the five renders in preview/final_*.m4a) against BLUEPRINT.md and the user's request (four versions: Bach organ, Beethoven piano, symphonic, piano+quartet; plus the quartet). List what is missing or unverified. Write ${R}/NOTES.md: a plain-English listener's guide (form table with bar numbers and timings in the piano render; a paragraph per version on what to listen for; each device and where to hear it; the tune tweaks and why). Commit NOTES.md.`,
    { label: 'completeness critic', phase: 'Final', schema: { type: 'object', properties: { gaps: { type: 'array', items: { type: 'string' } }, notes_path: { type: 'string' } }, required: ['gaps', 'notes_path'] } })
}
return { music, engines, polish, renders: renders.map((r, i) => r ? { version: VERSIONS[i].key, m4a: r.m4a, duration: r.duration_sec } : null), final }
