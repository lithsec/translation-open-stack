// Times Gemini Flash REST on the 30 sentences exactly as the app's exception
// calls it (translateOnce in src/main/providers/omni.ts: same prompt,
// temperature 0, thinking default or 'low'), one call at a time, so each time
// is a clean send -> full answer. Timing only: quality is graded by
// translate_ht.py. No hedge to the fallback model (the app's 6 s / 3 s hedge
// is noted from these times instead).
//
//   GEMINI_API_KEY=... node text-mt/flash_timing_ht.mjs <inputs.json> <model> <default|low> [input]
// Writes text-mt/out/<input>__<model>[@low].timing.json and ...rerun.json (the text).
import fs from "node:fs";

const KEY = process.env.GEMINI_API_KEY;
if (!KEY) { console.error("Set GEMINI_API_KEY."); process.exit(1); }
const [inputsPath, MODEL, THINK, name = "omnilingual"] = process.argv.slice(2);
const sents = JSON.parse(fs.readFileSync(inputsPath, "utf8"))[name];
const timing = [], out = [];
for (let i = 0; i < sents.length; i++) {
  const prompt =
    `Translate this Haitian Creole sentence, transcribed from live speech (it may contain recognition errors), ` +
    `into natural English. Keep numbers, names and negation exact. Output only the English.\n` +
    `Sentence: ${sents[i]}`;
  const t0 = performance.now();
  const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent`, {
    method: "POST",
    headers: { "x-goog-api-key": KEY, "content-type": "application/json" },
    body: JSON.stringify({ contents: [{ role: "user", parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0, ...(THINK === "low" ? { thinkingConfig: { thinkingLevel: "low" } } : {}) } })
  });
  const j = await res.json();
  const ms = Math.round(performance.now() - t0);
  const t = (j.candidates?.[0]?.content?.parts ?? []).filter((p) => !p.thought).map((p) => p.text ?? "").join("").trim();
  timing.push({ i, ms, status: res.status, thoughtsTokens: j.usageMetadata?.thoughtsTokenCount ?? 0 });
  out.push(t);
  console.log(`${i} ${ms} ms ${res.status}: ${t.slice(0, 80)}`);
}
const tag = `${name}__${MODEL}${THINK === "low" ? "@low" : ""}`;
fs.writeFileSync(`text-mt/out/${tag}.timing.json`, JSON.stringify({ model: MODEL, thinking: THINK, timing }, null, 1));
fs.writeFileSync(`text-mt/out/${tag}.rerun.json`, JSON.stringify(out, null, 1));
