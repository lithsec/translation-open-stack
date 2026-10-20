// Latency harness: drives Live Translation's OWN provider classes, each
// wrapped in its reconnecting session as the app's audio router does
// (src/main/providers/*, unmodified except two passive __probe hooks in
// azure.ts) with a clip streamed at real-time pace, and logs every callback
// with its time on the clip's speech timeline. No secrets in this file: keys
// come from the environment (see env.example).
//
//   npx tsx harness/run_route.ts <route> <src> <tgt> <clipDir> <out.json> [model]
//
// Routes: azure-foundry | azure-gemini | azure-gemini-stream | gemini-lt |
//         ht-exception (Azure + omni-stt /listen -> Foundry -> target voice) |
//         ht-voice-gemini | ht-voice-coqui (Azure + Foundry into Haitian Creole)
import { readFileSync, writeFileSync } from 'fs'
import { performance } from 'perf_hooks'
import { azureFoundryProvider, azureGeminiProvider } from '../src/main/providers/azure'
import { geminiProvider } from '../src/main/providers/gemini'
import { openReconnectingSession } from '../src/main/providers/reconnecting'
import type { OpenSessionOptions, TranslationSession } from '../src/main/providers/types'
import { omniListenUrl, omniSpeakUrl } from '../src/main/providers/omni'
import WebSocket from 'ws'

/** omni-stt runs on Cloud Run and scales to zero (a cold start is ~40 s). A
 *  room connects once at the start of a service, so its cold start is not a
 *  per-sentence delay: wake the service first (wait for its hello). */
function prewarm(url: string, token: string): Promise<number> {
  const t = performance.now()
  return new Promise((resolve) => {
    const ws = new WebSocket(url, { headers: { authorization: `Bearer ${token}` }, handshakeTimeout: 90_000 })
    const done = () => { try { ws.close() } catch {} ; resolve(Math.round(performance.now() - t)) }
    ws.on('message', (d, bin) => { if (!bin && /hello/.test(d.toString())) done() })
    ws.on('close', done)
    ws.on('error', () => {})
    setTimeout(done, 90_000)
  })
}

const [route, src, tgt, clipDir, outPath, modelArg] = process.argv.slice(2)
if (!route || !src || !tgt || !clipDir || !outPath) throw new Error('usage: route src tgt clipDir out.json [model]')
const env = (k: string): string => {
  const v = process.env[k]
  if (!v) throw new Error(`${k} not set`)
  return v
}

const CHUNK_MS = 100
const RATE = 16000
const wav = readFileSync(`${clipDir}/${src}.wav`)
const pcm = wav.subarray(44) // 16 kHz mono s16 from build_clips.py (44-byte header)
const marks = JSON.parse(readFileSync(`${clipDir}/${src}.json`, 'utf8'))

// The speech timeline: chunk k covers audio [k*100, (k+1)*100) ms and, like a
// microphone, is delivered when it ends, at origin + (k+1)*100 ms.
let origin = 0
const now = (): number => +(performance.now() - origin).toFixed(1)
const events: Record<string, unknown>[] = []
let lastEvent = 0
const log = (kind: string, extra: Record<string, unknown> = {}): void => {
  lastEvent = performance.now()
  events.push({ t: origin ? now() : null, kind, ...extra })
}
;(globalThis as any).__probe = (kind: string, data: Record<string, unknown>) => log(kind, data)

const AZURE_GEMINI_DEFAULT = 'gemini-2.5-flash-native-audio-preview-09-2025' // LT config.ts default voice model
const foundry = { url: env('FOUNDRY_URL'), key: env('FOUNDRY_KEY'), deployment: process.env.FOUNDRY_DEPLOYMENT || 'gpt-5.6-sol-us' }
const omniBase = { url: process.env.OMNI_URL || '', token: process.env.OMNI_TOKEN || '', langs: ['ht'], model: foundry.deployment, thinking: 'default' as const }

let state = ''
let stateErr = ''
const callbacks = {
  onTranscriptDelta: (text: string) => log('text', { text }),
  onTranscriptDone: (text: string) => log('done', { text }),
  onAudioDelta: (b: Buffer, rate: number) => log('audio', { samples: b.length / 2, rate, ...voiced(b, rate) }),
  onInputTranscript: (text: string) => log('input', { text }),
  onStateChange: (s: string, e?: string) => {
    state = s
    if (e) stateErr = e
    log('state', { state: s, ...(e ? { error: e } : {}) })
  },
  onProgress: () => {},
  onInputLanguage: (code: string) => log('lang', { code }),
  onRecovery: (ev: { action: string; detail: string }) => log('recovery', { action: ev.action, detail: String(ev.detail).slice(0, 200) })
}

