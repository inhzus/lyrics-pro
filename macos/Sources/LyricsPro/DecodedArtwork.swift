import Foundation
import CoreGraphics
import ImageIO

// CGImage is immutable. Created on the event queue and consumed on the main actor.
struct DecodedArtwork: @unchecked Sendable {
    let image: CGImage?

    init(base64: String?) {
        guard let base64, let data = Data(base64Encoded: base64), data.count <= 4 * 1024 * 1024,
              let source = CGImageSourceCreateWithData(data as CFData, nil) else {
            image = nil
            return
        }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 1024,
            kCGImageSourceShouldCacheImmediately: true,
        ]
        image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }
}
