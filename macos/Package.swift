// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "LyricsPro",
    platforms: [.macOS(.v26)],
    products: [.executable(name: "LyricsPro", targets: ["LyricsPro"])],
    targets: [
        .executableTarget(name: "LyricsPro"),
        .testTarget(name: "LyricsProTests", dependencies: ["LyricsPro"]),
    ]
)
