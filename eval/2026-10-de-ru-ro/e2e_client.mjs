// One direction through the open stack, October latency method (copied from ../2026-10-open-stack-e2e, with ?context=1 as full-stack ran it).
//   STACK_URL=wss://<stack host> STACK_TOKEN=... node e2e_client.mjs <clips> <src> <tgt> <out.json>
// Fixed source language (?src=<src>), one connection in its own room (as the apps connect).
// 16 kHz clip resampled to the hello rate; 100 ms PCM16 chunks at real time; chunk k is sent
// when its 100 ms ends, t0 + (k+1)*100 ms; every event's t is ms on that timeline.
// 1.5 s of silence before the clip (the room opens first); after it, silence until 10 s pass
// with no output (cap 90 s).
import fs from "node:fs";

const [clips, src, tgt, out] = process.argv.slice(2);
const BASE = process.env.STACK_URL.replace(/\/+$/, "");
const TOKEN = process.env.STACK_TOKEN;
const VOICED_RMS = 150;

function voiced(b) {
  const f = Math.round(RATE / 100), n = Math.floor(b.length / 2 / f);
  let on = -1, off = -1;
  for (let k = 0; k < n; k++) {
    let s = 0;
    for (let j = 0; j < f; j++) { const v = b.readInt16LE((k * f + j) * 2); s += v * v; }
    if (Math.sqrt(s / f) > VOICED_RMS) { if (on < 0) on = k * 10; off = (k + 1) * 10; }
  }
  return on < 0 ? {} : { on, off };
}
function resample(pcm, from, to) {
  const n = Math.floor((pcm.length / 2) * (to / from)), o = Buffer.alloc(n * 2), L = pcm.length / 2 - 1;
  for (let i = 0; i < n; i++) {
    const x = (i * from) / to, j = Math.floor(x);
    const a = pcm.readInt16LE(Math.min(j, L) * 2), b = pcm.readInt16LE(Math.min(j + 1, L) * 2);
    o.writeInt16LE(Math.round(a + (b - a) * (x - j)), i * 2);
  }
  return o;
}

let RATE = 24000, t0 = 0, lastOut = 0;
const events = [];
const now = () => performance.now();
const tl = () => (t0 ? now() - t0 : -1);
const room = `e2e_${src}_${tgt}_${Math.random().toString(36).slice(2, 8)}`;
const ws = new WebSocket(`${BASE}/translate?lang=${tgt}&src=${src}&room=${room}&context=1`, { headers: { authorization: `Bearer ${TOKEN}` } });
ws.binaryType = "arraybuffer";
let err = "";
const hello = new Promise((res) => {
  ws.onmessage = (e) => {
    const t = tl();
    if (typeof e.data !== "string") {
      const b = Buffer.from(e.data);
      lastOut = now();
      events.push({ kind: "audio", t, samples: b.length / 2, rate: RATE, ...voiced(b) });
      return;
    }
    const m = JSON.parse(e.data);
    if (m.type === "hello") { RATE = m.rate || RATE; events.push({ kind: "hello", ...m }); res(); return; }
    lastOut = now();
    if (m.type === "inputTranscript") events.push({ kind: "input", t, text: m.text });
    else if (m.type === "transcript") events.push({ kind: "text", t, text: m.delta ?? "" });
    else if (m.type === "error") { err = m.detail; events.push({ kind: "error", t, detail: m.detail }); }
    else events.push({ kind: m.type, t, ...m });
  };
  ws.onerror = () => { err ||= "socket error"; res(); };
  ws.onclose = (e) => { events.push({ kind: "close", t: tl(), code: e.code }); };
});
await hello;
if (ws.readyState !== 1) { console.log(`${src}-${tgt}: ERROR ${err}`); process.exit(1); }
const pcm = resample(fs.readFileSync(`${clips}/${src}.wav`).subarray(44), 16000, RATE);
const frame = Math.round(RATE * 0.1) * 2, sil = Buffer.alloc(frame);
const sleepUntil = async (at) => { const d = at - now(); if (d > 0) await new Promise((r) => setTimeout(r, d)); };
// pre-roll 1.5 s
let p0 = now();
for (let k = 0; k < 15; k++) { await sleepUntil(p0 + (k + 1) * 100); ws.send(sil); }
t0 = now();
const nChunks = Math.ceil(pcm.length / frame);
for (let k = 0; k < nChunks; k++) {
  await sleepUntil(t0 + (k + 1) * 100);
  const c = pcm.subarray(k * frame, (k + 1) * frame);
  ws.send(c.length === frame ? c : Buffer.concat([c, Buffer.alloc(frame - c.length)]));
}
lastOut = Math.max(lastOut, now());
for (let k = nChunks; ; k++) {
  await sleepUntil(t0 + (k + 1) * 100);
  ws.send(sil);
  if (now() - lastOut > 10000 || (k - nChunks) > 900) break;
}
ws.close();
await new Promise((r) => setTimeout(r, 300));
fs.writeFileSync(out, JSON.stringify({ src, tgt, rate: RATE, room_opened_ms_before: 1500, err, clip_ms: nChunks * 100, events }, null, 0));
const inputs = events.filter((e) => e.kind === "input").length, auds = events.filter((e) => e.kind === "audio").length;
console.log(`${src}-${tgt}: ${inputs} utterances, ${auds} audio msgs, err=${err || "-"}`);
