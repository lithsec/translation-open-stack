// Lithos self-hosted stack harness, connecting exactly as the live-translation app does
// (src/main/providers/local.ts): one WebSocket per target language, all in one room, src=auto,
// optional stream=1. The first connection is the room's primary and carries the microphone audio
// (24 kHz mono PCM16, 100 ms frames, real time); the others only receive.
//   node stack.mjs clip.wav es,de,fr [stream 0|1]     (server at ws://localhost:8790 via ssh tunnel)
import fs from "node:fs";
const [file, langsArg = "es", stream = "0"] = process.argv.slice(2);
const langs = langsArg.split(",");
const pcm = fs.readFileSync(file).subarray(44);
const room = `cmp_${Math.random().toString(36).slice(2)}`;
const base = `ws://localhost:${process.env.PORT || 8790}`;
let t0 = 0;
const t = () => ((Date.now() - t0) / 1000).toFixed(2);
const out = {};

function connect(lang, primary) {
  return new Promise((resolve) => {
    const ws = new WebSocket(`${base}/translate?lang=${lang}&src=auto&room=${room}${stream === "1" ? "&stream=1" : ""}`);
    ws.binaryType = "arraybuffer";
    const r = (out[lang] = { events: [], heard: [], said: "", voiceSeconds: 0 });
    let rate = 24000, lastAudio = 0, lastText = 0;
    ws.onmessage = (e) => {
      if (typeof e.data !== "string") {
        const now = Date.now();
        if (now - lastAudio > 1500) r.events.push(`voice ${t()}`);
        lastAudio = now;
        r.voiceSeconds += e.data.byteLength / 2 / rate;
        (r.pcm ??= []).push(Buffer.from(e.data));
        return;
      }
      const m = JSON.parse(e.data);
      if (m.type === "hello") { rate = m.rate; resolve({ ws, rate, primary }); }
      else if (m.type === "route") r.events.push(`route:${m.src} ${t()}`);
      else if (m.type === "inputTranscript") r.heard.push(m.text);
      else if (m.type === "transcript" && m.delta) {
        const now = Date.now();
        if (now - lastText > 1500) r.events.push(`text ${t()}`);
        lastText = now;
        r.said += m.delta;
      } else if (m.type === "error") r.events.push(`error ${m.detail}`);
    };
    ws.onerror = () => { r.events.push("connect failed"); resolve(null); };
  });
}

// Primary first, so it opens (and configures) the room.
const conns = [await connect(langs[0], true)];
for (const l of langs.slice(1)) conns.push(await connect(l, false));
if (!conns[0]) { console.log(JSON.stringify(out)); process.exit(1); }
const { ws, rate } = conns[0];
t0 = Date.now();
const frame = Math.round(rate * 0.1) * 2;
let off = 0;
const iv = setInterval(() => {
  const c = off < pcm.length ? pcm.subarray(off, off + frame) : Buffer.alloc(frame);
  ws.send(c);
  // Non-primary connections send silence, as the app's other sessions do (the room discards it).
  for (const x of conns.slice(1)) x?.ws.send(Buffer.alloc(frame));
  off += frame;
  if (off > pcm.length + rate * 2 * 6) clearInterval(iv);
}, 100);
setTimeout(() => {
  if (process.env.SAVE) for (const [l, r] of Object.entries(out)) if (r.pcm) {
    const body = Buffer.concat(r.pcm), h = Buffer.alloc(44);
    h.write("RIFF", 0); h.writeUInt32LE(36 + body.length, 4); h.write("WAVEfmt ", 8); h.writeUInt32LE(16, 16);
    h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(24000, 24); h.writeUInt32LE(48000, 28);
    h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write("data", 36); h.writeUInt32LE(body.length, 40);
    fs.writeFileSync(`${process.env.SAVE}/${l}.wav`, Buffer.concat([h, body]));
  }
  for (const [l, r] of Object.entries(out)) { delete r.pcm; r.heard = r.heard.join(" "); r.said = r.said.trim(); r.voiceSeconds = +r.voiceSeconds.toFixed(1); }
  console.log(JSON.stringify({ file, stream, room, out }));
  process.exit(0);
}, Number(process.env.WAIT || 34000));
