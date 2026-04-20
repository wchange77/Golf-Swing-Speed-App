import SwiftUI

struct SettingsView: View {
    @AppStorage("speedUnit") private var speedUnit: String = SpeedUnit.mph.rawValue
    @AppStorage("audioFeedbackMode") private var audioMode: String = AudioFeedbackMode.beep.rawValue
    @AppStorage("defaultClubType") private var defaultClub: String = ClubType.driver.rawValue
    @AppStorage("autoCapture") private var autoCapture = true
    @AppStorage("showConfidence") private var showConfidence = true
    @AppStorage("saveVideoClips") private var saveVideoClips = "ask"
    @AppStorage("hapticFeedback") private var hapticFeedback = true

    var body: some View {
        NavigationStack {
            Form {
                // Measurement
                Section("Measurement") {
                    Picker("Speed Units", selection: $speedUnit) {
                        ForEach(SpeedUnit.allCases, id: \.rawValue) { unit in
                            Text(unit.displayName).tag(unit.rawValue)
                        }
                    }

                    Toggle("Show Confidence Score", isOn: $showConfidence)
                }

                // Audio
                Section("Audio Feedback") {
                    Picker("Feedback Mode", selection: $audioMode) {
                        ForEach(AudioFeedbackMode.allCases, id: \.rawValue) { mode in
                            Text(mode.displayName).tag(mode.rawValue)
                        }
                    }

                    Toggle("Haptic Feedback", isOn: $hapticFeedback)
                }

                // Capture
                Section("Capture") {
                    Toggle("Auto-Capture", isOn: $autoCapture)

                    Picker("Default Club", selection: $defaultClub) {
                        ForEach(ClubType.allCases) { club in
                            Text(club.displayName).tag(club.rawValue)
                        }
                    }

                    Picker("Save Video Clips", selection: $saveVideoClips) {
                        Text("Always").tag("always")
                        Text("Ask Each Time").tag("ask")
                        Text("Never").tag("never")
                    }
                }

                // About
                Section("About") {
                    LabeledContent("Version", value: AppConstants.appVersion)
                    LabeledContent("Camera FPS", value: "240fps @ 1080p")

                    NavigationLink("Calibration") {
                        Text("Recalibrate from here — Phase 2")
                    }
                }

                // Data
                Section("Data") {
                    Button("Export Swing Data (CSV)", role: .none) {
                        // Phase 4 implementation
                    }
                    .disabled(true)

                    Button("Clear All Data", role: .destructive) {
                        // Confirmation dialog in Phase 4
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }
}

#Preview {
    SettingsView()
}
