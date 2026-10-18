// Google's live speech-to-text model (gemini-3.5-transcribe-live, Gemini Live
// API on AI Studio) on audio/<lang>.wav, streamed at real-time pace in 100 ms
// chunks, then 3 s of silence and audioStreamEnd.
//
//   GEMINI_API_KEY=... node transcribe_live.mjs ht:auto ht:ht-HT fr:fr-FR fr:auto ...
//
// <lang>:<code> where code is a BCP-47 code for inputAudioTranscription.languageCodes
// or "auto" (empty list = automatic detection). Writes
// out/stt-transcribe-live/<lang>__<code>.json: every interim and final
// transcription with its arrival time (ms since the clip started), plus any
// error or close reason. The key is never printed.
import fs from "node:fs";

const KEY = process.env.GEMINI_API_KEY;
if (!KEY) { console.error("Set GEMINI_API_KEY."); process.exit(1); }
const MODEL = process.env.TRANSCRIBE_MODEL || "gemini-3.5-transcribe-live";
const URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent";
const OUT = "out/stt-transcribe-live";

async function run(lang, code) {
  const pcm = fs.readFileSync(`audio/${lang}.wav`).subarray(44);
  const setup = {
    model: `models/${MODEL}`,
    generationConfig: { responseModalities: ["TEXT"] },
    inputAudioTranscription: { languageCodes: code === "auto" ? [] : [code] }
  };
  const res = { lang, code, model: MODEL, setup, err: "", close: "", finals: [], interims: [], other: [] };
  let ws, start = 0, closed = false;
  try {
    ws = await new Promise((resolve, reject) => {
      const w = new WebSocket(`${URL}?key=${KEY}`);
      const timer = setTimeout(() => { try { w.close(); } catch {} reject(new Error("no setupComplete in 15 s")); }, 15000);
      let ready = false;
      w.onopen = () => w.send(JSON.stringify({ setup }));
      w.onclose = (e) => {
        closed = true;
        res.close = `${e.code} ${e.reason}`.trim();
        if (!ready) { clearTimeout(timer); reject(new Error(`closed ${res.close}`)); }
      };
      w.onmessage = async (e) => {
        const text = typeof e.data === "string" ? e.data : Buffer.from(await e.data.arrayBuffer()).toString();
        const m = JSON.parse(text);
        if (m.setupComplete && !ready) { ready = true; clearTimeout(timer); resolve(w); return; }
        const at = Date.now() - start;
        const sc = m.serverContent || {};
        if (sc.inputTranscription) res.finals.push({ at, ...sc.inputTranscription });
        if (sc.interimInputTranscription) res.interims.push({ at, ...sc.interimInputTranscription });
        const rest = { ...m, serverContent: { ...sc } };
        delete rest.serverContent.inputTranscription;
        delete rest.serverContent.interimInputTranscription;
        if (!Object.keys(rest.serverContent).length) delete rest.serverContent;
        if (Object.keys(rest).length && res.other.length < 200) res.other.push({ at, ...rest });
      };
    });
  } catch (e) {
    res.err = e.message;
    return res;
  }
  start = Date.now();
  const tail = 32000 * 3;
  for (let off = 0; off < pcm.length + tail && !closed; off += 3200) {
    const c = off < pcm.length ? pcm.subarray(off, off + 3200) : Buffer.alloc(3200);
    ws.send(JSON.stringify({ realtimeInput: { audio: { data: c.toString("base64"), mimeType: "audio/pcm;rate=16000" } } }));
    await new Promise((r) => setTimeout(r, Math.max(0, start + off / 32 + 100 - Date.now())));
  }
  if (!closed) ws.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } }));
  await new Promise((r) => setTimeout(r, 6000));
  if (closed && !res.err && Date.now() - start < pcm.length / 32) res.err = `closed early: ${res.close}`;
  try { ws.close(); } catch {}
  return res;
}

const jobs = process.argv.slice(2).map((a) => a.split(":"));
if (!jobs.length) { console.error("usage: node transcribe_live.mjs <lang>:<code|auto> ..."); process.exit(1); }
fs.mkdirSync(OUT, { recursive: true });
await Promise.all(jobs.map(async ([lang, code]) => {
  const r = await run(lang, code);
  fs.writeFileSync(`${OUT}/${lang}__${code}.json`, JSON.stringify(r, null, 1));
  console.log(`${lang} ${code}: ${r.err ? "ERROR " + r.err : `${r.finals.length} finals, ${r.interims.length} interims, close=${r.close || "-"}`}`);
}));
