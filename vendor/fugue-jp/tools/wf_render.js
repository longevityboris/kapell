export const meta = {
  name: 'ricercar-final-renders',
  description: 'Final renders of the finished ricercar in all versions (Bach organ, Beethoven piano, bonus quartet, symphonic, piano+quartet), one listening-QA and revision round each, then the listener notes and README update',
  phases: [
    { title: 'Render', detail: 'performer/orchestrator per version, listening QA, one revision' },
    { title: 'Final', detail: 'completeness check, NOTES.md, README' },
  ],
}

const ROOT = '/Users/biobook/Music/llm-music/fugue-jp'
const R = ROOT + '/ricercar'
const MAX = 5  // one engine-QA agent is still running; stay within the user's 6-worker limit
let active = 0
const waiters = []
async function A(prompt, opts) {
  while (active >= MAX) await new Promise(r => waiters.push(r))
  active++
  try { return await agent(prompt, opts) } finally { active--; const w = waiters.shift(); if (w) w() }
}

const CONTEXT = `
PROJECT: ${R} (git repo ${ROOT}; a background job pushes to GitHub, you only commit). Stage only your own paths: \`git add <paths> && git commit -m "<why>" -- <paths>\` (retry on index.lock). Commit after every verified step. Never commit audio. NEVER play audio through the speakers.
THE PIECE is finished: "The Neighbour", a ricercar a 4 on John Williams's Theme from Jurassic Park, B-flat minor to a transfigured B-flat major, 66 bars, about 232 s. Score: ${R}/score/music-voices.ly (assembled from ${R}/score/sections/, whose comments mark every subject entry and device); design and performance sketch: ${R}/design/BLUEPRINT.md; performance plan: ${R}/design/final-lab/plan.json ("measure": "1"); printed scores in ${R}/score/out/. Do not change the notes.
ENGINES (read each one's README/CONTRACT.md/docstring first): piano ${R}/audio/piano/render_piano.py; string quartet ${R}/audio/strings/render_quartet.py; pipe organ ${R}/audio/organ/render_organ.py; orchestra ${R}/audio/orchestra/render_orchestra.py; ensembles ${R}/tools/orchestrate.py + ${R}/tools/mix.py (spec format ${R}/tools/ORCHESTRATION.md, example specs in ${R}/orchestration/). Performance logic ${R}/tools/perform.py.
KNOWN CAVEATS: (1) orchestrate.py's compass check stops a render when a part goes outside its instrument's range. In the final score the alto goes below violin II's G3 at 9:4 (F3), 12:1 (F#3) and 12:4 (F3); give those notes to the viola (hand-off) or reassign that voice in those bars. (2) Disk is nearly full: keep only final WAV/m4a files and delete your own scratch renders and stems when done. (3) The orchestra engine's QA may still be finishing; if its renderer changes under you, re-run your render.`

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    issues: { type: 'array', items: { type: 'object', properties: { severity: { type: 'string', enum: ['major', 'minor'] }, where: { type: 'string' }, issue: { type: 'string' }, fix: { type: 'string' } }, required: ['severity', 'where', 'issue', 'fix'] } },
    verdict: { type: 'string', enum: ['ready', 'needs-fixes'] },
  },
  required: ['issues', 'verdict'],
}
const RENDER_SCHEMA = {
  type: 'object',
  properties: { version: { type: 'string' }, specs: { type: 'array', items: { type: 'string' } }, wav: { type: 'string' }, m4a: { type: 'string' }, duration_sec: { type: 'number' }, timestamps: { type: 'string', description: 'mm:ss of each section start in this render' }, notes: { type: 'string' } },
  required: ['version', 'specs', 'wav', 'm4a', 'duration_sec', 'timestamps', 'notes'],
}
const fmt = xs => xs.map((x, i) => `${i + 1}. [${x.severity}] ${x.where}: ${x.issue}\n   fix: ${x.fix}`).join('\n')

