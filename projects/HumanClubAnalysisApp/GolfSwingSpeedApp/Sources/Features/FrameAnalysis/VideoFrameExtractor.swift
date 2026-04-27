import AVFoundation
import UIKit

/// Extracts individual frames from a recorded video for manual analysis.
/// Uses AVAssetImageGenerator for precise frame-level access.
actor VideoFrameExtractor {

    struct FrameInfo {
        let image: UIImage
        let timestamp: TimeInterval
        let frameIndex: Int
    }

    private let asset: AVAsset
    private let generator: AVAssetImageGenerator

    init(url: URL) {
        self.asset = AVAsset(url: url)
        self.generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.requestedTimeToleranceBefore = .zero
        generator.requestedTimeToleranceAfter = .zero
    }

    /// Get video duration in seconds.
    func duration() async throws -> Double {
        let duration = try await asset.load(.duration)
        return CMTimeGetSeconds(duration)
    }

    /// Get total frame count and actual FPS from the video track.
    func videoInfo() async throws -> (frameCount: Int, fps: Double, duration: Double) {
        let tracks = try await asset.loadTracks(withMediaType: .video)
        guard let track = tracks.first else {
            throw FrameExtractionError.noVideoTrack
        }

        let duration = try await asset.load(.duration)
        let durationSeconds = CMTimeGetSeconds(duration)
        let frameRate = try await track.load(.nominalFrameRate)
        let totalFrames = Int(Double(frameRate) * durationSeconds)

        return (totalFrames, Double(frameRate), durationSeconds)
    }

    /// Extract a single frame at a specific time.
    func frame(at time: TimeInterval) async throws -> FrameInfo {
        let cmTime = CMTime(seconds: time, preferredTimescale: 600)
        let (cgImage, actualTime) = try await generator.image(at: cmTime)
        let image = UIImage(cgImage: cgImage)
        let actualSeconds = CMTimeGetSeconds(actualTime)

        return FrameInfo(
            image: image,
            timestamp: actualSeconds,
            frameIndex: 0
        )
    }

    /// Extract frames at evenly spaced intervals.
    /// Returns up to `count` frames spanning the video duration.
    func extractFrames(count: Int) async throws -> [FrameInfo] {
        let info = try await videoInfo()
        let durationSeconds = info.duration
        guard durationSeconds > 0, count > 0 else { return [] }

        let interval = durationSeconds / Double(count)
        var frames: [FrameInfo] = []

        for i in 0..<count {
            let time = Double(i) * interval
            let cmTime = CMTime(seconds: time, preferredTimescale: 600)

            do {
                let (cgImage, actualTime) = try await generator.image(at: cmTime)
                let image = UIImage(cgImage: cgImage)
                let actualSeconds = CMTimeGetSeconds(actualTime)

                frames.append(FrameInfo(
                    image: image,
                    timestamp: actualSeconds,
                    frameIndex: i
                ))
            } catch {
                // Skip frames that fail to extract
                continue
            }
        }

        return frames
    }

    /// Extract all frames at the video's native frame rate.
    /// WARNING: For 240fps video this can be hundreds of frames — use extractFrames(count:) for UI.
    func extractAllFrames(progressCallback: ((Double) -> Void)? = nil) async throws -> [FrameInfo] {
        let info = try await videoInfo()
        let frameInterval = 1.0 / info.fps
        let totalFrames = info.frameCount
        var frames: [FrameInfo] = []

        for i in 0..<totalFrames {
            let time = Double(i) * frameInterval
            let cmTime = CMTime(seconds: time, preferredTimescale: 600)

            do {
                let (cgImage, actualTime) = try await generator.image(at: cmTime)
                let image = UIImage(cgImage: cgImage)
                let actualSeconds = CMTimeGetSeconds(actualTime)

                frames.append(FrameInfo(
                    image: image,
                    timestamp: actualSeconds,
                    frameIndex: i
                ))
            } catch {
                continue
            }

            progressCallback?(Double(i + 1) / Double(totalFrames))
        }

        return frames
    }
}

enum FrameExtractionError: LocalizedError {
    case noVideoTrack

    var errorDescription: String? {
        switch self {
        case .noVideoTrack: return "No video track found in recording"
        }
    }
}
