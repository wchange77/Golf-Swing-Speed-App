import SwiftUI
import RealityKit
import ARKit

/// LiDAR-based calibration view that uses ARKit plane detection and 3D body pose
/// to automatically measure club length, lie angle, and arm length.
///
/// Flow:
/// 1. AR camera feed with plane detection overlays
/// 2. Ground plane detected (green highlight)
/// 3. User stands at address with club
/// 4. Body pose analysed automatically
/// 5. Results displayed with validation
/// 6. User confirms to lock calibration
struct LiDARCalibrationView: View {
    @Bindable var lidarManager: LiDARCalibrationManager
    var onFallbackToManual: (() -> Void)?
    var onCalibrationComplete: ((CalibrationSnapshot) -> Void)?

    @State private var arView: ARView?
    @State private var groundCheckTimer: Timer?
    @State private var showConfirmation = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                if LiDARCalibrationManager.isLiDARAvailable {
                    lidarContent
                } else {
                    noLiDARContent
                }
            }
            .ignoresSafeArea()
            .navigationTitle("LiDAR Calibration")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.hidden, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        stopAndDismiss()
                    }
                    .tint(.white)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if case .failed = lidarManager.state {
                        // No reset shown in failed state
                    } else if case .inactive = lidarManager.state {
                        // No reset shown in inactive state
                    } else {
                        Button("Reset") {
                            resetCalibration()
                        }
                        .tint(.white)
                    }
                }
            }
            .onDisappear {
                groundCheckTimer?.invalidate()
                groundCheckTimer = nil
            }
        }
    }

    // MARK: - LiDAR Content

    @ViewBuilder
    private var lidarContent: some View {
        // AR camera feed as background
        if let arView {
            ARViewContainer(arView: arView)
        } else {
            Color.black
        }

        // Status and controls overlay
        VStack {
            statusBanner
            Spacer()
            bottomControls
        }
    }

    // MARK: - No LiDAR Content

    private var noLiDARContent: some View {
        VStack(spacing: 24) {
            Spacer()

            VStack(spacing: 16) {
                Image(systemName: "sensor.tag.radiowaves.forward.fill")
                    .font(.system(size: 50))
                    .foregroundStyle(.orange)

                Text("LiDAR Not Available")
                    .font(.title2)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)

                Text("This device does not have a LiDAR scanner. LiDAR calibration requires iPhone 12 Pro or later.")
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.8))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
            }
            .padding(24)
            .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 20))
            .padding(.horizontal)

            Button {
                onFallbackToManual?()
                dismiss()
            } label: {
                Text("Use Manual Calibration Instead")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.blue, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 40)

            Spacer()
        }
        .background(Color.black)
    }

    // MARK: - Status Banner

    @ViewBuilder
    private var statusBanner: some View {
        VStack(spacing: 8) {
            switch lidarManager.state {
            case .inactive:
                statusCard(
                    icon: "arrow.triangle.2.circlepath",
                    iconColor: .gray,
                    title: "Ready to Start",
                    detail: "Tap below to begin LiDAR scanning"
                )
            case .scanning:
                statusCard(
                    icon: "dot.radiowaves.left.and.right",
                    iconColor: .blue,
                    title: "Scanning...",
                    detail: "Point the camera at the ground near your hitting area",
                    showProgress: true
                )
            case .groundDetected:
                statusCard(
                    icon: "checkmark.circle.fill",
                    iconColor: .green,
                    title: "Ground Plane Detected",
                    detail: "Stand at address with your club"
                )
            case .waitingForAddress:
                statusCard(
                    icon: "figure.golf",
                    iconColor: .cyan,
                    title: "Analysing Pose...",
                    detail: "Hold your address position steady",
                    showProgress: true
                )
            case .addressAnalysed:
                statusCard(
                    icon: "checkmark.circle.fill",
                    iconColor: .green,
                    title: "Analysis Complete",
                    detail: "Review your measurements below"
                )
            case .complete:
                statusCard(
                    icon: "checkmark.seal.fill",
                    iconColor: .green,
                    title: "Calibration Locked",
                    detail: "Ready for swing capture"
                )
            case .failed(let message):
                statusCard(
                    icon: "exclamationmark.triangle.fill",
                    iconColor: .red,
                    title: "Calibration Failed",
                    detail: message
                )
            }
        }
        .padding(.top, 60)
        .padding(.horizontal)
    }

    private func statusCard(
        icon: String,
        iconColor: Color,
        title: String,
        detail: String,
        showProgress: Bool = false
    ) -> some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                if showProgress {
                    ProgressView()
                        .tint(.white)
                } else {
                    Image(systemName: icon)
                        .foregroundStyle(iconColor)
                }

                Text(title)
                    .font(.headline)
                    .foregroundStyle(.white)
            }

            Text(detail)
                .font(.caption)
                .foregroundStyle(.white.opacity(0.7))
                .multilineTextAlignment(.center)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 12))
    }

    // MARK: - Bottom Controls

    @ViewBuilder
    private var bottomControls: some View {
        VStack(spacing: 16) {
            // Show measurement results when analysis is done
            if case .addressAnalysed = lidarManager.state {
                measurementResults
            }
            if case .complete = lidarManager.state {
                measurementResults
            }

            // Action buttons
            actionButtons
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 40)
    }

    // MARK: - Measurement Results

    private var measurementResults: some View {
        VStack(spacing: 12) {
            Text("Calibration Measurements")
                .font(.subheadline)
                .fontWeight(.semibold)
                .foregroundStyle(.white)

            VStack(spacing: 8) {
                if let clubLength = lidarManager.clubLengthMetres {
                    measurementRow(
                        label: "Club Length",
                        value: String(format: "%.2f m (%.1f in)", clubLength, clubLength / 0.0254),
                        isInRange: Double(clubLength) >= AppConstants.Calibration.minClubLengthMetres
                            && Double(clubLength) <= AppConstants.Calibration.maxClubLengthMetres
                    )
                }

                if let lieAngle = lidarManager.lieAngleDegrees {
                    measurementRow(
                        label: "Lie Angle",
                        value: String(format: "%.1f\u{00B0}", lieAngle),
                        isInRange: Double(lieAngle) >= AppConstants.Calibration.minLieAngleDegrees
                            && Double(lieAngle) <= AppConstants.Calibration.maxLieAngleDegrees
                    )
                }

                if let armLength = lidarManager.armLengthMetres {
                    // Typical arm length range: 0.50 - 0.85 m
                    measurementRow(
                        label: "Arm Length",
                        value: String(format: "%.2f m (%.1f in)", armLength, armLength / 0.0254),
                        isInRange: armLength >= 0.50 && armLength <= 0.85
                    )
                }

                if let distance = lidarManager.cameraToSubjectDistance {
                    measurementRow(
                        label: "Camera Distance",
                        value: String(format: "%.1f m", distance),
                        isInRange: Double(distance) <= AppConstants.Calibration.maxCameraDistanceMetres
                    )
                }
            }
        }
        .padding(16)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private func measurementRow(label: String, value: String, isInRange: Bool) -> some View {
        HStack {
            Text(label)
                .font(.subheadline)
                .foregroundStyle(.white.opacity(0.8))

            Spacer()

            HStack(spacing: 6) {
                Text(value)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundStyle(.white)

                Image(systemName: isInRange ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(isInRange ? .green : .yellow)
            }
        }
    }

    // MARK: - Action Buttons

    @ViewBuilder
    private var actionButtons: some View {
        switch lidarManager.state {
        case .inactive:
            Button {
                startScanning()
            } label: {
                Text("Start LiDAR Scan")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.blue, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }

            fallbackButton

        case .scanning:
            fallbackButton

        case .groundDetected:
            Button {
                beginAddressAnalysis()
            } label: {
                Text("Analyse Address Position")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.cyan, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }

            fallbackButton

        case .waitingForAddress:
            // No action while analysing
            EmptyView()

        case .addressAnalysed:
            Button {
                confirmCalibration()
            } label: {
                Label("Confirm & Lock", systemImage: "lock.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.green, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }

            fallbackButton

        case .complete:
            Button {
                dismiss()
            } label: {
                Text("Done")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.green, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }

        case .failed:
            Button {
                resetCalibration()
                startScanning()
            } label: {
                Text("Retry")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.blue, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }

            fallbackButton
        }
    }

    private var fallbackButton: some View {
        Button {
            stopScanning()
            onFallbackToManual?()
            dismiss()
        } label: {
            Text("Use Manual Calibration Instead")
                .font(.subheadline)
                .foregroundStyle(.white.opacity(0.7))
                .padding(.vertical, 8)
        }
    }

    // MARK: - Actions

    private func startScanning() {
        arView = lidarManager.startScanning()
        startGroundCheckTimer()
    }

    private func stopScanning() {
        groundCheckTimer?.invalidate()
        groundCheckTimer = nil
        lidarManager.stopScanning()
    }

    private func stopAndDismiss() {
        stopScanning()
        dismiss()
    }

    /// Poll for ground plane detection every 0.5 seconds.
    private func startGroundCheckTimer() {
        groundCheckTimer?.invalidate()
        groundCheckTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
            Task { @MainActor in
                if case .scanning = lidarManager.state {
                    lidarManager.checkForGroundPlane()
                } else {
                    groundCheckTimer?.invalidate()
                    groundCheckTimer = nil
                }
            }
        }
    }

    private func beginAddressAnalysis() {
        Task {
            _ = await lidarManager.analyseAddressPosition()
            // analyseAddressPosition updates state internally;
            // the view reacts to the published state changes.
        }
    }

    /// Finalise calibration using the current manager measurements.
    /// In a full implementation, club head position and ball position
    /// would come from CV detection. Here we use placeholder values
    /// derived from the body pose analysis.
    private func confirmCalibration() {
        guard let armLength = lidarManager.armLengthMetres,
              let cameraDistance = lidarManager.cameraToSubjectDistance else {
            return
        }

        // Compute pixels-per-metre from camera intrinsics at the measured distance
        let ppm = lidarManager.pixelsPerMetreFromIntrinsics(atDistance: cameraDistance)
            ?? Double(AppConstants.Camera.captureWidth) / Double(AppConstants.Calibration.maxCameraDistanceMetres)

        // Placeholder 3D positions — in full implementation these come from
        // club head detection and ball detection during address analysis
        let wrist = SIMD3<Float>(0, Float(armLength), 0)
        let clubHead = SIMD3<Float>(0, 0, 0)
        let shoulder = SIMD3<Float>(0, Float(armLength) + 0.3, 0)
        let spine = SIMD3<Float>(0, Float(armLength) + 0.5, 0)

        let snapshot = lidarManager.finaliseCalibration(
            clubHeadPosition3D: clubHead,
            leadWrist3D: wrist,
            leadShoulder3D: shoulder,
            spine3D: spine,
            ballPosition3D: nil,
            pixelsPerMetre: ppm
        )

        onCalibrationComplete?(snapshot)
    }

    private func resetCalibration() {
        groundCheckTimer?.invalidate()
        groundCheckTimer = nil
        arView = nil
        lidarManager.reset()
    }
}

// MARK: - ARViewContainer

/// UIViewRepresentable wrapper for RealityKit's ARView.
/// Displays the live AR camera feed with plane detection overlays.
struct ARViewContainer: UIViewRepresentable {
    let arView: ARView

    func makeUIView(context: Context) -> ARView {
        arView.environment.background = .cameraFeed()
        return arView
    }

    func updateUIView(_ uiView: ARView, context: Context) {
        // ARView session is managed by LiDARCalibrationManager
    }
}

// MARK: - Preview

#Preview {
    LiDARCalibrationView(lidarManager: LiDARCalibrationManager())
}
