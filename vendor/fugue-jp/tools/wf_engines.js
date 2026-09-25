export const meta = {
  name: 'ricercar-four-versions-engines',
  description: 'Build the sound engines for four versions of the ricercar (Bach organ, Beethoven piano, symphonic orchestra, piano+quartet ensemble): organ and orchestra renderers, orchestration/mix tool, adversarial audio QA, then a four-version demo of the current skeleton',
  phases: [
    { title: 'Build', detail: 'organ engine, orchestra engine, orchestration + ensemble mix tool, in parallel' },
    { title: 'QA', detail: 'adversarial audio QA and fix loop per engine, up to 2 rounds' },
    { title: 'Demo', detail: 'render the current 62-bar skeleton in all four versions through the shared chain' },
  ],
}

const ROOT = '/Users/biobook/Music/llm-music/fugue-jp'
const R = ROOT + '/ricercar'
const LIB = '/Users/biobook/Music/SampleLibraries'

const COMMON = `
PROJECT: ${R} (git repo ${ROOT}, no remote: commit, never push). Other agents work concurrently in this repo: stage ONLY your own paths and commit with \`git add <paths> && git commit -m "..." -- <paths>\` (retry on index.lock). Commit after every verified step; a previous session lost work to a usage limit. Never commit audio or samples.
PIECE: a 4-voice double fugue ("ricercar") on the Jurassic Park theme, B-flat minor to B-flat major, 62 bars, about 227 s. Voices soprano, alto, tenor, bass (MIDI ranges S 60-84, A 53-77, T 48-72, B 36-62). The notes are being composed right now; for testing use the current verified skeleton ${R}/design/final-lab/SK_final.ly with its performance plan ${R}/design/final-lab/plan.json (read them; they may be updated while you work).
THE FOUR VERSIONS the user asked for, all from the same 4-voice score: (1) BACH: pipe organ (manuals + pedal, registration instead of dynamics); (2) BEETHOVEN: solo piano (already built: ${R}/audio/piano/render_piano.py), plus the string-quartet version as a bonus (already built: ${R}/audio/strings/render_quartet.py); (3) SYMPHONIC: orchestra; (4) ENSEMBLE: piano + string quartet together (a piano quintet, cf. Shostakovich Op. 57 II Fugue), with the scoring changing across the piece.
EXISTING CHAIN: \`python3 ${R}/tools/perform.py SCORE.ly PLAN.json OUT.mid --target piano|strings\` (read its docstring: tempo map, dynamics, roles that bring out subject entries, humanize) feeds the renderers. The piano and quartet renderers were just finished by other agents (one may still be applying final fixes): DO NOT modify anything in ${R}/audio/piano/, ${R}/audio/strings/ or ${R}/tools/perform.py; call or import them, and if you need a change there, report it in your "problems" instead.
SAMPLES: ${LIB}/ holds SalamanderGrandPiano, IowaMIS (solo strings built into SFZ under IowaMIS/quartet), VPO3 (Virtual Playing Orchestra 3: Strings, Woodwinds, Brass, Percussion, Keys=celesta only, plus bundled libs VSCO2-CE, SSO, NoBudgetOrch, Iowa, Mattias-Westlund...), IR (Detmold Konzerthaus hall IR used by piano and quartet, DetmoldSRIR, 3D-MARCo), bin/sfizz_render (built, float-output patch). The user authorised downloads from reputable official sources (project sites, GitHub releases, archive.org uploads by the authors, OpenAIR, freepats); record URLs and licences. DISK IS TIGHT (about 46 GB free): keep your total new downloads under 6 GB, delete archives after extracting, check \`df -h ~\` before any large download.
RENDER STANDARD: 48 kHz stereo 24-bit WAV + 256 kb/s AAC .m4a (\`afconvert -f m4af -d aac -b 256000\`), true peak about -1 dBTP, tasteful convolution reverb. NEVER play audio through the speakers. Prove quality with measurements (numpy/scipy/soundfile/mido are installed): pitch per note, onset alignment vs MIDI, no dropped/stuck notes, no clicks, dynamics changing timbre not just gain, balance.`

