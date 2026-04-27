import AVFoundation
import Vision

struct ValidationResult {
    let passed: Bool
    let checks: [ValidationCheck]
    let metrics: RecordingQualityMetrics?

    init(passed: Bool, checks: [ValidationCheck], metrics: RecordingQualityMetrics? = nil) {
        self.passed = passed
        self.checks = checks
        self.metrics = metrics
    }

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
    private let minFrameCount = CollectorQualityThresholds.baseline.minFrameCount
    private let minDuration = CollectorQualityThresholds.baseline.minDurationSeconds
    private let maxDuration = CollectorQualityThresholds.baseline.maxDurationSeconds
    private let frameRateJitterThreshold = CollectorQualityThresholds.baseline.maxFrameRateJitterPercent / 100.0
    private let humanDetectionMinRatio = CollectorQualityThresholds.baseline.minHumanDetectionRatio
    private let laplacianVarianceThreshold = CollectorQualityThresholds.baseline.minSharpness
    private let minBrightness = CollectorQualityThresholds.baseline.minBrightness
    private let maxBrightness = CollectorQualityThresholds.baseline.maxBrightness
    private let minLongSidePixels = CollectorQualityThresholds.baseline.minLongSidePixels
    private let minShortSidePixels = CollectorQualityThresholds.baseline.minShortSidePixels
    private let minEstimatedFPS = CollectorQualityThresholds.baseline.minEstimatedFPS
    private let minBodyCoverageRatio = CollectorQualityThresholds.baseline.minBodyCoverageRatio
    private let maxBodyCoverageRatio = CollectorQualityThresholds.baseline.maxBodyCoverageRatio
    private let maxBodyCenterStability = CollectorQualityThresholds.baseline.maxBodyCenterStability
    private let maxBodyBoundingBoxStability = CollectorQualityThresholds.baseline.maxBodyBoundingBoxStability
    private let maxCroppedBodyRatio = CollectorQualityThresholds.baseline.maxCroppedBodyRatio
    private let maxUnderexposedPixelRatio = CollectorQualityThresholds.baseline.maxUnderexposedPixelRatio
    private let maxOverexposedPixelRatio = CollectorQualityThresholds.baseline.maxOverexposedPixelRatio
    private let minSwingWindowDurationSeconds = CollectorQualityThresholds.baseline.minSwingWindowDurationSeconds

    func validate(
        videoURL: URL,
        timestamps: [TimeInterval]
    ) async -> ValidationResult {
        var checks: [ValidationCheck] = []
        let frameStats = RecordingQualityHeuristics.makeFrameStats(timestamps)
        let hasSwingWindow = RecordingQualityHeuristics.hasSwingWindowCandidate(
            frameCount: timestamps.count,
            durationSeconds: frameStats.duration,
            minFrameCount: minFrameCount,
            minDurationSeconds: minSwingWindowDurationSeconds
        )
        var metrics = RecordingQualityMetrics(
            frameCount: timestamps.count,
            durationSeconds: frameStats.duration,
            estimatedFPS: frameStats.estimatedFPS,
            frameRateJitterPercent: frameStats.jitterRatio * 100,
            sampledFrameCount: 0,
            humanDetectionRatio: nil,
            averageBodyCoverageRatio: nil,
            bodyCenterStability: nil,
            bodyBoundingBoxStability: nil,
            croppedBodyRatio: nil,
            averageSharpness: nil,
            averageBrightness: nil,
            underexposedPixelRatio: nil,
            overexposedPixelRatio: nil,
            videoWidth: nil,
            videoHeight: nil,
            orientation: "unknown",
            swingWindowCandidateAvailable: hasSwingWindow,
            generatedAt: DatasetCollectorDateFormatter.nowISO8601()
        )

        checks.append(checkFrameCount(timestamps.count))
        checks.append(checkDuration(frameStats.duration, hasFrames: !timestamps.isEmpty))
        checks.append(checkActualFPS(frameStats))
        checks.append(checkFrameRateStability(frameStats))
        checks.append(checkSwingWindowCandidate(hasSwingWindow))

        let content = await validateVideoContent(videoURL: videoURL)
        checks.append(contentsOf: content.checks)
        metrics.sampledFrameCount = content.sampledFrameCount
        metrics.humanDetectionRatio = content.humanDetectionRatio
        metrics.averageBodyCoverageRatio = content.averageBodyCoverageRatio
        metrics.bodyCenterStability = content.bodyCenterStability
        metrics.bodyBoundingBoxStability = content.bodyBoundingBoxStability
        metrics.croppedBodyRatio = content.croppedBodyRatio
        metrics.averageSharpness = content.averageSharpness
        metrics.averageBrightness = content.averageBrightness
        metrics.underexposedPixelRatio = content.underexposedPixelRatio
        metrics.overexposedPixelRatio = content.overexposedPixelRatio
        metrics.videoWidth = content.videoWidth
        metrics.videoHeight = content.videoHeight
        metrics.orientation = content.orientation

        let allPassed = checks.allSatisfy(\.passed)
        return ValidationResult(passed: allPassed, checks: checks, metrics: metrics)
    }

