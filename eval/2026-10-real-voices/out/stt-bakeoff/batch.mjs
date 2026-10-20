// STT bake-off (2026-10-19), batch systems on audio/<lang>.wav.
//
//   node out/stt-bakeoff/batch.mjs <system> en ja km lo     (run from eval/2026-10-real-voices)
//
// systems:
//   el-scribe-v2        ElevenLabs Scribe v2 batch, whole clip, language_code given
//   aai-batch           AssemblyAI batch, whole clip, language_code given, newest Universal
//                       first with Universal-2 as fallback (speech_model_used recorded)
//   oai:<model>         OpenAI /v1/audio/transcriptions per sentence (gpt-transcribe,
//                       gpt-4o-transcribe, gpt-4o-mini-transcribe), language given;
//                       if the code is refused, the prompt names the language instead
//   gem:<model>         Gemini generateContent per sentence (AI Studio key), audio inline
//
// Per-sentence systems cut each sentence with ffmpeg at the clip's own marks
// (audio/<lang>.json) into out/stt-bakeoff/.cuts/ (not committed). "ms" per
// sentence = request round trip, i.e. the delay after a sentence ends if it
// were sent the moment it ended. Writes out/stt-bakeoff/raw/<system>/<lang>.json.
// Keys come from the environment and are never printed or stored.
import fs from "node:fs";
import { execFileSync } from "node:child_process";

const [system, ...langs] = process.argv.slice(2);
const OUT = `out/stt-bakeoff/raw/${system.replace(":", "__")}`;
const NAME = { en: "English", ja: "Japanese", km: "Khmer", lo: "Lao" };
const SCRIPT = { en: "Latin script", ja: "Japanese script (kanji and kana)", km: "Khmer script", lo: "Lao script (not Thai)" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function cuts(lang) {
  const marks = JSON.parse(fs.readFileSync(`audio/${lang}.json`, "utf8")).sentences;
  const dir = `out/stt-bakeoff/.cuts/${lang}`;
  fs.mkdirSync(dir, { recursive: true });
  return marks.map((m) => {
    const f = `${dir}/${String(m.i).padStart(2, "0")}.wav`;
    if (!fs.existsSync(f))
      execFileSync("ffmpeg", ["-loglevel", "error", "-y", "-i", `audio/${lang}.wav`, "-ss", String(m.start), "-to", String(m.end), "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", f]);
    return { ...m, file: f };
  });
}

async function pool(items, n, fn) {
  const out = new Array(items.length);
  let k = 0;
  await Promise.all(Array.from({ length: n }, async () => {
    while (k < items.length) {
      const i = k++;
      out[i] = await fn(items[i]);
    }
  }));
  return out;
}

async function retry(fn, tries = 4) {
  for (let t = 1; ; t++) {
    try {
      return await fn();
    } catch (e) {
      if (t >= tries || !/429|500|502|503|504|fetch failed|ECONNRESET|timeout/i.test(String(e?.message || e))) throw e;
      await sleep(2000 * t);
    }
  }
}

// ---- ElevenLabs Scribe v2 batch
async function elevenlabs(lang) {
  const KEY = process.env.ELEVENLABS_API_KEY?.trim();
  const CODE = { en: "eng", ja: "jpn", km: "khm", lo: "lao" };
  const fd = new FormData();
  fd.append("file", new Blob([fs.readFileSync(`audio/${lang}.wav`)], { type: "audio/wav" }), `${lang}.wav`);
  fd.append("model_id", "scribe_v2");
  fd.append("language_code", CODE[lang]);
  fd.append("tag_audio_events", "false");
  fd.append("timestamps_granularity", "word");
  const t0 = performance.now();
  const r = await fetch("https://api.elevenlabs.io/v1/speech-to-text", { method: "POST", headers: { "xi-api-key": KEY }, body: fd });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) return { err: `${r.status} ${JSON.stringify(j).slice(0, 300)}` };
  const words = (j.words ?? []).filter((w) => w.type === "word").map((w) => ({ t: w.text, s: w.start, e: w.end }));
  return { err: "", model: "scribe_v2", language: j.language_code, language_probability: j.language_probability, ms: Math.round(performance.now() - t0), text: (j.text ?? "").trim(), words };
}

