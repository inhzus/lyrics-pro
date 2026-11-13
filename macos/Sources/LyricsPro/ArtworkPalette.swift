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
    /// Highlight colour for the current lyric's reading: the cover's dominant hue, kept light.
    var accent = Self.fallbackAccent
    static let fallbackAccent = BackgroundRGB(red: 0.43, green: 0.72, blue: 0.70)
    static let neutral = Self(colors: [
        .init(red: 0.19, green: 0.22, blue: 0.25), .init(red: 0.13, green: 0.16, blue: 0.20),
        .init(red: 0.16, green: 0.20, blue: 0.22), .init(red: 0.12, green: 0.14, blue: 0.18)
    ])
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
        var hues = HueHistogram()
        for y in 0..<side {
            for x in 0..<side {
                let offset = (y * side + x) * 4
                let region = (y / 16) * 2 + x / 16
                for channel in 0..<4 { sums[region][channel] += Double(pixels[offset + channel]) / 255 }
                let alpha = Double(pixels[offset + 3]) / 255
                if alpha > 0.5 {
                    hues.add(Double(pixels[offset]) / 255 / alpha, Double(pixels[offset + 1]) / 255 / alpha,
                             Double(pixels[offset + 2]) / 255 / alpha)
                }
            }
        }
        return Self(colors: sums.enumerated().map { index, sum in
            guard sum[3] > 1 else { return neutral.colors[index] }
            return .moderated(sum[0] / sum[3], sum[1] / sum[3], sum[2] / sum[3])
        }, accent: hues.accent ?? fallbackAccent)
    }
}

/// Finds the most prominent vivid hue; grey, very dark, and very pale pixels don't vote.
struct HueHistogram {
    private static let bins = 12
    private var weight = [Double](repeating: 0, count: bins)
    private var x = [Double](repeating: 0, count: bins)
    private var y = [Double](repeating: 0, count: bins)
    private var saturation = [Double](repeating: 0, count: bins)
    private var total = 0.0
    private var count = 0

    mutating func add(_ red: Double, _ green: Double, _ blue: Double) {
        count += 1
        let (r, g, b) = (min(1, red), min(1, green), min(1, blue))
        let peak = max(r, g, b), chroma = peak - min(r, g, b)
        guard peak > 0.25, chroma > 0.12 else { return }
        var hue: Double
        if peak == r { hue = (g - b) / chroma } else if peak == g { hue = (b - r) / chroma + 2 } else { hue = (r - g) / chroma + 4 }
        hue = (hue / 6).truncatingRemainder(dividingBy: 1)
        if hue < 0 { hue += 1 }
        let vote = chroma * peak
        let bin = min(Self.bins - 1, Int(hue * Double(Self.bins)))
        weight[bin] += vote
        x[bin] += cos(hue * 2 * .pi) * vote
        y[bin] += sin(hue * 2 * .pi) * vote
        saturation[bin] += chroma / peak * vote
        total += vote
    }

    /// Nil when less than about 4% of the cover is colourful.
    var accent: BackgroundRGB? {
        guard count > 0, total > Double(count) * 0.04 * 0.25,
              let bin = weight.indices.max(by: { weight[$0] < weight[$1] }), weight[bin] > 0 else { return nil }
        var hue = atan2(y[bin], x[bin]) / (2 * .pi)
        if hue < 0 { hue += 1 }
        return Self.light(hue: hue, saturation: min(0.55, max(0.35, saturation[bin] / weight[bin])))
    }

    /// A pale tint that stays readable on the dark player background.
    static func light(hue: Double, saturation: Double) -> BackgroundRGB {
        let brightness = 0.9
        let sector = hue * 6, index = Int(sector) % 6, fraction = sector - Double(Int(sector))
        let p = brightness * (1 - saturation)
        let q = brightness * (1 - saturation * fraction)
        let t = brightness * (1 - saturation * (1 - fraction))
        var rgb: [Double] = switch index {
        case 0: [brightness, t, p]
        case 1: [q, brightness, p]
        case 2: [p, brightness, t]
        case 3: [p, q, brightness]
        case 4: [t, p, brightness]
        default: [brightness, p, q]
        }
        // Blue and violet tints are darker at the same brightness; lift them toward white.
        let luminance = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
        if luminance < 0.5 { rgb = rgb.map { $0 + (1 - $0) * (0.5 - luminance) / (1 - luminance) } }
        return BackgroundRGB(red: rgb[0], green: rgb[1], blue: rgb[2])
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
