// Streams Khmer FLEURS sentences to ElevenLabs realtime STT at real-time pace (100 ms chunks of 16 kHz PCM16),
// one session per sentence, VAD commit; records time to first partial and to the committed text after the audio ends.
// COMMIT=manual: one explicit commit after the audio (Talk's phone-cut turn) instead of VAD commits at 0.6 s pauses.
//   ELEVENLABS_API_KEY=... [COMMIT=manual] node el_realtime.mjs MODEL DATA OUT.json N
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
// `ws` from a lithos-server checkout next to this repo (as translate.ts imports it).
const WS = createRequire(new URL("../../../../lithos-server/package.json", import.meta.url))("ws");
const [MODEL, D, OUT, N] = process.argv.slice(2);
const set = JSON.parse(readFileSync(`${D}/set.json`, "utf8")).slice(0, Number(N ?? 5));
const KEY = process.env.ELEVENLABS_API_KEY;
const rows = [];
for (const s of set) {
  const pcm = readFileSync(`${D}/km/${s.km_file.replace(".wav", ".raw")}`);
  const url = `wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=${MODEL}&language_code=km&audio_format=pcm_16000&${process.env.COMMIT === "manual" ? "commit_strategy=manual" : "commit_strategy=vad&vad_silence_threshold_secs=0.6"}`;
  const row = await new Promise((done) => {
    const ws = new WS(url, { headers: { "xi-api-key": KEY } });
    let commits = [], t0 = 0, firstPartial = null, audioEnd = null, committed = [], lastCommitAt = null, err = null, started = false, msgs = {};
    const finish = () => { try { ws.close(); } catch {} ; done({ file: s.km_file, hyp: committed.join(" "), audio_s: pcm.length / 32000,
      first_partial_s: firstPartial, commits, final_after_end_s: lastCommitAt != null && audioEnd != null ? +(lastCommitAt - audioEnd).toFixed(2) : null, msgs, ...(err ? { error: err } : {}) }); };
    const timer = setTimeout(finish, (pcm.length / 32000 + 15) * 1000);
    ws.on("message", (m) => {
      const j = JSON.parse(m.toString()); const now = (Date.now() - t0) / 1000;
      msgs[j.message_type] = (msgs[j.message_type] ?? 0) + 1;
      if (j.message_type === "session_started" && !started) {
        started = true; t0 = Date.now(); let off = 0;
        const send = () => {
          if (off >= pcm.length) {
            // 1.5 s of silence so VAD commits, then an explicit commit.
            const sil = Buffer.alloc(32000 * 1.5); audioEnd = (Date.now() - t0) / 1000;
            ws.send(JSON.stringify({ message_type: "input_audio_chunk", audio_base_64: sil.toString("base64"), commit: true, sample_rate: 16000 }));
            return;
          }
          const c = pcm.subarray(off, off + 3200); off += 3200;
          ws.send(JSON.stringify({ message_type: "input_audio_chunk", audio_base_64: c.toString("base64"), commit: false, sample_rate: 16000 }));
          setTimeout(send, 100);
        };
        send();
      } else if (j.message_type === "partial_transcript") {
        if (firstPartial == null && j.text?.trim()) firstPartial = +now.toFixed(2);
      } else if (j.message_type === "committed_transcript" || j.message_type === "committed_transcript_with_timestamps") {
        if (j.message_type === "committed_transcript") {
          if (j.text?.trim()) committed.push(j.text.trim());
          commits.push(+now.toFixed(2));
          if (audioEnd != null) { lastCommitAt = now; clearTimeout(timer); setTimeout(finish, 2500); }
        }
      } else if (/error/i.test(j.message_type)) { err = JSON.stringify(j).slice(0, 300); }
    });
    ws.on("unexpected-response", (_q, r) => { let b = ""; r.on("data", (d) => (b += d)); r.on("end", () => { err = `${r.statusCode} ${b.slice(0, 300)}`; clearTimeout(timer); finish(); }); });
    ws.on("error", (e) => { err = err ?? String(e).slice(0, 200); });
  });
  console.log(MODEL, s.km_file, row.error ?? `${row.hyp.length} chars, first partial ${row.first_partial_s}s, final ${row.final_after_end_s}s after end`, JSON.stringify(row.msgs));
  rows.push(row);
}
writeFileSync(OUT, JSON.stringify(rows, null, 1));