// ---- AssemblyAI batch, whole clip
async function assemblyai(lang) {
  const KEY = process.env.ASSEMBLYAI_API_KEY?.trim();
  const API = "https://api.assemblyai.com/v2";
  const H = { authorization: KEY };
  const t0 = performance.now();
  const up = await fetch(`${API}/upload`, { method: "POST", headers: { ...H, "content-type": "application/octet-stream" }, body: fs.readFileSync(`audio/${lang}.wav`) });
  const u = await up.json().catch(() => ({}));
  if (!up.ok) return { err: `upload ${up.status} ${JSON.stringify(u).slice(0, 200)}` };
  const tried = [];
  for (const models of [["universal-3-6-pro", "universal-2"], ["universal-3-5-pro", "universal-2"], ["universal-2"]]) {
    const sub = await fetch(`${API}/transcript`, {
      method: "POST",
      headers: { ...H, "content-type": "application/json" },
      body: JSON.stringify({ audio_url: u.upload_url, speech_models: models, language_code: lang })
    });
    const s = await sub.json().catch(() => ({}));
    if (!sub.ok || !s.id) {
      tried.push(`${models.join("+")}: ${sub.status} ${JSON.stringify(s).slice(0, 200)}`);
      continue;
    }
    for (;;) {
      await sleep(1000);
      const g = await (await fetch(`${API}/transcript/${s.id}`, { headers: H })).json();
      if (g.status === "completed" || g.status === "error") {
        await fetch(`${API}/transcript/${s.id}`, { method: "DELETE", headers: H }).catch(() => {});
        if (g.status === "error") {
          tried.push(`${models.join("+")}: ${String(g.error).slice(0, 200)}`);
          break;
        }
        return { err: "", requested: models, model: g.speech_model_used ?? g.speech_model ?? null, language: g.language_code, tried, ms: Math.round(performance.now() - t0), text: (g.text ?? "").trim() };
      }
    }
  }
  return { err: tried.join(" | ") };
}

