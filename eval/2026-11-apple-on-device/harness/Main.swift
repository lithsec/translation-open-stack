// applehear: the Apple on-device eval's harness (see ../README.md).
//   applehear hear <clip.wav> <code> <stage1.json>
//   applehear cut  <stage1.json> <clip.wav> <src> <tgt> <out.json>
import Foundation

@main struct AppleHear {
    static func main() async {
        let a = CommandLine.arguments
        do {
            switch a.count > 1 ? a[1] : "" {
            case "hear" where a.count == 5: try await hear(wav: a[2], code: a[3], out: a[4])
            case "cut" where a.count == 7: try await cut(stage1: a[2], wav: a[3], src: a[4], tgt: a[5], out: a[6])
            default:
                FileHandle.standardError.write("usage: applehear hear <wav> <code> <out> | cut <stage1> <wav> <src> <tgt> <out>\n".data(using: .utf8)!)
                exit(2)
            }
        } catch {
            FileHandle.standardError.write("error: \(error)\n".data(using: .utf8)!)
            exit(1)
        }
    }
}
