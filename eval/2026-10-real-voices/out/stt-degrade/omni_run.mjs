// Omnilingual ASR (omni-stt on Cloud Run) over out/stt-degrade/audio/<cond>/<lang>.wav:
// streams PCM16 16 kHz at real time in 100 ms binary chunks to
//   wss <OMNI_URL>/listen?langs=<l>&transcribe=<l>   (Authorization: Bearer)
// after the "hello" message, then {"type":"flush"}; collects "inputTranscript"
// {text,start_ms,end_ms}; closes on "flushed". At most 3 at once (service: 4).
//
//   OMNI_URL=https://... OMNI_TOKEN=... node out/stt-degrade/omni_run.mjs [cond ...]
//
// Writes out/stt-degrade/raw/omni/<cond>/<lang>.json. Done clips (no error) are skipped.
import fs from "node:fs";
import path from "node:path";

const HERE = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..");
const AUD = path.join(HERE, "out/stt-degrade/audio");
const RAW = path.join(HERE, "out/stt-degrade/raw/omni");
const BASE = process.env.OMNI_URL.replace(/\/+$/, "").replace(/^http/, "ws");
const TOKEN = process.env.OMNI_TOKEN;
const LANGS = ["en", "km", "lo", "ht"];
const CONDS = ["clean", "reverb", "noise10", "noise5", "revnoise10", "hfp_nb", "hfp_wb", "opus12", "opus24",
  "revnoise10_hpnorm", "revnoise10_afftdn", "revnoise10_rnn"];

function pcmOf(file) {
  const b = fs.readFileSync(file);
  let o = 12;
  while (o < b.length) {
    const id = b.toString("ascii", o, o + 4), n = b.readUInt32LE(o + 4);
    if (id === "data") return b.subarray(o + 8, o + 8 + n);
    o += 8 + n + (n & 1);
  }
  throw new Error("no data chunk");
}

function run(cond, lang) {
  return new Promise((resolve) => {
    const pcm = pcmOf(path.join(AUD, cond, `${lang}.wav`));
    const rec = { cond, lang, err: "", audio_s: pcm.length / 32000, hello: null, finals: [] };
    let t0 = 0, done = false, timer = null;
    const finish = (why) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      if (why) rec.err ||= why;
      try { ws.close(); } catch {}
      fs.mkdirSync(path.join(RAW, cond), { recursive: true });
      fs.writeFileSync(path.join(RAW, cond, `${lang}.json`), JSON.stringify(rec, null, 1));
      console.log(`${new Date().toTimeString().slice(0, 8)} omni ${cond}/${lang}: ${rec.err ? "ERROR " + rec.err : rec.finals.length + " finals"}`);
      resolve();
    };
    const ws = new WebSocket(`${BASE}/listen?langs=${lang}&transcribe=${lang}`, { headers: { authorization: `Bearer ${TOKEN}` } });
    ws.binaryType = "arraybuffer";
    ws.onmessage = async (e) => {
      if (typeof e.data !== "string") return;
      const m = JSON.parse(e.data);
      if (m.type === "hello" && !t0) {
        rec.hello = m;
        t0 = Date.now();
        for (let off = 0; off < pcm.length; off += 3200) {
          if (done) return;
          ws.send(pcm.subarray(off, off + 3200));
          await new Promise((r) => setTimeout(r, Math.max(0, t0 + off / 32 + 100 - Date.now())));
        }
        ws.send(JSON.stringify({ type: "flush" }));
        timer = setTimeout(() => finish("no 'flushed' within 120 s"), 120000);
      } else if (m.type === "inputTranscript") {
        rec.finals.push({ text: m.text, start_ms: m.start_ms, end_ms: m.end_ms, arrivedMs: Date.now() - t0 });
      } else if (m.type === "flushed") {
        finish("");
      } else if (m.type === "error") {
        rec.err = String(m.detail ?? m.message ?? JSON.stringify(m)).slice(0, 300);
      }
    };
    ws.onerror = () => finish("socket error");
    ws.onclose = (e) => finish(`closed ${e.code} before flushed`);
  });
}

const todo = [];
for (const c of process.argv.slice(2).length ? process.argv.slice(2) : CONDS)
  for (const l of LANGS) {
    const p = path.join(RAW, c, `${l}.json`);
    if (fs.existsSync(p) && !JSON.parse(fs.readFileSync(p)).err) continue;
    todo.push([c, l]);
  }
console.log(`${todo.length} clips`);
let i = 0;
await Promise.all([0, 1, 2].map(async () => {
  while (i < todo.length) await run(...todo[i++]);
}));
