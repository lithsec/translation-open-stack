// AssemblyAI on Haitian Creole, sentence by sentence. Its live models don't
// list Haitian Creole; its batch Universal-3.5 Pro does. So each sentence is
// cut out (at the clip's own sentence marks, as the Gemini 2.5 Pro
// per-sentence test did) and sent as soon as it ends: upload, submit, poll.
// "Delay" = from the end of the sentence to the text coming back.
//
//   ASSEMBLYAI_API_KEY=... node assemblyai_batch.mjs ht [--secs=60] [--auto]
//
// Writes out/stt-assemblyai[-auto][-short]/<lang>.json. Prints no secrets.
import fs from "node:fs";

const KEY = process.env.ASSEMBLYAI_API_KEY?.trim();
if (!KEY) {
  console.error("Set ASSEMBLYAI_API_KEY.");
  process.exit(1);
}
const args = process.argv.slice(2);
const AUTO = args.includes("--auto");
const SECS = Number(args.find((a) => a.startsWith("--secs="))?.slice(7) || 0);
const lang = args.find((a) => !a.startsWith("--")) ?? "ht";
const OUT = "out/stt-assemblyai" + (AUTO ? "-auto" : "") + (SECS ? "-short" : "");
const API = "https://api.assemblyai.com/v2";
const H = { authorization: KEY };
const RATE = 16000;

function wav(pcm) {
  const h = Buffer.alloc(44);
  h.write("RIFF", 0);
  h.writeUInt32LE(36 + pcm.length, 4);
  h.write("WAVEfmt ", 8);
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20);
  h.writeUInt16LE(1, 22);
  h.writeUInt32LE(RATE, 24);
  h.writeUInt32LE(RATE * 2, 28);
  h.writeUInt16LE(2, 32);
  h.writeUInt16LE(16, 34);
  h.write("data", 36);
  h.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([h, pcm]);
}

async function transcribe(pcm) {
  const t0 = performance.now();
  const up = await fetch(`${API}/upload`, { method: "POST", headers: { ...H, "content-type": "application/octet-stream" }, body: wav(pcm) });
  const u = await up.json().catch(() => ({}));
  if (!up.ok || !u.upload_url) throw new Error(`upload ${up.status}: ${JSON.stringify(u).slice(0, 200)}`);
  const uploadedMs = performance.now() - t0;
  const sub = await fetch(`${API}/transcript`, {
    method: "POST",
    headers: { ...H, "content-type": "application/json" },
    body: JSON.stringify({
      audio_url: u.upload_url,
      speech_models: ["universal-3-5-pro", "universal-2"],
      ...(AUTO ? {} : { language_code: lang })
    })
  });
  const s = await sub.json().catch(() => ({}));
  if (!sub.ok || !s.id) throw new Error(`submit ${sub.status}: ${JSON.stringify(s).slice(0, 200)}`);
  for (;;) {
    await new Promise((r) => setTimeout(r, 250));
    const g = await (await fetch(`${API}/transcript/${s.id}`, { headers: H })).json();
    if (g.status === "completed" || g.status === "error") {
      // Delete it: nothing of ours is kept there longer than the test needs.
      await fetch(`${API}/transcript/${s.id}`, { method: "DELETE", headers: H }).catch(() => {});
      return {
        text: (g.text ?? "").trim(),
        err: g.status === "error" ? String(g.error).slice(0, 200) : "",
        model: g.speech_model_used ?? g.speech_model ?? null,
        language: g.language_code ?? null,
        uploadedMs: Math.round(uploadedMs),
        totalMs: Math.round(performance.now() - t0)
      };
    }
  }
}

const all = fs.readFileSync(`audio/${lang}.wav`).subarray(44);
const marks = JSON.parse(fs.readFileSync(`audio/${lang}.json`, "utf8")).sentences.filter((m) => !SECS || m.end <= SECS);
const rows = [];
for (const m of marks) {
  const pcm = all.subarray(Math.floor(m.start * RATE) * 2, Math.floor(m.end * RATE) * 2);
  try {
    const r = await transcribe(pcm);
    rows.push({ i: m.i, start: m.start, end: m.end, ...r });
    console.log(`#${m.i} ${(m.end - m.start).toFixed(1)} s audio -> text after ${(r.totalMs / 1000).toFixed(1)} s (upload ${r.uploadedMs} ms) [${r.model}, ${r.language}] ${r.err || r.text.slice(0, 110)}`);
  } catch (e) {
    rows.push({ i: m.i, err: String(e?.message || e) });
    console.log(`#${m.i} ERROR ${e?.message || e}`);
  }
}
fs.mkdirSync(OUT, { recursive: true });
fs.writeFileSync(`${OUT}/${lang}.json`, JSON.stringify({ lang, auto: AUTO, secs: SECS || null, rows }, null, 1));
