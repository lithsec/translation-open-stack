// Condense with context, final prompt: A (today's prompt) vs final B (the app's condensePrompt(pieces, lang, spoken),
// imported from the feat/condense-context worktree, i.e. the eval's prompt B plus the meaning line), on the SAME runs
// as eval/2026-11-condense-context (its translated pieces in prev/condense_<lang>.json, so only the prompt differs).
// B's answer is judged as the app judges it (judgeRewrite: markers stripped, the 5% rule, then the repeat check).
// Also writes the old B (prev) as arm A of runs/oldB_vs_final_<lang>.json for a direct old-B vs final-B grading.
//   npx tsx condense_eval.mts pt|es        (LT_AWS_* in the environment)
import { readFileSync, writeFileSync } from 'node:fs'
import type { FoundryPrompt } from '/Users/sstone/.t3/worktrees/live-translation/t3-763703d3/src/main/providers/foundry-stream'
import { condensePrompt, condenseCall, condenseVerdict, judgeRewrite } from '/Users/sstone/.t3/worktrees/live-translation/t3-763703d3/src/main/providers/voice-condense'

const F = '/Users/sstone/dev/translation-open-stack/eval/2026-11-condense-context-final'
const lang = process.argv[2]!
const keys = { bedrockAws: { accessKeyId: process.env.LT_AWS_ACCESS_KEY_ID!, secretAccessKey: process.env.LT_AWS_SECRET_ACCESS_KEY!, region: process.env.LT_AWS_REGION || 'us-east-2' }, openRouterModel: '' }
const call = condenseCall(keys)
type Arm = { text: string; ms: number; verdict: string; error: string | null }
async function condense(prompt: FoundryPrompt, judge: (answer: string) => { outcome: string; rewrite: string }): Promise<Arm> {
  const t0 = performance.now()
  const r = await call(prompt, new AbortController().signal).catch((e: unknown) => ({ text: '', error: String(e) }))
  const j = judge(r.text ?? '')
  return { text: j.rewrite, ms: Math.round(performance.now() - t0), verdict: j.outcome, error: (r as { error?: string }).error ?? null }
}
const prev = JSON.parse(readFileSync(`${F}/prev/condense_${lang}.json`, 'utf8')) as any[]
const out: any[] = [], cmp: any[] = []
for (const r of prev) {
  const spoken = (r.spoken as string[]).map((text, k, all) => ({ text, ends: k === all.length - 1 ? !r.continues : true }))
  const pieces = (r.run as { text: string; ends: string }[]).map((p) => ({ text: p.text, ends: p.ends === 'sentence' }))
  const original = r.original as string
  const [a, b] = await Promise.all([
    condense(condensePrompt(original, lang), (t) => { const x = t.replace(/\s*\[(?:end|cut)\]\s*/g, ' ').trim(); return { outcome: condenseVerdict(original, x), rewrite: x } }),
    condense(condensePrompt(pieces, lang, spoken), (t) => judgeRewrite(original, t, spoken[spoken.length - 1]?.text ?? '', lang))
  ])
  const base = { speech: r.speech, at: r.at, spoken: r.spoken, run: r.run, next: r.next, continues: r.continues, endsCut: r.endsCut, original }
  out.push({ ...base, A: a, B: b })
  cmp.push({ ...base, A: r.B, B: b })
  process.stdout.write(`${lang} ${String(r.speech).slice(0, 30)} run@${r.at} A ${a.verdict} ${a.ms}ms B ${b.verdict} ${b.ms}ms\n`)
}
writeFileSync(`${F}/runs/condense_${lang}.json`, JSON.stringify(out, null, 1))
writeFileSync(`${F}/runs/oldB_vs_final_${lang}.json`, JSON.stringify(cmp, null, 1))
console.log(lang, 'runs', out.length)
