// Haitian Creole TTS: gpt-4o-mini-tts (Azure eastus2) vs Gemini flash-tts / flash-lite-tts, blind judged.
//   GK=<gemini key> AK=<azure key> node run.mjs gen|judge|timing
import fs from "node:fs";
import { execFileSync } from "node:child_process";
const GK = process.env.GK, AK = process.env.AK;
const AZ = "https://lithos-foundry-eastus2.cognitiveservices.azure.com/openai/deployments/gpt-4o-mini-tts/audio/speech?api-version=2025-03-01-preview";
const all = JSON.parse(fs.readFileSync(process.env.HOME + "/dev/translation-open-stack/eval/2026-10-real-voices/sentences/ht.json"));
const INSTR = "Speak in Haitian Creole (Kreyòl ayisyen) with a natural native Haitian accent and Haitian pronunciation, not French.";
const variants = {
  "gemini-flash": (t) => gemini("gemini-3.8-flash-tts", t),
  "gemini-lite": (t) => gemini("gemini-3.8-flash-lite-tts", t),
  "oai-coral": (t) => oai(t, "coral"),
  "oai-coral-instr": (t) => oai(t, "coral", INSTR),
  "oai-sage-instr": (t) => oai(t, "sage", INSTR),
};
async function gemini(model, text) {
  const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, { method: "POST",
    headers: { "content-type": "application/json", "x-goog-api-key": GK },
    body: JSON.stringify({ contents: [{ parts: [{ text }] }], generationConfig: { responseModalities: ["AUDIO"], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: "Kore" } } } } }) });
  const j = await r.json();
  const d = j.candidates?.[0]?.content?.parts?.find((p) => p.inlineData)?.inlineData?.data;
  if (!d) throw new Error(`${model} ${r.status} ${JSON.stringify(j).slice(0, 200)}`);
  return Buffer.from(d, "base64");
}
async function oai(text, voice, instructions, onFirst) {
  const t0 = Date.now();
  const r = await fetch(AZ, { method: "POST", headers: { "content-type": "application/json", "api-key": AK },
    body: JSON.stringify({ model: "gpt-4o-mini-tts", input: text, voice, response_format: "pcm", ...(instructions ? { instructions } : {}) }) });
  if (!r.ok) throw new Error(`oai ${r.status} ${(await r.text()).slice(0, 200)}`);
  const chunks = []; let first = null;
  for await (const c of r.body) { if (first === null) first = Date.now() - t0; chunks.push(Buffer.from(c)); }
  onFirst?.(first);
  return Buffer.concat(chunks);
}
const wav = (pcm, path) => { fs.writeFileSync(path + ".pcm", pcm); execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", path + ".pcm", path + ".wav"]); };

const cmd = process.argv[2];
if (cmd === "gen") {
  const out = [];
  for (const [v, f] of Object.entries(variants)) for (let i = 0; i < 6; i++) {
    try { const pcm = await f(all[i]); const p = `${v}__${i}`; wav(pcm, p); out.push({ v, i, file: p + ".wav", text: all[i], secs: pcm.length / 48000 }); }
    catch (e) { console.error(v, i, e.message); }
  }
  fs.writeFileSync("samples.json", JSON.stringify(out, null, 1)); console.log(out.length, "samples");
} else if (cmd === "judge") {
  const s = JSON.parse(fs.readFileSync("samples.json")).map((x) => ({ x, k: Math.random() })).sort((a, b) => a.k - b.k).map((o) => o.x);
  const res = [];
  for (const x of s) {
    const audio = fs.readFileSync(x.file).toString("base64");
    const prompt = `You are an expert in Haitian Creole phonetics. The audio is a speech synthesizer reading this Haitian Creole text: "${x.text}".
Judge it. Answer ONLY JSON: {"haitian_score":1-5 (5 = sounds like a native Haitian speaker, 1 = sounds like French or English pronunciation), "intelligibility":1-5 (5 = a Haitian listener understands every word), "read_instruction_aloud": true/false (did it speak any instruction or text not in the sentence?), "notes":"<=20 words"}`;
    const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent`, { method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": GK },
      body: JSON.stringify({ contents: [{ parts: [{ inlineData: { mimeType: "audio/wav", data: audio } }, { text: prompt }] }], generationConfig: { responseMimeType: "application/json" } }) });
    const j = await r.json(); const t = j.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") ?? "";
    let v; try { v = JSON.parse(t); } catch { v = { err: t.slice(0, 100) || JSON.stringify(j).slice(0, 150) }; }
    res.push({ ...x, ...v });
  }
  fs.writeFileSync("judge.json", JSON.stringify(res, null, 1));
  const by = {};
  for (const r of res) (by[r.v] ??= []).push(r);
  for (const [v, rs] of Object.entries(by)) {
    const m = (k) => (rs.reduce((a, r) => a + (Number(r[k]) || 0), 0) / rs.length).toFixed(2);
    console.log(v.padEnd(16), "haitian", m("haitian_score"), "intel", m("intelligibility"), "readAloud", rs.filter((r) => r.read_instruction_aloud === true).length, "/", rs.length);
  }
} else if (cmd === "timing") {
  for (const [v, voice, ins] of [["oai-coral", "coral"], ["oai-coral-instr", "coral", INSTR]]) {
    const ts = [];
    for (let i = 6; i < 12; i++) await oai(all[i], voice, ins, (f) => ts.push(f));
    ts.sort((a, b) => a - b);
    console.log(v, "first audio ms median", ts[Math.floor(ts.length / 2)], "all", ts.join(","));
  }
}
