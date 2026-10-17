// The open stack as a fifth contender, connecting as the app does
// (live-translation src/main/providers/local.ts): one WebSocket per target
// language, all in one room, src=auto; the first connection carries the audio
// (resampled to the stack's rate, real time), the others send silence.
//
//   STACK_URL=wss://<pod>-8790.proxy.runpod.net STACK_TOKEN=... \
//     node stack_client.mjs en:ja,km,ht km:en ht:en
//
// Each argument is <clip>:<targets>. Writes out/stack/<src>-<tgt>.json in the
// shape gemini_live.mjs writes: turns (one per translated sentence, with when
// its voice started, ms since the clip started) and every voice chunk's time.
import fs from "node:fs";

const BASE = process.env.STACK_URL?.replace(/\/+$/, "");
const TOKEN = process.env.STACK_TOKEN ?? "";
if (!BASE) {
  console.error("Set STACK_URL (and STACK_TOKEN).");
  process.exit(1);
}

/** 16 kHz s16 -> `rate` s16, linear (speech; the stack resamples again inside). */
function resample(pcm, from, to) {
  const n = Math.floor((pcm.length / 2) * (to / from));
  const out = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const x = (i * from) / to;
    const j = Math.floor(x);
    const a = pcm.readInt16LE(Math.min(j, pcm.length / 2 - 1) * 2);
    const b = pcm.readInt16LE(Math.min(j + 1, pcm.length / 2 - 1) * 2);
    out.writeInt16LE(Math.round(a + (b - a) * (x - j)), i * 2);
  }
  return out;
}

function connect(room, lang, rec, clock) {
  return new Promise((resolve) => {
    const ws = new WebSocket(`${BASE}/translate?lang=${lang}&src=auto&room=${room}`, {
      headers: TOKEN ? { authorization: `Bearer ${TOKEN}` } : {}
    });
    ws.binaryType = "arraybuffer";
    let rate = 24000;
    let pending = null; // a sentence whose voice hasn't started yet
    ws.onmessage = (e) => {
      if (typeof e.data !== "string") {
        const at = clock();
        rec.chunks.push(at);
        if (pending && pending.audioAt === null) pending.audioAt = at;
        return;
      }
      const m = JSON.parse(e.data);
      if (m.type === "hello") {
        rate = m.rate || rate;
        resolve({ ws, rate });
      } else if (m.type === "transcript" && m.delta?.trim()) {
        pending = { audioAt: null, said: m.delta.trim(), textAt: clock() };
        rec.turns.push(pending);
      } else if (m.type === "inputTranscript" && m.text) {
        rec.heard.push(m.text);
      } else if (m.type === "error") {
        rec.err = m.detail ?? "stack error";
      }
    };
    ws.onerror = () => {
      rec.err ||= "connect failed";
      resolve(null);
    };
    ws.onclose = (e) => {
      if (e.code === 4401) rec.err = "stack refused the token (4401)";
    };
  });
}

async function run(src, targets) {
  const raw = fs.readFileSync(`audio/${src}.wav`).subarray(44);
  const room = `eval_${src}_${Math.random().toString(36).slice(2, 8)}`;
  let t0 = 0;
  const clock = () => (t0 ? Date.now() - t0 : 0);
  const recs = Object.fromEntries(targets.map((l) => [l, { turns: [], chunks: [], heard: [], err: "" }]));
  const conns = [];
  for (const l of targets) conns.push(await connect(room, l, recs[l], clock)); // primary first
  if (!conns[0]) {
    for (const l of targets) save(src, l, recs[l]);
    return console.log(`stack ${src}: ERROR ${recs[targets[0]].err}`);
  }
  const { ws, rate } = conns[0];
  const pcm = resample(raw, 16000, rate);
  const frame = Math.round(rate * 0.1) * 2;
  t0 = Date.now();
  for (let off = 0; off < pcm.length + rate * 2 * 8; off += frame) {
    ws.send(off < pcm.length ? pcm.subarray(off, off + frame) : Buffer.alloc(frame));
    for (const c of conns.slice(1)) c?.ws.send(Buffer.alloc(frame));
    await new Promise((r) => setTimeout(r, Math.max(0, t0 + ((off / 2 / rate) * 1000) + 100 - Date.now())));
  }
  await new Promise((r) => setTimeout(r, 6000));
  for (const c of conns) c?.ws.close();
  for (const l of targets) {
    save(src, l, recs[l]);
    const r = recs[l];
    console.log(`stack ${src}-${l}: ${r.err ? "ERROR " + r.err : `${r.turns.length} sentences, ${r.turns.map((x) => x.said).join(" ").length} chars said`}`);
  }
}

function save(src, tgt, r) {
  fs.mkdirSync("out/stack", { recursive: true });
  fs.writeFileSync(
    `out/stack/${src}-${tgt}.json`,
    JSON.stringify({ direction: `${src}-${tgt}`, mode: "stack", err: r.err, heard: r.heard.join(" "), turns: r.turns, chunks: r.chunks }, null, 1)
  );
}

// Every clip at once, each in its own room: the A100 has room for it.
await Promise.all(
  process.argv.slice(2).map((arg) => {
    const [src, t] = arg.split(":");
    return run(src, t.split(","));
  })
);
