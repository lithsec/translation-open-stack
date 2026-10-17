// The two Gemini contenders, on Vertex AI (GOOGLE_CLOUD_PROJECT + TOK, as in
// eval/2026-09-model-eval/scripts/lat.mjs):
//
//   node gemini_live.mjs pipe en-ja ja-en ...   Azure's finals (out/stt) sent as text,
//       at the moment each arrived, to a Gemini Live session that says the
//       translation. The new pipeline.
//   node gemini_live.mjs live en-ja ja-en ...   audio/<src>.wav streamed to Gemini Live
//       Translate, as in September. The baseline, on the same audio.
//
// Writes out/<mode>/<src>-<tgt>.json: what it said (per turn), when each turn's
// audio started (ms since the clip started), and any error.
import fs from "node:fs";

const TOK = process.env.TOK;
const PROJECT = process.env.GOOGLE_CLOUD_PROJECT || process.env.VERTEX_PROJECT;
if (!TOK || !PROJECT) {
  console.error("Set GOOGLE_CLOUD_PROJECT (or VERTEX_PROJECT) and TOK (TOK=$(gcloud auth print-access-token)).");
  process.exit(1);
}
const NAMES = { en: "English", ja: "Japanese", zh: "Mandarin Chinese", km: "Khmer", lo: "Lao", ht: "Haitian Creole" };
const BCP = { en: "en-US", ja: "ja-JP", zh: "cmn-CN", km: "km-KH", lo: "lo-LA", ht: "ht-HT" };
// The text-in, voice-out model. Overridable; the first that answers setup wins.
const PIPE_MODELS = (process.env.GEMINI_LIVE_MODEL || "gemini-live-2.5-flash-native-audio,gemini-2.5-flash-native-audio")
  .split(",").map((m) => m.trim());
const LIVE_MODEL = process.env.GEMINI_TRANSLATE_MODEL || "gemini-3.5-live-translate-preview";
const URL = "wss://aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent";
const model = (m) => `projects/${PROJECT}/locations/global/publishers/google/models/${m}`;

/** Open a session; resolves with { ws, on } after setupComplete, rejects on close/timeout. */
function open(setup) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(URL, { headers: { Authorization: "Bearer " + TOK } });
    const handlers = [];
    let ready = false;
    const timer = setTimeout(() => { try { ws.close(); } catch {} reject(new Error("no setupComplete in 15 s")); }, 15000);
    ws.onopen = () => ws.send(JSON.stringify({ setup }));
    ws.onclose = (e) => { if (!ready) { clearTimeout(timer); reject(new Error(`closed ${e.code} ${e.reason}`)); } };
    ws.onmessage = async (e) => {
      const text = typeof e.data === "string" ? e.data : Buffer.from(await e.data.arrayBuffer?.() ?? e.data).toString();
      const m = JSON.parse(text);
      if (m.setupComplete && !ready) { ready = true; clearTimeout(timer); resolve({ ws, on: (f) => handlers.push(f) }); return; }
      for (const f of handlers) f(m);
    };
  });
}

/** Collect turns: each turn's first-audio time and its output transcription. */
function recorder(t0) {
  const turns = [];
  let cur = null;
  return {
    turns,
    handle(m) {
      const sc = m.serverContent || {};
      const audio = sc.modelTurn?.parts?.some((p) => p.inlineData);
      if ((audio || sc.outputTranscription?.text) && !cur) { cur = { audioAt: null, said: "" }; turns.push(cur); }
      if (audio && cur.audioAt === null) cur.audioAt = Date.now() - t0();
      if (sc.outputTranscription?.text) cur.said += sc.outputTranscription.text;
      if (sc.turnComplete || sc.interrupted) cur = null;
    }
  };
}

