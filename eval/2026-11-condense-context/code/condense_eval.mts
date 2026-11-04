// Condense with context, A/B. English VoxPopuli speeches (data/speeches.json) are cut into pieces the way a long
// sentence reaches the voice (sentence ends, and long sentences cut at a clause), each piece translated into `lang`
// in order with the app's own prompt and Gemma on Bedrock (omni.ts translateMessages, previous 2 pieces as context,
// gemma.ts gemmaStream), as a room's voice queue would receive them. Runs of waiting pieces are built as
// AzureVoice.condensable takes them (>= 2 pieces, >= 80 characters), and each run is condensed twice:
//   A: today's prompt (voice-condense.ts condensePrompt): the run's text alone.
//   B: the context prompt below: what was already spoken, the pieces one per line with where each ends, and whether
//      the passage continues a sentence or is followed straight on.
// Same caller as the app (condenseCall: Gemma with a phrase's short waits). Writes runs/condense_<lang>.json.
//   npx tsx condense_eval.mts pt|es        (LT_AWS_* in the environment)
import { readFileSync, writeFileSync } from 'node:fs'
import { translateMessages, CONTEXT_CHUNKS, languageName } from '/Users/sstone/dev/live-translation/src/main/providers/omni'
import { forPair, type FoundryPrompt } from '/Users/sstone/dev/live-translation/src/main/providers/foundry-stream'
import { gemmaStream } from '/Users/sstone/dev/live-translation/src/main/providers/gemma'
import { condensePrompt, condenseCall, condenseVerdict, CONDENSE_MIN_CHARS, CONDENSE_MIN_PIECES } from '/Users/sstone/dev/live-translation/src/main/providers/voice-condense'

const lang = process.argv[2]!
const keys = { bedrockAws: { accessKeyId: process.env.LT_AWS_ACCESS_KEY_ID!, secretAccessKey: process.env.LT_AWS_SECRET_ACCESS_KEY!, region: process.env.LT_AWS_REGION || 'us-east-2' }, openRouterModel: '' }

// ---------------------------------------------------------------- pieces
type Piece = { en: string; ends: 'sentence' | 'cut' }
const CONJ = /\s(?=(?:and|but|which|because|so|while|whereas|although|that is|where|when)\s)/i
function cutSentence(s: string): Piece[] {
  const words = s.split(/\s+/)
  if (words.length <= 16) return [{ en: s, ends: 'sentence' }]
  // At a comma or before a conjunction, nearest the middle, each side >= 5 words; then again on the longer half.
  const spots: number[] = []
  let at = 0
  for (const part of s.split(/(?<=,)\s|(?=\s(?:and|but|which|because|so|while|whereas|although|where|when)\s)/i)) {
    at += part.length
    spots.push(at)
  }
  const mid = s.length / 2
  const ok = spots.filter((p) => s.slice(0, p).trim().split(/\s+/).length >= 5 && s.slice(p).trim().split(/\s+/).length >= 5)
  if (!ok.length) return [{ en: s, ends: 'sentence' }]
  const p = ok.sort((a, b) => Math.abs(a - mid) - Math.abs(b - mid))[0]!
  const left = s.slice(0, p).trim(), right = s.slice(p).trim()
  return [...cutSentence(left).map((x) => ({ ...x, ends: 'cut' as const })), ...cutSentence(right)]
}
void CONJ
const speeches = JSON.parse(readFileSync('/tmp/rs/cond/data/speeches.json', 'utf8')) as { id: string; text: string }[]

// ---------------------------------------------------------------- translate, as the room does
async function translate(text: string, before: string[], said: string): Promise<string> {
  const prompt = forPair(translateMessages(text, 'en', lang, before.length ? { before, ...(said ? { translation: said } : {}) } : undefined), 'en', lang)
  const r = await gemmaStream(keys, prompt, () => {})
  return r.text.trim()
}

