// Stage 2: what each arm translates, and when, from one stage-1 log (the same transcript stream for both arms).
//   whole   the app's on-device path: every final with a letter or digit, translated whole (OnDevice.swift enqueue)
//   pieces  the same stream cut as Talk's cloud routes cut it (StandardTranslateSession with fast mode, the server's
//           boundaryCutter on, fastCuts = FastPhrases.latestLevel): the boundary cutter where
//           FastPhrases.cutsAtBoundaries says so, else the phrase Cutter where FastPhrases.policy says phrases, else
//           whole sentences. Volatile results are the partials (window = the result's audio range), finals the
//           sentences (never `forced`: Apple has no forced cut), and the mic gate of the app's streaming hub
//           (AzureStreamHub.gate: 100 ms chunks, loud = rms > max(0.012, 2.5 x noise floor), 300 ms of quiet = a pause,
//           its 10 ms energy track for the boundary cutter's dip) is run on the clip's audio on the same clock.
// Every piece is then translated by Apple (TranslationSession(installedSource:target:), one piece per call, no
// context: Apple's API has none), in order, after a warm-up call. A piece's translation is available at
//   done = max(piece ready, previous piece done) + its translate time
// (the app translates strictly in order). Translate times are measured here, one call at a time.
//
//   applehear cut <stage1.json> <clip.wav> <src code> <tgt code> <out.json>
import Foundation
import Translation

struct Piece {
    var arm: String
    var text: String
    var ready: Double
    var seg: Int          // index of the final (segment) the words belong to
    var whole: Bool       // a whole final / sentence, not a cut piece
}

func rms(_ pcm: Data) -> Float {
    let n = pcm.count / 2
    guard n > 0 else { return 0 }
    var sum: Float = 0
    pcm.withUnsafeBytes { raw in
        for i in 0..<n {
            let f = Float(Int16(littleEndian: raw.loadUnaligned(fromByteOffset: i * 2, as: Int16.self))) / 32768
            sum += f * f
        }
    }
    return sqrt(sum / Float(n))
}

