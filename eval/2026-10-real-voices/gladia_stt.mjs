// Gladia live speech-to-text (Solaria-1, the only live model) on audio/<lang>.wav,
// fed in real time, so "when did each final arrive" is what a room would see.
// It hears Haitian Creole, which Azure doesn't.
//
//   GLADIA_API_KEY=... node gladia_stt.mjs en ja km lo ht
//
// Writes out/stt-gladia/<lang>.json in azure_stt.py's shape (finals with text,
// offset/duration in the clip, arrival time), so gemini_live.mjs can take it.
// One clip at a time; a language already done is kept. Prints no secrets.
import fs from "node:fs";

const KEY = process.env.GLADIA_API_KEY?.trim();
if (!KEY) {
  console.error("Set GLADIA_API_KEY.");
  process.exit(1);
}
const OUT = "out/stt-gladia";

async function run(lang) {
  const pcm = fs.readFileSync(`audio/${lang}.wav`).subarray(44);
  const init = await fetch("https://api.gladia.io/v2/live", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-gladia-key": KEY },
    body: JSON.stringify({
      encoding: "wav/pcm",
      sample_rate: 16000,
      bit_depth: 16,
      channels: 1,
      model: "solaria-1",
      language_config: { languages: [lang], code_switching: false },
      messages_config: { receive_partial_transcripts: false, receive_final_transcripts: true }
    })
  });
  const body = await init.json().catch(() => ({}));
  const save = (o) => {
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(`${OUT}/${lang}.json`, JSON.stringify({ lang, ...o }, null, 1));
  };
  if (!init.ok || !body.url) {
    const err = `init ${init.status}: ${JSON.stringify(body).slice(0, 200)}`;
    save({ err, finals: [] });
    return console.log(`${lang}: ERROR ${err}`);
  }
  const finals = [];
  let err = "";
  let t0 = 0;
  await new Promise((resolve) => {
    const ws = new WebSocket(body.url);
    ws.onerror = () => {};
    ws.onclose = (e) => {
      if (e.code !== 1000 && !err) err = `closed ${e.code} ${e.reason}`;
      resolve();
    };
    ws.onmessage = (e) => {
      let m;
      try {
        m = JSON.parse(typeof e.data === "string" ? e.data : Buffer.from(e.data).toString());
      } catch {
        return;
      }
      if (m.type === "transcript" && m.data?.is_final && m.data.utterance?.text?.trim()) {
        const u = m.data.utterance;
        finals.push({ text: u.text.trim(), offsetMs: u.start * 1000, durationMs: (u.end - u.start) * 1000, arrivedMs: Date.now() - t0 });
      } else if (m.type === "error") {
        err = JSON.stringify(m).slice(0, 200);
      }
    };
    ws.onopen = async () => {
      t0 = Date.now();
      for (let off = 0; off < pcm.length; off += 3200) {
        if (ws.readyState !== 1) break;
        ws.send(pcm.subarray(off, off + 3200));
        await new Promise((r) => setTimeout(r, Math.max(0, t0 + off / 32 + 100 - Date.now())));
      }
      if (ws.readyState === 1) ws.send(Buffer.alloc(32000 * 2)); // 2 s of silence closes the last sentence
      await new Promise((r) => setTimeout(r, 2500));
      if (ws.readyState === 1) ws.send(JSON.stringify({ type: "stop_recording" }));
      setTimeout(resolve, 20000); // post-processing; the close usually comes first
    };
  });
  save({ err, finals });
  const lag = finals.map((f) => f.arrivedMs - (f.offsetMs + f.durationMs)).sort((a, b) => a - b);
  console.log(`${lang} (gladia): ${err ? "ERROR " + err : `${finals.length} finals, final arrives ~${Math.round(lag[Math.floor(lag.length / 2)] ?? 0)} ms after the words end`}`);
}

const todo = process.argv.slice(2).filter((l) => {
  try {
    const prev = JSON.parse(fs.readFileSync(`${OUT}/${l}.json`, "utf8"));
    if (!prev.err && prev.finals.length) {
      console.log(`${l}: kept (done)`);
      return false;
    }
  } catch {}
  return true;
});
// One clip at a time: the free plan dropped two sessions run side by side
// (closed 1006). A clip that fails is tried once more; a network error is a
// failed clip, not the end of the run.
for (const lang of todo) {
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      await run(lang)
    } catch (e) {
      console.log(`${lang} (gladia): ERROR ${e?.cause?.code || e?.message || e}`)
      fs.mkdirSync(OUT, { recursive: true })
      fs.writeFileSync(`${OUT}/${lang}.json`, JSON.stringify({ lang, err: String(e?.message || e), finals: [] }))
    }
    let ok = false
    try {
      const r = JSON.parse(fs.readFileSync(`${OUT}/${lang}.json`, "utf8"))
      ok = !r.err && r.finals.length > 0
    } catch {}
    if (ok) break
    if (attempt === 1) console.log(`${lang} (gladia): trying once more`)
  }
}
