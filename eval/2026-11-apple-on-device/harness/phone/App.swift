// AppleHearCheck: the Apple on-device eval run on an iPhone. Inputs are copied into Documents/in by devicectl:
//   in/plan.json  {"hear":[{"set":"a","lang":"en","code":"en-US"}...], "cut":[{"set":"a","src":"en","tgt":"es","mt_src":"en","mt_tgt":"es"}...]}
//   in/clips_a/en.wav ...   in/text/in_apple_a_en-es.json ... ({"src","tgt","lines"})
// Outputs go to Documents/out (hear/<set>/<lang>.json, cut/<set>/<dir>.json, text/out_*.json, log.txt).
import Speech
import SwiftUI
import Translation

@main struct AppleHearCheckApp: App {
    var body: some Scene { WindowGroup { RunView() } }
}

@MainActor final class Runner: ObservableObject {
    @Published var lines: [String] = []
    @Published var running = false
    @Published var missing: [TranslationSession.Configuration] = []
    @Published var config: TranslationSession.Configuration?
    let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    var inDir: URL { docs.appendingPathComponent("in") }
    var outDir: URL { docs.appendingPathComponent("out") }

    func say(_ s: String) {
        lines.append(s)
        let p = outDir.appendingPathComponent("log.txt")
        try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
        if let h = try? FileHandle(forWritingTo: p) { h.seekToEndOfFile(); h.write((s + "\n").data(using: .utf8)!); try? h.close() }
        else { try? (s + "\n").write(to: p, atomically: true, encoding: .utf8) }
    }

    func textJobs() -> [URL] {
        let d = inDir.appendingPathComponent("text")
        return ((try? FileManager.default.contentsOfDirectory(at: d, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.lastPathComponent.hasPrefix("in_") }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    func pairs() -> Set<[String]> {
        var s = Set<[String]>()
        for u in textJobs() {
            if let j = try? JSONSerialization.jsonObject(with: Data(contentsOf: u)) as? [String: Any],
               let a = j["src"] as? String, let b = j["tgt"] as? String { s.insert([a, b]) }
        }
        if let plan = plan() { for c in plan["cut"] as? [[String: String]] ?? [] { s.insert([c["mt_src"]!, c["mt_tgt"]!]) } }
        return s
    }

    func plan() -> [String: Any]? {
        try? JSONSerialization.jsonObject(with: Data(contentsOf: inDir.appendingPathComponent("plan.json"))) as? [String: Any]
    }

    func check() async {
        say("device: \(UIDevice.current.model) iOS \(UIDevice.current.systemVersion)")
        var m: [TranslationSession.Configuration] = []
        for p in pairs().sorted(by: { $0.joined() < $1.joined() }) {
            let st = await LanguageAvailability().status(from: .init(identifier: p[0]), to: .init(identifier: p[1]))
            say("translation \(p[0])->\(p[1]): \(st)")
            if st == .supported { m.append(.init(source: .init(identifier: p[0]), target: .init(identifier: p[1]))) }
        }
        missing = m
        let inst = await SpeechTranscriber.installedLocales.map { $0.identifier(.bcp47) }.sorted()
        say("speech installed: \(inst.joined(separator: " "))")
    }

    func downloadNext() {
        guard let c = missing.first else { say("all translation languages installed"); return }
        config = c
    }

    func run() async {
        running = true
        UIApplication.shared.isIdleTimerDisabled = true
        defer { running = false; UIApplication.shared.isIdleTimerDisabled = false }
        let fm = FileManager.default
        // 1. translation alone on the reference text
        let td = outDir.appendingPathComponent("text")
        try? fm.createDirectory(at: td, withIntermediateDirectories: true)
        for u in textJobs() {
            let o = td.appendingPathComponent(u.lastPathComponent.replacingOccurrences(of: "in_", with: "out_"))
            if fm.fileExists(atPath: o.path) { continue }
            do {
                let j = try JSONSerialization.jsonObject(with: Data(contentsOf: u)) as! [String: Any]
                let s = TranslationSession(installedSource: .init(identifier: j["src"] as! String), target: .init(identifier: j["tgt"] as! String))
                var out: [String] = []
                for l in j["lines"] as! [String] { out.append(try await s.translate(l).targetText) }
                try JSONSerialization.data(withJSONObject: ["out": out]).write(to: o)
                say("text \(u.lastPathComponent): ok")
            } catch { say("text \(u.lastPathComponent): \(error)") }
        }
        guard let plan = plan() else { say("no plan.json"); return }
        // 2. hearing, real time
        for h in plan["hear"] as? [[String: String]] ?? [] {
            let (st, lang, code) = (h["set"]!, h["lang"]!, h["code"]!)
            let o = outDir.appendingPathComponent("hear/\(st)/\(lang).json")
            if fm.fileExists(atPath: o.path) { continue }
            try? fm.createDirectory(at: o.deletingLastPathComponent(), withIntermediateDirectories: true)
            do {
                if let loc = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: code)) {
                    let module = SpeechTranscriber(locale: loc, preset: .transcription)
                    if let req = try await AssetInventory.assetInstallationRequest(supporting: [module]) {
                        say("downloading speech \(loc.identifier(.bcp47))…"); try await req.downloadAndInstall()
                    }
                }
                say("hearing \(st)/\(lang) (\(code)), about 3 min…")
                try await hear(wav: inDir.appendingPathComponent("clips_\(st)/\(lang).wav").path, code: code, out: o.path)
                say("heard \(st)/\(lang)")
            } catch { say("hear \(st)/\(lang): \(error)") }
        }
        // 3. cut + translate what was heard
        for c in plan["cut"] as? [[String: String]] ?? [] {
            let (st, s, t) = (c["set"]!, c["src"]!, c["tgt"]!)
            let o = outDir.appendingPathComponent("cut/\(st)/\(s)-\(t).json")
            let h = outDir.appendingPathComponent("hear/\(st)/\(s).json")
            if fm.fileExists(atPath: o.path) || !fm.fileExists(atPath: h.path) { continue }
            try? fm.createDirectory(at: o.deletingLastPathComponent(), withIntermediateDirectories: true)
            do {
                try await cut(stage1: h.path, wav: inDir.appendingPathComponent("clips_\(st)/\(s).wav").path,
                              src: c["mt_src"]!, tgt: c["mt_tgt"]!, out: o.path)
                say("cut \(st)/\(s)-\(t): ok")
            } catch { say("cut \(st)/\(s)-\(t): \(error)") }
        }
        say("DONE")
    }
}

struct RunView: View {
    @StateObject var r = Runner()
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Apple on-device check").font(.headline)
            HStack {
                Button("Check") { Task { await r.check() } }
                Button("Download next (\(r.missing.count))") { r.downloadNext() }.disabled(r.missing.isEmpty)
                Button(r.running ? "Running…" : "Run") { Task { await r.run() } }.disabled(r.running)
            }.buttonStyle(.borderedProminent)
            ScrollView { Text(r.lines.suffix(200).joined(separator: "\n")).font(.caption.monospaced()).frame(maxWidth: .infinity, alignment: .leading) }
        }
        .padding()
        .translationTask(r.config) { session in
            do { try await session.prepareTranslation(); r.say("downloaded \(r.missing.first.map { "\($0.source?.minimalIdentifier ?? "")->\($0.target?.minimalIdentifier ?? "")" } ?? "")") }
            catch { r.say("download: \(error)") }
            if !r.missing.isEmpty { r.missing.removeFirst() }
            r.config = nil
        }
        .task { await r.check() }
    }
}
