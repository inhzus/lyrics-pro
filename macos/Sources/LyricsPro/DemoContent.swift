import SwiftUI

struct DemoLine: Identifiable {
    let id: Int
    let text: String
    let pronunciation: String?
}

enum DemoSong: String, CaseIterable, Identifiable {
    case cantonese = "Cantonese"
    case hokkien = "Hokkien"
    case mixed = "Long & mixed text"
    case noArtwork = "Missing artwork"

    var id: String { rawValue }
    var title: String { self == .hokkien ? "慢慢唱" : "夜色裡的歌" }
    var subtitle: String { "Lyrics Pro Studio — Original demo" }
    var language: String { self == .hokkien ? "TAIWANESE HOKKIEN" : "CANTONESE" }
    var system: String { self == .hokkien ? "TÂI-LÔ" : "JYUTPING" }
    var accent: Color { self == .hokkien ? Color(red: 0.82, green: 0.56, blue: 0.33) : Color(red: 0.43, green: 0.72, blue: 0.70) }

    // Original sample text. Readings are fixture data, not a live conversion.
    var lines: [DemoLine] {
        let samples: [(String, String?)]
        switch self {
        case .hokkien:
            samples = [
                ("慢慢行", "ban7-ban7 kiann5"),
                ("我欲學唱歌", "gua2 beh4 oh8 tshiunn3-kua1"),
                ("你佮我做伙唱", "li2 kah4 gua2 tso3-hue2 tshiunn3"),
                ("一工閣一工", "tsit8 kang1 koh4 tsit8 kang1"),
                ("慢慢唱", "ban7-ban7 tshiunn3"),
                ("♪", nil),
            ]
        case .mixed:
            samples = [
                ("你好，Hello 123！", "nei5 hou2，Hello 123！"),
                ("我想同你慢慢學唱歌，一句一句唱到天光", "ngo5 soeng2 tung4 nei5 maan6 maan6 hok6 coeng3 go1，jat1 geoi3 jat1 geoi3 coeng3 dou3 tin1 gwong1"),
                ("Sing a little softer, let the evening find its own way home.", nil),
                ("你好，世界。Hello, world.", "nei5 hou2，sai3 gaai3。Hello, world."),
                ("♪", nil),
            ]
        case .cantonese, .noArtwork:
            samples = [
                ("窗邊有微光", "coeng1 bin1 jau5 mei4 gwong1"),
                ("我想學唱歌", "ngo5 soeng2 hok6 coeng3 go1"),
                ("一句一句慢慢唱", "jat1 geoi3 jat1 geoi3 maan6 maan6 coeng3"),
                ("讓聲音陪住我", "joeng6 seng1 jam1 pui4 zyu6 ngo5"),
                ("今晚繼續唱", "gam1 maan5 gai3 zuk6 coeng3"),
                ("♪", nil),
            ]
        }
        return samples.enumerated().map { DemoLine(id: $0.offset, text: $0.element.0, pronunciation: $0.element.1) }
    }
}

struct DemoLyricsPanel: View {
    let song: DemoSong
    let fontSize: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 8) {
                Text(song.language)
                Circle().fill(song.accent).frame(width: 3, height: 3)
                Text(song.system)
            }
            .font(.system(size: 10, weight: .semibold))
            .tracking(2)
            .foregroundStyle(song.accent.opacity(0.8))
            ScrollView {
                VStack(alignment: .leading, spacing: 36) {
                    Color.clear.frame(height: 28).accessibilityHidden(true)
                    ForEach(song.lines) { line in
                        row(line)
                    }
                    Color.clear.frame(height: 100).accessibilityHidden(true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.trailing, 14)
            }
            .id(song)
            .scrollIndicators(.hidden)
            .mask {
                VStack(spacing: 0) {
                    LinearGradient(colors: [.clear, .black], startPoint: .top, endPoint: .bottom).frame(height: 24)
                    Color.black
                    LinearGradient(colors: [.black, .clear], startPoint: .top, endPoint: .bottom).frame(height: 64)
                }
            }
        }
    }

    private func row(_ line: DemoLine) -> some View {
        let active = line.id == 1
        return VStack(alignment: .leading, spacing: 12) {
            Text(line.text)
                .font(.system(size: fontSize, weight: .bold))
                .foregroundStyle(.white.opacity(active ? 0.98 : 0.28))
                .lineSpacing(9)
            if let pronunciation = line.pronunciation {
                Text(pronunciation)
                    .font(.system(size: fontSize * 0.44, weight: .medium))
                    .foregroundStyle(active ? song.accent : .white.opacity(0.25))
                    .lineSpacing(6)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
        .accessibilityElement(children: .combine)
    }
}

/// A static timeline for demo content, which never controls Music.
struct DemoTimeline: View {
    var body: some View {
        VStack(spacing: 9) {
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule().fill(.white.opacity(0.13))
                    Capsule().fill(.white.opacity(0.65)).frame(width: geometry.size.width * 0.28)
                }
            }
            .frame(height: 4)
            HStack {
                Text("0:42")
                Spacer()
                Text("2:30")
            }
            .overlay {
                Text("DEMO TIMELINE")
                    .font(.system(size: 9, weight: .medium)).tracking(1.4)
            }
            .font(.system(size: 11, design: .monospaced))
            .foregroundStyle(.white.opacity(0.35))
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Demo progress: 42 seconds of 2 minutes 30 seconds")
    }
}