const VERSIONS = [
  { key: 'bach_organ', text: 'BACH: pipe organ. Performance plan + REGISTRATION plan: terraced changes at section joins (not hairpins), distinct manuals so the four voices separate, pedal 16+8 for the bass, plenum with pedal reed for the climaxes and the apotheosis; steadier tempo; baroque articulation (slight detachment of repeated notes and leaps, legato stepwise lines).' },
  { key: 'beethoven_piano', text: 'BEETHOVEN: solo piano, played like the fugue of Op. 110 which this design follows: wide dynamic arc, every subject entry brought out, rubato in the arioso, subito pianos, long crescendo into Climax II, a glowing, broadening major apotheosis with light pedal only where chordal.' },
  { key: 'beethoven_quartet', text: 'BONUS: string quartet (Grosse Fuge / Op. 131 spirit): the same interpretation for vn1, vn2, va, vc; swells on long notes, clear detache on fast notes.' },
  { key: 'symphonic', text: 'SYMPHONIC: orchestra. A real ORCHESTRATION spec: Webern Ricercar-style colour hand-offs at phrase joins, strings as the backbone, woodwind choir in the arioso, horns on pedal points, brass and timpani saved for the climaxes and the apotheosis, octave doublings only in tuttis so the counterpoint stays clear; through orchestrate.py + mix.py.' },
  { key: 'quintet', text: 'ENSEMBLE: piano + string quartet (Shostakovich Op. 57 fugue as model): strings alone for the exposition and the arioso, piano entering for the fuga inversa, both with doublings for the climaxes and the major apotheosis; through orchestrate.py + mix.py.' },
]

async function renderVersion(v) {
  let r = await A(`${CONTEXT}
ROLE: PERFORMER/ORCHESTRATOR for the ${v.key} version. ${v.text}
Write your specs under ${R}/performance/${v.key}/, render to ${R}/performance/${v.key}/ricercar_${v.key}.wav/.m4a and copy the m4a to ${R}/preview/final_${v.key}.m4a. Duration 215-250 s; every score note present (orchestrated versions: orchestrate.py's integrity check must pass). Report section timestamps. Commit specs.`,
    { label: `render ${v.key}`, phase: 'Render', schema: RENDER_SCHEMA })
  if (!r) return null
  const qa = await A(`${CONTEXT}
ROLE: LISTENING QA for the ${v.key} version: ${r.wav} (specs ${r.specs.join(', ')}). ${v.text}
You cannot hear, so measure: loudness envelope vs the planned arc (are the climaxes the loudest points, do subito pianos register, does the apotheosis bloom?), per-part balance from stems, subject entries standing out, clarity of the four lines in tuttis, onsets, tuning, clipping, clicks, stuck notes, duration; and whether the version's concept is realised. Major = audible and worth a re-render. Do not modify files.`,
    { label: `listen ${v.key}`, phase: 'Render', schema: REVIEW_SCHEMA })
  if (!qa || !qa.issues.some(x => x.severity === 'major')) return r
  return (await A(`${CONTEXT}
ROLE: PERFORMER/ORCHESTRATOR (${v.key}) revision. Fix these listening-QA findings in ${R}/performance/${v.key}/ or render options, re-render to the same outputs and ${R}/preview/final_${v.key}.m4a, commit specs.
${fmt(qa.issues)}`, { label: `revise ${v.key}`, phase: 'Render', schema: RENDER_SCHEMA })) || r
}

phase('Render')
const renders = await parallel(VERSIONS.map(v => () => renderVersion(v)))
log(`Renders: ${renders.map((r, i) => r ? `${VERSIONS[i].key} ${Math.round(r.duration_sec)} s` : `${VERSIONS[i].key} FAILED`).join(', ')}`)

phase('Final')
const final = await A(`${CONTEXT}
ROLE: FINISHER. The renders are done: ${renders.map((r, i) => r ? `${VERSIONS[i].key}: ${r.m4a} (${r.duration_sec} s; ${r.timestamps})` : `${VERSIONS[i].key}: failed`).join(' | ')}.
1. Write ${R}/NOTES.md: a plain-English listener's guide to "The Neighbour": the idea (the theme's lower neighbour at five scales), a form table with bar numbers and timings (piano render), what to listen for in each version, each learned device and where to hear it (bar numbers), the tune tweaks and why. Concise, no filler.
2. Update ${ROOT}/README.md: the ricercar is finished (update the status table, its length and bar count, the four versions table), link NOTES.md and the printed scores in ricercar/score/out/, keep the existing style and badges; say that audio renders are produced locally by the render scripts (they are not in the repo).
3. List anything the user asked for that is missing or unverified.
Commit NOTES.md and README.md.`,
  { label: 'finisher', phase: 'Final', schema: { type: 'object', properties: { gaps: { type: 'array', items: { type: 'string' } }, notes_path: { type: 'string' } }, required: ['gaps', 'notes_path'] } })
return { renders: renders.map((r, i) => r ? { version: VERSIONS[i].key, m4a: r.m4a, duration: r.duration_sec, timestamps: r.timestamps } : null), final }