const ENGINE_SCHEMA = {
  type: 'object',
  properties: {
    engine: { type: 'string' },
    libraries: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, url: { type: 'string' }, license: { type: 'string' } }, required: ['name', 'url', 'license'] } },
    scripts: { type: 'array', items: { type: 'string' } },
    contract: { type: 'string', description: 'path of CONTRACT.md / usage doc' },
    demo_files: { type: 'array', items: { type: 'string' } },
    evidence: { type: 'string', description: 'measured quality evidence' },
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

const CONTRACT_NOTE = dir => `Within your FIRST steps, write ${dir}/CONTRACT.md (the exact MIDI input contract: track names, channels, which CCs/velocities/program changes/sidecar files mean what, time base, how a caller asks for each instrument/registration) and commit it, because the orchestration tool is being written in parallel against it. Keep it accurate as you go.`

const ORGAN_TASK = `${COMMON}
ROLE: build the BACH version's engine: a realistic sampled PIPE ORGAN renderer in ${R}/audio/organ/ (samples under ${LIB}/Organ/).
${CONTRACT_NOTE(`${R}/audio/organ`)}
Requirements:
 - A real pipe-organ sample set, freely licensed, with per-pipe samples including loops and release tails (the sound of a real baroque or baroque-style instrument; ideally a North German/Silbermann-type organ suited to Bach). Candidates to evaluate: free GrandOrgue sample sets (e.g. those published free by Lars Palo, Piteå/Burea/others, or free demo sets by reputable producers), VSCO/other SFZ organs, freepats. Convert what you choose into SFZ for sfizz_render (respect loop points and release samples; GrandOrgue ODF files map pipes to WAVs), or use another reliable headless renderer. Do not ship a bad organ: if nothing convincing can be made to work, say so and fall back to the best harpsichord you can make work.
 - At least two manuals and pedal: the four voices must be clearly distinguishable (e.g. soprano+alto on one manual, tenor on another, bass on pedal with 16' + 8'), and the caller chooses per-voice manual assignment.
 - REGISTRATION instead of dynamics: named registrations (e.g. "flute8", "principal8", "principal8+4", "plenum" with mixture, "pedal16+8", "pedal_plenum" with reed) switched at bar:beat positions from a sidecar JSON or MIDI events (document which); optionally a swell box (enclosed division) following CC11 for hairpins. Map perform.py's dynamic plan sensibly to terraced registration changes at section boundaries.
 - Wind and tuning realism: pipes in tune with each other (check), no loop clicks, natural attack chiff and release into the room.
 - Acoustic: a church/cathedral impulse response with a freely licensed source (e.g. OpenAIR), RT60 about 2.5-4 s, but keep counterpoint clear (report C80).
 - render_organ.py IN.mid [--registration REG.json] -o OUT (+ --stems DIR dry per division, --no-reverb, --lead-in), with a usage docstring; setup_organ.sh (idempotent, reproducible download + build).
 - Demo: render the skeleton (SK_final.ly via perform.py --target piano, whose tracks are named soprano/alto/tenor/bass) with a registration plan you write under ${R}/audio/organ/demo/ (quiet 8' flute exposition, principals building, plenum with pedal reed at the climax and the major apotheosis). Output ${R}/audio/organ/out/skeleton_organ.wav/.m4a.
Return the structured summary.`