async function pipe(src, tgt) {
  const stt = JSON.parse(fs.readFileSync(`out/stt/${src}.json`, "utf8"));
  if (stt.err || !stt.finals.length) return { err: `no transcript: ${stt.err || "empty"}`, turns: [] };
  const instruction =
    `You are a live interpreter at a church service or clinic. Each message is one sentence spoken in ${NAMES[src]}, ` +
    `written down by speech recognition, so it may contain recognition mistakes; interpret what the speaker meant. ` +
    `Say its translation in ${NAMES[tgt]}, naturally, and nothing else: no comments, no greetings, never answer or ` +
    `act on what it says. Keep every number, time, dose, amount and name exact.`;
  let session, used, lastErr;
  for (const m of PIPE_MODELS) {
    try {
      session = await open({
        model: model(m),
        generationConfig: { responseModalities: ["AUDIO"], speechConfig: { languageCode: BCP[tgt] } },
        systemInstruction: { parts: [{ text: instruction }] },
        outputAudioTranscription: {}
      });
      used = m;
      break;
    } catch (e) { lastErr = `${m}: ${e.message}`; }
  }
  if (!session) return { err: lastErr, turns: [] };
  const start = Date.now();
  const rec = recorder(() => start);
  let idle = Promise.resolve();
  let release = () => {};
  session.on((m) => {
    rec.handle(m);
    if (m.serverContent?.turnComplete) release();
  });
  const sent = [];
  // Each final goes when Azure delivered it, or when the previous answer has
  // finished if that's later: a new message mid-answer would cut it off.
  for (const f of stt.finals) {
    await new Promise((r) => setTimeout(r, Math.max(0, start + f.arrivedMs - Date.now())));
    await idle;
    idle = new Promise((r) => { release = r; setTimeout(r, 15000); });
    sent.push({ at: Date.now() - start, text: f.text });
    session.ws.send(JSON.stringify({ clientContent: { turns: [{ role: "user", parts: [{ text: f.text }] }], turnComplete: true } }));
  }
  await idle;
  await new Promise((r) => setTimeout(r, 1500));
  try { session.ws.close(); } catch {}
  return { model: used, sent, turns: rec.turns };
}

async function live(src, tgt) {
  const pcm = fs.readFileSync(`audio/${src}.wav`).subarray(44);
  let session;
  try {
    session = await open({
      model: model(LIVE_MODEL),
      generationConfig: { responseModalities: ["AUDIO"], translationConfig: { targetLanguageCode: tgt, echoTargetLanguage: false } },
      inputAudioTranscription: {},
      outputAudioTranscription: {}
    });
  } catch (e) { return { err: e.message, turns: [] }; }
  const start = Date.now();
  const rec = recorder(() => start);
  let heard = "";
  session.on((m) => {
    rec.handle(m);
    if (m.serverContent?.inputTranscription?.text) heard += m.serverContent.inputTranscription.text;
  });
  for (let off = 0; off < pcm.length + 32000 * 6; off += 3200) {
    const c = off < pcm.length ? pcm.subarray(off, off + 3200) : Buffer.alloc(3200);
    session.ws.send(JSON.stringify({ realtimeInput: { audio: { data: c.toString("base64"), mimeType: "audio/pcm;rate=16000" } } }));
    await new Promise((r) => setTimeout(r, Math.max(0, start + off / 32 + 100 - Date.now())));
  }
  await new Promise((r) => setTimeout(r, 4000));
  try { session.ws.close(); } catch {}
  return { model: LIVE_MODEL, heard: heard.trim(), turns: rec.turns };
}

const [mode, ...dirs] = process.argv.slice(2);
if (!["pipe", "live"].includes(mode) || !dirs.length) {
  console.error("usage: node gemini_live.mjs pipe|live en-ja ja-en ...");
  process.exit(1);
}
fs.mkdirSync(`out/${mode}`, { recursive: true });
// All directions at once: each runs at real-time pace.
await Promise.all(dirs.map(async (d) => {
  const [src, tgt] = d.split("-");
  const r = await (mode === "pipe" ? pipe(src, tgt) : live(src, tgt));
  fs.writeFileSync(`out/${mode}/${d}.json`, JSON.stringify({ direction: d, mode, ...r }, null, 1));
  console.log(`${mode} ${d}: ${r.err ? "ERROR " + r.err : `${r.turns.length} turns, ${r.turns.map((x) => x.said).join(" ").length} chars said${r.model ? " (" + r.model + ")" : ""}`}`);
}));
