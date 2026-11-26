// Apple Translation on given text: appletext in.json out.json ; in = {"src","tgt","lines":[...]}
import Foundation
import Translation
@main struct M { static func main() async throws {
  let a = CommandLine.arguments
  let j = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: a[1]))) as! [String: Any]
  let s = TranslationSession(installedSource: Locale.Language(identifier: j["src"] as! String), target: Locale.Language(identifier: j["tgt"] as! String))
  var out: [String] = []
  for l in j["lines"] as! [String] { out.append(try await s.translate(l).targetText) }
  try JSONSerialization.data(withJSONObject: ["out": out]).write(to: URL(fileURLWithPath: a[2]))
}}