const ORCH_TASK = `${COMMON}
ROLE: build the SYMPHONIC version's engine: an ORCHESTRA renderer in ${R}/audio/orchestra/ (extra samples, if any, under ${LIB}/Orchestra/).
${CONTRACT_NOTE(`${R}/audio/orchestra`)}
Requirements:
 - Roster (romantic symphony orchestra, Beethoven 9 / Brahms scale): flute, oboe, clarinet, bassoon (solo each, 2 players where the library allows), 4 horns (solo and a2), trumpet, trombone (tenor and bass), tuba, timpani (B-flat and F at least, rolls), string sections (violins I, violins II, violas, celli, double basses). Part IDs (track names) must be stable and documented, e.g. fl, ob, cl, bn, hn, tpt, tbn, btbn, tba, timp, vn1, vn2, va, vc, cb.
 - Choose the best free samples per instrument: VPO3 SFZ (its SEC/SOLO, PERF/sustain/staccato, mod-wheel dynamic crossfade patches), its bundled VSCO2-CE/SSO/NoBudgetOrch sources, Iowa MIS winds/brass (pp/mf/ff real recordings, download if worthwhile), or others. Evaluate on the same test phrase and justify by measurement and by the realism of attack/legato/dynamics.
 - Dynamics through CC1 (layer crossfade) + CC11 (expression), velocity for accents; sustained notes can swell; short notes for fast figures (detache/staccato by duration threshold); legato connection for slurred lines.
 - Orchestral seating and depth: per-instrument stereo placement (violins I left, celli/basses right-centre, winds centre behind strings, brass and timpani at the back) and distance via the hall (use the Detmold Konzerthaus IR already used by the piano and quartet, or the DetmoldSRIR set if it offers positions, so all versions share one hall); a tutti must stay clear.
 - Tuning at A=440 across all instruments (measure every sample set used; correct deviations).
 - render_orchestra.py IN.mid -o OUT (+ --stems DIR, --no-reverb, --lead-in), usage docstring, setup_orchestra.sh idempotent.
 - Demo: a short orchestral test of your own (each instrument alone pp/mf/ff, a tutti chord, a crescendo) and the skeleton with a simple orchestration you map yourself (strings carry the four voices, winds double at section changes, brass + timpani only in the climax and the apotheosis). Output ${R}/audio/orchestra/out/skeleton_orchestra.wav/.m4a.
Return the structured summary.`

const TOOL_TASK = `${COMMON}
ROLE: build the shared ORCHESTRATION + ENSEMBLE MIX tools, used by the SYMPHONIC and ENSEMBLE versions (and optionally the organ). Files you own: ${R}/tools/orchestrate.py, ${R}/tools/mix.py, ${R}/tools/ORCHESTRATION.md, ${R}/orchestration/ (spec files and demos). Nothing else.
1. ORCH spec format (JSON, documented in ORCHESTRATION.md): which instrument parts play which voice when, as a list of assignments {voice, part, at "bar:beat", until "bar:beat", octave (0, -12, +12), level (dB offset or dynamic override), articulation hints optional}. It must support: doubling a voice in several parts, octave doublings, hand-offs of one voice between parts (Webern-style colour changes at phrase joins), parts resting, sustaining the bass as a pedal note in a derived part (e.g. timpani roll or horn on a pedal point). No new pitches beyond the score's voices and their octave doublings (counterpoint integrity). Also carry per-group performance options (e.g. organ registration sidecar, piano pedal).
2. orchestrate.py SCORE.ly PLAN.json ORCH.json OUTDIR: builds ONE MIDI FILE PER RENDERER GROUP (piano, quartet, orchestra, organ), each in that renderer's native contract, all sharing the exact same tempo map and time zero, using perform.py's performance logic (import it; do not modify it) so dynamics, tempo, subject-entry roles and humanisation match. Contracts: piano and quartet are documented in their scripts' docstrings/READMEs in ${R}/audio/piano and ${R}/audio/strings; organ and orchestra contracts will appear as ${R}/audio/organ/CONTRACT.md and ${R}/audio/orchestra/CONTRACT.md while you work (other agents are building those engines now; poll for them, build and test the piano+quartet path first, then add organ and orchestra as their contracts and renderers land).
3. mix.py MANIFEST: renders each group with its renderer to DRY stems where available (or wet with a flag), aligns them sample-accurately (all renderers have lead-in options; verify alignment by cross-correlating a common click or known onsets), places each group in the same hall (Detmold Konzerthaus IR in ${LIB}/IR, the same one the piano and quartet use) with per-group position/width/wet level, balances, masters to -1 dBTP, writes WAV + m4a. Measure and report inter-group timing error (must be under 5 ms) and balance.
4. ENSEMBLE demo: write ${R}/orchestration/quintet_skeleton.json for the skeleton, following the Shostakovich-quintet arc: string quartet alone for the exposition and the lament, piano entering for the inverted fugue, piano and quartet together (with doublings) for the climax and the B-flat major apotheosis. Render ${R}/orchestration/out/skeleton_quintet.wav/.m4a. Verify every note of the orchestrated MIDI against the score (a checker: each part's notes are the assigned voice's notes, transposed only by the declared octave).
Usage docstrings in both scripts. Return the structured summary.`

