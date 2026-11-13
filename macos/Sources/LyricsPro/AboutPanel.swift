import AppKit

/// The standard About panel, with the project's GitHub links in its credits.
enum AboutPanel {
    static let repository = URL(string: "https://github.com/inhzus/lyrics-pro")!

    static let links: [(title: String, url: URL)] = [
        ("GitHub", repository),
        ("Releases", repository.appending(path: "releases")),
        ("Report an Issue", repository.appending(path: "issues")),
    ]

    @MainActor static func show() {
        NSApp.orderFrontStandardAboutPanel(options: [.credits: credits()])
        NSApp.activate()
    }

    /// One centred line of links separated by middle dots.
    static func credits() -> NSAttributedString {
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .center
        let font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        let plain: [NSAttributedString.Key: Any] = [
            .font: font, .foregroundColor: NSColor.secondaryLabelColor, .paragraphStyle: paragraph,
        ]
        let text = NSMutableAttributedString()
        for (index, link) in links.enumerated() {
            if index > 0 { text.append(NSAttributedString(string: "  ·  ", attributes: plain)) }
            var attributes = plain
            attributes[.link] = link.url
            text.append(NSAttributedString(string: link.title, attributes: attributes))
        }
        return text
    }
}
