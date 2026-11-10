#!/usr/bin/env swift
// Original editable vector drawing. Produces the standard macOS iconset locally.
import AppKit
import CoreGraphics
import ImageIO

guard CommandLine.arguments.count == 2 else { fatalError("Usage: render-icon.swift output.iconset") }
let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

func render(_ size: Int, name: String) throws {
    let space = CGColorSpace(name: CGColorSpace.sRGB)!
    let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                            bytesPerRow: size * 4, space: space,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    context.scaleBy(x: CGFloat(size) / 1024, y: CGFloat(size) / 1024)
    let tile = CGPath(roundedRect: CGRect(x: 80, y: 80, width: 864, height: 864),
                      cornerWidth: 192, cornerHeight: 192, transform: nil)
    context.saveGState()
    context.setShadow(offset: CGSize(width: 0, height: -10), blur: 24,
                      color: CGColor(gray: 0, alpha: 0.22))
    context.addPath(tile)
    context.setFillColor(CGColor(red: 0.05, green: 0.25, blue: 0.28, alpha: 1))
    context.fillPath()
    context.restoreGState()
    context.saveGState()
    context.addPath(tile); context.clip()
    let gradient = CGGradient(colorsSpace: space, colors: [
        CGColor(red: 0.14, green: 0.56, blue: 0.55, alpha: 1),
        CGColor(red: 0.04, green: 0.19, blue: 0.25, alpha: 1)
    ] as CFArray, locations: [0, 1])!
    context.drawLinearGradient(gradient, start: CGPoint(x: 180, y: 940),
                               end: CGPoint(x: 850, y: 90), options: [])
    context.restoreGState()
    context.addPath(tile)
    context.setStrokeColor(CGColor(gray: 1, alpha: 0.16)); context.setLineWidth(3); context.strokePath()

    // Lyrics: three generously spaced lines, kept clear at 16–32 px.
    context.setStrokeColor(CGColor(gray: 1, alpha: 0.94))
    context.setLineCap(.round); context.setLineWidth(46)
    for (y, width) in [(650.0, 210.0), (520.0, 165.0), (390.0, 120.0)] {
        context.move(to: CGPoint(x: 240, y: y)); context.addLine(to: CGPoint(x: 240 + width, y: y)); context.strokePath()
    }
    // A single note, drawn as paths rather than a font or borrowed symbol.
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.fillEllipse(in: CGRect(x: 540, y: 310, width: 165, height: 115))
    context.addPath(CGPath(roundedRect: CGRect(x: 660, y: 363, width: 44, height: 360),
                          cornerWidth: 22, cornerHeight: 22, transform: nil))
    context.fillPath()
    let flag = CGMutablePath()
    flag.move(to: CGPoint(x: 682, y: 724))
    flag.addCurve(to: CGPoint(x: 811, y: 558), control1: CGPoint(x: 705, y: 649), control2: CGPoint(x: 815, y: 665))
    flag.addCurve(to: CGPoint(x: 785, y: 510), control1: CGPoint(x: 812, y: 532), control2: CGPoint(x: 800, y: 515))
    flag.addCurve(to: CGPoint(x: 680, y: 625), control1: CGPoint(x: 799, y: 592), control2: CGPoint(x: 712, y: 579))
    flag.closeSubpath(); context.addPath(flag); context.fillPath()

    let image = context.makeImage()!
    let url = directory.appendingPathComponent(name)
    let destination = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil)!
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else { throw CocoaError(.fileWriteUnknown) }
}

for points in [16, 32, 128, 256, 512] {
    try render(points, name: "icon_\(points)x\(points).png")
    try render(points * 2, name: "icon_\(points)x\(points)@2x.png")
}