const QA_TASK = (what, dir) => `${COMMON}
ROLE: ADVERSARIAL AUDIO QA for the ${what} in ${dir}. Try to break it. Do NOT modify its code; scratch files under /tmp only.
Check with measurements: the documented chain works end to end on the skeleton; every MIDI note is audible at the right time and pitch (onset within ~20 ms, tuning within ~5 cents, no dropped or stuck notes, releases when keys lift); dynamics/registration changes are audible in level AND spectrum and smooth where they should be; no clicks, loop artefacts, clipping, DC, cut reverb tails; balance and clarity of four contrapuntal voices (can each voice be followed? measure per-stem levels in the mix); licences recorded; docs match behaviour; setup script idempotent. For the mix tool additionally: sample-accurate alignment between groups, and the note-for-note integrity check of orchestrated parts against the score.
Report every defect with evidence and a concrete fix. verdict=ready only with no major defects.`

async function lane(label, task, what, dir) {
  let res = await agent(task, { label: `${label} build`, phase: 'Build', schema: ENGINE_SCHEMA })
  const qaLog = []
  for (let round = 1; round <= 2 && res; round++) {
    const qa = await agent(QA_TASK(what, dir), { label: `${label} QA r${round}`, phase: 'QA', schema: QA_SCHEMA })
    if (!qa) break
    const major = qa.defects.filter(d => d.severity === 'major').length
    qaLog.push({ round, major, minor: qa.defects.length - major, verdict: qa.verdict })
    log(`${label} QA r${round}: ${major} major, ${qa.defects.length - major} minor`)
    if (!qa.defects.length || (qa.verdict === 'ready' && major === 0)) break
    res = await agent(`${task}\n\nFOLLOW-UP (round ${round}): an adversarial QA agent found these defects. Fix them (major first), re-render the demos, re-measure, commit.\n${qa.defects.map((d, i) => `${i + 1}. [${d.severity}] ${d.issue}\n   evidence: ${d.evidence}\n   fix: ${d.fix}`).join('\n')}\nQA measurements: ${qa.measurements}`,
      { label: `${label} fix r${round}`, phase: 'QA', schema: ENGINE_SCHEMA }) || res
  }
  return { res, qaLog }
}

const [organ, orchestra, tool] = await parallel([
  () => lane('organ', ORGAN_TASK, 'pipe-organ renderer (Bach version)', `${R}/audio/organ`),
  () => lane('orchestra', ORCH_TASK, 'orchestra renderer (symphonic version)', `${R}/audio/orchestra`),
  () => lane('mix', TOOL_TASK, 'orchestration and ensemble mix tools (orchestrate.py, mix.py)', `${R}/tools and ${R}/orchestration`),
])

phase('Demo')
const demo = await agent(`${COMMON}
ROLE: FOUR-VERSION DEMO INTEGRATOR. The engines are built: organ (${R}/audio/organ), orchestra (${R}/audio/orchestra), orchestration + mix tools (${R}/tools/orchestrate.py, mix.py, ORCHESTRATION.md), piano and quartet renderers. Using ONLY the documented chain (orchestrate.py + mix.py, or perform.py + renderer for single-instrument versions), render the current skeleton (${R}/design/final-lab/SK_final.ly + plan.json) in all versions into ${R}/preview/:
 sound_bach_organ.m4a (organ, registration plan), sound_beethoven_piano.m4a (solo piano), sound_beethoven_quartet.m4a (string quartet), sound_symphonic.m4a (write ${R}/orchestration/symphonic_skeleton.json: a real orchestration with colour hand-offs, woodwind choirs in the lament, brass and timpani reserved for the climax and apotheosis, strings as the backbone), sound_quintet.m4a (piano + quartet, using orchestration/quintet_skeleton.json).
Fix small integration bugs in files you are allowed to touch (orchestration/, the demo specs); report anything else. Measure each render (duration, loudness, true peak, section-wise loudness curve) and list the timestamps of the main sections. Commit specs (not audio). Return a short report: paths, durations, measurements, remaining problems.`,
  { label: 'four-version demo', phase: 'Demo' })
return { organ, orchestra, tool, demo }
