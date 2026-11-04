// Today's hearing for a clip, as the app sets it up (providers/azure.ts): MAI streaming (ja, vi, zh: best-routes
// hear 'mai') or Azure standard (ko, hi), the app's segmentation (Time strategy, its per-language sentence silence,
// 20 s cap), continuous recognition on a push stream fed at real time in 100 ms frames (paced by the clock).
// Records every final with its audio offset/duration and arrival.
//   npx tsx azure_stream.mts <lang> mai|azure      (MAI_KEY/MAI_REGION or AZURE_SPEECH_KEY/AZURE_SPEECH_REGION)
import { readFileSync, writeFileSync } from 'node:fs'
import * as sdk from 'microsoft-cognitiveservices-speech-sdk'
import { sentenceSilenceMs, AZURE_MAX_SEGMENT_MS } from '/Users/sstone/dev/live-translation/src/main/providers/azure'
import { azureSttLocale } from '/Users/sstone/dev/live-translation/src/shared/azure-locales'
import { MAI_MODEL } from '/Users/sstone/dev/live-translation/src/shared/mai'

const lang = process.argv[2]!
const how = process.argv[3] as 'mai' | 'azure'
const D = `/tmp/rs/chirp/data/asia/${lang}`
const audio = Buffer.concat([readFileSync(`${D}/clip.raw`), Buffer.alloc(5 * 16000 * 2)])
const locale = azureSttLocale(lang === 'kot' ? 'ko' : lang === 'jat' ? 'ja' : lang)!
const cfg = how === 'mai' ? sdk.SpeechConfig.fromSubscription(process.env.MAI_KEY!, process.env.MAI_REGION!) : sdk.SpeechConfig.fromSubscription(process.env.AZURE_SPEECH_KEY!, process.env.AZURE_SPEECH_REGION!)
if (how === 'mai') (cfg as unknown as { setModel(m: string): void }).setModel(MAI_MODEL)
cfg.speechRecognitionLanguage = locale
cfg.setProperty(sdk.PropertyId.Speech_SegmentationStrategy, 'Time')
cfg.setProperty(sdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, String(sentenceSilenceMs([locale])))
cfg.setProperty(sdk.PropertyId.Speech_SegmentationMaximumTimeMs, String(AZURE_MAX_SEGMENT_MS))
const push = sdk.AudioInputStream.createPushStream(sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1))
const sr = new sdk.SpeechRecognizer(cfg, sdk.AudioConfig.fromStreamInput(push))
const ev: { t: number; type: string; text: string; start: number; end: number }[] = []
let t0 = 0
let firstPartial: number | null = null
sr.recognizing = (_s, e) => { if (firstPartial === null) firstPartial = (performance.now() - t0) / 1000 }
sr.recognized = (_s, e) => {
  if (e.result.reason !== sdk.ResultReason.RecognizedSpeech || !e.result.text.trim()) return
  const start = e.result.offset / 1e7
  ev.push({ t: +((performance.now() - t0) / 1000).toFixed(2), type: 'final', text: e.result.text, start: +start.toFixed(2), end: +(start + e.result.duration / 1e7).toFixed(2) })
}
let canceled = ''
sr.canceled = (_s, e) => { if (e.reason === sdk.CancellationReason.Error) canceled = `${e.errorCode} ${String(e.errorDetails)}` }
await new Promise<void>((ok, bad) => sr.startContinuousRecognitionAsync(ok, bad))
t0 = performance.now()
for (let k = 0, i = 0; i < audio.length; k++, i += 3200) {
  const b = audio.subarray(i, i + 3200)
  push.write(b.buffer.slice(b.byteOffset, b.byteOffset + b.length) as ArrayBuffer)
  const lag = t0 + (k + 1) * 100 - performance.now()
  if (lag > 0) await new Promise((r) => setTimeout(r, lag))
}
push.close()
await new Promise((r) => setTimeout(r, 3000))
await new Promise<void>((ok) => sr.stopContinuousRecognitionAsync(() => ok(), () => ok()))
sr.close()
writeFileSync(`/tmp/rs/chirp/runs/asia_${lang}_${how}.json`, JSON.stringify(ev, null, 1))
console.log(lang, how, locale, 'finals', ev.length, canceled ? `ERROR ${String(canceled).slice(0, 300)}` : '', 'first partial', firstPartial)
