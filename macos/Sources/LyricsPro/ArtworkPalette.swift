import Foundation
import CoreGraphics
import ImageIO

struct BackgroundRGB: Equatable, Hashable, Sendable {
    let red: Double
    let green: Double
    let blue: Double

    static func moderated(_ red: Double, _ green: Double, _ blue: Double) -> Self {
        let gray = (red + green + blue) / 3
        var values = [red, green, blue].map { gray + ($0 - gray) * 0.82 }
        let peak = values.max() ?? 0
        if peak > 0.66 { values = values.map { $0 * 0.66 / peak } }
        let luminance = values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722
        if luminance < 0.12 { values = values.map { $0 + 0.12 - luminance } }
        values = values.map { min(0.66, max(0, $0)) }
        return Self(red: values[0], green: values[1], blue: values[2])
    }
}

struct ArtworkPalette: Equatable, Hashable, Sendable {
    let colors: [BackgroundRGB]
    static let neutral = Self(colors: [
        .init(red: 0.19, green: 0.22, blue: 0.25), .init(red: 0.13, green: 0.16, blue: 0.20),
        .init(red: 0.16, green: 0.20, blue: 0.22), .init(red: 0.12, green: 0.14, blue: 0.18)
    ])
    static func demo(warm: Bool) -> Self {
        Self(colors: warm ? [
            .moderated(0.54, 0.30, 0.17), .moderated(0.24, 0.21, 0.22),
            .moderated(0.30, 0.24, 0.15), .moderated(0.18, 0.25, 0.28)
        ] : [
            .moderated(0.15, 0.35, 0.39), .moderated(0.22, 0.31, 0.32),
            .moderated(0.35, 0.36, 0.24), .moderated(0.12, 0.22, 0.29)
        ])
    }

    /// ImageIO downsamples before decoding; no full-size image is drawn or blurred.
    static func load(from data: Data) async -> Self? {
        guard !Task.isCancelled else { return nil }
        let worker = Task.detached(priority: .utility) { extract(from: data) }
        let palette = await withTaskCancellationHandler(operation: { await worker.value },
                                                       onCancel: { worker.cancel() })
        return Task.isCancelled ? nil : palette
    }

    static func extract(from data: Data) -> Self {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: 32
              ] as CFDictionary) else { return .neutral }
        let side = 32
        var pixels = [UInt8](repeating: 0, count: side * side * 4)
        let drawn = pixels.withUnsafeMutableBytes { buffer -> Bool in
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let context = CGContext(data: buffer.baseAddress, width: side, height: side,
                    bitsPerComponent: 8, bytesPerRow: side * 4, space: space,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)
            else { return false }
            context.interpolationQuality = .medium
            context.draw(image, in: CGRect(x: 0, y: 0, width: side, height: side))
            return true
        }
        guard drawn else { return .neutral }
        var sums = Array(repeating: [Double](repeating: 0, count: 4), count: 4)
        for y in 0..<side {
            for x in 0..<side {
                let offset = (y * side + x) * 4
                let region = (y / 16) * 2 + x / 16
                for channel in 0..<4 { sums[region][channel] += Double(pixels[offset + channel]) / 255 }
            }
        }
        return Self(colors: sums.enumerated().map { index, sum in
            guard sum[3] > 1 else { return neutral.colors[index] }
            return .moderated(sum[0] / sum[3], sum[1] / sum[3], sum[2] / sum[3])
        })
    }
}

/// Only elapsed visible, playing time contributes to motion, preserving position on pause.
struct BackgroundMotionClock {
    private var elapsed = 0.0
    private var started: Double?
    func time(at now: Double) -> Double { elapsed + (started.map { max(0, now - $0) } ?? 0) }
    mutating func setRunning(_ running: Bool, at now: Double) {
        if running, started == nil { started = now }
        else if !running, started != nil { elapsed = time(at: now); started = nil }
    }
}
