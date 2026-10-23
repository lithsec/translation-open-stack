// Runs Live Translation's own code — the phone's hands-free gate (OwnVoiceGate), the central app's
// PhoneAutomix and PhonePaCanceller — over a simulated room, frame by frame, the way the app does:
//   phone   100 ms frames; sends while its voice gate is open (slider 0.031 RMS, 250 ms sustain,
//           900 ms hangover, 0.5 s pre-roll on opening), optionally only its wearer's level
//           (OwnVoiceGate, what conversation rooms do today)
//   uplink  each phone's frames arrive uplink + 0-30 ms jitter after they end
//   server  PA canceller on arrival (if the method has one), one queue per phone, a mixer tick
//           every 100 ms taking one frame per phone through the automixer (if any)
// Writes OUT/<scene>/<method>/phone<i>.wav: each phone's contribution to the mix, put back at the
// time it was spoken (dropped frames silent), and OUT/<scene>/<method>/stats.json.
//
//   npx tsx run_methods.mts LT_SRC ROOM OUT
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const [LT, ROOM, OUT] = process.argv.slice(2) as [string, string, string]
const mod = async (p: string) => import(pathToFileURL(join(LT, p)).href)
const { OwnVoiceGate } = await mod('shared/own-voice-gate.ts')
const { PhoneAutomix } = await mod('main/phone-automix.ts')
const { PaReference, PhonePaCanceller } = await mod('main/pa-reference.ts')

const RATE = 24000
const FRAME = 2400 // 100 ms
const FB = FRAME * 2

function readWav(path: string): Buffer {
  const b = readFileSync(path)
  let off = 12
  while (off < b.length) {
    const id = b.toString('ascii', off, off + 4)
    const size = b.readUInt32LE(off + 4)
    if (id === 'data') return b.subarray(off + 8, off + 8 + size)
    off += 8 + size
  }
  throw new Error('no data chunk')
}

function writeWav(path: string, pcm: Buffer): void {
  const h = Buffer.alloc(44)
  h.write('RIFF', 0); h.writeUInt32LE(36 + pcm.length, 4); h.write('WAVE', 8); h.write('fmt ', 12)
  h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(RATE, 24)
  h.writeUInt32LE(RATE * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write('data', 36)
  h.writeUInt32LE(pcm.length, 40)
  writeFileSync(path, Buffer.concat([h, pcm]))
}

function rmsOf(pcm: Buffer): number {
  let s = 0
  const n = pcm.length >> 1
  for (let i = 0; i < n; i++) { const v = pcm.readInt16LE(i * 2) / 32768; s += v * v }
  return Math.sqrt(s / Math.max(1, n))
}

// Deterministic jitter.
let seed = 99
const rand = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)

interface Method { name: string; own: boolean; automix?: 'gate' | 'share'; pa?: 'predict' | 'gate' | 'nlms' }
const METHODS: Method[] = [
  { name: 'slider', own: false },
  { name: 'ownvoice', own: true },
  { name: 'automix_gate', own: true, automix: 'gate' },
  { name: 'automix_share', own: true, automix: 'share' },
  { name: 'pa_gate', own: true, pa: 'gate' },
  { name: 'pa_predict', own: true, pa: 'predict' },
  { name: 'pa_nlms', own: true, pa: 'nlms' },
  { name: 'automix_pa_predict', own: true, automix: 'gate', pa: 'predict' },

]