    private func checkFrameCount(_ count: Int) -> ValidationCheck {
        let passed = count >= minFrameCount
        return ValidationCheck(
            name: "帧数",
            passed: passed,
            detail: passed ? "共 \(count) 帧" : "仅 \(count) 帧，需至少 \(minFrameCount) 帧"
        )
    }

    private func checkDuration(_ duration: TimeInterval, hasFrames: Bool) -> ValidationCheck {
        guard hasFrames else {
            return ValidationCheck(name: "时长", passed: false, detail: "无帧数据")
        }
        let passed = duration >= minDuration && duration <= maxDuration
        let detail = passed
            ? String(format: "%.2f 秒", duration)
            : String(format: "%.2f 秒（需 %.1f-%.1f 秒）", duration, minDuration, maxDuration)
        return ValidationCheck(name: "时长", passed: passed, detail: detail)
    }

    private func checkActualFPS(_ stats: RecordingFrameStats) -> ValidationCheck {
        guard stats.estimatedFPS > 0 else {
            return ValidationCheck(name: "实际帧率", passed: false, detail: "无法估算实际 fps")
        }
        let passed = stats.estimatedFPS >= minEstimatedFPS
        let detail = passed
            ? String(format: "%.1f fps", stats.estimatedFPS)
            : String(format: "%.1f fps（需至少 %.0f fps）", stats.estimatedFPS, minEstimatedFPS)
        return ValidationCheck(name: "实际帧率", passed: passed, detail: detail)
    }

    private func checkFrameRateStability(_ stats: RecordingFrameStats) -> ValidationCheck {
        guard stats.intervalCount > 1 else {
            return ValidationCheck(name: "帧率稳定性", passed: false, detail: "帧数不足")
        }

        let passed = stats.jitterRatio < frameRateJitterThreshold
        let detail = passed
            ? String(format: "%.1f fps，抖动 %.1f%%", stats.estimatedFPS, stats.jitterRatio * 100)
            : String(format: "帧率抖动过大 %.1f%%（阈值 %.0f%%）", stats.jitterRatio * 100, frameRateJitterThreshold * 100)
        return ValidationCheck(name: "帧率稳定性", passed: passed, detail: detail)
    }

    private func checkSwingWindowCandidate(_ available: Bool) -> ValidationCheck {
        ValidationCheck(
            name: "击球候选窗口",
            passed: available,
            detail: available
                ? "已生成可复核击球窗口"
                : String(format: "帧数或时长不足，无法形成 %.2f 秒候选窗口", minSwingWindowDurationSeconds)
        )
    }

