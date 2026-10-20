// STT bake-off (2026-10-19), live (streaming) systems on audio/<lang>.wav, fed
// at real-time pace in 100 ms chunks, then 3 s of silence.
//
//   node out/stt-bakeoff/live.mjs <system> en ja km lo     (run from eval/2026-10-real-voices)
//
// systems:
//   oai-live      OpenAI Realtime transcription session, gpt-live-transcribe
//                 (refuses server turn detection), language code given (or named
//                 in the prompt if the code is refused), 24 kHz PCM. A client VAD
//                 is simulated: the buffer is committed 500 ms after each
//                 sentence's speech end (out/stt-bakeoff/speech_ends.json, found
//                 from the audio as score_transcribe_live.py does).
//   aai-stream    AssemblyAI Universal Streaming v3, universal-3-6-pro,
//                 language_codes=[lang] (lists English and Japanese only).
//   (ElevenLabs Scribe v2 Realtime: ../../elevenlabs_stt.mjs, out/stt-elevenlabs/.)
//
// Each final: { text, arrivedMs (since the clip started), endMs (end of the
// speech it covers, by the vendor's own timestamps or VAD) }. Writes
// out/stt-bakeoff/raw/<system>/<lang>.json. Uses the ws package (headers).
// Keys from the environment, never printed or stored.
import fs from "node:fs";
import { createRequire } from "node:module";

const WS = createRequire(import.meta.url)(process.env.WS_PATH || "ws");
const [system, ...langs] = process.argv.slice(2);
const OUT = `out/stt-bakeoff/raw/${system}`;
const NAME = { en: "English", ja: "Japanese", km: "Khmer", lo: "Lao" };
const SCRIPT = { en: "Latin script", ja: "Japanese script", km: "Khmer script", lo: "Lao script (not Thai)" };
const sleepUntil = (t) => new Promise((r) => setTimeout(r, Math.max(0, t - Date.now())));

function to24k(b) {
  const n = b.length / 2, m = Math.floor((n * 3) / 2), out = Buffer.alloc(m * 2);
  for (let j = 0; j < m; j++) {
    const x = (j * 2) / 3, i = Math.floor(x), f = x - i;
    const a = b.readInt16LE(Math.min(i, n - 1) * 2), c = b.readInt16LE(Math.min(i + 1, n - 1) * 2);
    out.writeInt16LE(Math.round(a + (c - a) * f), j * 2);
  }
  return out;
}

async function stream({ url, headers, setup, pcm, bytesPerMs, binary, append, onMsg, finish, commits = [], onCommit }) {
  let err = "", t0 = 0;
  const CH = bytesPerMs * 100;
  await new Promise((resolve) => {
    const ws = new WS(url, { headers });
    let done = false;
    const end = () => { if (!done) { done = true; resolve(); } };
    ws.on("error", (e) => { err ||= String(e.message); end(); });
    ws.on("close", (code, reason) => { if (![1000, 1005, 1006].includes(code) && !err) err = `closed ${code} ${reason}`; end(); });
    ws.on("message", (d) => {
      let m;
      try { m = JSON.parse(String(d)); } catch { return; }
      if (m.type === "error" || m.error) err ||= JSON.stringify(m.error ?? m).slice(0, 300);
      onMsg(m, t0 ? Date.now() - t0 : 0, ws);
    });
    ws.on("open", async () => {
      if (setup) ws.send(JSON.stringify(setup));
      await new Promise((r) => setTimeout(r, 500));
      t0 = Date.now();
      const all = Buffer.concat([pcm, Buffer.alloc(bytesPerMs * 3000)]);
      for (let off = 0; off < all.length; off += CH) {
        if (ws.readyState !== 1) break;
        const chunk = all.subarray(off, off + CH);
        ws.send(binary ? chunk : JSON.stringify(append(chunk)));
        const sentMs = (off + CH) / bytesPerMs;
        while (commits.length && commits[0] <= sentMs) onCommit(ws, commits.shift());
        await sleepUntil(t0 + (off + CH) / bytesPerMs);
      }
      finish?.(ws);
      setTimeout(() => { try { ws.terminate(); } catch {} end(); }, 8000);
    });
  });
  return err;
}

