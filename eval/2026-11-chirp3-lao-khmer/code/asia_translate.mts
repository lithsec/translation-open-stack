// Lao -> English with the app's own translators and prompt, piece by piece as a live room would: each recogniser's
// finished pieces in order, each translated when it arrives, with the previous 2 pieces (and the last translation)
// as context (omni.ts CONTEXT_CHUNKS). Arms: recogniser {chirp, omni} x translator {sol, gemma}. Times each call.
//   npx tsx translate.mts reg|irr OUT.json      (FOUNDRY_*, LT_AWS_* in the environment)
import { readFileSync, writeFileSync } from 'node:fs'
import { translateMessages, CONTEXT_CHUNKS } from '/Users/sstone/dev/live-translation/src/main/providers/omni'
import { foundryStream, forPair } from '/Users/sstone/dev/live-translation/src/main/providers/foundry-stream'
import { gemmaStream } from '/Users/sstone/dev/live-translation/src/main/providers/gemma'

const lang = process.argv[2]!
const pat = lang
const BASE = lang === 'ja' || lang === 'vi' || lang === 'zh' ? 'mai' : 'azure'
const out = process.argv[3]!

type Piece = { text: string; start: number; end: number; arrive: number }
function chirp(): Piece[] {
  const ev = JSON.parse(readFileSync(`/tmp/rs/chirp/runs/asia_${lang}_chirp.json`, 'utf8')) as { type: string; t: number; text?: string; end_offset?: number }[]
  let last = 0
  return ev.filter((e) => e.type === 'final' && e.text?.trim()).map((e) => {
    const p = { text: e.text!.trim(), start: last, end: e.end_offset!, arrive: e.t }
    last = e.end_offset!
    return p
  })
}
function base(): Piece[] {
  const ev = JSON.parse(readFileSync(`/tmp/rs/chirp/runs/asia_${lang}_${BASE}.json`, 'utf8')) as { t: number; text: string; start: number; end: number }[]
  return ev.map((e) => ({ text: e.text.trim(), start: e.start, end: e.end, arrive: e.t }))
}

const foundry = { base: process.env.FOUNDRY_ENDPOINT!, key: process.env.FOUNDRY_KEY!, deployment: process.env.FOUNDRY_DEPLOYMENT! }
const aws = { accessKeyId: process.env.LT_AWS_ACCESS_KEY_ID!, secretAccessKey: process.env.LT_AWS_SECRET_ACCESS_KEY!, region: process.env.LT_AWS_REGION || 'us-east-2' }

async function translate(mt: 'sol' | 'gemma', text: string, before: string[], said: string) {
  const prompt = forPair(translateMessages(text, lang, 'en', before.length ? { before, ...(said ? { translation: said } : {}) } : undefined), lang, 'en')
  const t0 = performance.now()
  let first: number | null = null
  const onDelta = () => { if (first === null) first = performance.now() - t0 }
  const r = mt === 'sol'
    ? await foundryStream(foundry.base, foundry.key, foundry.deployment, prompt, onDelta)
    : await gemmaStream({ bedrockAws: aws, openRouterModel: '' }, prompt, onDelta)
  return { en: r.text.trim(), first_s: first === null ? null : +(first / 1000).toFixed(2), total_s: +((performance.now() - t0) / 1000).toFixed(2), error: r.error ?? null, by: (r as { by?: string }).by ?? mt }
}

async function arm(rec: 'chirp' | 'base', mt: 'sol' | 'gemma') {
  const pieces = rec === 'chirp' ? chirp() : base()
  const rows = []
  let said = ''
  for (let i = 0; i < pieces.length; i++) {
    const p = pieces[i]!
    const before = pieces.slice(Math.max(0, i - CONTEXT_CHUNKS), i).map((x) => x.text)
    const r = await translate(mt, p.text, before, said)
    said = r.en || said
    rows.push({ ...p, ...r, done: +(p.arrive + r.total_s).toFixed(2) })
    process.stdout.write(`${pat} ${rec}-${mt} ${i + 1}/${pieces.length} ${r.total_s}s${r.error ? ' ERR ' + r.error.slice(0, 80) : ''}\n`)
  }
  return [`${rec === 'base' ? BASE : rec}-${mt}`, rows] as const
}

const res = Object.fromEntries(await Promise.all([arm('chirp', 'gemma'), arm('base', 'gemma')]))
writeFileSync(out, JSON.stringify(res, null, 1))
