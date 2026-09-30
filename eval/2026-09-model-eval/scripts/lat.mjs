import fs from "node:fs";
const [file, variant] = process.argv.slice(2);
const pcm = fs.readFileSync(file).subarray(44);
const tok = process.env.TOK;
const project = process.env.GOOGLE_CLOUD_PROJECT || process.env.VERTEX_PROJECT;
if (!project || !tok) { console.error("Set GOOGLE_CLOUD_PROJECT (or VERTEX_PROJECT) and TOK (e.g. TOK=$(gcloud auth print-access-token))."); process.exit(1); }
const extra = {
  base: {},
  lowstart: { realtimeInputConfig: { automaticActivityDetection: { startOfSpeechSensitivity: "START_SENSITIVITY_LOW" } } },
  fastend: { realtimeInputConfig: { automaticActivityDetection: { endOfSpeechSensitivity: "END_SENSITIVITY_HIGH", silenceDurationMs: 300 } } },
}[variant];
const ws = new WebSocket("wss://aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent", { headers: { Authorization: "Bearer " + tok } });
let t0 = 0, firstAudio = null, lastAudio = null, heard = "", said = "", err = "";
ws.onopen = () => ws.send(JSON.stringify({ setup: { model: `projects/${project}/locations/global/publishers/google/models/gemini-3.5-live-translate-preview`,
  generationConfig: { responseModalities: ["AUDIO"], translationConfig: { targetLanguageCode: process.env.TARGET || "es", echoTargetLanguage: false } },
  inputAudioTranscription: {}, outputAudioTranscription: {}, ...extra } }));
ws.onclose = (e) => { if (e.code !== 1000 && e.code !== 1005) err = `closed ${e.code} ${e.reason}`; };
ws.onmessage = async (e) => {
  const text = typeof e.data === "string" ? e.data : Buffer.from(await e.data.arrayBuffer?.() ?? e.data).toString();
  const m = JSON.parse(text);
  if (m.setupComplete) {
    t0 = Date.now(); let off = 0;
    const iv = setInterval(() => {
      const c = off < pcm.length ? pcm.subarray(off, off + 3200) : Buffer.alloc(3200);
      ws.send(JSON.stringify({ realtimeInput: { audio: { data: c.toString("base64"), mimeType: "audio/pcm;rate=16000" } } }));
      off += 3200; if (off > pcm.length + 32000 * 4) clearInterval(iv);
    }, 100);
  }
  const sc = m.serverContent || {};
  if (sc.modelTurn?.parts?.some((p) => p.inlineData)) { const t = (Date.now() - t0) / 1000; firstAudio ??= t; lastAudio = t; }
  if (sc.inputTranscription?.text) heard += sc.inputTranscription.text;
  if (sc.outputTranscription?.text) said += sc.outputTranscription.text;
};
setTimeout(() => {
  try { ws.close(); } catch {}
  console.log(JSON.stringify({ file, variant, err, firstAudio, lastAudio, heard: heard.trim(), said: said.trim() }));
  process.exit(0);
}, Number(process.env.WAIT || 17000));