    private func validateVideoContent(videoURL: URL) async -> VideoContentValidation {
        let asset = AVURLAsset(url: videoURL)
        guard let track = try? await asset.loadTracks(withMediaType: .video).first else {
            return VideoContentValidation(
                checks: [
                    ValidationCheck(name: "分辨率", passed: false, detail: "无法读取视频轨道"),
                    ValidationCheck(name: "方向", passed: false, detail: "无法读取视频轨道"),
                    ValidationCheck(name: "人体检测", passed: false, detail: "无法读取视频轨道"),
                    ValidationCheck(name: "清晰度", passed: false, detail: "无法读取视频轨道"),
                    ValidationCheck(name: "亮度", passed: false, detail: "无法读取视频轨道")
                ],
                sampledFrameCount: 0,
                humanDetectionRatio: nil,
                averageBodyCoverageRatio: nil,
                bodyCenterStability: nil,
                bodyBoundingBoxStability: nil,
                croppedBodyRatio: nil,
                averageSharpness: nil,
                averageBrightness: nil,
                underexposedPixelRatio: nil,
                overexposedPixelRatio: nil,
                videoWidth: nil,
                videoHeight: nil,
                orientation: "unknown"
            )
        }

        let size = (try? await track.load(.naturalSize)) ?? .zero
        let transform = (try? await track.load(.preferredTransform)) ?? .identity
        let transformed = size.applying(transform)
        let width = Int(abs(transformed.width))
        let height = Int(abs(transformed.height))
        let orientation = width >= height ? "landscape" : "portrait"
        var checks = [
            checkResolution(width: width, height: height),
            ValidationCheck(
                name: "方向",
                passed: orientation == "landscape",
                detail: orientation == "landscape" ? "横屏" : "检测为竖屏，需横屏录制"
            )
        ]

        let duration = try? await asset.load(.duration)
        let totalSeconds = max(duration.map { CMTimeGetSeconds($0) } ?? 1.0, 0.1)
        let sampleTimes = makeSampleTimes(totalSeconds: totalSeconds)

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
            checks.append(contentsOf: [
                ValidationCheck(name: "人体检测", passed: false, detail: "无法提取视频帧"),
                ValidationCheck(name: "清晰度", passed: false, detail: "无法提取视频帧"),
                ValidationCheck(name: "亮度", passed: false, detail: "无法提取视频帧")
            ])
            return VideoContentValidation(
                checks: checks,
                sampledFrameCount: 0,
                humanDetectionRatio: nil,
                averageBodyCoverageRatio: nil,
                bodyCenterStability: nil,
                bodyBoundingBoxStability: nil,
                croppedBodyRatio: nil,
                averageSharpness: nil,
                averageBrightness: nil,
                underexposedPixelRatio: nil,
                overexposedPixelRatio: nil,
                videoWidth: width,
                videoHeight: height,
                orientation: orientation
            )
        }

        let human = await checkHumanPresence(images: images)
        let sharpness = checkSharpness(images: images)
        let brightness = checkExposure(images: images)
        checks.append(contentsOf: human.checks)
        checks.append(sharpness.check)
        checks.append(contentsOf: brightness.checks)

