import AppKit
import Testing
@testable import LyricsPro

struct AboutPanelTests {
    @Test func creditsLinkEveryTitleToItsGitHubPage() {
        let credits = AboutPanel.credits()
        var found: [String: URL] = [:]
        credits.enumerateAttribute(.link, in: NSRange(location: 0, length: credits.length)) { value, range, _ in
            if let url = value as? URL { found[(credits.string as NSString).substring(with: range)] = url }
        }
        #expect(found["GitHub"]?.absoluteString == "https://github.com/inhzus/lyrics-pro")
        #expect(found["Releases"]?.absoluteString == "https://github.com/inhzus/lyrics-pro/releases")
        #expect(found["Report an Issue"]?.absoluteString == "https://github.com/inhzus/lyrics-pro/issues")
        #expect(credits.string == "GitHub  ·  Releases  ·  Report an Issue")
    }
}
