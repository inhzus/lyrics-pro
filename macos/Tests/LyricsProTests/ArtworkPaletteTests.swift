import Foundation
import CoreGraphics
import ImageIO
import Testing
@testable import LyricsPro

struct ArtworkPaletteTests {
    @Test func artworkDecoderRejectsInvalidDataAndAcceptsImage() throws {
        #expect(DecodedArtwork(base64: nil).image == nil)
        #expect(DecodedArtwork(base64: "not base64").image == nil)
        #expect(DecodedArtwork(base64: Data("not an image".utf8).base64EncodedString()).image == nil)
        #expect(DecodedArtwork(base64: Data(repeating: 0, count: 4 * 1024 * 1024 + 1).base64EncodedString()).image == nil)
        let data = try png([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255])
        let image = try #require(DecodedArtwork(base64: data.base64EncodedString()).image)
        #expect(image.width == 2 && image.height == 2)
    }

    private func png(_ pixels: [UInt8], side: Int = 2) throws -> Data {
        let provider = try #require(CGDataProvider(data: Data(pixels) as CFData))
        let image = try #require(CGImage(width: side, height: side, bitsPerComponent: 8, bitsPerPixel: 32,
            bytesPerRow: side * 4, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue), provider: provider,
            decode: nil, shouldInterpolate: false, intent: .defaultIntent))
        let data = NSMutableData()
        let destination = try #require(CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, nil)
        #expect(CGImageDestinationFinalize(destination))
        return data as Data
    }

    @Test func invalidAndTransparentArtworkUseNeutralPalette() throws {
        #expect(ArtworkPalette.extract(from: Data("bad image".utf8)) == .neutral)
        #expect(ArtworkPalette.extract(from: try png(Array(repeating: 0, count: 16))) == .neutral)
    }

    @Test func brightDarkAndMonochromeArtworkStayBounded() throws {
        for level: UInt8 in [0, 127, 255] {
            let pixel = [level, level, level, 255]
            let data = try png(Array(repeating: pixel, count: 4).flatMap { $0 })
            let palette = ArtworkPalette.extract(from: data)
            #expect(palette == ArtworkPalette.extract(from: data))
            #expect(palette.colors.count == 4)
            for color in palette.colors {
                #expect(abs(color.red - color.green) < 0.001)
                #expect(abs(color.green - color.blue) < 0.001)
                #expect(color.red >= 0.119 && color.red <= 0.661)
            }
        }
    }

    @Test func regionalColorsAndTransparentPixelsPreserveHue() throws {
        let palette = ArtworkPalette.extract(from: try png([
            255, 0, 0, 255, 0, 255, 0, 255,
            0, 0, 255, 255, 255, 0, 0, 128
        ]))
        #expect(palette.colors.contains { $0.red > $0.green * 2 && $0.red > $0.blue * 2 })
        #expect(palette.colors.contains { $0.green > $0.red * 2 && $0.green > $0.blue * 2 })
        #expect(palette.colors.contains { $0.blue > $0.red * 2 && $0.blue > $0.green * 2 })
        #expect(palette.colors.allSatisfy { [$0.red, $0.green, $0.blue].allSatisfy { $0.isFinite && $0 >= 0 && $0 <= 0.661 } })
    }

    @Test func motionFreezesAndResumesWithoutElapsedHiddenTime() {
        var clock = BackgroundMotionClock()
        #expect(clock.time(at: 10) == 0)
        clock.setRunning(true, at: 10)
        clock.setRunning(true, at: 12)
        #expect(clock.time(at: 14) == 4)
        clock.setRunning(false, at: 14)
        #expect(clock.time(at: 100) == 4)
        clock.setRunning(false, at: 101)
        clock.setRunning(true, at: 200)
        #expect(clock.time(at: 200) == 4)
        #expect(clock.time(at: 205) == 9)
    }

    @Test @MainActor func cancelledArtworkRequestCannotSupplyAPalette() async throws {
        let data = try png(Array(repeating: [UInt8(255), 0, 0, 255], count: 4).flatMap { $0 })
        let stale = Task { await ArtworkPalette.load(from: data) }
        stale.cancel()
        #expect(await stale.value == nil)
        #expect(await ArtworkPalette.load(from: data) == ArtworkPalette.extract(from: data))
    }
}

struct ArtworkAccentTests {
    private func luminance(_ c: BackgroundRGB) -> Double { c.red * 0.2126 + c.green * 0.7152 + c.blue * 0.0722 }

    private func accent(_ pixels: [(Double, Double, Double)]) -> BackgroundRGB? {
        var histogram = HueHistogram()
        for (r, g, b) in pixels { histogram.add(r, g, b) }
        return histogram.accent
    }

    @Test func greyOrTransparentArtworkFallsBackToTeal() throws {
        #expect(accent(Array(repeating: (0.5, 0.5, 0.5), count: 100)) == nil)
        #expect(accent([]) == nil)
        #expect(ArtworkPalette.neutral.accent == ArtworkPalette.fallbackAccent)
        #expect(ArtworkPalette.extract(from: Data("bad image".utf8)).accent == ArtworkPalette.fallbackAccent)
    }

    @Test func dominantHueWinsOverAMixedAverage() throws {
        // Mostly orange with some violet: the accent is orange, not a muddy red-pink average.
        let pixels = Array(repeating: (0.95, 0.5, 0.1), count: 70) + Array(repeating: (0.5, 0.2, 0.9), count: 30)
        let color = try #require(accent(pixels))
        #expect(color.red > color.green && color.green > color.blue)
    }

    @Test func accentsStayLightEnoughToReadOnTheDarkBackground() {
        for step in 0..<24 {
            let color = HueHistogram.light(hue: Double(step) / 24, saturation: 0.55)
            #expect(luminance(color) >= 0.49)
            #expect([color.red, color.green, color.blue].allSatisfy { $0 >= 0 && $0 <= 1 })
        }
    }

    @Test func vividCoverImageProducesItsHue() throws {
        let provider = try #require(CGDataProvider(data: Data(Array(repeating: [UInt8(30), 60, 230, 255], count: 4).flatMap { $0 }) as CFData))
        let image = try #require(CGImage(width: 2, height: 2, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 8,
            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
            provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
        let data = NSMutableData()
        let destination = try #require(CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, nil)
        #expect(CGImageDestinationFinalize(destination))
        let accent = ArtworkPalette.extract(from: data as Data).accent
        #expect(accent != ArtworkPalette.fallbackAccent)
        #expect(accent.blue > accent.red && accent.blue > accent.green)
    }
}
