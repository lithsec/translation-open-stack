// ElevenLabs text-to-speech as the room voice: September's 24 sentences per
// language (numbers, times, doses, negations) read by one voice, streamed.
// Measures time to first audio byte and to the last, and saves each reading
// for listening and for the naturalness grader.
//
//   ELEVENLABS_API_KEY=... node elevenlabs_tts.mjs --models     (what each model says it speaks)
//   ELEVENLABS_API_KEY=... node elevenlabs_tts.mjs es en ja ht fr km lo
//   ELEVENLABS_MODEL=eleven_turbo_v2_5 ELEVENLABS_VOICE_ID=... node elevenlabs_tts.mjs es
//
// Defaults: model eleven_flash_v2_5, the first premade voice on the account,
// 16 kHz PCM (what the Pis play). Writes out/tts-<model>/<lang>/NN.wav and
// out/tts-<model>/<lang>.json. A language the model doesn't list is still
// tried (language_code is ignored by the server then) and marked. Prints no
// secrets.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KEY = process.env.ELEVENLABS_API_KEY?.trim();
if (!KEY) {
  console.error("Set ELEVENLABS_API_KEY.");
  process.exit(1);
}
const API = "https://api.elevenlabs.io";
const MODEL = process.env.ELEVENLABS_MODEL || "eleven_flash_v2_5";
const RATE = 16000;
const H = { "xi-api-key": KEY };
const args = process.argv.slice(2);

async function getJson(url) {
  const r = await fetch(API + url, { headers: H });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${url} ${r.status}: ${JSON.stringify(b).slice(0, 200)}`);
  return b;
}

// A restricted key may lack models_read / voices_read: then the language list
// is unknown and the voice falls back to a premade one (George).
const models = await getJson("/v1/models").catch((e) => {
  console.log(`(models unreadable with this key: ${e.message.slice(0, 90)})`);
  return null;
});
if (args.includes("--models")) {
  if (!models) process.exit(1);
  for (const m of models.filter((m) => m.can_do_text_to_speech)) {
    console.log(`${m.model_id}: ${(m.languages ?? []).map((l) => l.language_id).join(" ")}`);
  }
  process.exit(0);
}
const model = models ? models.find((m) => m.model_id === MODEL) : { languages: null };
if (!model) {
  console.error(`No model ${MODEL} on this account; try --models.`);
  process.exit(1);
}
const listed = model.languages ? new Set(model.languages.map((l) => l.language_id)) : null;

let voice = process.env.ELEVENLABS_VOICE_ID?.trim();
if (!voice) {
  const { voices } = await getJson("/v1/voices").catch(() => ({ voices: [{ name: "George (premade)", voice_id: "JBFqnCBsd6RMkjVDRZzb", category: "premade" }] }));
  const v = voices.find((v) => v.category === "premade") ?? voices[0];
  if (!v) throw new Error("No voices on this account.");
  voice = v.voice_id;
  console.log(`voice: ${v.name} (${v.voice_id}); set ELEVENLABS_VOICE_ID to choose another`);
}

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

async function say(text, lang) {
  const t0 = performance.now();
  const r = await fetch(`${API}/v1/text-to-speech/${voice}/stream?output_format=pcm_${RATE}`, {
    method: "POST",
    headers: { ...H, "Content-Type": "application/json" },
    body: JSON.stringify({ text, model_id: MODEL, language_code: lang })
  });
  if (!r.ok) throw new Error(`tts ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const parts = [];
  let first = null;
  for await (const chunk of r.body) {
    if (first == null) first = performance.now() - t0;
    parts.push(Buffer.from(chunk));
  }
  const pcm = Buffer.concat(parts);
  return { firstMs: Math.round(first ?? 0), totalMs: Math.round(performance.now() - t0), audioMs: Math.round((pcm.length / 2 / RATE) * 1000), pcm, chars: text.length };
}

const pct = (xs, p) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.min(s.length - 1, Math.round(p * (s.length - 1)))] : null;
};

const OUT = path.join(HERE, "out", `tts-${MODEL}`);
for (const lang of args.filter((a) => !a.startsWith("--"))) {
  const file = path.join(HERE, "..", "2026-09-model-eval", "sentences", lang === "en" ? "en.json" : `src_${lang}.json`);
  const sentences = JSON.parse(fs.readFileSync(file, "utf8"));
  fs.mkdirSync(path.join(OUT, lang), { recursive: true });
  const rows = [];
  let err = "";
  for (const [i, text] of sentences.entries()) {
    try {
      const r = await say(text, lang);
      fs.writeFileSync(path.join(OUT, lang, `${String(i).padStart(2, "0")}.wav`), wav(r.pcm));
      rows.push({ i, text, firstMs: r.firstMs, totalMs: r.totalMs, audioMs: r.audioMs, chars: r.chars });
    } catch (e) {
      err = String(e?.message || e);
      break;
    }
  }
  const first = rows.map((r) => r.firstMs);
  const summary = {
    lang,
    model: MODEL,
    voice,
    listed: listed ? listed.has(lang) : null,
    err,
    first_audio_ms_median: pct(first, 0.5),
    first_audio_ms_p90: pct(first, 0.9),
    chars: rows.reduce((a, r) => a + r.chars, 0),
    rows
  };
  fs.writeFileSync(path.join(OUT, `${lang}.json`), JSON.stringify(summary, null, 1));
  console.log(
    `${lang} (${MODEL}${!listed ? "" : listed.has(lang) ? "" : ", NOT listed"}): ${err ? "ERROR " + err + " · " : ""}${rows.length}/${sentences.length} read; first audio ${summary.first_audio_ms_median} ms median, ${summary.first_audio_ms_p90} ms p90; ${summary.chars} characters`
  );
}
