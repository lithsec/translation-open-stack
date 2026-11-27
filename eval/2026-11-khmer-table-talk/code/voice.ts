// Does the multilingual voice Talk uses at Standard (en-US-AvaMultilingualNeural, with <lang xml:lang='km-KH'>)
// speak Khmer? The SSML is production's (lithos-server testroutes.ts azureSsml, bundled in). Five of sol's Khmer
// translations, each with Ava and with Azure's own Khmer voice (km-KH-SreymomNeural); 24 kHz PCM16 saved as wav.
// Measures seconds of audio and of voiced audio (20 ms frames above -40 dBFS), and characters a second.
//   node voice.cjs DATA OUTDIR   (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION)
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { azureSsml } from "/Users/sstone/dev/lithos-server/src/testroutes";
const [D, O] = process.argv.slice(2) as [string, string];
mkdirSync(O, { recursive: true });
const mt = JSON.parse(readFileSync(`${D}/mt.json`, "utf8"))["en-km:ref:sol"] as { out: string }[];
const VOICES = ["en-US-AvaMultilingualNeural", "km-KH-SreymomNeural"];
const wav = (pcm: Buffer) => { const h = Buffer.alloc(44); h.write("RIFF", 0); h.writeUInt32LE(36 + pcm.length, 4); h.write("WAVEfmt ", 8); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(24000, 24); h.writeUInt32LE(48000, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write("data", 36); h.writeUInt32LE(pcm.length, 40); return Buffer.concat([h, pcm]); };
const rows = [];
for (let i = 0; i < 5; i++) {
  const text = mt[i]!.out;
  for (const v of VOICES) {
    const ssml = azureSsml(text, "km", undefined, v);
    const r = await fetch(`https://${process.env.AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1`, {
      method: "POST", headers: { "Ocp-Apim-Subscription-Key": process.env.AZURE_SPEECH_KEY!, "content-type": "application/ssml+xml", "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm", "User-Agent": "eval" }, body: ssml });
    const pcm = Buffer.from(await r.arrayBuffer());
    let voiced = 0;
    for (let f = 0; f + 960 <= pcm.length; f += 960) { let s = 0; for (let k = f; k < f + 960; k += 2) { const x = pcm.readInt16LE(k) / 32768; s += x * x; } if (10 * Math.log10(s / 480 + 1e-12) > -40) voiced++; }
    const name = `${i + 1}_${v.split("-")[2]}.wav`;
    if (r.ok) writeFileSync(`${O}/${name}`, wav(pcm));
    rows.push({ i: i + 1, voice: v, status: r.status, chars: [...text].length, seconds: +(pcm.length / 48000).toFixed(2), voiced_s: +(voiced * 0.02).toFixed(2), chars_per_voiced_s: voiced ? +([...text].length / (voiced * 0.02)).toFixed(1) : null, file: name, ssml });
    console.log(i + 1, v, r.status, rows.at(-1)!.seconds, rows.at(-1)!.voiced_s);
  }
}
writeFileSync(`${O}/voice.json`, JSON.stringify(rows, null, 1));