        return VideoContentValidation(
            checks: checks,
            sampledFrameCount: images.count,
            humanDetectionRatio: human.ratio,
            averageBodyCoverageRatio: human.averageBodyCoverageRatio,
            bodyCenterStability: human.bodyCenterStability,
            bodyBoundingBoxStability: human.bodyBoundingBoxStability,
            croppedBodyRatio: human.croppedBodyRatio,
            averageSharpness: sharpness.average,
            averageBrightness: brightness.averageBrightness,
            underexposedPixelRatio: brightness.underexposedPixelRatio,
            overexposedPixelRatio: brightness.overexposedPixelRatio,
            videoWidth: width,
            videoHeight: height,
            orientation: orientation
        )
    }

    private func checkResolution(width: Int, height: Int) -> ValidationCheck {
        let longSide = max(width, height)
        let shortSide = min(width, height)
        let passed = longSide >= minLongSidePixels && shortSide >= minShortSidePixels
        let detail = passed
            ? "\(width)x\(height)"
            : "\(width)x\(height)，需至少 \(minLongSidePixels)x\(minShortSidePixels)"
        return ValidationCheck(name: "分辨率", passed: passed, detail: detail)
    }

    private func makeSampleTimes(totalSeconds: Double) -> [CMTime] {
        let safeEnd = max(totalSeconds - 0.1, 0.05)
        let positions = [0.15, 0.3, 0.5, 0.7, 0.85]
        return positions.map { ratio in
            let seconds = min(max(totalSeconds * ratio, 0.02), safeEnd)
            return CMTime(seconds: seconds, preferredTimescale: 600)
        }
    }

    private func checkHumanPresence(images: [CGImage]) async -> HumanPresenceResult {
        var detectedCount = 0
        var boxes: [NormalizedBox] = []

        for image in images {
            let request = VNDetectHumanBodyPoseRequest()
            let handler = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
            do {
                try handler.perform([request])
                if let observation = request.results?.first {
                    detectedCount += 1
                    if let box = normalizedBodyBox(from: observation) {
                        boxes.append(box)
                    }
                }
            } catch {}
        }

        let ratio = Double(detectedCount) / Double(images.count)
        let passed = ratio >= humanDetectionMinRatio
        let detail = passed
            ? "\(detectedCount)/\(images.count) 帧检测到人体"
            : "仅 \(detectedCount)/\(images.count) 帧检测到人体（需 \(Int(humanDetectionMinRatio * 100))%）"
        let boxStats = makeBodyBoxStats(boxes)
        let coveragePassed = boxStats.averageCoverage.map {
            $0 >= minBodyCoverageRatio && $0 <= maxBodyCoverageRatio
        } ?? false
        let croppedPassed = boxStats.croppedRatio.map { $0 <= maxCroppedBodyRatio } ?? false
        let stabilityPassed = boxStats.centerStability.map { centerStability in
            centerStability <= maxBodyCenterStability &&
            (boxStats.sizeStability ?? 1) <= maxBodyBoundingBoxStability
        } ?? false

        let coverageDetail: String
        if let averageCoverage = boxStats.averageCoverage, let croppedRatio = boxStats.croppedRatio {
            coverageDetail = String(format: "人体覆盖 %.1f%%，裁切 %.1f%%", averageCoverage * 100, croppedRatio * 100)
        } else {
            coverageDetail = "无法计算人体覆盖"
        }

        let stabilityDetail: String
        if let center = boxStats.centerStability, let size = boxStats.sizeStability {
            stabilityDetail = String(format: "中心波动 %.2f，框尺寸波动 %.2f", center, size)
        } else {
            stabilityDetail = "可用人体框不足"
        }

        return HumanPresenceResult(
            checks: [
                ValidationCheck(name: "人体检测", passed: passed, detail: detail),
                ValidationCheck(name: "画面覆盖", passed: coveragePassed && croppedPassed, detail: coverageDetail),
                ValidationCheck(name: "人体框稳定性", passed: stabilityPassed, detail: stabilityDetail)
            ],
            ratio: ratio,
            averageBodyCoverageRatio: boxStats.averageCoverage,
            bodyCenterStability: boxStats.centerStability,
            bodyBoundingBoxStability: boxStats.sizeStability,
            croppedBodyRatio: boxStats.croppedRatio
        )
    }

    private func normalizedBodyBox(from observation: VNHumanBodyPoseObservation) -> NormalizedBox? {
        guard let points = try? observation.recognizedPoints(.all) else { return nil }
        let valid = points.values.filter { $0.confidence >= 0.2 }
        guard !valid.isEmpty else { return nil }

        let xs = valid.map(\.location.x)
        let ys = valid.map(\.location.y)
        guard let minX = xs.min(), let maxX = xs.max(), let minY = ys.min(), let maxY = ys.max() else {
            return nil
        }
        let width = max(0, maxX - minX)
        let height = max(0, maxY - minY)
        guard width > 0, height > 0 else { return nil }
        return NormalizedBox(minX: minX, minY: minY, maxX: maxX, maxY: maxY)
    }

    private func makeBodyBoxStats(_ boxes: [NormalizedBox]) -> BodyBoxStats {
        guard !boxes.isEmpty else {
            return BodyBoxStats(averageCoverage: nil, centerStability: nil, sizeStability: nil, croppedRatio: nil)
        }
        let coverages = boxes.map(\.area)
        let averageCoverage = coverages.reduce(0, +) / Double(coverages.count)
        let croppedCount = boxes.filter(\.isNearFrameEdge).count
        let croppedRatio = Double(croppedCount) / Double(boxes.count)

        guard boxes.count >= 2 else {
            return BodyBoxStats(
                averageCoverage: averageCoverage,
                centerStability: nil,
                sizeStability: nil,
                croppedRatio: croppedRatio
            )
        }

        let avgCenterX = boxes.map(\.centerX).reduce(0, +) / Double(boxes.count)
        let avgCenterY = boxes.map(\.centerY).reduce(0, +) / Double(boxes.count)
        let centerStability = boxes
            .map { hypot($0.centerX - avgCenterX, $0.centerY - avgCenterY) }
            .reduce(0, +) / Double(boxes.count)
        let sizeStability = coefficientOfVariation(coverages)
        return BodyBoxStats(
            averageCoverage: averageCoverage,
            centerStability: centerStability,
            sizeStability: sizeStability,
            croppedRatio: croppedRatio
        )
    }

    private func checkSharpness(images: [CGImage]) -> NumericCheckResult {
        var variances: [Double] = []

        for cgImage in images {
            let width = cgImage.width
            let height = cgImage.height
            guard let data = cgImage.dataProvider?.data,
                  let ptr = CFDataGetBytePtr(data) else { continue }

            let dataLength = CFDataGetLength(data)
            let bytesPerPixel = max(cgImage.bitsPerPixel / 8, 1)
            let bytesPerRow = cgImage.bytesPerRow
            let sampleStep = 8
            var sumSq: Double = 0
            var count = 0

            for y in stride(from: sampleStep, to: max(height - sampleStep, sampleStep), by: sampleStep) {
                for x in stride(from: sampleStep, to: max(width - sampleStep, sampleStep), by: sampleStep) {
                    let idx = y * bytesPerRow + x * bytesPerPixel
                    guard idx + 2 < dataLength,
                          idx - bytesPerPixel >= 0,
                          idx + bytesPerPixel + 2 < dataLength,
                          idx - bytesPerRow >= 0,
                          idx + bytesPerRow + 2 < dataLength else { continue }

                    let center = Double(ptr[idx]) + Double(ptr[idx + 1]) + Double(ptr[idx + 2])
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
            return NumericCheckResult(
                check: ValidationCheck(name: "清晰度", passed: true, detail: "无法计算（跳过）"),
                average: nil
            )
        }

        let avgVariance = variances.reduce(0, +) / Double(variances.count)
        let passed = avgVariance >= laplacianVarianceThreshold
        let detail = passed
            ? String(format: "清晰度 %.0f", avgVariance)
            : String(format: "画面模糊（%.0f < %.0f）", avgVariance, laplacianVarianceThreshold)
        return NumericCheckResult(
            check: ValidationCheck(name: "清晰度", passed: passed, detail: detail),
            average: avgVariance
        )
    }

    private func checkExposure(images: [CGImage]) -> ExposureCheckResult {
        var brightnesses: [Double] = []
        var underexposedRatios: [Double] = []
        var overexposedRatios: [Double] = []

        for cgImage in images {
            let width = cgImage.width
            let height = cgImage.height
            guard let data = cgImage.dataProvider?.data,
                  let ptr = CFDataGetBytePtr(data) else { continue }

            let dataLength = CFDataGetLength(data)
            let bytesPerPixel = max(cgImage.bitsPerPixel / 8, 1)
            let bytesPerRow = cgImage.bytesPerRow
            let xStep = max(width / 40, 1)
            let yStep = max(height / 25, 1)
            var sum: Double = 0
            var count = 0
            var underexposed = 0
            var overexposed = 0

            for y in stride(from: 0, to: height, by: yStep) {
                for x in stride(from: 0, to: width, by: xStep) {
                    let offset = y * bytesPerRow + x * bytesPerPixel
                    guard offset + 2 < dataLength else { continue }
                    let r = Double(ptr[offset])
                    let g = Double(ptr[offset + 1])
                    let b = Double(ptr[offset + 2])
                    let value = (r + g + b) / 3.0
                    sum += value
                    if value < 20 {
                        underexposed += 1
                    } else if value > 245 {
                        overexposed += 1
                    }
                    count += 1
                }
            }

            if count > 0 {
                brightnesses.append(sum / Double(count))
                underexposedRatios.append(Double(underexposed) / Double(count))
                overexposedRatios.append(Double(overexposed) / Double(count))
            }
        }

        guard !brightnesses.isEmpty else {
            return ExposureCheckResult(
                checks: [
                    ValidationCheck(name: "亮度", passed: true, detail: "无法计算（跳过）"),
                    ValidationCheck(name: "曝光比例", passed: true, detail: "无法计算（跳过）")
                ],
                averageBrightness: nil,
                underexposedPixelRatio: nil,
                overexposedPixelRatio: nil
            )
        }

        let avgBrightness = brightnesses.reduce(0, +) / Double(brightnesses.count)
        let underexposedRatio = underexposedRatios.reduce(0, +) / Double(underexposedRatios.count)
        let overexposedRatio = overexposedRatios.reduce(0, +) / Double(overexposedRatios.count)
        let passed = avgBrightness >= minBrightness && avgBrightness <= maxBrightness
        let detail: String
        if avgBrightness < minBrightness {
            detail = String(format: "画面过暗（亮度 %.0f）", avgBrightness)
        } else if avgBrightness > maxBrightness {
            detail = String(format: "画面过曝（亮度 %.0f）", avgBrightness)
        } else {
            detail = String(format: "亮度 %.0f", avgBrightness)
        }

        let exposurePassed = underexposedRatio <= maxUnderexposedPixelRatio && overexposedRatio <= maxOverexposedPixelRatio
        let exposureDetail = String(
            format: "欠曝 %.1f%% / 过曝 %.1f%%",
            underexposedRatio * 100,
            overexposedRatio * 100
        )
        return ExposureCheckResult(
            checks: [
                ValidationCheck(name: "亮度", passed: passed, detail: detail),
                ValidationCheck(name: "曝光比例", passed: exposurePassed, detail: exposureDetail)
            ],
            averageBrightness: avgBrightness,
            underexposedPixelRatio: underexposedRatio,
            overexposedPixelRatio: overexposedRatio
        )
    }

    private func coefficientOfVariation(_ values: [Double]) -> Double? {
        guard !values.isEmpty else { return nil }
        let mean = values.reduce(0, +) / Double(values.count)
        guard mean > 0 else { return nil }
        let variance = values.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Double(values.count)
        return variance.squareRoot() / mean
    }
}

struct RecordingFrameStats {
    let duration: Double
    let estimatedFPS: Double
    let jitterRatio: Double
    let intervalCount: Int
}

enum RecordingQualityHeuristics {
    static func makeFrameStats(_ timestamps: [TimeInterval]) -> RecordingFrameStats {
        guard let first = timestamps.first, let last = timestamps.last else {
            return RecordingFrameStats(duration: 0, estimatedFPS: 0, jitterRatio: 0, intervalCount: 0)
        }

        var intervals: [Double] = []
        for i in 1..<timestamps.count {
            intervals.append(timestamps[i] - timestamps[i - 1])
        }
        guard !intervals.isEmpty else {
            return RecordingFrameStats(duration: max(last - first, 0), estimatedFPS: 0, jitterRatio: 0, intervalCount: 0)
        }

        let mean = intervals.reduce(0, +) / Double(intervals.count)
        guard mean > 0 else {
            return RecordingFrameStats(duration: max(last - first, 0), estimatedFPS: 0, jitterRatio: 1, intervalCount: intervals.count)
        }
        let variance = intervals.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Double(intervals.count)
        let std = variance.squareRoot()
        return RecordingFrameStats(
            duration: max(last - first, 0),
            estimatedFPS: 1.0 / mean,
            jitterRatio: std / mean,
            intervalCount: intervals.count
        )
    }

    static func hasSwingWindowCandidate(
        frameCount: Int,
        durationSeconds: Double,
        minFrameCount: Int,
        minDurationSeconds: Double
    ) -> Bool {
        frameCount >= minFrameCount && durationSeconds >= minDurationSeconds
    }
}

private struct VideoContentValidation {
    let checks: [ValidationCheck]
    let sampledFrameCount: Int
    let humanDetectionRatio: Double?
    let averageBodyCoverageRatio: Double?
    let bodyCenterStability: Double?
    let bodyBoundingBoxStability: Double?
    let croppedBodyRatio: Double?
    let averageSharpness: Double?
    let averageBrightness: Double?
    let underexposedPixelRatio: Double?
    let overexposedPixelRatio: Double?
    let videoWidth: Int?
    let videoHeight: Int?
    let orientation: String
}

private struct HumanPresenceResult {
    let checks: [ValidationCheck]
    let ratio: Double
    let averageBodyCoverageRatio: Double?
    let bodyCenterStability: Double?
    let bodyBoundingBoxStability: Double?
    let croppedBodyRatio: Double?
}

private struct NumericCheckResult {
    let check: ValidationCheck
    let average: Double?
}

private struct ExposureCheckResult {
    let checks: [ValidationCheck]
    let averageBrightness: Double?
    let underexposedPixelRatio: Double?
    let overexposedPixelRatio: Double?
}

private struct NormalizedBox {
    let minX: Double
    let minY: Double
    let maxX: Double
    let maxY: Double

    var centerX: Double { (minX + maxX) / 2 }
    var centerY: Double { (minY + maxY) / 2 }
    var area: Double { max(0, maxX - minX) * max(0, maxY - minY) }
    var isNearFrameEdge: Bool {
        minX <= 0.03 || minY <= 0.03 || maxX >= 0.97 || maxY >= 0.97
    }
}

private struct BodyBoxStats {
    let averageCoverage: Double?
    let centerStability: Double?
    let sizeStability: Double?
    let croppedRatio: Double?
}
