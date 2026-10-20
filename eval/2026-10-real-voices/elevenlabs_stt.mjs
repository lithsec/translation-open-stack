// ElevenLabs live speech-to-text (Scribe v2 Realtime) on audio/<lang>.wav, fed
// in real time, so "when did each final arrive" is what a room would see.
// Scribe lists Haitian Creole, which Azure doesn't.
//
//   ELEVENLABS_API_KEY=... node elevenlabs_stt.mjs ht fr en ja km lo
//   ... node elevenlabs_stt.mjs --auto ht     (no language given: Scribe detects)
//   ... node elevenlabs_stt.mjs --secs=40 ht  (a smoke test on the first 40 s; out/...-short)
//
// Writes out/stt-elevenlabs[-auto]/<lang>.json in azure_stt.py's shape (finals
// with text, offset/duration in the clip, arrival time). The key only buys a
// single-use token (Node's built-in WebSocket can't send headers); the token
// goes in the socket's query string. One clip at a time; a language already
// done is kept. Prints no secrets.
import fs from "node:fs";

const KEY = process.env.ELEVENLABS_API_KEY?.trim();
if (!KEY) {
  console.error("Set ELEVENLABS_API_KEY.");
  process.exit(1);
}
const args = process.argv.slice(2);
const AUTO = args.includes("--auto");
const SECS = Number(args.find((a) => a.startsWith("--secs="))?.slice(7) || 0);
const OUT = process.env.EL_OUT || (AUTO ? "out/stt-elevenlabs-auto" : "out/stt-elevenlabs") + (SECS ? "-short" : "");
// EL_VAD_SILENCE=0.5: end a turn after 0.5 s of silence (server default 1.5 s,
// longer than the clips' 0.8 s pauses, so sentences merge into long turns).
// ISO 639-3 where Scribe documents it; the 639-1 code otherwise.
const CODE = { ht: "hat", en: "en", fr: "fr", ja: "ja", km: "km", lo: "lo" };

async function token() {
  const r = await fetch("https://api.elevenlabs.io/v1/single-use-token/realtime_scribe", {
    method: "POST",
    headers: { "xi-api-key": KEY }
  });
  const b = await r.json().catch(() => ({}));
  if (!r.ok || !b.token) throw new Error(`token ${r.status}: ${JSON.stringify(b).slice(0, 200)}`);
  return b.token;
}