function open(): { session: TranslationSession; meta: Record<string, unknown> } {
  const azureCfg = (extra: Record<string, unknown>) => ({
    endpoint: '',
    model: modelArg || AZURE_GEMINI_DEFAULT,
    inputRate: RATE,
    voice: '',
    region: env('AZURE_SPEECH_REGION'),
    foundry,
    ...extra
  })
  const base = { targetLang: tgt, sourceLang: src, callbacks } as unknown as OpenSessionOptions
  switch (route) {
    case 'azure-foundry': {
      const cfg = azureCfg({})
      return { session: openReconnectingSession(azureFoundryProvider, { ...base, apiKey: env('AZURE_SPEECH_KEY'), config: cfg as any }), meta: { stt: 'Azure Speech', mt: `Foundry ${foundry.deployment}`, voice: 'Azure neural (locale default)' } }
    }
    case 'azure-gemini':
    case 'azure-gemini-stream': {
      const stream = route === 'azure-gemini-stream'
      const model = modelArg || (stream ? 'gemini-3.8-live' : AZURE_GEMINI_DEFAULT)
      const cfg = azureCfg({ model, geminiStreaming: stream })
      return { session: openReconnectingSession(azureGeminiProvider, { ...base, apiKey: env('AZURE_SPEECH_KEY'), config: cfg as any }), meta: { stt: 'Azure Speech', mt_voice: `Gemini Live ${model}`, streaming: stream } }
    }
    case 'gemini-lt': {
      const model = modelArg || 'gemini-3.5-live-translate-preview'
      const cfg = { endpoint: 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent', model, inputRate: RATE, voice: 'Kore' }
      return { session: openReconnectingSession(geminiProvider, { ...base, apiKey: env('GEMINI_API_KEY'), config: cfg as any }), meta: { model, voice: 'Kore' } }
    }
    case 'ht-exception': {
      // The language exception as a room runs it: speaker language on auto,
      // omni-stt /listen beside Azure, Foundry translating the Haitian.
      const cfg = azureCfg({ omni: { ...omniBase, enabled: true, voice: 'gemini' } })
      return {
        session: openReconnectingSession(azureFoundryProvider, { ...base, sourceLang: 'auto', roomLanguages: ['en', 'ht'], apiKey: env('AZURE_SPEECH_KEY'), config: cfg as any }),
        meta: { stt: 'omni-stt /listen (Omnilingual) beside Azure', mt: `Foundry ${foundry.deployment}`, voice: 'Azure neural (en-US default)' }
      }
    }
    case 'ht-voice-gemini':
    case 'ht-voice-coqui': {
      const voice = route === 'ht-voice-gemini' ? 'gemini' : 'coqui'
      const cfg = azureCfg({ omni: { ...omniBase, enabled: false, voice } })
      return {
        session: openReconnectingSession(azureFoundryProvider, { ...base, apiKey: env('AZURE_SPEECH_KEY'), config: cfg as any }),
        meta: { stt: 'Azure Speech', mt: `Foundry ${foundry.deployment}`, voice: voice === 'gemini' ? `Gemini Live ${cfg.model} (read mode)` : 'omni-stt /speak coqui' }
      }
    }
  }
  throw new Error(`unknown route ${route}`)
}

/** Where speech is inside an output chunk: 10 ms frames whose RMS is over
 *  VOICED_RMS (about -47 dBFS). Some routes stream silence between turns
 *  (Gemini Live Translate sends audio continuously), so "first audio" means
 *  the first voiced frame, not the first byte. */
const VOICED_RMS = 150
function voiced(b: Buffer, rate: number): { on?: number; off?: number } {
  const f = Math.round(rate / 100)
  const n = Math.floor(b.length / 2 / f)
  let on = -1
  let off = -1
  for (let k = 0; k < n; k++) {
    let sum = 0
    for (let j = 0; j < f; j++) {
      const v = b.readInt16LE((k * f + j) * 2)
      sum += v * v
    }
    if (Math.sqrt(sum / f) > VOICED_RMS) {
      if (on < 0) on = k * 10
      off = (k + 1) * 10
    }
  }
  return on < 0 ? {} : { on, off }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function main(): Promise<void> {
  let warmMs: number[] = []
  if (route.startsWith('ht-')) {
    const u = env('OMNI_URL'), tok = env('OMNI_TOKEN')
    warmMs = await Promise.all([prewarm(omniListenUrl(u, ['ht'], ['ht'])!, tok), prewarm(omniSpeakUrl(u, 'coqui')!, tok)])
    await sleep(2000)
  }
  const opened = performance.now()
  const { session, meta } = open()
  const inRate = session.inputRate
  if (inRate !== RATE) throw new Error(`session wants ${inRate} Hz`)
  for (let i = 0; i < 150 && state !== 'live' && state !== 'error'; i++) await sleep(100)
  const setupMs = Math.round(performance.now() - opened)
  if (state !== 'live') throw new Error(`not live: ${state} ${stateErr}`)
  // Pre-roll: a room is open before anyone speaks (and omni-stt's sockets
  // reconnect after the prewarm).
  await sleep(route.startsWith('ht-') ? 5000 : 1500)
  const bytesPerChunk = (RATE * CHUNK_MS) / 1000 * 2
  const n = Math.ceil(pcm.length / bytesPerChunk)
  const silence = Buffer.alloc(bytesPerChunk)
  origin = performance.now()
  log('start', { clipSeconds: marks.seconds })
  for (let k = 0; ; k++) {
    const due = origin + (k + 1) * CHUNK_MS
    const wait = due - performance.now()
    if (wait > 0) await sleep(wait)
    if (k < n) {
      const c = pcm.subarray(k * bytesPerChunk, (k + 1) * bytesPerChunk)
      session.sendAudio(c.length === bytesPerChunk ? c : Buffer.concat([c, silence.subarray(c.length)]))
    } else {
      // Room tone after the clip: keep the mic open until output settles
      // (10 s without any event, at most 45 s).
      session.sendAudio(silence)
      const quiet = performance.now() - lastEvent
      if (quiet > 10_000 || (k - n) * CHUNK_MS > 45_000) break
    }
  }
  log('end')
  session.close()
  writeFileSync(
    outPath,
    JSON.stringify({ route, src, tgt, model: modelArg || null, meta, setupMs, warmMs, date: new Date().toISOString(), chunkMs: CHUNK_MS, marks: marks.sentences, events }, null, 0)
  )
  console.log(`${route} ${src}-${tgt}: ${events.filter((e) => e.kind === 'audio').length} audio chunks, ${events.filter((e) => e.kind === 'done').length} dones, setup ${setupMs} ms`)
  setTimeout(() => process.exit(0), 1500)
}
main().catch((e) => {
  console.error(String(e?.stack || e))
  process.exit(1)
})
