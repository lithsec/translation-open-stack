// Which Live model ids answer setup on this project, globally and in us-central1.
// Setup only: nothing is sent, nothing is billed.  TOK=... GOOGLE_CLOUD_PROJECT=... node probe_models.mjs
const TOK = process.env.TOK, P = process.env.GOOGLE_CLOUD_PROJECT;
const models = ["gemini-live-2.5-flash-native-audio", "gemini-live-2.5-flash", "gemini-live-2.5-flash-preview-native-audio-09-2025",
  "gemini-2.5-flash-native-audio-preview-09-2025", "gemini-2.0-flash-live-preview-04-09", "gemini-3.5-flash-live", "gemini-3.5-live",
  "gemini-3.5-live-translate-preview"];
const locs = ["global", "us-central1"];
const host = (l) => (l === "global" ? "aiplatform.googleapis.com" : `${l}-aiplatform.googleapis.com`);
const probe = (m, l) => new Promise((res) => {
  const ws = new WebSocket(`wss://${host(l)}/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent`, { headers: { Authorization: "Bearer " + TOK } });
  const done = (r) => { try { ws.close(); } catch {} res(r); };
  setTimeout(() => done("timeout"), 12000);
  ws.onopen = () => ws.send(JSON.stringify({ setup: { model: `projects/${P}/locations/${l}/publishers/google/models/${m}`,
    generationConfig: { responseModalities: ["AUDIO"] } } }));
  ws.onmessage = async (e) => { const t = typeof e.data === "string" ? e.data : Buffer.from(await e.data.arrayBuffer()).toString(); if (JSON.parse(t).setupComplete) done("OK"); };
  ws.onclose = (e) => done(`closed ${e.code} ${String(e.reason).slice(0, 70)}`);
});
for (const l of locs) for (const m of models) console.log(l.padEnd(12), m.padEnd(52), await probe(m, l));