func cut(stage1: String, wav: String, src: String, tgt: String, out: String) async throws {
    let doc = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: stage1))) as! [String: Any]
    let events = (doc["events"] as! [[String: Any]]).filter { ["volatile", "final"].contains($0["kind"] as? String) }
    let (pcm, _) = try readWav(wav)
    let level = FastPhrases.latestLevel
    let boundaryOn = FastPhrases.cutsAtBoundaries(source: src, target: tgt, level: level)
    let policy = FastPhrases.policy(source: src, target: tgt, level: level)
    let mode = boundaryOn ? "boundary" : policy.phrases ? "phrases \(policy.min)-\(policy.max)" : "whole"

    var pieces: [Piece] = []
    var segments: [[String: Any]] = []
    // whole: the app's path
    for e in events where (e["kind"] as! String) == "final" {
        let text = e["text"] as! String
        guard text.contains(where: { $0.isLetter || $0.isNumber }) else { continue }
        segments.append(["text": text, "start": e["start"]!, "end": e["end"]!, "t": e["t"]!])
        pieces.append(Piece(arm: "whole", text: text, ready: e["t"] as! Double, seg: segments.count - 1, whole: true))
    }

    // pieces: replay the stream with the hub's gate on the same clock
    var cutter = FastPhrases.Cutter(source: src, policy: policy)
    var boundary = FastPhrases.BoundaryCutter(source: src)
    var energy = FastPhrases.EnergyTrack()
    var noiseFloor: Float = 0, gateOpen = false, quiet = 0
    var seg = 0
    var pend: [Piece] = []
    func emit(_ words: [String], at: Double, whole: Bool = false) {
        guard !words.isEmpty else { return }
        pend.append(Piece(arm: "pieces", text: words.joined(separator: " "), ready: at, seg: -1, whole: whole))
    }
    let nChunks = (pcm.count + 3199) / 3200
    var ei = 0
    for k in 0...nChunks {
        // chunk k (audio k*100..(k+1)*100 ms) is fed at (k+1)*100 ms; after the last chunk, every event left (the
        // finals Apple sends after the audio ends)
        let tChunkEnd = k < nChunks ? Double(k + 1) * 100 : .infinity
        // recogniser events that arrived before this chunk was fed
        while ei < events.count, (events[ei]["t"] as! Double) <= tChunkEnd {
            let e = events[ei]; ei += 1
            let text = e["text"] as! String, t = e["t"] as! Double
            let a = (e["start"] as! Double) * 1000, b = (e["end"] as! Double) * 1000
            if (e["kind"] as! String) == "volatile" {
                guard !text.isEmpty else { continue }
                if boundaryOn {
                    boundary.dip = { energy.dipMs(from: $0, to: $1) }
                    for p in boundary.partial(text, startMs: a, endMs: b, nowMs: t) { emit(p, at: t) }
                } else if policy.phrases {
                    for p in cutter.partial(text) { emit(p, at: t) }
                }
            } else {
                guard text.contains(where: { $0.isLetter || $0.isNumber }) else { continue }
                if boundaryOn {
                    if let r = boundary.final(text, startMs: a, endMs: b, forced: false) {
                        if r.whole { emit(FastPhrases.words(r.sentence), at: t, whole: true) } else { emit(r.words, at: t) }
                    }
                } else if policy.phrases {
                    emit(cutter.final(text), at: t)
                } else {
                    emit(FastPhrases.words(text), at: t, whole: true)
                }
                for i in pend.indices { pend[i].seg = seg }
                pieces += pend; pend = []
                seg += 1
            }
        }
        guard k < nChunks else { break }
        let chunk = pcm.subdata(in: k * 3200..<min(pcm.count, (k + 1) * 3200))
        let at = Double(k) * 100
        energy.push(pcm: chunk, atMs: at)
        let r = rms(chunk)
        if !gateOpen { noiseFloor = noiseFloor * 0.95 + r * 0.05 }
        let loud = r > max(0.012, noiseFloor * 2.5)
        if loud { gateOpen = true; quiet = 0 } else if gateOpen {
            quiet += 1
            if quiet == 3 {
                let q = at + 100
                if boundaryOn {
                    boundary.dip = { energy.dipMs(from: $0, to: $1) }
                    for p in boundary.pause(atMs: q) { emit(p, at: q) }
                } else if policy.phrases {
                    for p in cutter.pause() { emit(p, at: q) }
                }
            }
            if quiet >= 10 { gateOpen = false; quiet = 0 }
        }
        if boundaryOn, boundary.hasCarried { for p in boundary.tick(nowMs: at + 100) { emit(p, at: at + 100) } }
    }
    for i in pend.indices { pend[i].seg = max(0, seg - 1) }
    pieces += pend

    // translate, in order per arm
    let session = TranslationSession(installedSource: Locale.Language(identifier: src), target: Locale.Language(identifier: tgt))
    let w0 = ContinuousClock.now
    _ = try await session.translate("Hello.")
    let warm = w0.duration(to: .now)
    var rows: [[String: Any]] = []
    for arm in ["whole", "pieces"] {
        var prevDone = 0.0
        for p in pieces where p.arm == arm {
            let c = ContinuousClock.now
            var tr = ""
            do { tr = try await session.translate(p.text).targetText } catch { tr = "" }
            let d = c.duration(to: .now)
            let ms = Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15
            let done = max(p.ready, prevDone) + ms
            prevDone = done
            rows.append(["arm": arm, "text": p.text, "translation": tr, "ready": p.ready, "translate_ms": ms,
                         "done": done, "seg": p.seg, "whole": p.whole])
        }
    }
    let res: [String: Any] = ["src": src, "tgt": tgt, "locale": doc["locale"]!, "cut_mode": mode, "fast_cuts": level,
                              "warmup_ms": Double(warm.components.seconds) * 1000 + Double(warm.components.attoseconds) / 1e15,
                              "segments": segments, "pieces": rows]
    try JSONSerialization.data(withJSONObject: res, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: out))
    let n = rows.filter { ($0["arm"] as! String) == "pieces" }.count
    print("\(src)->\(tgt) \(mode): \(segments.count) finals, \(n) pieces")
}
