// Azure live speech-to-text on audio/<lang>.wav, fed in real time (100 ms
// chunks), so "when did each final arrive" is what a room would see.
//
//   node azure_stt.mjs en ja zh km lo ht
//
// Key and region from the environment: AZURE_SPEECH_KEY (or SPEECH_KEY,
// AZURE_SPEECH_SUBSCRIPTION_KEY) and AZURE_SPEECH_REGION (or SPEECH_REGION,
// AZURE_REGION). Nothing secret is printed.
// Writes out/stt/<lang>.json: each final with its text, lexical form, where it
// sits in the clip (offset/duration) and when it arrived (ms since start).
import fs from "node:fs";
import sdkMod from "microsoft-cognitiveservices-speech-sdk";
const sdk = sdkMod.default ?? sdkMod;

const env = (...names) => names.map((n) => process.env[n]).find((v) => v && v.trim())?.trim();
const KEY = env("AZURE_SPEECH_KEY", "SPEECH_KEY", "AZURE_SPEECH_SUBSCRIPTION_KEY", "AZURE_COGNITIVE_KEY");
const REGION = env("AZURE_SPEECH_REGION", "SPEECH_REGION", "AZURE_REGION", "AZURE_COGNITIVE_REGION");
if (!KEY || !REGION) {
  console.error("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION (see the header for other names it accepts).");
  process.exit(1);
}
const LOCALE = { en: "en-US", ja: "ja-JP", zh: "zh-CN", km: "km-KH", lo: "lo-LA", ht: "ht-HT" };

async function run(lang) {
  const wav = fs.readFileSync(`audio/${lang}.wav`);
  const pcm = wav.subarray(44);
  const cfg = sdk.SpeechConfig.fromSubscription(KEY, REGION);
  cfg.speechRecognitionLanguage = LOCALE[lang];
  cfg.outputFormat = sdk.OutputFormat.Detailed;
  const push = sdk.AudioInputStream.createPushStream(sdk.AudioStreamFormat.getWaveFormatPCM(16000, 16, 1));
  const rec = new sdk.SpeechRecognizer(cfg, sdk.AudioConfig.fromStreamInput(push));
  const finals = [];
  let t0 = 0, err = "";
  rec.recognized = (_s, e) => {
    if (e.result.reason !== sdk.ResultReason.RecognizedSpeech || !e.result.text) return;
    let lexical = "";
    try { lexical = JSON.parse(e.result.json).NBest?.[0]?.Lexical ?? ""; } catch {}
    finals.push({
      text: e.result.text,
      lexical,
      offsetMs: e.result.offset / 1e4,
      durationMs: e.result.duration / 1e4,
      arrivedMs: Date.now() - t0
    });
  };
  rec.canceled = (_s, e) => {
    if (e.reason === sdk.CancellationReason.Error) err = `${e.errorCode}: ${e.errorDetails}`;
  };
  await new Promise((res, rej) => rec.startContinuousRecognitionAsync(res, rej));
  t0 = Date.now();
  for (let off = 0; off < pcm.length; off += 3200) {
    push.write(pcm.subarray(off, off + 3200));
    await new Promise((r) => setTimeout(r, Math.max(0, t0 + (off / 32) + 100 - Date.now())));
  }
  push.write(Buffer.alloc(32000 * 2)); // 2 s of silence so the last sentence closes
  await new Promise((r) => setTimeout(r, 2500));
  push.close();
  await new Promise((r) => setTimeout(r, 3000));
  await new Promise((res) => rec.stopContinuousRecognitionAsync(res, res));
  rec.close();
  fs.mkdirSync("out/stt", { recursive: true });
  fs.writeFileSync(`out/stt/${lang}.json`, JSON.stringify({ lang, locale: LOCALE[lang], err, finals }, null, 1));
  const lag = finals.map((f) => f.arrivedMs - (f.offsetMs + f.durationMs));
  const med = lag.sort((a, b) => a - b)[Math.floor(lag.length / 2)];
  console.log(`${lang} (${LOCALE[lang]}): ${err ? "ERROR " + err : `${finals.length} finals, final arrives ~${Math.round(med)} ms after the words end`}`);
}

// Every clip at once: each is fed at real-time pace, so this takes as long as the longest.
await Promise.all(process.argv.slice(2).map(run));