// ---------------------------------------------------------------- the context prompt (B)
function contextPrompt(spoken: string[], run: { text: string; ends: 'sentence' | 'cut' }[], continues: boolean): FoundryPrompt {
  const L = languageName(lang)
  const endsCut = run[run.length - 1]!.ends === 'cut'
  const system =
    `You shorten a stretch of live interpretation in ${L} so it can be spoken sooner. Listeners have just heard the ` +
    `text under "Already spoken". Rewrite only the passage as one shorter passage in ${L} that carries on smoothly from ` +
    `what was already spoken. Keep every fact, name, number and negation; drop only repetition and filler; aim for ` +
    `about 70% of the length. Never repeat or rephrase anything already spoken. ` +
    (continues ? `The passage continues a sentence that is already under way: carry it on, do not start it again. ` : '') +
    (endsCut ? `It ends mid-sentence and the speaker's next words follow straight after: end it so they can follow on. ` : `It ends at the end of a sentence. `) +
    `Never complete, question or comment on it, never add words, and never output the markers. Output only the rewritten passage.`
  const user =
    `Already spoken (context only, never repeat it):\n${spoken.join(' ') || '(nothing yet)'}\n\n` +
    `Passage to shorten, one piece per line ([end] = a sentence ends there, [cut] = the sentence goes on):\n` +
    run.map((p) => `${p.text} [${p.ends === 'sentence' ? 'end' : 'cut'}]`).join('\n')
  return { system, user, pair: { from: lang, to: lang } }
}

const call = condenseCall(keys)
async function condense(prompt: FoundryPrompt, original: string) {
  const t0 = performance.now()
  const ac = new AbortController()
  const r = await call(prompt, ac.signal).catch((e: unknown) => ({ text: '', error: String(e) }))
  const text = (r.text ?? '').replace(/\s*\[(?:end|cut)\]\s*/g, ' ').trim()
  return { text, ms: Math.round(performance.now() - t0), verdict: condenseVerdict(original, text), error: (r as { error?: string }).error ?? null }
}

const out: unknown[] = []
for (const sp of speeches) {
  const sentences = sp.text.replace(/\s+/g, ' ').match(/[^.!?]+[.!?]+(?:["')\]]+)?|[^.!?]+$/g)!.map((s) => s.trim()).filter(Boolean)
  const pieces = sentences.flatMap(cutSentence)
  // Translate in order, as the room would.
  const tr: { text: string; ends: Piece['ends']; en: string }[] = []
  for (let i = 0; i < pieces.length; i++) {
    const before = pieces.slice(Math.max(0, i - CONTEXT_CHUNKS), i).map((p) => p.en)
    tr.push({ text: await translate(pieces[i]!.en, before, tr[i - 1]?.text ?? ''), ends: pieces[i]!.ends, en: pieces[i]!.en })
  }
  // Runs: from piece 2 on (something already spoken), 2-4 pieces and >= 80 characters, then skip past the run.
  for (let i = 1; i < tr.length - 1; ) {
    let j = i, chars = 0
    while (j < tr.length - 1 && j - i < 4 && (j - i < CONDENSE_MIN_PIECES || chars < CONDENSE_MIN_CHARS)) chars += tr[j++]!.text.length
    const run = tr.slice(i, j)
    if (run.length < CONDENSE_MIN_PIECES || chars < CONDENSE_MIN_CHARS) break
    const original = run.map((p) => p.text).join(' ')
    const spoken = tr.slice(Math.max(0, i - 2), i).map((p) => p.text)
    const continues = tr[i - 1]!.ends === 'cut'
    const [a, b] = await Promise.all([condense(condensePrompt(original, lang), original), condense(contextPrompt(spoken, run, continues), original)])
    out.push({ speech: sp.id, at: i, spoken, run: run.map((p) => ({ text: p.text, ends: p.ends })), next: tr[j]!.text, continues, endsCut: run[run.length - 1]!.ends === 'cut', original, A: a, B: b })
    process.stdout.write(`${lang} ${sp.id.slice(0, 30)} run@${i} A ${a.verdict} ${a.ms}ms B ${b.verdict} ${b.ms}ms\n`)
    i = j + 1
  }
}
writeFileSync(`/tmp/rs/cond/runs/condense_${lang}.json`, JSON.stringify(out, null, 1))
console.log(lang, 'runs', out.length)
