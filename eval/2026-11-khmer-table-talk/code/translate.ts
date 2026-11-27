// The translators Talk can use, on the production prompt (lithos-server src/standard.ts speechPrompt, bundled in, so
// the instructions are exactly the app's), each sentence with the previous two of its set as context.
//   sol:    gpt-6-sol on our Foundry (gpt-6-sol-us), reasoning_effort "low" (foundry-effort.ts: every pair on gpt-6-sol)
//   flash:  gemini-3.5-flash, thinking "medium" (index.ts: Listen into Khmer at Standard, azure-gemini)
//   gemma:  google/gemma-4-31b-it on OpenRouter, the production body (gemma.ts gemmaBody: ZDR, named US hosts)
//   azure:  Azure Translator (api-version 3.0), on our AI Services resource
// Three requests at once per translator. Output: { "<set>:<arm>": [{ out, ms } ...] }.
//   node translate.cjs DATA OUT.json   (FOUNDRY_*, GEMINI_API_KEY, OPENROUTER_API_KEY, AZURE_TR_KEY, AZURE_TR_REGION)
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { speechPrompt } from "/Users/sstone/dev/lithos-server/src/standard";
import { gemmaBody, cleanGemma } from "/Users/sstone/dev/lithos-server/src/gemma";

const [D, OUT] = process.argv.slice(2) as [string, string];
const E = process.env;
type Job = { set: string; src: string; tgt: string; texts: string[] };
const set = JSON.parse(readFileSync(`${D}/set.json`, "utf8")) as { km_file: string; km: string; en: string }[];
const hyp = (f: string, key = "hyp") => {
  const rows = JSON.parse(readFileSync(`${D}/${f}`, "utf8")) as Record<string, string>[];
  const by = new Map(rows.map((r) => [r.file, r[key] ?? ""]));
  return set.map((s) => by.get(s.km_file) ?? "");
};
const jobs: Job[] = [
  { set: "en-km:ref", src: "en", tgt: "km", texts: set.map((s) => s.en) },
  { set: "km-en:ref", src: "km", tgt: "en", texts: set.map((s) => s.km) },
  { set: "km-en:transcribe", src: "km", tgt: "en", texts: hyp("tr_km.json") },
  ...(existsSync(`${D}/az_km_pin.json`) ? [{ set: "km-en:azure", src: "km", tgt: "en", texts: hyp("az_km_pin.json") }] : []),
];
const ARMS = (E.ARMS ?? "sol,flash,gemma,azure").split(",");
const R: Record<string, ({ out: string; ms: number; error?: string } | null)[]> = existsSync(OUT) ? JSON.parse(readFileSync(OUT, "utf8")) : {};

async function post(url: string, body: unknown, headers: Record<string, string>, tries = 5): Promise<any> {
  for (let a = 0; ; a++) {
    const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body), signal: AbortSignal.timeout(90_000) }).catch((e) => e as Error);
    if (!(r instanceof Error) && r.ok) return r.json();
    const status = r instanceof Error ? 0 : r.status;
    if (a >= tries - 1 || ![0, 408, 429, 500, 502, 503, 504].includes(status)) throw new Error(`${status} ${r instanceof Error ? r.message : (await r.text()).slice(0, 200)}`);
    await new Promise((ok) => setTimeout(ok, 2000 * (a + 1)));
  }
}
async function translate(arm: string, text: string, src: string, tgt: string, ctx: string[]): Promise<string> {
  if (!text.trim()) return "";
  const p = speechPrompt(text, tgt, src, ctx);
  if (arm === "sol") {
    const j = await post(`${E.FOUNDRY_ENDPOINT!.replace(/\/$/, "")}/openai/v1/chat/completions`,
      { model: E.FOUNDRY_DEPLOYMENT, reasoning_effort: "low", messages: [{ role: "system", content: p.system }, { role: "user", content: p.user }] }, { "api-key": E.FOUNDRY_KEY! });
    return (j.choices?.[0]?.message?.content ?? "").trim();
  }
  if (arm === "flash") {
    const j = await post(`https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent`,
      { systemInstruction: { parts: [{ text: p.system }] }, contents: [{ role: "user", parts: [{ text: p.user }] }], generationConfig: { maxOutputTokens: 4000, thinkingConfig: { thinkingLevel: "medium" } } },
      { "x-goog-api-key": E.GEMINI_API_KEY! });
    return (j.candidates?.[0]?.content?.parts ?? []).map((x: { text?: string }) => x.text ?? "").join("").trim();
  }
  if (arm === "gemma") {
    for (let i = 0; i < 3; i++) {
      const j = await post("https://openrouter.ai/api/v1/chat/completions", gemmaBody({ OPENROUTER_API_KEY: "x" } as never, "openrouter", p), { Authorization: `Bearer ${E.OPENROUTER_API_KEY}` });
      const o = cleanGemma(j.choices?.[0]?.message?.content ?? "");
      if (o) return o;
    }
    return "";
  }
  const q = new URLSearchParams({ "api-version": "3.0", to: tgt, from: src });
  const j = await post(`https://api.cognitive.microsofttranslator.com/translate?${q}`, [{ Text: text }],
    { "Ocp-Apim-Subscription-Key": E.AZURE_TR_KEY!, "Ocp-Apim-Subscription-Region": E.AZURE_TR_REGION! });
  return (j[0]?.translations?.[0]?.text ?? "").trim();
}
async function arm(name: string) {
  const work: [string, number, Job][] = [];
  for (const j of jobs) {
    const k = `${j.set}:${name}`;
    R[k] ??= j.texts.map(() => null);
    j.texts.forEach((_, i) => { if (!R[k]![i] || R[k]![i]!.error) work.push([k, i, j]); });
  }
  let next = 0;
  await Promise.all([0, 1, 2].map(async () => {
    while (next < work.length) {
      const [k, i, j] = work[next++]!;
      const t0 = performance.now();
      try { R[k]![i] = { out: await translate(name, j.texts[i]!, j.src, j.tgt, j.texts.slice(Math.max(0, i - 2), i)), ms: Math.round(performance.now() - t0) }; }
      catch (e) { R[k]![i] = { out: "", ms: Math.round(performance.now() - t0), error: String(e).slice(0, 200) }; }
    }
  }));
  console.log(name, "done", work.length, "errors", Object.entries(R).filter(([k]) => k.endsWith(`:${name}`)).flatMap(([, v]) => v).filter((x) => x?.error).length);
}
await Promise.all(ARMS.map(arm));
writeFileSync(OUT, JSON.stringify(R, null, 1));
