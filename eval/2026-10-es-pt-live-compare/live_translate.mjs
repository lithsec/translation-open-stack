// Gemini Live Translate (the model Talk's worker uses, on Vertex AI) on the
// held-out English clip, streamed at real time, into each target language.
// The live() mode of ../2026-10-real-voices/gemini_live.mjs, keeping every
// output-transcription fragment and audio chunk with its arrival time so the
// continuous answer can be cut per sentence afterwards (segment.py).
//
//   GEMINI_API_KEY=... node live_translate.mjs CLIPS/en.wav OUT es pt fr ja km lo ht   (AI Studio)
//   TOK=$(gcloud auth print-access-token) GOOGLE_CLOUD_PROJECT=<project> node live_translate.mjs ...   (Vertex)
//
// Writes OUT/live/en-<tgt>.json. Nothing secret is printed.
import fs from "node:fs";

const TOK = process.env.TOK, PROJECT = process.env.GOOGLE_CLOUD_PROJECT, KEY = process.env.GEMINI_API_KEY;
const MODEL = process.env.GEMINI_TRANSLATE_MODEL || "gemini-3.5-live-translate-preview";
const URL = KEY
  ? "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
  : "wss://aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent";
const AUTH = KEY ? { "x-goog-api-key": KEY } : { Authorization: "Bearer " + TOK };
const MODEL_PATH = KEY ? `models/${MODEL}` : `projects/${PROJECT}/locations/global/publishers/google/models/${MODEL}`;
const [wav, out, ...targets] = process.argv.slice(2);
const pcm = fs.readFileSync(wav).subarray(44);

function open(setup) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(URL, { headers: AUTH });
    const handlers = [];
    let ready = false;
    const timer = setTimeout(() => { try { ws.close(); } catch {} reject(new Error("no setupComplete in 15 s")); }, 15000);
    ws.onopen = () => ws.send(JSON.stringify({ setup }));
    ws.onclose = (e) => { if (!ready) { clearTimeout(timer); reject(new Error(`closed ${e.code} ${e.reason}`)); } };
    ws.onmessage = async (e) => {
      const text = typeof e.data === "string" ? e.data : Buffer.from(await e.data.arrayBuffer()).toString();
      const m = JSON.parse(text);
      if (m.setupComplete && !ready) { ready = true; clearTimeout(timer); resolve({ ws, on: (f) => handlers.push(f) }); return; }
      for (const f of handlers) f(m);
    };
  });
}

async function run(tgt) {
  let s;
  try {
    s = await open({
      model: MODEL_PATH,
      generationConfig: { responseModalities: ["AUDIO"], translationConfig: { targetLanguageCode: tgt, echoTargetLanguage: false } },
      inputAudioTranscription: {},
      outputAudioTranscription: {}
    });
  } catch (e) { return { tgt, err: e.message }; }
  const start = Date.now();
  const said = [], heard = [], audio = [];
  s.on((m) => {
    const sc = m.serverContent || {};
    const t = Date.now() - start;
    for (const p of sc.modelTurn?.parts || []) if (p.inlineData) audio.push({ t, bytes: Buffer.from(p.inlineData.data, "base64").length });
    if (sc.outputTranscription?.text) said.push({ t, text: sc.outputTranscription.text });
    if (sc.inputTranscription?.text) heard.push({ t, text: sc.inputTranscription.text });
  });
  for (let off = 0; off < pcm.length + 32000 * 8; off += 3200) {
    const c = off < pcm.length ? pcm.subarray(off, off + 3200) : Buffer.alloc(3200);
    s.ws.send(JSON.stringify({ realtimeInput: { audio: { data: c.toString("base64"), mimeType: "audio/pcm;rate=16000" } } }));
    await new Promise((r) => setTimeout(r, Math.max(0, start + off / 32 + 100 - Date.now())));
  }
  await new Promise((r) => setTimeout(r, 4000));
  try { s.ws.close(); } catch {}
  return { tgt, model: MODEL, said, heard, audio };
}

fs.mkdirSync(`${out}/live`, { recursive: true });
await Promise.all(targets.map(async (tgt) => {
  const r = await run(tgt);
  fs.writeFileSync(`${out}/live/en-${tgt}.json`, JSON.stringify(r, null, 1));
  console.log(`en-${tgt}: ${r.err ? "ERROR " + r.err : r.said.length + " text pieces, " + r.audio.length + " audio chunks"}`);
}));