async function run(lang) {
  const all = fs.readFileSync(`audio/${lang}.wav`).subarray(44);
  const pcm = SECS ? all.subarray(0, SECS * 32000) : all;
  const save = (o) => {
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(`${OUT}/${lang}.json`, JSON.stringify({ lang, auto: AUTO, ...o }, null, 1));
  };
  const q = new URLSearchParams({
    model_id: "scribe_v2_realtime",
    audio_format: "pcm_16000",
    commit_strategy: "vad",
    ...(process.env.EL_VAD_SILENCE ? { vad_silence_threshold_secs: process.env.EL_VAD_SILENCE } : {}),
    include_timestamps: "true",
    include_language_detection: "true",
    // Zero retention is enterprise-only; on other plans the server may refuse
    // this, and the run says so rather than quietly logging.
    ...(process.env.ELEVENLABS_NO_LOGGING === "1" ? { enable_logging: "false" } : {}),
    token: await token()
  });
  if (!AUTO) q.set("language_code", CODE[lang] ?? lang);
  const finals = [];
  const partials = [];
  let err = "";
  let t0 = 0;
  let config = null;
  await new Promise((resolve) => {
    const ws = new WebSocket(`wss://api.elevenlabs.io/v1/speech-to-text/realtime?${q}`);
    ws.onerror = () => {};
    ws.onclose = (e) => {
      if (e.code !== 1000 && !err) err = `closed ${e.code} ${e.reason}`;
      resolve();
    };
    ws.onmessage = (e) => {
      let m;
      try {
        m = JSON.parse(typeof e.data === "string" ? e.data : Buffer.from(e.data).toString());
      } catch {
        return;
      }
      const at = Date.now() - t0;
      if (m.message_type === "session_started") config = m.config ?? null;
      else if (m.message_type === "partial_transcript" && m.text?.trim()) partials.push(at);
      else if (m.message_type === "committed_transcript_with_timestamps" && m.text?.trim()) {
        const words = (m.words ?? []).filter((w) => w.type !== "spacing");
        const start = words[0]?.start ?? 0;
        const end = words.at(-1)?.end ?? start;
        finals.push({ text: m.text.trim(), language: m.language_code ?? null, offsetMs: start * 1000, durationMs: (end - start) * 1000, arrivedMs: at });
      } else if (m.message_type === "committed_transcript" && m.text?.trim()) {
        // Kept only when the timestamped twin never comes (paired below).
        finals.push({ text: m.text.trim(), language: null, offsetMs: null, durationMs: null, arrivedMs: at, plain: true });
      } else if (m.message_type && m.message_type !== "partial_transcript" && "error" in m) {
        err = `${m.message_type}: ${String(m.error).slice(0, 200)}`;
      }
    };
    ws.onopen = async () => {
      t0 = Date.now();
      for (let off = 0; off < pcm.length; off += 3200) {
        if (ws.readyState !== 1) break;
        ws.send(JSON.stringify({ message_type: "input_audio_chunk", audio_base_64: pcm.subarray(off, off + 3200).toString("base64"), commit: false, sample_rate: 16000 }));
        await new Promise((r) => setTimeout(r, Math.max(0, t0 + off / 32 + 100 - Date.now())));
      }
      // 2 s of silence closes the last sentence; then a manual commit for luck.
      if (ws.readyState === 1) ws.send(JSON.stringify({ message_type: "input_audio_chunk", audio_base_64: Buffer.alloc(64000).toString("base64"), commit: true, sample_rate: 16000 }));
      await new Promise((r) => setTimeout(r, 4000));
      ws.close(1000);
    };
  });
  // A commit arrives as plain text and, with timestamps on, again with words:
  // keep the timestamped one where both came.
  const stamped = finals.filter((f) => !f.plain);
  const kept = stamped.length ? stamped : finals;
  save({ err, config, finals: kept, firstPartialMs: partials[0] ?? null });
  const lag = kept.filter((f) => f.offsetMs != null).map((f) => f.arrivedMs - (f.offsetMs + f.durationMs)).sort((a, b) => a - b);
  const said = {};
  for (const f of kept) said[f.language ?? "?"] = (said[f.language ?? "?"] ?? 0) + 1;
  console.log(`${lang} (elevenlabs${AUTO ? ", auto" : ""}): ${err ? "ERROR " + err + " · " : ""}${kept.length} finals, final arrives ~${Math.round(lag[Math.floor(lag.length / 2)] ?? 0)} ms after the words end; reported as ${JSON.stringify(said)}`);
}

const todo = args.filter((a) => !a.startsWith("--")).filter((l) => {
  try {
    const prev = JSON.parse(fs.readFileSync(`${OUT}/${l}.json`, "utf8"));
    if (!prev.err && prev.finals.length) {
      console.log(`${l}: kept (done)`);
      return false;
    }
  } catch {}
  return true;
});
for (const lang of todo) {
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      await run(lang);
    } catch (e) {
      console.log(`${lang} (elevenlabs): ERROR ${e?.cause?.code || e?.message || e}`);
      fs.mkdirSync(OUT, { recursive: true });
      fs.writeFileSync(`${OUT}/${lang}.json`, JSON.stringify({ lang, err: String(e?.message || e), finals: [] }));
    }
    let ok = false;
    try {
      const r = JSON.parse(fs.readFileSync(`${OUT}/${lang}.json`, "utf8"));
      ok = !r.err && r.finals.length > 0;
    } catch {}
    if (ok) break;
    if (attempt === 1) console.log(`${lang} (elevenlabs): trying once more`);
  }
}
