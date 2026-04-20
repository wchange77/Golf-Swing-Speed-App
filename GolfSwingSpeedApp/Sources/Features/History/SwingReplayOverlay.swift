import SwiftUI

/// Draws body pose and club shaft overlay on a swing frame.
/// Shows arm lines, shaft line, lag angle, and speed at each frame.
struct SwingReplayOverlay: View {
    let bodyPose: BodyPoseFrame?
    let clubHeadPosition: CGPoint?
    let lagAngleDegrees: Double?
    let speedMph: Double?
    let swingPhase: SwingPhase?
    let imageSize: CGSize

    var body: some View {
        Canvas { context, size in
            let scaleX = size.width / imageSize.width
            let scaleY = size.height / imageSize.height

            // Draw body pose skeleton
            if let pose = bodyPose {
                drawSkeleton(context: context, pose: pose, scaleX: scaleX, scaleY: scaleY)
            }

            // Draw club shaft
            if let pose = bodyPose, let wrist2D = pose.leadWrist2D, let clubHead = clubHeadPosition {
                let from = CGPoint(x: wrist2D.x * scaleX, y: wrist2D.y * scaleY)
                let to = CGPoint(x: clubHead.x * scaleX, y: clubHead.y * scaleY)

                // Shaft line coloured by lag angle
                let shaftColor = lagColor(lagAngleDegrees)
                var shaftPath = Path()
                shaftPath.move(to: from)
                shaftPath.addLine(to: to)
                context.stroke(shaftPath, with: .color(shaftColor), lineWidth: 3)

                // Club head marker
                let clubRect = CGRect(x: to.x - 6, y: to.y - 6, width: 12, height: 12)
                context.fill(Path(ellipseIn: clubRect), with: .color(.yellow.opacity(0.8)))
                context.stroke(Path(ellipseIn: clubRect), with: .color(.yellow), lineWidth: 2)
            }

            // Draw lag angle arc
            if let pose = bodyPose, let elbow2D = pose.leadElbow2D, let wrist2D = pose.leadWrist2D,
               let clubHead = clubHeadPosition, let angle = lagAngleDegrees {
                drawLagArc(
                    context: context,
                    elbow: CGPoint(x: elbow2D.x * scaleX, y: elbow2D.y * scaleY),
                    wrist: CGPoint(x: wrist2D.x * scaleX, y: wrist2D.y * scaleY),
                    clubHead: CGPoint(x: clubHead.x * scaleX, y: clubHead.y * scaleY),
                    angle: angle
                )
            }
        }
        .allowsHitTesting(false)
        .overlay(alignment: .topTrailing) {
            // Speed and phase badge
            if let speed = speedMph {
                VStack(alignment: .trailing, spacing: 2) {
                    Text("\(speed.formattedSpeed) mph")
                        .font(.system(size: 16, weight: .bold, design: .rounded))
                        .foregroundStyle(.white)

                    if let phase = swingPhase {
                        Text(phase.rawValue)
                            .font(.caption2)
                            .foregroundStyle(phaseColor(phase))
                    }

                    if let lag = lagAngleDegrees {
                        Text("Lag: \(lag.formattedAngle)")
                            .font(.caption2)
                            .foregroundStyle(lagColor(lag))
                    }
                }
                .padding(8)
                .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
                .padding(8)
            }
        }
    }

    // MARK: - Skeleton Drawing

    private func drawSkeleton(context: GraphicsContext, pose: BodyPoseFrame, scaleX: CGFloat, scaleY: CGFloat) {
        // Draw lead arm: shoulder → elbow → wrist
        if let shoulder2D = pose.leadShoulder3D, let elbow2D = pose.leadElbow2D, let wrist2D = pose.leadWrist2D {
            // Use 2D positions for overlay (3D for calculations only)
            let elbowScaled = CGPoint(x: elbow2D.x * scaleX, y: elbow2D.y * scaleY)
            let wristScaled = CGPoint(x: wrist2D.x * scaleX, y: wrist2D.y * scaleY)

            var armPath = Path()
            armPath.move(to: elbowScaled)
            armPath.addLine(to: wristScaled)
            context.stroke(armPath, with: .color(.cyan.opacity(0.8)), lineWidth: 2)

            // Joint dots
            let joints = [elbowScaled, wristScaled]
            for joint in joints {
                let rect = CGRect(x: joint.x - 4, y: joint.y - 4, width: 8, height: 8)
                context.fill(Path(ellipseIn: rect), with: .color(.cyan.opacity(0.6)))
            }
        }
    }

    // MARK: - Lag Arc Drawing

    private func drawLagArc(context: GraphicsContext, elbow: CGPoint, wrist: CGPoint, clubHead: CGPoint, angle: Double) {
        // Draw a small arc at the wrist showing the lag angle
        let radius: CGFloat = 25

        let forearmAngle = atan2(wrist.y - elbow.y, wrist.x - elbow.x)
        let shaftAngle = atan2(clubHead.y - wrist.y, clubHead.x - wrist.x)

        var arcPath = Path()
        arcPath.addArc(
            center: wrist,
            radius: radius,
            startAngle: Angle(radians: forearmAngle),
            endAngle: Angle(radians: shaftAngle),
            clockwise: false
        )
        context.stroke(arcPath, with: .color(lagColor(angle).opacity(0.7)), lineWidth: 2)

        // Angle label
        let labelX = wrist.x + (radius + 10) * cos((forearmAngle + shaftAngle) / 2)
        let labelY = wrist.y + (radius + 10) * sin((forearmAngle + shaftAngle) / 2)
        context.draw(
            Text(angle.formattedAngle)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(lagColor(angle)),
            at: CGPoint(x: labelX, y: labelY)
        )
    }

    // MARK: - Colours

    private func lagColor(_ angle: Double?) -> Color {
        guard let angle else { return .white }
        if angle > 90 { return .green }   // Good lag retention
        if angle > 60 { return .yellow }  // Moderate
        return .red                        // Early release / casting
    }

    private func phaseColor(_ phase: SwingPhase) -> Color {
        switch phase {
        case .address: return .gray
        case .backswing: return .blue
        case .top: return .cyan
        case .earlyDownswing: return .yellow
        case .lateDownswing: return .orange
        case .impact: return .red
        case .postImpact: return .orange
        case .followThrough: return .green
        }
    }
}

// MARK: - 2D Pose Extension

extension BodyPoseFrame {
    /// Convert 3D shoulder to approximate 2D for overlay (simplified projection)
    var leadShoulder2D: CGPoint? {
        guard let shoulder = leadShoulder3D else { return nil }
        // Simple orthographic projection for overlay purposes
        return CGPoint(x: CGFloat(shoulder.x * 500 + 960), y: CGFloat(-shoulder.y * 500 + 540))
    }
}
