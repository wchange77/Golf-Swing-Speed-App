import SwiftUI
import GolfAnalysisKit

struct TrajectoryOverlayView: View {
    let bezierPoints: [TrajectoryPoint]
    let detectionPoints: [CGPoint]
    let impactPoint: CGPoint?
    let landingPoint: CGPoint?
    let frameSize: CGSize
    let animationProgress: Double

    init(
        bezierPoints: [TrajectoryPoint] = [],
        detectionPoints: [CGPoint] = [],
        impactPoint: CGPoint? = nil,
        landingPoint: CGPoint? = nil,
        frameSize: CGSize = CGSize(width: 1920, height: 1080),
        animationProgress: Double = 1.0
    ) {
        self.bezierPoints = bezierPoints
        self.detectionPoints = detectionPoints
        self.impactPoint = impactPoint
        self.landingPoint = landingPoint
        self.frameSize = frameSize
        self.animationProgress = animationProgress
    }

    var body: some View {
        Canvas { context, size in
            let scaleX = size.width / frameSize.width
            let scaleY = size.height / frameSize.height

            func scaled(_ p: CGPoint) -> CGPoint {
                CGPoint(x: p.x * scaleX, y: p.y * scaleY)
            }

            func scaledFromNormalized(_ p: TrajectoryPoint) -> CGPoint {
                CGPoint(x: p.x * size.width, y: p.y * size.height)
            }

            drawTrajectoryLine(context: context, size: size)
            drawDetectionPoints(context: context, scale: scaled)
            drawImpactPoint(context: context, scale: scaled)
            drawLandingPoint(context: context, size: size)
        }
    }

    private func drawTrajectoryLine(context: GraphicsContext, size: CGSize) {
        guard bezierPoints.count >= 2 else { return }

        let visibleCount = Int(Double(bezierPoints.count) * animationProgress)
        guard visibleCount >= 2 else { return }

        let visible = Array(bezierPoints.prefix(visibleCount))

        var path = Path()
        let first = CGPoint(x: visible[0].x * size.width, y: visible[0].y * size.height)
        path.move(to: first)

        for i in 1..<visible.count {
            let p = CGPoint(x: visible[i].x * size.width, y: visible[i].y * size.height)
            path.addLine(to: p)
        }

        var glowContext = context
        glowContext.addFilter(.blur(radius: 6))
        glowContext.stroke(path, with: .color(.yellow.opacity(0.4)), lineWidth: 6)

        let gradient = Gradient(colors: [.yellow, .orange, .red])
        context.stroke(
            path,
            with: .linearGradient(
                gradient,
                startPoint: first,
                endPoint: CGPoint(
                    x: visible.last!.x * size.width,
                    y: visible.last!.y * size.height
                )
            ),
            style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round)
        )
    }

    private func drawDetectionPoints(context: GraphicsContext, scale: (CGPoint) -> CGPoint) {
        for (i, point) in detectionPoints.enumerated() {
            let sp = scale(point)
            let opacity = 0.4 + 0.6 * Double(i) / Double(max(1, detectionPoints.count - 1))
            let rect = CGRect(x: sp.x - 4, y: sp.y - 4, width: 8, height: 8)
            context.fill(Circle().path(in: rect), with: .color(.cyan.opacity(opacity)))
            let outerRect = CGRect(x: sp.x - 5, y: sp.y - 5, width: 10, height: 10)
            context.stroke(Circle().path(in: outerRect), with: .color(.white.opacity(0.6)), lineWidth: 1)
        }
    }

    private func drawImpactPoint(context: GraphicsContext, scale: (CGPoint) -> CGPoint) {
        guard let impact = impactPoint else { return }
        let sp = scale(impact)

        let outerRect = CGRect(x: sp.x - 12, y: sp.y - 12, width: 24, height: 24)
        context.stroke(Circle().path(in: outerRect), with: .color(.green), lineWidth: 2)

        let innerRect = CGRect(x: sp.x - 4, y: sp.y - 4, width: 8, height: 8)
        context.fill(Circle().path(in: innerRect), with: .color(.green))

        context.draw(
            Text("IMPACT").font(.system(size: 10, weight: .bold)).foregroundColor(.green),
            at: CGPoint(x: sp.x, y: sp.y - 20)
        )
    }

    private func drawLandingPoint(context: GraphicsContext, size: CGSize) {
        guard let landing = landingPoint else { return }
        let sp = CGPoint(x: landing.x * size.width, y: landing.y * size.height)

        let crossSize: CGFloat = 8
        var crossPath = Path()
        crossPath.move(to: CGPoint(x: sp.x - crossSize, y: sp.y))
        crossPath.addLine(to: CGPoint(x: sp.x + crossSize, y: sp.y))
        crossPath.move(to: CGPoint(x: sp.x, y: sp.y - crossSize))
        crossPath.addLine(to: CGPoint(x: sp.x, y: sp.y + crossSize))
        context.stroke(crossPath, with: .color(.red), lineWidth: 2)

        let circleRect = CGRect(x: sp.x - 10, y: sp.y - 10, width: 20, height: 20)
        context.stroke(Circle().path(in: circleRect), with: .color(.red.opacity(0.6)), lineWidth: 1)
    }
}

#Preview {
    ZStack {
        Color.black
        TrajectoryOverlayView(
            bezierPoints: (0...60).map { i in
                let t = Double(i) / 60.0
                let x = 0.1 + t * 0.8
                let y = 0.85 - 0.3 * sin(t * .pi)
                return TrajectoryPoint(x: x, y: y)
            },
            detectionPoints: [
                CGPoint(x: 200, y: 900),
                CGPoint(x: 400, y: 700),
                CGPoint(x: 600, y: 500),
            ],
            impactPoint: CGPoint(x: 200, y: 900),
            landingPoint: CGPoint(x: 0.9, y: 0.85),
            frameSize: CGSize(width: 1920, height: 1080)
        )
    }
}
