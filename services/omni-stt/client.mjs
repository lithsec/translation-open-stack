#!/usr/bin/env node
// Streams WAV files to the omni-stt service in real time and prints what it hears.
//
//   STT_URL=wss://host STT_TOKEN=... node client.mjs file.wav ht,en
//   node client.mjs ht.wav ht,en en.wav ht,en fr.wav ht,fr      # three streams at once
//   node client.mjs --streams 4 ht.wav ht,en                    # the same file on 4 streams
//
// Options: --out result.json (default omni-stt-<time>.json), --speed 2 (twice real
// time; 0 = as fast as the socket takes it), --refs <dir> (an eval directory with
// audio/<name>.json sentence marks and sentences/<name>.json texts: adds CER, and the
// expected language for LID, by the file's base name), --expect ht (the language
// spoken, when the base name isn't it). Node 22+ (the global WebSocket).
//
// The output is {heard, utterances: [...]} for one stream, {streams: [...]} for several,
// each with latency: from the end of an utterance's audio (as sent) to its transcript.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { basename, join } from "node:path";

const args = process.argv.slice(2);
const opt = { out: `omni-stt-${Date.now()}.json`, speed: 1, refs: "", expect: "", streams: 0 };
const pos = [];
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a.startsWith("--")) {
    const k = a.slice(2);
    if (!(k in opt)) { console.error(`unknown option ${a}`); process.exit(2); }
    opt[k] = typeof opt[k] === "number" ? Number(args[++i]) : args[++i];
  } else pos.push(a);
}
if (pos.length < 2 || pos.length % 2) {
  console.error("usage: STT_URL=wss://... STT_TOKEN=... node client.mjs file.wav ht,en [file2.wav langs ...] [--streams N] [--refs dir] [--out f.json]");
  process.exit(2);
}
let jobs = [];
for (let i = 0; i < pos.length; i += 2) jobs.push({ file: pos[i], langs: pos[i + 1] });
if (opt.streams > jobs.length) jobs = Array.from({ length: opt.streams }, (_, i) => ({ ...jobs[i % jobs.length] }));

const BASE = (process.env.STT_URL || "ws://127.0.0.1:8080").replace(/\/+$/, "").replace(/\/listen$/, "");
const TOKEN = process.env.STT_TOKEN || "";

function readWav(path) {
  // Only what the service takes: PCM16 mono at 16 or 24 kHz.
  const b = readFileSync(path);
  if (b.toString("ascii", 0, 4) !== "RIFF" || b.toString("ascii", 8, 12) !== "WAVE") throw new Error(`${path}: not a WAV`);
  let off = 12, fmt = null, data = null;
  while (off + 8 <= b.length) {
    const id = b.toString("ascii", off, off + 4), size = b.readUInt32LE(off + 4);
    if (id === "fmt ") fmt = { format: b.readUInt16LE(off + 8), channels: b.readUInt16LE(off + 10), rate: b.readUInt32LE(off + 12), bits: b.readUInt16LE(off + 22) };
    if (id === "data") data = b.subarray(off + 8, off + 8 + size);
    off += 8 + size + (size % 2);
  }
  if (!fmt || !data) throw new Error(`${path}: no fmt/data chunk`);
  if (fmt.format !== 1 || fmt.channels !== 1 || fmt.bits !== 16 || ![16000, 24000].includes(fmt.rate))
    throw new Error(`${path}: need PCM16 mono at 16 or 24 kHz (got ${fmt.channels} ch, ${fmt.bits} bit, ${fmt.rate} Hz)`);
  return { rate: fmt.rate, pcm: data };
}

// CER as eval/2026-10-real-voices/judge.py computes it: NFKC, lowercase, letters and digits only.
const norm = (s) => [...s.normalize("NFKC").toLowerCase()].filter((c) => /[\p{L}\p{N}]/u.test(c)).join("");
function editDistance(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) cur.push(Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] !== b[j - 1] ? 1 : 0)));
    prev = cur;
  }
  return prev[b.length];
}

