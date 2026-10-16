// make_logo: LZ4 Compression art - a black block with "LZ4" in white, in the
// same style as PS5VR's logo.
//   swiftc -O make_logo.swift -o make_logo && ./make_logo <bold.ttf> <out_dir>
// Writes icon0.png (512x512, the block), pic0.png and pic1.png (1920x1080:
// the block and the "LZ4 Compression" wordmark on the home-screen backdrop)
// and web logo sizes for the app UI.
import AppKit
import CoreText

let args = CommandLine.arguments
guard args.count == 3 else { print("usage: make_logo bold.ttf out_dir"); exit(2) }
let fontURL = URL(fileURLWithPath: args[1]) as CFURL
CTFontManagerRegisterFontsForURL(fontURL, .process, nil)
let desc = (CTFontManagerCreateFontDescriptorsFromURL(fontURL) as! [CTFontDescriptor])[0]
let black = CGColor(srgbRed: 0, green: 0, blue: 0, alpha: 1)
let white = CGColor(gray: 1, alpha: 1)
let edge = CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 0.16)
let backdrop = CGColor(srgbRed: 0.035, green: 0.035, blue: 0.04, alpha: 1)

func drawText(_ ctx: CGContext, _ text: String, size: CGFloat, color: CGColor,
              kern: CGFloat, centerX: CGFloat? = nil, x: CGFloat = 0, midY: CGFloat) -> CGRect {
    let font = CTFontCreateWithFontDescriptor(desc, size, nil)
    let attr = NSAttributedString(string: text, attributes: [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTForegroundColorAttributeName as String): color,
        NSAttributedString.Key(kCTKernAttributeName as String): kern,
    ])
    let line = CTLineCreateWithAttributedString(attr)
    let b = CTLineGetBoundsWithOptions(line, .useGlyphPathBounds)
    let px = centerX != nil ? centerX! - b.width / 2 - b.minX : x - b.minX
    ctx.textPosition = CGPoint(x: px, y: midY - b.height / 2 - b.minY)
    CTLineDraw(line, ctx)
    return CGRect(x: px + b.minX, y: midY - b.height / 2, width: b.width, height: b.height)
}

func block(_ ctx: CGContext, _ r: CGRect, radius: CGFloat, outline: Bool) {
    let path = CGPath(roundedRect: r, cornerWidth: radius, cornerHeight: radius, transform: nil)
    ctx.setFillColor(black)
    ctx.addPath(path)
    ctx.fillPath()
    if outline {
        ctx.setStrokeColor(edge)
        ctx.setLineWidth(max(2, r.width * 0.008))
        ctx.addPath(path)
        ctx.strokePath()
    }
    // "LZ4", white, ~44% of the block's height, optically centred
    _ = drawText(ctx, "LZ4", size: r.height * 0.44, color: white, kern: r.height * -0.012,
                 centerX: r.midX, midY: r.midY)
}

func save(_ ctx: CGContext, _ path: String) {
    let rep = NSBitmapImageRep(cgImage: ctx.makeImage()!)
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
    print("wrote \(path) \(ctx.width)x\(ctx.height)")
}

func canvas(_ w: Int, _ h: Int) -> CGContext {
    CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
              space: CGColorSpace(name: CGColorSpace.sRGB)!,
              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
}

let out = args[2]
// Home-screen tile: the block itself, edge to edge like PS5VR's.
let icon = canvas(512, 512)
block(icon, CGRect(x: 0, y: 0, width: 512, height: 512), radius: 0, outline: false)
save(icon, out + "/icon0.png")

// Web logo (rounded block, transparent corners) for the in-app UI.
for size in [96, 256] {
    let c = canvas(size, size)
    block(c, CGRect(x: 0, y: 0, width: size, height: size), radius: CGFloat(size) * 0.18, outline: true)
    save(c, out + "/lz4-logo-\(size).png")
}

// Home-screen background / launch art: block + wordmark on a dark backdrop
// with a soft light behind the block.
for name in ["pic0.png", "pic1.png"] {
    let c = canvas(1920, 1080)
    c.setFillColor(backdrop)
    c.fill(CGRect(x: 0, y: 0, width: 1920, height: 1080))
    let glow = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
                          colors: [CGColor(srgbRed: 0.10, green: 0.42, blue: 0.95, alpha: 0.20),
                                   CGColor(srgbRed: 0.10, green: 0.42, blue: 0.95, alpha: 0.0)] as CFArray,
                          locations: [0, 1])!
    c.drawRadialGradient(glow, startCenter: CGPoint(x: 960, y: 560), startRadius: 0,
                         endCenter: CGPoint(x: 960, y: 560), endRadius: 760, options: [])
    let side: CGFloat = 300
    let text = "Compression"
    // measure wordmark to centre block + wordmark as one group
    let font = CTFontCreateWithFontDescriptor(desc, 132, nil)
    let measure = CTLineCreateWithAttributedString(NSAttributedString(string: text, attributes: [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTKernAttributeName as String): -2.0]))
    let tw = CTLineGetBoundsWithOptions(measure, .useGlyphPathBounds).width
    let gap: CGFloat = 64
    let total = side + gap + tw
    let left = 960 - total / 2
    block(c, CGRect(x: left, y: 540 - side / 2, width: side, height: side), radius: 46, outline: true)
    _ = drawText(c, text, size: 132, color: white, kern: -2.0, x: left + side + gap, midY: 540)
    save(c, out + "/" + name)
}
