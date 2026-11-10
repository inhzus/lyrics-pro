// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "LyricsPro",
    platforms: [.macOS(.v15)],
    products: [.executable(name: "LyricsPro", targets: ["LyricsPro"])],
    targets: [
        .executableTarget(name: "LyricsPro"),
        .testTarget(name: "LyricsProTests", dependencies: ["LyricsPro"]),
    ]
)