// Tuning runs: ONLY=<method,...> SCENES=<scene,...> AUTOMIX='{"marginDb":8}' PACANCEL='{...}'
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : null
const SCENES = process.env.SCENES ? process.env.SCENES.split(',') : ['nopa', 'pa20', 'pa10', 'pa0']
const AUTOMIX = process.env.AUTOMIX ? JSON.parse(process.env.AUTOMIX) : {}
const PACANCEL = process.env.PACANCEL ? JSON.parse(process.env.PACANCEL) : {}
for (const scene of SCENES) {
  const meta = JSON.parse(readFileSync(join(ROOM, scene, 'meta.json'), 'utf8'))
  const mics = [0, 1, 2, 3].map((p) => readWav(join(ROOM, scene, `phone${p}.wav`)))
  const sent = readWav(join(ROOM, scene, 'pa_sent.wav'))
  const nFrames = Math.floor(mics[0]!.length / FB)
  for (const m of METHODS) {
    if (scene === 'nopa' && m.pa) continue
    if (ONLY && !ONLY.includes(m.name)) continue
    seed = 99
    // ---- phones: which frames each sends, and when they arrive -------------------------------
    type Arrival = { p: number; idx: number; at: number }
    const arrivals: Arrival[] = []
    let sentFrames = 0
    for (let p = 0; p < 4; p++) {
      const gate = new OwnVoiceGate()
      let aboveSince = 0, belowSince = 0, hotUntil = 0, sending = false
      const pre: number[] = []
      for (let i = 0; i < nFrames; i++) {
        const now = (i + 1) * 100
        const r = rmsOf(mics[p]!.subarray(i * FB, (i + 1) * FB))
        const above = r >= 0.031
        const pass = m.own ? gate.update(r, 100, above) && above : above
        if (pass) { belowSince = 0; if (!aboveSince) aboveSince = now }
        else if (aboveSince) { if (!belowSince) belowSince = now; if (now - belowSince >= 150) aboveSince = 0 }
        if (pass && (sending || (aboveSince && now - aboveSince >= 250))) hotUntil = now + 900
        const was = sending
        sending = now < hotUntil
        const at = now + meta.uplink_s[p] * 1000 + rand() * 30
        if (sending) {
          if (!was) for (const j of pre) arrivals.push({ p, idx: j, at })
          arrivals.push({ p, idx: i, at })
          sentFrames++
        } else {
          pre.push(i)
          if (pre.length > 5) pre.shift()
        }
      }
    }
    arrivals.sort((a, b) => a.at - b.at)
    // ---- server --------------------------------------------------------------------------------
    const ref = new PaReference()
    const canc = [0, 1, 2, 3].map(() => new PhonePaCanceller({ ...PACANCEL, mode: m.pa ?? 'off' }))
    const mix = new PhoneAutomix({ ...AUTOMIX, mode: m.automix ?? 'off' })
    const queues: { idx: number; pcm: Buffer }[][] = [[], [], [], []]
    const closed: number[][] = [[], [], [], []]
    const out = [0, 1, 2, 3].map(() => Buffer.alloc(nFrames * FB))
    let paDropped = 0, mixClosed = 0, cpuPa = 0, cpuMix = 0, paCalls = 0, mixCalls = 0
    // The PA copy is pushed in 100 ms pieces as the app sends it (wall time = its sample time).
    let refPos = 0
    const pushRefUntil = (t: number) => {
      while (refPos * 100 < t && (refPos + 1) * FB <= sent.length) {
        ref.push(sent.subarray(refPos * FB, (refPos + 1) * FB), RATE, refPos * 100)
        refPos++
      }
    }
    let ai = 0
    const endT = nFrames * 100 + 1000
    for (let tick = 37; tick < endT; tick += 100) {
      pushRefUntil(tick)
      while (ai < arrivals.length && arrivals[ai]!.at <= tick) {
        const a = arrivals[ai++]!
        let pcm: Buffer | null = mics[a.p]!.subarray(a.idx * FB, (a.idx + 1) * FB)
        if (m.pa) {
          const t0 = performance.now()
          pcm = canc[a.p]!.process(pcm, a.at, ref)
          cpuPa += performance.now() - t0
          paCalls++
          if (!pcm) { paDropped++; continue }
        }
        queues[a.p]!.push({ idx: a.idx, pcm })
        if (queues[a.p]!.length > 8) queues[a.p]!.shift()
      }
      const frames: { id: string; pcm: Buffer }[] = []
      const idxOf = new Map<string, number>()
      for (let p = 0; p < 4; p++) {
        const f = queues[p]!.shift()
        if (f) { frames.push({ id: String(p), pcm: f.pcm }); idxOf.set(String(p), f.idx) }
      }
      if (!frames.length) continue
      const t0 = performance.now()
      const res = mix.process(frames, tick)
      cpuMix += performance.now() - t0
      mixCalls++
      const got = new Set(res.map((r: { id: string }) => r.id))
      for (const f of frames) if (!got.has(f.id)) {
        mixClosed++
        const c = closed[Number(f.id)]!
        c.push(idxOf.get(f.id)!)
        if (c.length > 3) c.shift()
      }
      for (const r of res as { id: string; pcm: Buffer }[]) {
        const p = Number(r.id)
        const cur = idxOf.get(r.id)!
        const k = Math.round(r.pcm.length / FB)
        const idxs = k > 1 ? [...closed[p]!.slice(-(k - 1)), cur] : [cur]
        if (k > 1) closed[p] = []
        idxs.forEach((ix, j) => r.pcm.copy(out[p]!, ix * FB, j * FB, Math.min(r.pcm.length, (j + 1) * FB)))
      }
    }
    const dir = join(OUT, scene, m.name)
    mkdirSync(dir, { recursive: true })
    for (let p = 0; p < 4; p++) writeWav(join(dir, `phone${p}.wav`), out[p]!)
    writeFileSync(join(dir, 'stats.json'), JSON.stringify({
      method: m, frames: nFrames * 4, sent: sentFrames, paDropped, mixClosed,
      cpu_ms_per_audio_s_pa: paCalls ? (cpuPa / (paCalls / 10)) : 0,
      cpu_ms_per_audio_s_mix: mixCalls ? (cpuMix / (mixCalls / 10)) : 0,
      lags: canc.map((c: { lag(): number | null }) => c.lag())
    }, null, 1))
    console.log(scene, m.name, `sent ${sentFrames}`, `paDropped ${paDropped}`, `mixClosed ${mixClosed}`,
      `lags ${canc.map((c: { lag(): number | null }) => c.lag()).join(',')}`)
  }
}
