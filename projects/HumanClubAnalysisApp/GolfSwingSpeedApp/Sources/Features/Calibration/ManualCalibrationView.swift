import SwiftUI
import AVFoundation

struct ManualCalibrationView: View {
    @Bindable var calibrationManager: CalibrationManager
    var cameraManager: CameraManager?
    var audioFeedback: AudioFeedbackManager?
    @State private var phase: CalibrationPhase = .instructions
    @State private var countdownSeconds: Int = 10
    @State private var capturedImage: UIImage?
    @State private var clubLengthInput = ""
    @State private var clubLengthUnit: DistanceInputUnit = .centimetres
    @State private var countdownTimer: Timer?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                // Background: camera or captured photo
                backgroundContent

                // Calibration markers — full screen coordinate space
                if phase.isMarkingPhase {
                    calibrationMarkers
                }

                // Tap capture layer — full screen, behind UI controls
                if phase == .markClubHead || phase == .markGrip || phase == .markImpact {
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture { location in
                            handleTap(at: location)
                        }
                }

                // Phase-specific UI overlay
                phaseOverlay
                    .allowsHitTesting(phase != .markClubHead && phase != .markGrip && phase != .markImpact)
            }
            .ignoresSafeArea()
            .navigationTitle("Calibrate")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.hidden, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        cancelCalibration()
                        dismiss()
                    }
                    .tint(.white)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if phase != .instructions && phase != .countdown {
                        Button("Reset") {
                            resetCalibration()
                        }
                        .tint(.white)
                    }
                }
            }
            .onDisappear {
                countdownTimer?.invalidate()
            }
        }
    }

    // MARK: - Background

    @ViewBuilder
    private var backgroundContent: some View {
        if let capturedImage {
            GeometryReader { geometry in
                Image(uiImage: capturedImage)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .frame(width: geometry.size.width, height: geometry.size.height)
                    .clipped()
                    .position(x: geometry.size.width / 2, y: geometry.size.height / 2)
            }
        } else {
            Color.black
        }
    }

    // MARK: - Phase Overlay

    @ViewBuilder
    private var phaseOverlay: some View {
        switch phase {
        case .instructions:
            instructionsOverlay
        case .countdown:
            countdownOverlay
        case .markClubHead:
            markingBanner(instruction: "Tap the club head", icon: "1.circle", detail: "Tap the very bottom of the club face")
        case .markGrip:
            markingBanner(instruction: "Tap the top of the grip", icon: "2.circle", detail: "Tap where your top hand holds the club")
        case .enterLength:
            enterLengthOverlay
        case .markImpact:
            markingBanner(instruction: "Tap the impact zone", icon: "target", detail: "Tap where the ball is (or would be)")
        case .complete:
            completeOverlay
        }
    }

    // MARK: - Instructions Phase

    private var instructionsOverlay: some View {
        VStack(spacing: 24) {
            Spacer()

            VStack(spacing: 16) {
                Image(systemName: "timer")
                    .font(.system(size: 50))
                    .foregroundStyle(.white)

                Text("Solo Calibration")
                    .font(.title2)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)

                VStack(alignment: .leading, spacing: 8) {
                    instructionRow(number: "1", text: "Place your phone on a tripod facing your hitting position")
                    instructionRow(number: "2", text: "Tap Start — you'll have 10 seconds")
                    instructionRow(number: "3", text: "Stand at address with your club")
                    instructionRow(number: "4", text: "A photo will be taken automatically")
                    instructionRow(number: "5", text: "Walk back and mark the club on the photo")
                }
                .padding(.horizontal)
            }
            .padding(24)
            .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 20))
            .padding(.horizontal)

            Button {
                startCountdown()
            } label: {
                Text("Start (10 seconds)")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.blue, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 40)
        }
    }

    private func instructionRow(number: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(number)
                .font(.caption)
                .fontWeight(.bold)
                .foregroundStyle(.blue)
                .frame(width: 20, height: 20)
                .background(.blue.opacity(0.2), in: Circle())
            Text(text)
                .font(.subheadline)
                .foregroundStyle(.white.opacity(0.9))
        }
    }

    // MARK: - Countdown Phase

    private var countdownOverlay: some View {
        VStack(spacing: 16) {
            Spacer()

            Text("\(countdownSeconds)")
                .font(.system(size: 120, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .shadow(color: .black.opacity(0.5), radius: 10)

            Text("Get into position...")
                .font(.title3)
                .foregroundStyle(.white.opacity(0.8))

            Spacer()
        }
    }

    // MARK: - Marking Banner (instruction only, no tap handling)

    private func markingBanner(instruction: String, icon: String, detail: String) -> some View {
        VStack {
            VStack(spacing: 4) {
                Label(instruction, systemImage: icon)
                    .font(.headline)
                    .foregroundStyle(.white)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.7))
            }
            .padding(12)
            .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 12))
            .padding(.top, 60)

            Spacer()
        }
        .allowsHitTesting(false)
    }

    // MARK: - Enter Length Overlay

    private var enterLengthOverlay: some View {
        VStack {
            VStack(spacing: 16) {
                Text("Enter your club length")
                    .font(.headline)

                HStack {
                    TextField("Length", text: $clubLengthInput)
                        .keyboardType(.decimalPad)
                        .textFieldStyle(.roundedBorder)
                        .toolbar {
                            ToolbarItemGroup(placement: .keyboard) {
                                Spacer()
                                Button("Done") {
                                    UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
                                }
                            }
                        }

                    Picker("Unit", selection: $clubLengthUnit) {
                        Text("cm").tag(DistanceInputUnit.centimetres)
                        Text("in").tag(DistanceInputUnit.feet)
                        Text("m").tag(DistanceInputUnit.metres)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 140)
                }

                Text("Standard driver: ~114 cm / 45 in")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Button("Confirm Length") {
                    confirmLength()
                }
                .buttonStyle(.borderedProminent)
                .disabled(Double(clubLengthInput) == nil)
            }
            .padding(20)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
            .padding(.horizontal)
            .padding(.top, 80)

            Spacer()
        }
    }

    private func confirmLength() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        if let value = Double(clubLengthInput), value > 0 {
            let metres = clubLengthUnit.toMetres(value)
            calibrationManager.setKnownDistance(metres)
            phase = .markImpact
        }
    }

    // MARK: - Complete Overlay

    private var completeOverlay: some View {
        VStack {
            Label("Calibration complete", systemImage: "checkmark.circle.fill")
                .font(.headline)
                .foregroundStyle(.green)
                .padding(12)
                .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 12))
                .padding(.top, 60)

            Spacer()

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
            .padding(.horizontal, 24)
            .padding(.bottom, 40)
        }
    }

    // MARK: - Calibration Markers

    private var calibrationMarkers: some View {
        ZStack {
            if let p1 = calibrationManager.firstPoint {
                CalibrationMarker(position: p1, label: "Club", color: .yellow)
            }
            if let p2 = calibrationManager.secondPoint {
                CalibrationMarker(position: p2, label: "Grip", color: .cyan)
            }
            if let impact = calibrationManager.impactZone {
                CalibrationMarker(position: impact, label: "Ball", color: .red)
            }

            if let p1 = calibrationManager.firstPoint, let p2 = calibrationManager.secondPoint {
                Path { path in
                    path.move(to: p1)
                    path.addLine(to: p2)
                }
                .stroke(.white.opacity(0.6), style: StrokeStyle(lineWidth: 2, dash: [8, 4]))
            }
        }
        .allowsHitTesting(false)
    }

    // MARK: - Actions

    private func startCountdown() {
        phase = .countdown
        countdownSeconds = 10

        countdownTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { timer in
            if countdownSeconds > 1 {
                countdownSeconds -= 1
                if countdownSeconds <= 3 {
                    audioFeedback?.ready()
                } else {
                    let feedback = UIImpactFeedbackGenerator(style: .light)
                    feedback.impactOccurred()
                }
            } else {
                timer.invalidate()
                countdownTimer = nil
                capturePhoto()
            }
        }
    }

    private func capturePhoto() {
        audioFeedback?.swingCaptured()

        Task {
            if let cameraManager {
                do {
                    let image = try await cameraManager.takePhoto()
                    await MainActor.run {
                        capturedImage = image
                        phase = .markClubHead
                    }
                } catch {
                    await MainActor.run {
                        phase = .markClubHead
                    }
                }
            } else {
                phase = .markClubHead
            }
        }
    }

    private func handleTap(at location: CGPoint) {
        switch phase {
        case .markClubHead:
            calibrationManager.setFirstPoint(location)
            phase = .markGrip
        case .markGrip:
            calibrationManager.setSecondPoint(location)
            phase = .enterLength
        case .markImpact:
            calibrationManager.setImpactZone(location)
            audioFeedback?.calibrationComplete()
            phase = .complete
        default:
            break
        }
    }

    private func resetCalibration() {
        calibrationManager.reset()
        capturedImage = nil
        clubLengthInput = ""
        phase = .instructions
    }

    private func cancelCalibration() {
        countdownTimer?.invalidate()
        calibrationManager.reset()
    }
}

// MARK: - Calibration Phase

enum CalibrationPhase {
    case instructions, countdown, markClubHead, markGrip, enterLength, markImpact, complete

    var isMarkingPhase: Bool {
        switch self {
        case .markClubHead, .markGrip, .enterLength, .markImpact, .complete: return true
        default: return false
        }
    }
}

// MARK: - Calibration Marker

struct CalibrationMarker: View {
    let position: CGPoint
    let label: String
    let color: Color

    var body: some View {
        ZStack {
            Circle()
                .fill(color.opacity(0.3))
                .frame(width: 32, height: 32)
            Circle()
                .stroke(color, lineWidth: 2)
                .frame(width: 32, height: 32)
            Text(label)
                .font(.system(size: 8, weight: .bold))
                .foregroundStyle(color)
        }
        .position(position)
    }
}

// MARK: - Distance Unit

enum DistanceInputUnit: String, CaseIterable {
    case metres, feet, centimetres

    func toMetres(_ value: Double) -> Double {
        switch self {
        case .metres: return value
        case .feet: return value * 0.3048
        case .centimetres: return value / 100.0
        }
    }
}

#Preview {
    ManualCalibrationView(calibrationManager: CalibrationManager())
}
