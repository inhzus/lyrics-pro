import SwiftUI

/// Original vector cover used only by the visual prototype.
struct ArtworkView: View {
    let song: DemoSong

    var body: some View {
        GeometryReader { geometry in
            let side = geometry.size.width
            ZStack {
                LinearGradient(colors: [Color(red: 0.10, green: 0.24, blue: 0.28), Color(red: 0.03, green: 0.08, blue: 0.12)], startPoint: .topLeading, endPoint: .bottomTrailing)
                if song != .noArtwork {
                    Circle()
                        .fill(song.accent.opacity(0.24))
                        .frame(width: side * 0.8, height: side * 0.8)
                        .blur(radius: side * 0.15)
                        .offset(x: side * 0.22, y: side * 0.1)
                    Circle()
                        .fill(Color(red: 0.92, green: 0.86, blue: 0.66))
                        .frame(width: side * 0.22, height: side * 0.22)
                        .shadow(color: song.accent.opacity(0.5), radius: side * 0.08)
                        .offset(x: side * 0.20, y: -side * 0.04)
                    Canvas { context, size in
                        for i in 0..<22 {
                            let height = size.height * (0.10 + Double((i * 7 + 3) % 11) / 100)
                            let rect = CGRect(x: Double(i) * size.width / 21, y: size.height - height, width: size.width / 18, height: height)
                            context.fill(Path(rect), with: .color(Color(red: 0.025, green: 0.065, blue: 0.085)))
                        }
                        for i in 0..<13 {
                            let y = size.height * (0.65 + Double(i) * 0.016)
                            var path = Path()
                            path.move(to: CGPoint(x: size.width * 0.52 - Double(i % 3) * 5, y: y))
                            path.addLine(to: CGPoint(x: size.width * 0.86 + Double(i % 4) * 4, y: y))
                            context.stroke(path, with: .color(song.accent.opacity(0.12)), lineWidth: 1)
                        }
                    }
                    VStack(alignment: .leading, spacing: side * 0.02) {
                        Text("AFTER\nHOURS")
                            .font(.system(size: side * 0.14, weight: .black, design: .rounded))
                            .tracking(-side * 0.006)
                            .lineSpacing(-side * 0.015)
                            .foregroundStyle(Color(red: 0.83, green: 0.91, blue: 0.87))
                        Text("夜 色 裡 的 歌")
                            .font(.system(size: side * 0.035, weight: .medium))
                            .tracking(side * 0.009)
                            .foregroundStyle(.white.opacity(0.65))
                        Spacer()
                        Text("LYRICS PRO  /  DEMO SESSIONS")
                            .font(.system(size: side * 0.022, weight: .medium, design: .monospaced))
                            .tracking(1)
                            .foregroundStyle(.white.opacity(0.55))
                    }
                    .padding(side * 0.085)
                    .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    VStack(spacing: 16) {
                        Image(systemName: "music.note")
                            .font(.system(size: side * 0.18, weight: .light))
                        Text("Artwork unavailable")
                            .font(.system(size: 14))
                    }
                    .foregroundStyle(.white.opacity(0.4))
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.white.opacity(0.10), lineWidth: 1))
        .accessibilityLabel(song == .noArtwork ? "Artwork unavailable" : "Demo cover: a moon above the city, After Hours")
    }
}