// ---- OpenAI per sentence
async function openai(lang, model) {
  const KEY = process.env.OPENAI_API_KEY?.trim();
  const plural = model === "gpt-transcribe";
  let useCode = true;
  const prompt = `${NAME[lang]} speech. Transcribe verbatim in ${NAME[lang]}, in ${SCRIPT[lang]}.`;
  const one = async (m) => {
    for (;;) {
      const fd = new FormData();
      fd.append("file", new Blob([fs.readFileSync(m.file)], { type: "audio/wav" }), "s.wav");
      fd.append("model", model);
      if (useCode) fd.append(plural ? "languages[]" : "language", lang);
      else fd.append("prompt", prompt);
      const t0 = performance.now();
      const r = await retry(async () => {
        const r = await fetch("https://api.openai.com/v1/audio/transcriptions", { method: "POST", headers: { Authorization: `Bearer ${KEY}` }, body: fd });
        if (r.status === 429 || r.status >= 500) throw new Error(`${r.status}`);
        return r;
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok && useCode && r.status === 400 && /language|invalid_value/i.test(JSON.stringify(j))) {
        useCode = false;
        console.log(`${model} ${lang}: code refused (${JSON.stringify(j).slice(0, 160)}), naming it in the prompt`);
        continue;
      }
      return { i: m.i, text: (j.text ?? "").trim(), ms: Math.round(performance.now() - t0), usage: j.usage ?? null, err: r.ok ? "" : `${r.status} ${JSON.stringify(j).slice(0, 200)}` };
    }
  };
  const ms = cuts(lang);
  const first = await one(ms[0]); // settles useCode before the pool
  const rest = await pool(ms.slice(1), 4, one);
  const rows = [first, ...rest];
  return { err: rows.filter((r) => r.err).map((r) => `#${r.i} ${r.err}`).join(" | "), model, languageGiven: useCode ? lang : `prompt: ${prompt}`, rows, text: rows.map((r) => r.text).join(" ") };
}

// ---- Gemini per sentence
async function gemini(lang, model) {
  const KEY = process.env.GEMINI_API_KEY?.trim();
  const prompt = `Transcribe this audio verbatim in ${NAME[lang]}, in its own script (${SCRIPT[lang]}). No translation, no commentary, no timestamps: output only the transcript.`;
  const thinking = /pro/.test(model) ? { thinkingLevel: "low" } : { thinkingLevel: "minimal" };
  const one = async (m) => {
    // An empty answer (no candidates) is retried up to twice; the last one is kept.
    let r;
    for (let k = 0; k < 3; k++) {
      r = await once(m);
      if (r.text || r.err) break;
    }
    return { ...r, attempts: r.attempts };
  };
  const once = async (m) => {
    const body = {
      contents: [{ role: "user", parts: [{ inlineData: { mimeType: "audio/wav", data: fs.readFileSync(m.file).toString("base64") } }, { text: prompt }] }],
      generationConfig: { temperature: 0, thinkingConfig: thinking }
    };
    const t0 = performance.now();
    let j, status;
    try {
      j = await retry(async () => {
        const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
          method: "POST",
          headers: { "content-type": "application/json", "x-goog-api-key": KEY },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(180000)
        });
        status = r.status;
        const j = await r.json().catch(() => ({}));
        if (r.status === 429 || r.status >= 500) throw new Error(`${r.status} ${JSON.stringify(j).slice(0, 120)}`);
        return j;
      });
    } catch (e) {
      return { i: m.i, text: "", ms: Math.round(performance.now() - t0), err: String(e.message).slice(0, 200) };
    }
    const text = (j.candidates?.[0]?.content?.parts ?? []).filter((p) => !p.thought).map((p) => p.text ?? "").join("").trim();
    if (process.env.VERBOSE) console.log(`  #${m.i} ${Math.round(performance.now() - t0)} ms ${status} ${text.slice(0, 60)}`);
    return { i: m.i, text, ms: Math.round(performance.now() - t0), usage: j.usageMetadata ?? null, finish: j.candidates?.[0]?.finishReason ?? null, blocked: j.promptFeedback?.blockReason ?? null, err: status === 200 ? "" : `${status} ${JSON.stringify(j.error ?? j).slice(0, 200)}` };
  };
  // Thinking-level names differ by model; fall back to no thinking config if refused.
  const ms = cuts(lang);
  let first = await one(ms[0]);
  if (first.err && /thinking/i.test(first.err)) {
    delete thinking.thinkingLevel;
    thinking.thinkingBudget = /pro/.test(model) ? 128 : 0;
    first = await one(ms[0]);
  }
  let rows;
  const prevFile = `${OUT}/${lang}.json`;
  if (process.env.ONLY_EMPTY && fs.existsSync(prevFile)) {
    // Re-ask only the sentences that came back empty last time (blocked / no candidates).
    const prev = JSON.parse(fs.readFileSync(prevFile, "utf8")).rows;
    rows = await pool(ms, 4, async (m) => {
      const p = prev.find((x) => x.i === m.i);
      return p?.text ? p : { ...(await one(m)), refilled: true };
    });
  } else rows = [first, ...(await pool(ms.slice(1), 4, one))];
  return { err: rows.filter((r) => r.err).map((r) => `#${r.i} ${r.err}`).join(" | "), model, prompt, thinking, rows, text: rows.map((r) => r.text).join(" ") };
}

for (const lang of langs) {
  const f = `${OUT}/${lang}.json`;
  if (fs.existsSync(f) && !JSON.parse(fs.readFileSync(f, "utf8")).err && !process.env.FORCE) {
    console.log(`${system} ${lang}: kept (done)`);
    continue;
  }
  let r;
  try {
    if (system === "el-scribe-v2") r = await elevenlabs(lang);
    else if (system === "aai-batch") r = await assemblyai(lang);
    else if (system.startsWith("oai:")) r = await openai(lang, system.slice(4));
    else if (system.startsWith("gem:")) r = await gemini(lang, system.slice(4));
    else throw new Error("unknown system");
  } catch (e) {
    r = { err: String(e?.message || e) };
  }
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(f, JSON.stringify({ system, lang, ...r }, null, 1));
  console.log(`${system} ${lang}: ${r.err ? "ERROR " + r.err.slice(0, 300) + " · " : ""}${(r.text ?? "").slice(0, 100)}`);
}
