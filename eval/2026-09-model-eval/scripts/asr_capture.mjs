// What the stack HEARD: stream a clip into the real server (src=auto, one room) and collect its
// inputTranscript messages (one per utterance its VAD cut). node asr_capture.mjs clip.wav <listenerLang>
import fs from "node:fs";
import { execSync } from "node:child_process";
const [file, lang] = process.argv.slice(2);
const pcm = fs.readFileSync(file).subarray(44);            // 24 kHz mono PCM16
const ws = new WebSocket(`ws://localhost:8790/translate?lang=${lang}&src=auto&room=asr_${file.replace(/\W/g, "_")}_${Math.random().toString(36).slice(2)}`);
ws.binaryType = "arraybuffer";
const heard = [], routes = [];
ws.onmessage = (e) => {
  if (typeof e.data !== "string") return;
  const m = JSON.parse(e.data);
  if (m.type === "hello") {
    const frame = Math.round(m.rate * 0.1) * 2; let off = 0;
    const iv = setInterval(() => {
      ws.send(off < pcm.length ? pcm.subarray(off, off + frame) : Buffer.alloc(frame));
      off += frame; if (off > pcm.length + m.rate * 2 * 6) clearInterval(iv);
    }, 100);
    setTimeout(() => { console.log(JSON.stringify({ file, heard, routes })); process.exit(0); }, (pcm.length / 2 / m.rate + 15) * 1000);
  } else if (m.type === "inputTranscript") heard.push(m.text);
  else if (m.type === "route") routes.push(m.src);
};
ws.onerror = () => { console.log(JSON.stringify({ file, error: "connect failed" })); process.exit(1); };
