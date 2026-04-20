import SwiftUI

/// Full-screen overlay displayed during post-capture swing analysis.
/// Shows a circular progress indicator, current analysis phase, and cancel button.
struct ProcessingOverlayView: View {

    let phase: String
    let progress: Double
    var onCancel: (() -> Void)?

    @State private var pulseScale: CGFloat = 1.0

    private var progressPercent: Int {
        Int((progress * 100).clamped(to: 0...100))
    }

    var body: some View {
        ZStack {
            // Dark background
            Color.black.opacity(0.85)
                .ignoresSafeArea()

            VStack(spacing: 32) {
                Spacer()

                // Pulsing golf ball
                Circle()
                    .fill(Color.white)
                    .frame(width: 24, height: 24)
                    .scaleEffect(pulseScale)
                    .opacity(2.0 - pulseScale) // fades as it grows
                    .onAppear {
                        withAnimation(
                            .easeInOut(duration: 1.0)
                            .repeatForever(autoreverses: true)
                        ) {
                            pulseScale = 1.4
                        }
                    }

                // Circular progress ring
                ZStack {
                    // Track
                    Circle()
                        .stroke(Color.white.opacity(0.15), lineWidth: 8)

                    // Progress arc
                    Circle()
                        .trim(from: 0, to: progress)
                        .stroke(
                            Color.blue,
                            style: StrokeStyle(lineWidth: 8, lineCap: .round)
                        )
                        .rotationEffect(.degrees(-90))
                        .animation(.easeInOut(duration: 0.4), value: progress)

                    // Percentage text
                    Text("\(progressPercent)%")
                        .font(.system(size: 36, weight: .bold, design: .rounded))
                        .foregroundStyle(.white)
                        .contentTransition(.numericText())
                        .animation(.easeInOut(duration: 0.3), value: progressPercent)
                }
                .frame(width: 160, height: 160)

                // Phase label
                Text(phase)
                    .font(.title3.weight(.medium))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .contentTransition(.opacity)
                    .animation(.easeInOut(duration: 0.3), value: phase)
                    .padding(.horizontal, 24)

                Spacer()

                // Cancel button
                if let onCancel {
                    Button(action: onCancel) {
                        Text("Cancel")
                            .font(.body.weight(.medium))
                            .foregroundStyle(.white.opacity(0.8))
                            .padding(.horizontal, 32)
                            .padding(.vertical, 12)
                            .background(
                                Capsule()
                                    .stroke(Color.white.opacity(0.3), lineWidth: 1)
                            )
                    }
                    .padding(.bottom, 48)
                }
            }
        }
    }
}

// MARK: - Helpers

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}

// MARK: - Preview

#Preview("Loading Video") {
    ProcessingOverlayView(
        phase: "Loading video",
        progress: 0.05,
        onCancel: {}
    )
}

#Preview("Tracking") {
    ProcessingOverlayView(
        phase: "Tracking club head",
        progress: 0.55,
        onCancel: {}
    )
}

#Preview("Nearly Done") {
    ProcessingOverlayView(
        phase: "Calculating speed",
        progress: 0.92,
        onCancel: {}
    )
}
