import AVFoundation
import UIKit

@Observable
final class AudioFeedbackManager {
    var mode: AudioFeedbackMode = .beep
    var hapticEnabled = true

    private let synthesizer = AVSpeechSynthesizer()
    private let hapticNotification = UINotificationFeedbackGenerator()
    private let hapticImpact = UIImpactFeedbackGenerator(style: .medium)
    private var tonePlayer: TonePlayer?

    init() {
        configureAudioSession()
        tonePlayer = TonePlayer()
    }

    // MARK: - Audio Session

    private func configureAudioSession() {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(
            .playback,
            mode: .voicePrompt,
            options: [.duckOthers, .interruptSpokenAudioAndMixWithOthers, .allowBluetoothA2DP]
        )
        try? session.setActive(true)
    }

    // MARK: - Feedback Events

    func playerDetected() {
        switch mode {
        case .beep:
            tonePlayer?.play(frequency: 200, duration: 0.1)
            haptic(.impact)
        case .voice:
            speak("Player detected")
        case .off:
            break
        }
    }

    func ready() {
        switch mode {
        case .beep:
            tonePlayer?.play(frequency: 400, duration: 0.08)
            Task {
                try? await Task.sleep(for: .milliseconds(120))
                tonePlayer?.play(frequency: 600, duration: 0.08)
            }
            haptic(.success)
        case .voice:
            speak("Ready")
        case .off:
            break
        }
    }

    func swingCaptured() {
        switch mode {
        case .beep:
            tonePlayer?.play(frequency: 800, duration: 0.15)
            haptic(.success)
        case .voice:
            speak("Swing captured")
        case .off:
            break
        }
    }

    func speedResult(mph: Double, unit: SpeedUnit = .mph) {
        let converted = unit.convert(fromMph: mph)
        let formatted = String(format: "%.0f", converted)

        switch mode {
        case .beep:
            // Triple ascending beep then speak the number
            tonePlayer?.play(frequency: 500, duration: 0.06)
            Task {
                try? await Task.sleep(for: .milliseconds(100))
                tonePlayer?.play(frequency: 700, duration: 0.06)
                try? await Task.sleep(for: .milliseconds(100))
                tonePlayer?.play(frequency: 900, duration: 0.06)
                try? await Task.sleep(for: .milliseconds(200))
                speak("\(formatted) \(unit.displayName)")
            }
            haptic(.success)
        case .voice:
            speak("\(formatted) \(unit.displayName)")
        case .off:
            break
        }
    }

    func errorSwingNotDetected() {
        switch mode {
        case .beep:
            tonePlayer?.play(frequency: 600, duration: 0.1)
            Task {
                try? await Task.sleep(for: .milliseconds(150))
                tonePlayer?.play(frequency: 300, duration: 0.15)
            }
            haptic(.error)
        case .voice:
            speak("Swing not detected, try again")
        case .off:
            break
        }
    }

    func errorTrackingLost() {
        switch mode {
        case .beep:
            for i in 0..<3 {
                Task {
                    try? await Task.sleep(for: .milliseconds(i * 100))
                    tonePlayer?.play(frequency: 500, duration: 0.05)
                }
            }
            haptic(.warning)
        case .voice:
            speak("Tracking lost, please retry")
        case .off:
            break
        }
    }

    func adjustPosition() {
        switch mode {
        case .beep:
            tonePlayer?.play(frequency: 400, duration: 0.2)
            haptic(.warning)
        case .voice:
            speak("Adjust position, stand in frame")
        case .off:
            break
        }
    }

    func calibrationComplete() {
        switch mode {
        case .beep:
            // Rising C-E-G chime
            tonePlayer?.play(frequency: 523, duration: 0.12)
            Task {
                try? await Task.sleep(for: .milliseconds(140))
                tonePlayer?.play(frequency: 659, duration: 0.12)
                try? await Task.sleep(for: .milliseconds(140))
                tonePlayer?.play(frequency: 784, duration: 0.2)
            }
            haptic(.success)
        case .voice:
            speak("Calibration complete")
        case .off:
            break
        }
    }

    // MARK: - Core Audio

    private func speak(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.pitchMultiplier = 1.0
        utterance.volume = 1.0
        synthesizer.speak(utterance)
    }

    private enum HapticType {
        case impact, success, warning, error
    }

    private func haptic(_ type: HapticType) {
        guard hapticEnabled else { return }
        switch type {
        case .impact:
            hapticImpact.impactOccurred()
        case .success:
            hapticNotification.notificationOccurred(.success)
        case .warning:
            hapticNotification.notificationOccurred(.warning)
        case .error:
            hapticNotification.notificationOccurred(.error)
        }
    }
}

// MARK: - Tone Generator

/// Generates sine wave tones using AVAudioEngine for low-latency beep feedback.
final class TonePlayer {
    private let engine = AVAudioEngine()
    private let playerNode = AVAudioPlayerNode()
    private let sampleRate: Double = 44100

    init() {
        engine.attach(playerNode)
        let format = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1)!
        engine.connect(playerNode, to: engine.mainMixerNode, format: format)

        do {
            try engine.start()
        } catch {
            // Audio engine failed to start — tones won't play but app continues
        }
    }

    func play(frequency: Double, duration: Double, volume: Float = 0.5) {
        let frameCount = AVAudioFrameCount(sampleRate * duration)
        guard let format = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else {
            return
        }

        buffer.frameLength = frameCount

        guard let channelData = buffer.floatChannelData?[0] else { return }

        // Generate sine wave with fade-in/fade-out envelope to avoid clicks
        let fadeFrames = min(Int(sampleRate * 0.005), Int(frameCount) / 4) // 5ms fade
        for i in 0..<Int(frameCount) {
            let sample = sin(2.0 * .pi * frequency * Double(i) / sampleRate)

            // Apply envelope
            var envelope: Double = 1.0
            if i < fadeFrames {
                envelope = Double(i) / Double(fadeFrames) // Fade in
            } else if i > Int(frameCount) - fadeFrames {
                envelope = Double(Int(frameCount) - i) / Double(fadeFrames) // Fade out
            }

            channelData[i] = Float(sample * envelope) * volume
        }

        playerNode.scheduleBuffer(buffer, completionHandler: nil)
        if !playerNode.isPlaying {
            playerNode.play()
        }
    }
}
