// Azure standard streaming on each FLEURS sentence, at real time (100 ms frames paced by the clock) plus 5 s of
// silence, as the app's AzureStreamHub sets it up (Time segmentation, 300 ms sentence silence, 20 s forced cut).
//   npx tsx azure_stream.mts DATA km|en pin|lid OUT.json   (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION in the environment)
//   pin: km-KH only. lid: continuous language ID between en-US and km-KH (the app's two-language stream).
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import * as sdk from 'microsoft-cognitiveservices-speech-sdk'
const [D, which, how, OUT] = process.argv.slice(2) as [string, 'km' | 'en', 'pin' | 'lid', string]
const set = JSON.parse(readFileSync(`${D}/set.json`, 'utf8')) as { id: string; km_file: string; en_file: string; km: string; en: string }[]
const rows: unknown[] = existsSync(OUT) ? JSON.parse(readFileSync(OUT, 'utf8')) : []
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
async function one(file: string) {
  const audio = Buffer.concat([readFileSync(`${D}/${which}/${file.replace('.wav', '.raw')}`), Buffer.alloc(5 * 32000)])
  const cfg = how === 'lid'
    ? sdk.SpeechConfig.fromEndpoint(new URL(`wss://${process.env.AZURE_SPEECH_REGION}.stt.speech.microsoft.com/speech/universal/v2`), process.env.AZURE_SPEECH_KEY!)
    : sdk.SpeechConfig.fromSubscription(process.env.AZURE_SPEECH_KEY!, process.env.AZURE_SPEECH_REGION!)
  if (how === 'pin') cfg.speechRecognitionLanguage = 'km-KH'
  cfg.setProperty(sdk.PropertyId.Speech_SegmentationStrategy, 'Time')
  cfg.setProperty(sdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, '300')
  cfg.setProperty(sdk.PropertyId.Speech_SegmentationMaximumTimeMs, '20000')
  if (how === 'lid') cfg.setProperty(sdk.PropertyId.SpeechServiceConnection_LanguageIdMode, 'Continuous')
  const push = sdk.AudioInputStream.createPushStream(sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1))
  const ac = sdk.AudioConfig.fromStreamInput(push)
  const sr = how === 'lid'
    ? sdk.SpeechRecognizer.FromConfig(cfg, sdk.AutoDetectSourceLanguageConfig.fromLanguages(['en-US', 'km-KH']), ac)
    : new sdk.SpeechRecognizer(cfg, ac)
  const finals: { text: string; lang: string | null; t: number; end: number }[] = []
  let t0 = 0, firstPartial: number | null = null, err = ''
  sr.recognizing = () => { if (firstPartial === null) firstPartial = (performance.now() - t0) / 1000 }
  sr.recognized = (_s, e) => {
    if (e.result.reason !== sdk.ResultReason.RecognizedSpeech || !e.result.text.trim()) return
    const lang = how === 'lid' ? sdk.AutoDetectSourceLanguageResult.fromResult(e.result).language ?? null : 'km-KH'
    finals.push({ text: e.result.text, lang, t: +((performance.now() - t0) / 1000).toFixed(2), end: +((e.result.offset + e.result.duration) / 1e7).toFixed(2) })
  }
  sr.canceled = (_s, e) => { if (e.reason === sdk.CancellationReason.Error) err = `${e.errorCode} ${e.errorDetails}` }
  await new Promise<void>((ok, bad) => sr.startContinuousRecognitionAsync(ok, bad))
  t0 = performance.now()
  for (let k = 0, i = 0; i < audio.length; k++, i += 3200) {
    const b = audio.subarray(i, i + 3200)
    push.write(b.buffer.slice(b.byteOffset, b.byteOffset + b.length) as ArrayBuffer)
    const due = t0 + (k + 1) * 100
    await sleep(Math.max(0, due - performance.now()))
  }
  push.close()
  await sleep(1500)
  await new Promise<void>((ok) => sr.stopContinuousRecognitionAsync(() => ok(), () => ok()))
  sr.close()
  const speech = (audio.length - 5 * 32000) / 32000
  const last = finals.at(-1)
  return { file, speech_s: +speech.toFixed(2), hyp: finals.map((f) => f.text).join(' '), langs: finals.map((f) => f.lang),
    first_partial_s: firstPartial === null ? null : +firstPartial.toFixed(2), final_after_end_s: last ? +(last.t - speech).toFixed(2) : null, finals, error: err || null }
}
const done = new Set(rows.map((r) => (r as { file: string }).file))
const files = set.map((s) => (which === 'km' ? s.km_file : s.en_file)).filter((f) => !done.has(f))
// Three streams at once (the eval concurrency cap).
for (let i = 0; i < files.length; i += 3) {
  const got = await Promise.all(files.slice(i, i + 3).map(one))
  rows.push(...got)
  writeFileSync(OUT, JSON.stringify(rows, null, 1))
  for (const g of got) process.stdout.write(`${which} ${how} ${g.file} ${g.final_after_end_s}s ${g.langs.join(',')}${g.error ? ' ERR ' + g.error : ''}\n`)
}
