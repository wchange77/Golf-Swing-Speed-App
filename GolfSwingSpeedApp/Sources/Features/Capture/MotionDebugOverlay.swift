import SwiftUI

/// Debug overlay that visualises the motion heatmap from MotionDetector.
/// Each cell in the grid is coloured by motion intensity.
/// Also shows the motion centroid and overall motion magnitude.
struct MotionDebugOverlay: View {
    let heatmap: [[Double]]
    let motionMagnitude: Double
    let centroid: CGPoint?
    let threshold: Double

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Heatmap grid
                heatmapGrid(in: geometry.size)

                // Motion centroid
                if let centroid {
                    Circle()
                        .stroke(.yellow, lineWidth: 2)
                        .frame(width: 20, height: 20)
                        .position(
                            x: centroid.x * geometry.size.width,
                            y: centroid.y * geometry.size.height
                        )

                    Circle()
                        .fill(.yellow)
                        .frame(width: 6, height: 6)
                        .position(
                            x: centroid.x * geometry.size.width,
                            y: centroid.y * geometry.size.height
                        )
                }

                // Motion magnitude bar
                VStack {
                    HStack {
                        Spacer()
                        motionBar
                    }
                    Spacer()
                }
                .padding(8)
            }
        }
        .allowsHitTesting(false) // Pass touches through
    }

    // MARK: - Heatmap Grid

    private func heatmapGrid(in size: CGSize) -> some View {
        let gridSize = heatmap.count
        guard gridSize > 0 else { return AnyView(EmptyView()) }

        let cellWidth = size.width / CGFloat(gridSize)
        let cellHeight = size.height / CGFloat(gridSize)

        // Find max value for normalisation
        let maxVal = heatmap.flatMap { $0 }.max() ?? 1.0
        let normaliser = maxVal > 0 ? maxVal : 1.0

        return AnyView(
            Canvas { context, canvasSize in
                for (y, row) in heatmap.enumerated() {
                    for (x, value) in row.enumerated() {
                        let normalised = value / normaliser
                        let rect = CGRect(
                            x: CGFloat(x) * cellWidth,
                            y: CGFloat(y) * cellHeight,
                            width: cellWidth,
                            height: cellHeight
                        )

                        // Colour: green (low) → yellow → red (high)
                        let color = motionColor(normalised)
                        context.fill(
                            Path(rect),
                            with: .color(color.opacity(normalised * 0.6))
                        )
                    }
                }
            }
        )
    }

    private func motionColor(_ normalised: Double) -> Color {
        if normalised < 0.3 { return .green }
        if normalised < 0.6 { return .yellow }
        return .red
    }

    // MARK: - Motion Bar

    private var motionBar: some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text("Motion")
                .font(.caption2)
                .foregroundStyle(.white)

            // Bar
            ZStack(alignment: .bottom) {
                RoundedRectangle(cornerRadius: 3)
                    .fill(.white.opacity(0.2))
                    .frame(width: 12, height: 60)

                RoundedRectangle(cornerRadius: 3)
                    .fill(motionMagnitude > threshold ? .red : .green)
                    .frame(width: 12, height: min(60, CGFloat(motionMagnitude / 50.0) * 60))
            }

            // Threshold line
            Text(String(format: "%.0f", motionMagnitude))
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(.white)
        }
        .padding(6)
        .background(.black.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
    }
}

#Preview {
    ZStack {
        Color.black
        MotionDebugOverlay(
            heatmap: [
                [0, 2, 5, 1, 0, 0, 0, 0],
                [1, 8, 15, 3, 0, 0, 0, 0],
                [0, 5, 20, 12, 2, 0, 0, 0],
                [0, 1, 10, 25, 8, 1, 0, 0],
                [0, 0, 3, 15, 20, 5, 0, 0],
                [0, 0, 0, 5, 12, 8, 1, 0],
                [0, 0, 0, 1, 3, 2, 0, 0],
                [0, 0, 0, 0, 1, 0, 0, 0],
            ],
            motionMagnitude: 18.5,
            centroid: CGPoint(x: 0.4, y: 0.45),
            threshold: 15.0
        )
    }
}
