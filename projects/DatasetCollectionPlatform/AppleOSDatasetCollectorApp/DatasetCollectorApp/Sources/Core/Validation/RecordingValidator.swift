import AVFoundation
import Vision

struct ValidationResult {
    let passed: Bool
    let checks: [ValidationCheck]

    var failedChecks: [ValidationCheck] {
        checks.filter { !$0.passed }
    }
}

struct ValidationCheck: Identifiable {
    let id = UUID()
    let name: String
    let passed: Bool
    let detail: String
}

actor RecordingValidator {
    private let minFrameCount = 120
    private let minDuration: TimeInterval = 0.5
    private let maxDuration: TimeInterval = 4.0
    private let frameRateJitterThreshold: Double = 0.15
    private let humanDetectionMinRatio: Double = 0.8
    private let laplacianVarianceThreshold: Double = 8.0
    private let minBrightness: Double = 30.0
    private let maxBrightness: Double = 230.0

    func validate(
        videoURL: URL,
        timestamps: [TimeInterval]
    ) async -> ValidationResult {
        var checks: [ValidationCheck] = []

        checks.append(checkFrameCount(timestamps))
        checks.append(checkDuration(timestamps))
        checks.append(checkFrameRateStability(timestamps))

        let videoChecks = await validateVideoContent(videoURL: videoURL)
        checks.append(contentsOf: videoChecks)

        let allPassed = checks.allSatisfy(\.passed)
        return ValidationResult(passed: allPassed, checks: checks)
    }

    private func checkFrameCount(_ timestamps: [TimeInterval]) -> ValidationCheck {
        let count = timestamps.count
        let passed = count >= minFrameCount
        return ValidationCheck(
            name: "帧数",
            passed: passed,
            detail: passed ? "共 \(count) 帧" : "仅 \(count) 帧，需至少 \(minFrameCount) 帧"
        )
    }

    private func checkDuration(_ timestamps: [TimeInterval]) -> ValidationCheck {
        guard let first = timestamps.first, let last = timestamps.last else {
            return ValidationCheck(name: "时长", passed: false, detail: "无帧数据")
        }
        let duration = last - first
        let passed = duration >= minDuration && duration <= maxDuration
        let detail = passed
            ? String(format: "%.2f 秒", duration)
            : String(format: "%.2f 秒（需 %.1f-%.1f 秒）", duration, minDuration, maxDuration)
        return ValidationCheck(name: "时长", passed: passed, detail: detail)
    }

    private func checkFrameRateStability(_ timestamps: [TimeInterval]) -> ValidationCheck {
        guard timestamps.count > 2 else {
            return ValidationCheck(name: "帧率稳定性", passed: false, detail: "帧数不足")
        }

        var intervals: [Double] = []
        for i in 1..<timestamps.count {
            intervals.append(timestamps[i] - timestamps[i - 1])
        }

        let mean = intervals.reduce(0, +) / Double(intervals.count)
        guard mean > 0 else {
            return ValidationCheck(name: "帧率稳定性", passed: false, detail: "帧间隔为零")
        }

        let variance = intervals.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Double(intervals.count)
        let std = variance.squareRoot()
        let cv = std / mean

        let passed = cv < frameRateJitterThreshold
        let fps = 1.0 / mean
        let detail = passed
            ? String(format: "%.1f fps，抖动 %.1f%%", fps, cv * 100)
            : String(format: "帧率抖动过大 %.1f%%（阈值 %.0f%%）", cv * 100, frameRateJitterThreshold * 100)
        return ValidationCheck(name: "帧率稳定性", passed: passed, detail: detail)
    }

    private func validateVideoContent(videoURL: URL) async -> [ValidationCheck] {
        let asset = AVURLAsset(url: videoURL)
        guard let track = try? await asset.loadTracks(withMediaType: .video).first else {
            return [
                ValidationCheck(name: "人体检测", passed: false, detail: "无法读取视频轨道"),
                ValidationCheck(name: "清晰度", passed: false, detail: "无法读取视频轨道"),
                ValidationCheck(name: "亮度", passed: false, detail: "无法读取视频轨道")
            ]
        }

        let duration = try? await asset.load(.duration)
        let totalSeconds = duration.map { CMTimeGetSeconds($0) } ?? 1.0
        let sampleTimes = stride(from: 0.2, to: totalSeconds - 0.1, by: max(totalSeconds / 5.0, 0.2))
            .prefix(5)
            .map { CMTime(seconds: $0, preferredTimescale: 600) }

        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.requestedTimeToleranceBefore = CMTime(seconds: 0.05, preferredTimescale: 600)
        generator.requestedTimeToleranceAfter = CMTime(seconds: 0.05, preferredTimescale: 600)

        var images: [CGImage] = []
        for time in sampleTimes {
            if let (image, _) = try? await generator.image(at: time) {
                images.append(image)
            }
        }

        guard !images.isEmpty else {
            return [
                ValidationCheck(name: "人体检测", passed: false, detail: "无法提取视频帧"),
                ValidationCheck(name: "清晰度", passed: false, detail: "无法提取视频帧"),
                ValidationCheck(name: "亮度", passed: false, detail: "无法提取视频帧")
            ]
        }

        let humanCheck = await checkHumanPresence(images: images)
        let sharpnessCheck = checkSharpness(images: images)
        let brightnessCheck = checkBrightness(images: images)

        return [humanCheck, sharpnessCheck, brightnessCheck]
    }

    private func checkHumanPresence(images: [CGImage]) async -> ValidationCheck {
        var detectedCount = 0

        for image in images {
            let request = VNDetectHumanBodyPoseRequest()
            let handler = VNImageRequestHandler(cgImage: image, options: [:])
            do {
                try handler.perform([request])
                if let results = request.results, !results.isEmpty {
                    detectedCount += 1
                }
            } catch {}
        }

        let ratio = Double(detectedCount) / Double(images.count)
        let passed = ratio >= humanDetectionMinRatio
        let detail = passed
            ? "\(detectedCount)/\(images.count) 帧检测到人体"
            : "仅 \(detectedCount)/\(images.count) 帧检测到人体（需 \(Int(humanDetectionMinRatio * 100))%）"
        return ValidationCheck(name: "人体检测", passed: passed, detail: detail)
    }

    private func checkSharpness(images: [CGImage]) -> ValidationCheck {
        var variances: [Double] = []

        for cgImage in images {
            let width = cgImage.width
            let height = cgImage.height
            guard let data = cgImage.dataProvider?.data,
                  let ptr = CFDataGetBytePtr(data) else { continue }

            let bytesPerPixel = cgImage.bitsPerPixel / 8
            let bytesPerRow = cgImage.bytesPerRow
            let sampleStep = 8
            var sumSq: Double = 0
            var count = 0

            for y in stride(from: sampleStep, to: height - sampleStep, by: sampleStep) {
                for x in stride(from: sampleStep, to: width - sampleStep, by: sampleStep) {
                    let idx = y * bytesPerRow + x * bytesPerPixel
                    let center = Double(ptr[idx]) + Double(ptr[idx+1]) + Double(ptr[idx+2])
                    let left = Double(ptr[idx - bytesPerPixel]) + Double(ptr[idx - bytesPerPixel + 1]) + Double(ptr[idx - bytesPerPixel + 2])
                    let right = Double(ptr[idx + bytesPerPixel]) + Double(ptr[idx + bytesPerPixel + 1]) + Double(ptr[idx + bytesPerPixel + 2])
                    let up = Double(ptr[idx - bytesPerRow]) + Double(ptr[idx - bytesPerRow + 1]) + Double(ptr[idx - bytesPerRow + 2])
                    let down = Double(ptr[idx + bytesPerRow]) + Double(ptr[idx + bytesPerRow + 1]) + Double(ptr[idx + bytesPerRow + 2])
                    let laplacian = abs(4.0 * center - left - right - up - down) / 3.0
                    sumSq += laplacian * laplacian
                    count += 1
                }
            }

            if count > 0 {
                variances.append(sumSq / Double(count))
            }
        }

        guard !variances.isEmpty else {
            return ValidationCheck(name: "清晰度", passed: true, detail: "无法计算（跳过）")
        }

        let avgVariance = variances.reduce(0, +) / Double(variances.count)
        let passed = avgVariance >= laplacianVarianceThreshold
        let detail = passed
            ? String(format: "清晰度 %.0f", avgVariance)
            : String(format: "画面模糊（%.0f < %.0f）", avgVariance, laplacianVarianceThreshold)
        return ValidationCheck(name: "清晰度", passed: passed, detail: detail)
    }

    private func checkBrightness(images: [CGImage]) -> ValidationCheck {
        var brightnesses: [Double] = []

        for cgImage in images {
            let width = cgImage.width
            let height = cgImage.height
            guard let data = cgImage.dataProvider?.data,
                  let ptr = CFDataGetBytePtr(data) else { continue }

            let bytesPerPixel = cgImage.bitsPerPixel / 8
            let totalPixels = width * height
            let sampleStep = max(totalPixels / 1000, 1)
            var sum: Double = 0
            var count = 0

            for i in stride(from: 0, to: totalPixels, by: sampleStep) {
                let offset = i * bytesPerPixel
                let r = Double(ptr[offset])
                let g = Double(ptr[offset + 1])
                let b = Double(ptr[offset + 2])
                sum += (r + g + b) / 3.0
                count += 1
            }

            if count > 0 {
                brightnesses.append(sum / Double(count))
            }
        }

        guard !brightnesses.isEmpty else {
            return ValidationCheck(name: "亮度", passed: true, detail: "无法计算（跳过）")
        }

        let avgBrightness = brightnesses.reduce(0, +) / Double(brightnesses.count)
        let passed = avgBrightness >= minBrightness && avgBrightness <= maxBrightness
        let detail: String
        if avgBrightness < minBrightness {
            detail = String(format: "画面过暗（亮度 %.0f）", avgBrightness)
        } else if avgBrightness > maxBrightness {
            detail = String(format: "画面过曝（亮度 %.0f）", avgBrightness)
        } else {
            detail = String(format: "亮度 %.0f", avgBrightness)
        }
        return ValidationCheck(name: "亮度", passed: passed, detail: detail)
    }
}
