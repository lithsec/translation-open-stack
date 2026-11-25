// Stage 1: Apple SpeechTranscriber on a clip, fed at real time, as the Talk app's on-device engine hears
// (LocalTranslateSession in the app's OnDevice.swift):
//   - SpeechTranscriber(locale: supportedLocale(equivalentTo: code), transcriptionOptions: [],
//     reportingOptions: [.volatileResults, .fastResults], attributeOptions: [])
//   - the mic's PCM16 16 kHz mono in 100 ms chunks, converted to bestAvailableAudioFormat
//   - in-progress results watched; when the text stops changing, the sentence is finalized by hand
//     (analyzer.finalize(through: nil)) after 0.8 s if it ends in . ? ! (or 。？！), else after 1.4 s
// Every result is logged with the wall time it arrived (ms since the first chunk was fed; at real-time pacing this
// is the clip's audio time) and its audio range. Real-time pacing matters here: the force-finalize timer runs on
// the wall clock, so feeding the file faster would finalize at different points.
//
//   applehear hear <clip.wav> <app language code> <out.json>
import AVFoundation
import Foundation
import Speech

final class Log: @unchecked Sendable {
    private let lock = NSLock()
    private var events: [[String: Any]] = []
    let t0: ContinuousClock.Instant
    init(t0: ContinuousClock.Instant) { self.t0 = t0 }
    var nowMs: Double {
        let d = t0.duration(to: .now)
        return Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15
    }
    func add(_ e: [String: Any]) { lock.withLock { var e = e; e["t"] = nowMs; events.append(e) } }
    var all: [[String: Any]] { lock.withLock { events } }
}

/// The app's force-finalize rule (OnDevice.swift finalizeSoon), on the same clock.
final class Finalizer: @unchecked Sendable {
    private let lock = NSLock()
    private var task: Task<Void, Never>?
    private var inProgress = ""
    let analyzer: SpeechAnalyzer
    let log: Log
    init(analyzer: SpeechAnalyzer, log: Log) { self.analyzer = analyzer; self.log = log }

    func final() { lock.withLock { task?.cancel(); task = nil; inProgress = "" } }

    func soon(_ text: String) {
        guard lock.withLock({ () -> Bool in
            defer { inProgress = text }
            return text != inProgress || task == nil
        }) else { return }
        let ended = text.last.map { ".?!。？！".contains($0) } ?? false
        let wait: Duration = ended ? .milliseconds(800) : .milliseconds(1400)
        let analyzer = self.analyzer, log = self.log
        let t = Task {
            try? await Task.sleep(for: wait)
            guard !Task.isCancelled else { return }
            log.add(["kind": "finalize", "ended": ended])
            try? await analyzer.finalize(through: nil)
        }
        lock.withLock { task?.cancel(); task = t }
    }
}

func readWav(_ path: String) throws -> (Data, Int) {
    let d = try Data(contentsOf: URL(fileURLWithPath: path))
    var i = 12, rate = 16000
    while i + 8 <= d.count {
        let id = String(decoding: d[i..<i + 4], as: UTF8.self)
        let n = Int(d[i + 4]) | Int(d[i + 5]) << 8 | Int(d[i + 6]) << 16 | Int(d[i + 7]) << 24
        if id == "fmt " { rate = Int(d[i + 12]) | Int(d[i + 13]) << 8 | Int(d[i + 14]) << 16 | Int(d[i + 15]) << 24 }
        if id == "data" { return (d.subdata(in: i + 8..<min(d.count, i + 8 + n)), rate) }
        i += 8 + n + (n & 1)
    }
    throw NSError(domain: "wav", code: 1)
}

func hear(wav: String, code: String, out: String) async throws {
    let (pcm, rate) = try readWav(wav)
    precondition(rate == 16000)
    guard let loc = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: code)) else {
        throw NSError(domain: "no SpeechTranscriber locale for \(code)", code: 2)
    }
    let installed = await SpeechTranscriber.installedLocales.contains { $0.identifier(.bcp47) == loc.identifier(.bcp47) }
    guard installed else { throw NSError(domain: "\(loc.identifier(.bcp47)) not installed", code: 3) }
    let transcriber = SpeechTranscriber(locale: loc, transcriptionOptions: [],
                                        reportingOptions: [.volatileResults, .fastResults], attributeOptions: [])
    let analyzer = SpeechAnalyzer(modules: [transcriber])
    guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]) else {
        throw NSError(domain: "no audio format", code: 4)
    }
    let micFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
    let converter = AVAudioConverter(from: micFormat, to: format)!
    let (stream, cont) = AsyncStream<AnalyzerInput>.makeStream()
    try await analyzer.prepareToAnalyze(in: format)
    try await analyzer.start(inputSequence: stream)

    let t0 = ContinuousClock.now
    let log = Log(t0: t0)
    let fin = Finalizer(analyzer: analyzer, log: log)
    let reader = Task {
        do {
            for try await r in transcriber.results {
                let text = String(r.text.characters).trimmingCharacters(in: .whitespacesAndNewlines)
                log.add(["kind": r.isFinal ? "final" : "volatile", "text": text,
                         "start": r.range.start.seconds, "end": r.range.end.seconds,
                         "fin": r.resultsFinalizationTime.seconds])
                if r.isFinal { fin.final() } else if !text.isEmpty { fin.soon(text) }
            }
        } catch { log.add(["kind": "error", "text": "\(error)"]) }
    }

    // Real time: chunk k goes in at t0 + k*100 ms (its audio is 100 ms long, so it has "arrived" by then).
    let chunk = 3200
    var k = 0, off = 0
    while off < pcm.count {
        let piece = pcm.subdata(in: off..<min(pcm.count, off + chunk))
        off += chunk
        k += 1
        try? await Task.sleep(until: t0 + .milliseconds(100 * k), clock: .continuous)
        let frames = AVAudioFrameCount(piece.count / 2)
        let inBuf = AVAudioPCMBuffer(pcmFormat: micFormat, frameCapacity: frames)!
        inBuf.frameLength = frames
        piece.withUnsafeBytes { raw in
            inBuf.int16ChannelData![0].update(from: raw.bindMemory(to: Int16.self).baseAddress!, count: Int(frames))
        }
        let cap = AVAudioFrameCount(Double(frames) * format.sampleRate / 16000) + 32
        let outBuf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: cap)!
        var fed = false
        var err: NSError?
        converter.convert(to: outBuf, error: &err) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return inBuf
        }
        if err == nil, outBuf.frameLength > 0 { cont.yield(AnalyzerInput(buffer: outBuf)) }
    }
    let audioMs = Double(pcm.count) / 32
    log.add(["kind": "audio_end", "audio_ms": audioMs])
    // The clip ends with 1-2 s of silence; give the force-finalize timer the time it would have on a phone.
    try? await Task.sleep(for: .seconds(3))
    cont.finish()
    try await analyzer.finalizeAndFinishThroughEndOfInput()
    _ = await reader.value
    let doc: [String: Any] = ["code": code, "locale": loc.identifier(.bcp47), "audio_ms": audioMs,
                              "pacing": "real time, 100 ms chunks", "events": log.all]
    try JSONSerialization.data(withJSONObject: doc, options: [.prettyPrinted, .sortedKeys])
        .write(to: URL(fileURLWithPath: out))
    let finals = log.all.filter { ($0["kind"] as? String) == "final" }.count
    print("heard \(wav) as \(loc.identifier(.bcp47)): \(finals) finals")
}
