export const meta = {
  name: 'ricercar-engines-finish',
  description: 'Finish and verify the sound engines while the score is reviewed: organ and orchestra (finish, adversarial QA, fix), mix tool (QA, fix), strings (complete the round-2 fix). Max 2 agents at once alongside the compose run.',
  phases: [
    { title: 'Finish', detail: 'each engine finished and self-verified from its committed state' },
    { title: 'QA', detail: 'one adversarial QA round per engine, fix only if major defects' },
  ],
}

const ROOT = '/Users/biobook/Music/llm-music/fugue-jp'
const R = ROOT + '/ricercar'
const LIB = '/Users/biobook/Music/SampleLibraries'

// at most 2 agents at once: the compose/review run uses the rest of the user's 6-worker budget
const MAX = 2
let active = 0
const waiters = []
async function A(prompt, opts) {
  while (active >= MAX) await new Promise(r => waiters.push(r))
  active++
  try { return await agent(prompt, opts) } finally { active--; const w = waiters.shift(); if (w) w() }
}

const COMMON = `
PROJECT: ${R} (git repo ${ROOT}; a background job pushes to GitHub, you only commit). Other agents are composing and reviewing the score in ${R}/score/ right now: do not touch ${R}/score/, ${R}/design/ or ${R}/tools/perform.py. Stage only your own paths: \`git add <paths> && git commit -m "<why>" -- <paths>\` (retry on index.lock). Commit after every verified step; earlier runs were killed by usage limits and only committed work survived. Never commit audio or samples. NEVER play audio through the speakers.
GOAL: the user asked for four versions of one 4-voice score (soprano, alto, tenor, bass): Bach = pipe organ, Beethoven = solo piano (+ string quartet bonus), symphonic orchestra, and piano + string quartet together. The engines are nearly built; the final renders start in about two hours, so finish reliably rather than perfectly. Be efficient: fix what is broken or clearly audible, measure to prove it, document, commit.
TEST MUSIC: ${R}/design/final-lab/SK_final.ly with ${R}/design/final-lab/plan.json (66 bars). Chain: \`python3 ${R}/tools/perform.py SCORE PLAN OUT.mid --target piano|strings\`, then the renderer; ensembles via ${R}/tools/orchestrate.py + ${R}/tools/mix.py (docs ${R}/tools/ORCHESTRATION.md). Samples under ${LIB}/. Disk is tight: no large new downloads.`

const QA_SCHEMA = {
  type: 'object',
  properties: {
    defects: { type: 'array', items: { type: 'object', properties: { severity: { type: 'string', enum: ['major', 'minor'] }, issue: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['severity', 'issue', 'evidence', 'fix'] } },
    verdict: { type: 'string', enum: ['ready', 'needs-fixes'] },
  },
  required: ['defects', 'verdict'],
}
const DONE_SCHEMA = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['ready', 'usable-with-caveats', 'broken'] }, usage: { type: 'string' }, demo: { type: 'string' }, evidence: { type: 'string' }, caveats: { type: 'array', items: { type: 'string' } } },
  required: ['status', 'usage', 'demo', 'evidence', 'caveats'],
}

const LANES = [
  { key: 'organ', dir: `${R}/audio/organ`, finish: `ROLE: FINISH the PIPE ORGAN renderer (Bach version) in ${R}/audio/organ/. Its build agent was killed by a usage limit; its last edits were committed unverified (commit "Organ engine WIP ..."). Read CONTRACT.md, render_organ.py, pipe_engine.py, registrations.json, setup_organ.sh, tests/ and qa/. Make sure: the contract tests pass, the skeleton renders end to end with a registration plan (demo/), tuning, no stuck/dropped notes, no loop clicks, registration changes audible and terraced, church acoustic clear enough for counterpoint, docs match behaviour. Re-render ${R}/audio/organ/out/skeleton_organ.m4a. Commit.` },
  { key: 'orchestra', dir: `${R}/audio/orchestra`, finish: `ROLE: FINISH the ORCHESTRA renderer (symphonic version) in ${R}/audio/orchestra/. Its build agent was killed by a usage limit; its last edits were committed unverified (commit "Orchestra engine WIP ..."). Read CONTRACT.md, render_orchestra.py, orch_build.py, tune_orchestra.py, qa_orchestra.py, evidence/. Make sure: every part renders in tune (A=440) with dynamics changing timbre, short and long notes behave, seating and hall are sane, a tutti stays clear, the contract matches what orchestrate.py writes for the orchestra group (run orchestrate.py with a small orchestra spec on the skeleton and render it). Re-render ${R}/audio/orchestra/out/skeleton_orchestra.m4a. Commit.` },
  { key: 'mix', dir: `${R}/tools/orchestrate.py, ${R}/tools/mix.py, ${R}/orchestration/`, finish: null },
  { key: 'strings', dir: `${R}/audio/strings`, finish: `ROLE: COMPLETE the STRING QUARTET round-2 fix in ${R}/audio/strings/. QA round 2 found the defects in ${R}/audio/strings/qa/round2/qa_r2_defects.json (2 major: sustain samples dipping 6-7.5 dB in their first second; --wet level mis-stated on string music). The fixer was killed mid-way; its edits are commit 9ec1a38 (unverified). Verify what that commit did, finish the two major fixes and any cheap minor ones, re-measure with the harness in qa/round2/, re-render the demos, update the README, commit.` },
]

async function lane(l) {
  let done = null
  if (l.finish) done = await A(`${COMMON}\n${l.finish}\nReturn the structured summary.`, { label: `${l.key} finish`, phase: 'Finish', schema: DONE_SCHEMA })
  if (l.key === 'strings') return { done }
  const qa = await A(`${COMMON}
ROLE: ADVERSARIAL AUDIO QA of ${l.dir}. Try to break it on the skeleton through its documented chain. Do NOT modify its code (scratch in /tmp). Measure: every note present at the right time and pitch, no stuck/dropped notes, clicks, clipping or cut tails; dynamics/registration audible in level and spectrum; four lines followable; ${l.key === 'mix' ? 'sample-accurate alignment between groups (< 5 ms), the note-for-note integrity check, orchestra and organ groups working through mix.py, ' : ''}docs match behaviour. Report defects with evidence and a concrete fix; major = would be audible or break the final renders.`,
    { label: `${l.key} QA`, phase: 'QA', schema: QA_SCHEMA })
  if (!qa) return { done, qa: null }
  const major = qa.defects.filter(d => d.severity === 'major')
  log(`${l.key} QA: ${major.length} major, ${qa.defects.length - major.length} minor`)
  if (!major.length) return { done, qa: { verdict: qa.verdict, minor: qa.defects.length } }
  const fix = await A(`${COMMON}
ROLE: FIX ${l.dir} (you may modify it). Adversarial QA found these defects; fix the major ones and any cheap minor ones, re-measure, re-render the demo, commit.
${qa.defects.map((d, i) => `${i + 1}. [${d.severity}] ${d.issue}\n   evidence: ${d.evidence}\n   fix: ${d.fix}`).join('\n')}
Return the structured summary.`, { label: `${l.key} fix`, phase: 'QA', schema: DONE_SCHEMA })
  return { done: fix || done, qa: { verdict: qa.verdict, major: major.length } }
}

const results = await parallel(LANES.map(l => () => lane(l)))
return Object.fromEntries(LANES.map((l, i) => [l.key, results[i]]))
