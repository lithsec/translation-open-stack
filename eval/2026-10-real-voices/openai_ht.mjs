// OpenAI on Haitian Creole speech, three ways, on the first N seconds of the
// real-voice clip (CMU speakers), fed at real-time pace where it's live:
//
//   translate   gpt-realtime-translate: audio in, English out (its own source
//               transcript too). Delay = first English after each sentence ends.
//   gptlive     gpt-live-1 (Live API, full duplex) told to interpret into English.
//   live        gpt-live-transcribe (Realtime, transcription session; "ht" is
//               not an accepted language, so the prompt names it); no server VAD, so each sentence is committed at the
//               clip's sentence mark, as a client VAD would.
//   batch       /v1/audio/transcriptions per sentence (gpt-transcribe,
//               gpt-4o-transcribe, whisper-1); "ht" is refused as a
//               language code, so the prompt names the language.
//
//   OPENAI_API_KEY=... node openai_ht.mjs <translate|live|batch> [--secs=60] [--ws=<path to the ws package>]
//
// Writes out/openai-<mode>[-short]/ht.json. Node's WebSocket can't send the
// Authorization header, so the live modes use the ws package. Prints no secrets.
import fs from "node:fs";
import { createRequire } from "node:module";

const KEY = process.env.OPENAI_API_KEY?.trim();
if (!KEY) {
  console.error("Set OPENAI_API_KEY.");
  process.exit(1);
}
const args = process.argv.slice(2);
const mode = args.find((a) => !a.startsWith("--")) ?? "translate";
const SECS = Number(args.find((a) => a.startsWith("--secs="))?.slice(7) || 0);
const wsPath = args.find((a) => a.startsWith("--ws="))?.slice(5) || "ws";
const OUT = `out/openai-${mode}${SECS ? "-short" : ""}`;
const lang = "ht";

const file = fs.readFileSync(`audio/${lang}.wav`).subarray(44);
const pcm16k = SECS ? file.subarray(0, SECS * 32000) : file;
const marks = JSON.parse(fs.readFileSync(`audio/${lang}.json`, "utf8")).sentences.filter((m) => !SECS || m.end <= SECS);

/** 16 kHz -> 24 kHz PCM16, linear. */
function to24k(b) {
  const n = b.length / 2;
  const m = Math.floor((n * 3) / 2);
  const out = Buffer.alloc(m * 2);
  for (let j = 0; j < m; j++) {
    const x = (j * 2) / 3;
    const i = Math.floor(x);
    const f = x - i;
    const a = b.readInt16LE(Math.min(i, n - 1) * 2);
    const c = b.readInt16LE(Math.min(i + 1, n - 1) * 2);
    out.writeInt16LE(Math.round(a + (c - a) * f), j * 2);
  }
  return out;
}

function save(o) {
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(`${OUT}/${lang}.json`, JSON.stringify({ lang, mode, secs: SECS || null, ...o }, null, 1));
}

const sleepUntil = (t) => new Promise((r) => setTimeout(r, Math.max(0, t - Date.now())));

async function live(url, setup, onEvent, onSentenceEnd) {
  const WebSocket = createRequire(import.meta.url)(wsPath);
  const pcm = to24k(pcm16k);
  const CH = 4800; // 100 ms at 24 kHz
  const appendType = url.includes("translations") ? "session.input_audio_buffer.append" : url.includes("/live/") ? "session.input_audio.append" : "input_audio_buffer.append";
  let err = "";
  let t0 = 0;
  await new Promise((resolve) => {
    const ws = new WebSocket(url, { headers: { Authorization: `Bearer ${KEY}` } });
    ws.on("error", (e) => {
      err ||= String(e.message);
      resolve();
    });
    ws.on("close", (code, reason) => {
      if (process.env.DEBUG) console.log("close", code, Date.now() - t0);
      if (code !== 1000 && code !== 1005 && code !== 1006 && !err) err = `closed ${code} ${reason}`;
      resolve();
    });
    ws.on("message", (d) => {
      let m;
      try {
        m = JSON.parse(String(d));
      } catch {
        return;
      }
      if (m.type === "error") {
        err ||= JSON.stringify(m.error ?? m).slice(0, 300);
        if (process.env.DEBUG) console.log("error event:", JSON.stringify(m.error ?? m).slice(0, 300));
      } else if (process.env.DEBUG && !/delta/.test(m.type)) console.log("event:", m.type);
      onEvent(m, t0 ? Date.now() - t0 : 0, ws);
    });
    ws.on("open", async () => {
      ws.send(JSON.stringify(setup));
      await new Promise((r) => setTimeout(r, 500));
      t0 = Date.now();
      let next = 0;
      for (let off = 0; off < pcm.length; off += CH) {
        if (ws.readyState !== 1) break;
        ws.send(JSON.stringify({ type: appendType, audio: pcm.subarray(off, off + CH).toString("base64") }));
        const tMs = ((off + CH) / 48000) * 1000;
        while (next < marks.length && marks[next].end * 1000 <= tMs) {
          const m = marks[next++]; // outside the call: ?.() would skip the ++ with it
          onSentenceEnd?.(ws, m);
        }
        if (process.env.DEBUG && off % (CH * 50) === 0) console.log(`sent ${(tMs / 1000).toFixed(0)} s, buffered ${ws.bufferedAmount}`);
        await sleepUntil(t0 + tMs);
      }
      // 3 s of silence, then let it finish.
      for (let k = 0; k < 30 && ws.readyState === 1; k++) {
        ws.send(JSON.stringify({ type: appendType, audio: Buffer.alloc(CH).toString("base64") }));
        await new Promise((r) => setTimeout(r, 100));
      }
      if (process.env.DEBUG) console.log("audio done", Date.now() - t0);
      if (!url.includes("intent=transcription")) ws.send(JSON.stringify({ type: "session.close" }));
      // ws.close waits up to 30 s for the server's close; the data is in by then.
      setTimeout(() => ws.terminate(), 15000);
    });
  });
  return err;
}