function refsFor(file) {
  const name = basename(file).replace(/\.wav$/i, "");
  if (!opt.refs) return null;
  const marks = join(opt.refs, "audio", `${name}.json`), texts = join(opt.refs, "sentences", `${name}.json`);
  if (!existsSync(marks) || !existsSync(texts)) return null;
  return { texts: JSON.parse(readFileSync(texts, "utf8")) };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function run(job, idx) {
  const { rate, pcm } = readWav(job.file);
  const name = basename(job.file).replace(/\.wav$/i, "");
  const expect = opt.expect || (job.langs.split(",").includes(name) ? name : "");
  const url = new URL(`${BASE}/listen`);
  url.searchParams.set("langs", job.langs);
  if (rate !== 16000) url.searchParams.set("rate", String(rate));
  // Node's WebSocket (undici) takes headers; STT_TOKEN_IN_URL=1 for a proxy that strips them.
  if (TOKEN && process.env.STT_TOKEN_IN_URL === "1") url.searchParams.set("token", TOKEN);
  const ws = new WebSocket(url, TOKEN && process.env.STT_TOKEN_IN_URL !== "1" ? { headers: { Authorization: `Bearer ${TOKEN}` } } : undefined);
  ws.binaryType = "arraybuffer";
  const tag = jobs.length > 1 ? `[${idx}:${name}] ` : "";
  const utterances = [];
  let t0 = 0, flushed, closed;
  const flushedP = new Promise((r) => (flushed = r));
  const closedP = new Promise((r) => (closed = r));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "inputTranscript") {
      // When the utterance's last sample left this client, at the pace it was sent.
      const sentAt = t0 + (opt.speed > 0 ? m.end_ms / opt.speed : 0);
      const u = { ...m, latency_ms: Math.round(performance.now() - sentAt) };
      delete u.type;
      utterances.push(u);
      console.log(`${tag}${(m.start_ms / 1000).toFixed(1)}-${(m.end_ms / 1000).toFixed(1)}s ${m.lang} ${m.confidence} +${u.latency_ms}ms  ${m.text}`);
    } else if (m.type === "flushed") flushed();
    else if (m.type === "error") console.error(`${tag}error: ${m.detail}`);
  };
  ws.onclose = (ev) => { if (ev.code !== 1000 && ev.code !== 1005) console.error(`${tag}closed ${ev.code} ${ev.reason}`); flushed(); closed(); };
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error(`${tag}could not connect to ${BASE}`)); });
  const chunk = (rate / 10) * 2;   // 100 ms
  t0 = performance.now();
  for (let off = 0, n = 0; off < pcm.length && ws.readyState === 1; off += chunk, n++) {
    ws.send(pcm.subarray(off, Math.min(off + chunk, pcm.length)));
    if (opt.speed > 0) {
      const due = t0 + ((n + 1) * 100) / opt.speed;
      const wait = due - performance.now();
      if (wait > 0) await sleep(wait);
    }
  }
  const audioS = pcm.length / 2 / rate;
  if (ws.readyState === 1) ws.send(JSON.stringify({ type: "flush" }));
  await flushedP;
  ws.close(1000);
  await Promise.race([closedP, sleep(2000)]);
  const heard = utterances.map((u) => u.text).join(" ");
  const out = { file: job.file, langs: job.langs.split(","), audio_s: Math.round(audioS * 10) / 10, heard, utterances };
  if (expect) {
    out.expected_lang = expect;
    out.lid_correct = utterances.filter((u) => u.lang === expect).length;
    out.lid_total = utterances.length;
  }
  const refs = refsFor(job.file);
  if (refs) {
    const ref = norm(refs.texts.join(" "));
    out.cer = Math.round((editDistance(ref, norm(heard)) / ref.length) * 10000) / 10000;
  }
  const lat = utterances.map((u) => u.latency_ms).sort((a, b) => a - b);
  if (lat.length) out.latency_ms = { median: lat[Math.floor(lat.length / 2)], max: lat[lat.length - 1] };
  return out;
}

const results = await Promise.all(jobs.map((j, i) => run(j, i)));
for (const [i, r] of results.entries()) {
  const bits = [`${r.utterances.length} utterances`];
  if (r.cer !== undefined) bits.push(`CER ${(r.cer * 100).toFixed(1)}%`);
  if (r.expected_lang) bits.push(`LID ${r.lid_correct}/${r.lid_total} ${r.expected_lang}`);
  if (r.latency_ms) bits.push(`latency median ${r.latency_ms.median} ms, max ${r.latency_ms.max} ms`);
  console.log(`${jobs.length > 1 ? `[${i}] ` : ""}${basename(r.file)} (${r.langs.join(",")}): ${bits.join(", ")}`);
}
writeFileSync(opt.out, JSON.stringify(results.length === 1 ? results[0] : { streams: results }, null, 1));
console.log(`wrote ${opt.out}`);