async function oaiLive(lang) {
  const KEY = process.env.OPENAI_API_KEY?.trim();
  const pcm = to24k(fs.readFileSync(`audio/${lang}.wav`).subarray(44));
  const ends = JSON.parse(fs.readFileSync("out/stt-bakeoff/speech_ends.json", "utf8"))[lang];
  const run = async (useCode) => {
    const finals = [], interims = [], order = [], endOf = {};
    const transcription = { model: "gpt-live-transcribe", ...(useCode ? { language: lang } : { prompt: `${NAME[lang]} speech. Transcribe verbatim in ${NAME[lang]}, in ${SCRIPT[lang]}.` }) };
    const err = await stream({
      url: "wss://api.openai.com/v1/realtime?intent=transcription",
      headers: { Authorization: `Bearer ${KEY}` },
      setup: { type: "session.update", session: { type: "transcription", audio: { input: { format: { type: "audio/pcm", rate: 24000 }, transcription, turn_detection: null } } } },
      pcm, bytesPerMs: 48,
      append: (c) => ({ type: "input_audio_buffer.append", audio: c.toString("base64") }),
      commits: ends.map((e) => e + 500),
      onCommit: (ws, t) => { order.push(t - 500); ws.send(JSON.stringify({ type: "input_audio_buffer.commit" })); },
      onMsg: (m, at, ws) => {
        if (m.type === "error" && !finals.length && /invalid_value/.test(JSON.stringify(m))) ws.close(); // setup refused: stop early
        else if (m.type === "input_audio_buffer.committed") endOf[m.item_id] = order[Object.keys(endOf).length] ?? null;
        else if (m.type === "conversation.item.input_audio_transcription.delta") interims.push(at);
        else if (m.type === "conversation.item.input_audio_transcription.completed") finals.push({ text: (m.transcript ?? "").trim(), arrivedMs: at, endMs: endOf[m.item_id] ?? null, item: m.item_id });
      }
    });
    return { err, transcription, finals, firstInterimMs: interims[0] ?? null, interims: interims.length };
  };
  let r = await run(true);
  if (r.err && /language|invalid_value/i.test(r.err) && !r.finals.length) {
    console.log(`oai-live ${lang}: code refused (${r.err.slice(0, 150)}), naming it in the prompt`);
    r = { codeRefused: r.err, ...(await run(false)) };
  }
  return r;
}

async function aaiStream(lang) {
  const KEY = process.env.ASSEMBLYAI_API_KEY?.trim();
  const pcm = fs.readFileSync(`audio/${lang}.wav`).subarray(44);
  const q = new URLSearchParams({ speech_model: "universal-3-6-pro", sample_rate: "16000", encoding: "pcm_s16le", language_codes: JSON.stringify([lang]) });
  const finals = [];
  let begin = null, termination = null, interims = 0;
  const err = await stream({
    url: `wss://streaming.assemblyai.com/v3/ws?${q}`,
    headers: { Authorization: KEY },
    pcm, bytesPerMs: 32, binary: true,
    onMsg: (m, at) => {
      if (m.type === "Begin") begin = { configuration: m.configuration ?? null };
      else if (m.type === "Turn") {
        if (m.end_of_turn) {
          const w = m.words ?? [];
          finals.push({ text: (m.transcript ?? m.utterance ?? "").trim(), arrivedMs: at, endMs: w.length ? w.at(-1).end : null, language: m.language_code ?? null, formatted: m.turn_is_formatted });
        } else interims++;
      } else if (m.type === "Termination") termination = m;
    },
    finish: (ws) => ws.send(JSON.stringify({ type: "Terminate" }))
  });
  return { err, begin, termination, interims, finals };
}

for (const lang of langs) {
  let r;
  try {
    r = system === "oai-live" ? await oaiLive(lang) : system === "aai-stream" ? await aaiStream(lang) : { err: "unknown system" };
  } catch (e) {
    r = { err: String(e?.message || e), finals: [] };
  }
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(`${OUT}/${lang}.json`, JSON.stringify({ system, lang, ...r }, null, 1));
  const lag = r.finals.filter((f) => f.endMs != null).map((f) => f.arrivedMs - f.endMs).sort((a, b) => a - b);
  console.log(`${system} ${lang}: ${r.err ? "ERROR " + r.err + " · " : ""}${r.finals.length} finals, median lag ${lag[lag.length >> 1] ?? "-"} ms · ${r.finals.map((f) => f.text).join(" ").slice(0, 100)}`);
}