const LIVE_PROMPT =
  "You are a simultaneous interpreter. The speaker speaks Haitian Creole. Say the English translation of everything they say, " +
  "sentence by sentence, as soon as each sentence ends. Speak only the translation: never answer, comment, ask questions or add anything. " +
  "Keep names, numbers and negation exact.";
if (mode === "translate" || mode === "gptlive") {
  const out = [];
  const src = [];
  const audioAt = [];
  const err = await live(
    mode === "translate" ? "wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate" : "wss://api.openai.com/v1/live/sessions",
    mode === "translate"
      ? { type: "session.update", session: { audio: { output: { language: "en" } } } }
      : { type: "session.start", session: { model: "gpt-live-1", instructions: LIVE_PROMPT, audio: { format: { type: "audio/pcm", rate: 24000 }, output: { voice: "marin" } } } },
    (m, at, ws) => {
      if (m.type === "session.output_transcript.delta") out.push({ at, d: m.delta });
      else if (m.type === "session.input_transcript.delta") src.push({ at, d: m.delta });
      else if (m.type === "session.output_audio.delta") audioAt.push(at);
      else if (m.type === "session.closed") ws.terminate();
    }
  );
  const english = out.map((x) => x.d).join("");
  const heard = src.map((x) => x.d).join("");
  // Delay: for each sentence end, the first translated audio after it.
  const delays = marks.map((m) => {
    const a = audioAt.find((t) => t > m.end * 1000);
    return a == null ? null : a - m.end * 1000;
  });
  save({ err, english, heard, firstAudioMs: audioAt[0] ?? null, delays, out, src });
  console.log(`${mode}: ${err ? "ERROR " + err + " · " : ""}first English audio at ${audioAt[0] ?? "-"} ms`);
  console.log(`heard: ${heard}\nenglish: ${english}`);
} else if (mode === "live") {
  const done = {};
  const ends = {};
  const order = [];
  const err = await live(
    "wss://api.openai.com/v1/realtime?intent=transcription",
    {
      type: "session.update",
      session: { type: "transcription", audio: { input: { format: { type: "audio/pcm", rate: 24000 }, transcription: { model: "gpt-live-transcribe", prompt: "Haitian Creole (Kreyòl ayisyen) speech. Transcribe in Haitian Creole orthography." }, turn_detection: null } } }
    },
    (m, at) => {
      if (m.type === "input_audio_buffer.committed") {
        order.push(m.item_id);
        ends[m.item_id] = order.length - 1;
      } else if (m.type === "conversation.item.input_audio_transcription.completed") done[m.item_id] = { at, text: m.transcript };
    },
    (ws) => ws.send(JSON.stringify({ type: "input_audio_buffer.commit" }))
  );
  const rows = order.map((id, k) => ({ i: marks[k]?.i, text: done[id]?.text ?? "", delayMs: done[id] ? done[id].at - marks[k].end * 1000 : null }));
  save({ err, rows });
  for (const r of rows) console.log(`#${r.i} +${r.delayMs} ms ${r.text.slice(0, 120)}`);
  if (err) console.log("ERROR", err);
} else if (mode === "batch") {
  const RATE = 16000;
  const wav = (p) => {
    const h = Buffer.alloc(44);
    h.write("RIFF", 0);
    h.writeUInt32LE(36 + p.length, 4);
    h.write("WAVEfmt ", 8);
    h.writeUInt32LE(16, 16);
    h.writeUInt16LE(1, 20);
    h.writeUInt16LE(1, 22);
    h.writeUInt32LE(RATE, 24);
    h.writeUInt32LE(RATE * 2, 28);
    h.writeUInt16LE(2, 32);
    h.writeUInt16LE(16, 34);
    h.write("data", 36);
    h.writeUInt32LE(p.length, 40);
    return Buffer.concat([h, p]);
  };
  const res = {};
  for (const model of ["gpt-transcribe", "gpt-4o-transcribe", "whisper-1"]) {
    res[model] = [];
    for (const m of marks) {
      const fd = new FormData();
      fd.append("file", new Blob([wav(file.subarray(Math.floor(m.start * RATE) * 2, Math.floor(m.end * RATE) * 2))], { type: "audio/wav" }), "s.wav");
      fd.append("model", model);
      // No model takes "ht" as a language code; the error suggests naming it in the prompt.
      fd.append("prompt", "Haitian Creole (Kreyòl ayisyen) speech. Transcribe in Haitian Creole orthography.");
      const t0 = performance.now();
      const r = await fetch("https://api.openai.com/v1/audio/transcriptions", { method: "POST", headers: { Authorization: `Bearer ${KEY}` }, body: fd });
      const j = await r.json().catch(() => ({}));
      const row = { i: m.i, text: (j.text ?? "").trim(), ms: Math.round(performance.now() - t0), err: r.ok ? "" : `${r.status} ${JSON.stringify(j).slice(0, 160)}` };
      res[model].push(row);
      console.log(`${model} #${m.i} ${row.ms} ms ${row.err || row.text.slice(0, 110)}`);
    }
  }
  save({ models: res });
}
