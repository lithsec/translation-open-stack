// Omnilingual (the omni-stt service's 300M card), one read sentence per connection,
// the language given alone (?langs=<code>, so no language ID), audio sent as fast as
// the socket takes it, then a flush. The protocol is services/omni-stt/README.md's.
//
//   STT_URL=https://... STT_TOKEN=... node omni.mjs WORK
//
// Writes WORK/asr/omni_<lang>.json: [{"n", "text", "s", "error"}]. Node 22+ (global WebSocket).
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const WORK = process.argv[2];
const BASE = (process.env.STT_URL || "").replace(/^http/, "ws").replace(/\/+$/, "");
const TOKEN = process.env.STT_TOKEN || "";
// Our codes -> the service's (services/omni-stt/server.py OMNI_CODES). Cantonese and
// Cape Verdean Creole are not mapped there, so they are not tried.
const CODE = { vi: "vi", fa: "fa", zh: "zh", ar: "ar", sw: "sw", fil: "tl", uk: "uk" };
const sentences = JSON.parse(readFileSync(join(WORK, "sentences.json"), "utf8"));

function pcmOf(path) {
  const b = readFileSync(path);
  let off = 12;
  while (off + 8 <= b.length) {
    const id = b.toString("ascii", off, off + 4), size = b.readUInt32LE(off + 4);
    if (id === "data") return b.subarray(off + 8, off + 8 + size);
    off += 8 + size + (size % 2);
  }
  throw new Error(`${path}: no data chunk`);
}

function one(code, path) {
  return new Promise((resolve) => {
    const url = `${BASE}/listen?langs=${code}`;
    const ws = new WebSocket(url, { headers: { Authorization: `Bearer ${TOKEN}` } });
    ws.binaryType = "arraybuffer";
    const texts = [];
    let t0 = 0, done = false, error = null;
    const finish = () => { if (done) return; done = true; try { ws.close(1000); } catch {} resolve({ text: texts.join(" ").trim(), s: t0 ? Math.round(performance.now() - t0) / 1000 : null, error }); };
    const timer = setTimeout(() => { error = error || "timeout"; finish(); }, 180000);
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "inputTranscript") texts.push(m.text);
      else if (m.type === "flushed") { clearTimeout(timer); finish(); }
      else if (m.type === "error") error = String(m.detail).slice(0, 200);
    };
    ws.onclose = (ev) => { if (ev.code !== 1000 && ev.code !== 1005 && !error) error = `closed ${ev.code} ${ev.reason}`; clearTimeout(timer); finish(); };
    ws.onerror = () => { error = error || "socket error"; };
    ws.onopen = () => {
      const pcm = pcmOf(path);
      t0 = performance.now();
      for (let off = 0; off < pcm.length; off += 3200) ws.send(pcm.subarray(off, Math.min(off + 3200, pcm.length)));
      ws.send(JSON.stringify({ type: "flush" }));
    };
  });
}

mkdirSync(join(WORK, "asr"), { recursive: true });
for (const [lang, rows] of Object.entries(sentences)) {
  if (!CODE[lang]) continue;
  const p = join(WORK, "asr", `omni_${lang}.json`);
  if (existsSync(p)) continue;
  const out = new Array(rows.length);
  let next = 0;
  async function worker() {
    while (next < rows.length) {
      const r = rows[next++];
      let res;
      for (let a = 0; a < 3; a++) {
        res = await one(CODE[lang], join(WORK, "audio", lang, `${String(r.n).padStart(2, "0")}.wav`));
        if (!res.error || res.text) break;
        await new Promise((z) => setTimeout(z, 5000 * (a + 1)));
      }
      out[r.n] = { n: r.n, ...res };
    }
  }
  await Promise.all([worker(), worker(), worker()]);
  writeFileSync(p, JSON.stringify(out, null, 1));
  console.log("omni", lang, "errors:", out.filter((o) => o.error).length, (out.find((o) => o.error) || {}).error || "");
}
