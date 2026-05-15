import Accelerate
import AVFoundation
import Foundation

public struct OfflineAudioImpactSample: Equatable, Codable {
    public let timeSeconds: Double
    public let rms: Float
    public let highBandRatio: Float
    public let peakFrequencyHz: Double
}

public struct OfflineAudioAnalysisResult: Equatable, Codable {
    public let sampleRate: Double
    public let channelCount: Int
    public let durationSeconds: Double
    public let peakAmplitude: Float
    public let rmsDbfs: Float
    public let impactWindows: [OfflineAudioImpactSample]
    public let impactTimeSeconds: Double?
}

public enum OfflineAudioAnalyserError: Error {
    case noAudioTrack
    case readerSetupFailed
    case emptyStream
}

/// Offline counterpart to `SwingAudioDetector`. Reads .mov / .m4a audio track
/// and locates the strongest impact transient in 2–5 kHz band.
public enum OfflineAudioAnalyser {
    public static func analyseFile(
        url: URL,
        windowSize: Int = 2048,
        impactBand: ClosedRange<Double> = 2000...5000,
        impactRatioThreshold: Float = 0.25
    ) async throws -> OfflineAudioAnalysisResult {
        let asset = AVURLAsset(url: url)
        let tracks = try await asset.loadTracks(withMediaType: .audio)
        guard let track = tracks.first else { throw OfflineAudioAnalyserError.noAudioTrack }

        let reader = try AVAssetReader(asset: asset)
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false
        ]
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        guard reader.canAdd(output) else {
            throw OfflineAudioAnalyserError.readerSetupFailed
        }
        reader.add(output)
        guard reader.startReading() else {
            throw OfflineAudioAnalyserError.readerSetupFailed
        }

        let descriptions = try await track.load(.formatDescriptions)
        guard let asbd = descriptions.first.flatMap({ CMAudioFormatDescriptionGetStreamBasicDescription($0)?.pointee }) else {
            throw OfflineAudioAnalyserError.emptyStream
        }
        let sampleRate = asbd.mSampleRate
        let channelCount = max(Int(asbd.mChannelsPerFrame), 1)

        var monoBuffer: [Float] = []
        var peakAmplitude: Float = 0
        var sumSquares: Double = 0
        var totalFrames: Int = 0

        while let sampleBuffer = output.copyNextSampleBuffer() {
            let numSamples = CMSampleBufferGetNumSamples(sampleBuffer)
            guard numSamples > 0, let dataBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { continue }
            var length = 0
            var dataPointer: UnsafeMutablePointer<Int8>? = nil
            guard CMBlockBufferGetDataPointer(dataBuffer, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &dataPointer) == kCMBlockBufferNoErr,
                  let rawPtr = dataPointer else { continue }

            let frames = numSamples
            var chunk = [Float](repeating: 0, count: frames)
            rawPtr.withMemoryRebound(to: Float32.self, capacity: frames * channelCount) { ptr in
                for i in 0..<frames {
                    var sum: Float = 0
                    for c in 0..<channelCount {
                        sum += ptr[i * channelCount + c]
                    }
                    chunk[i] = sum / Float(channelCount)
                }
            }
            for value in chunk {
                let abs = value < 0 ? -value : value
                if abs > peakAmplitude { peakAmplitude = abs }
                sumSquares += Double(value) * Double(value)
            }
            totalFrames += frames
            monoBuffer.append(contentsOf: chunk)
        }

        guard reader.status == .completed else {
            throw OfflineAudioAnalyserError.readerSetupFailed
        }
        guard totalFrames > 0 else { throw OfflineAudioAnalyserError.emptyStream }

        let windows = runWindowedFFT(
            samples: monoBuffer,
            sampleRate: sampleRate,
            windowSize: windowSize,
            impactBand: impactBand
        )
        let impactTime = windows
            .filter { $0.highBandRatio >= impactRatioThreshold }
            .max(by: { $0.highBandRatio < $1.highBandRatio })?
            .timeSeconds

        let duration = Double(totalFrames) / sampleRate
        let rms = Float((sumSquares / Double(totalFrames)).squareRoot())
        let rmsDb = rms > 0 ? 20 * log10(rms) : -120
        return OfflineAudioAnalysisResult(
            sampleRate: sampleRate,
            channelCount: channelCount,
            durationSeconds: duration,
            peakAmplitude: peakAmplitude,
            rmsDbfs: rmsDb,
            impactWindows: windows,
            impactTimeSeconds: impactTime
        )
    }

    private static func runWindowedFFT(
        samples: [Float],
        sampleRate: Double,
        windowSize: Int,
        impactBand: ClosedRange<Double>
    ) -> [OfflineAudioImpactSample] {
        guard samples.count >= windowSize, sampleRate > 0 else { return [] }
        let log2n = vDSP_Length(log2(Double(windowSize)))
        guard let fftSetup = vDSP_create_fftsetup(log2n, FFTRadix(kFFTRadix2)) else { return [] }
        defer { vDSP_destroy_fftsetup(fftSetup) }

        var hann = [Float](repeating: 0, count: windowSize)
        vDSP_hann_window(&hann, vDSP_Length(windowSize), Int32(vDSP_HANN_NORM))
        let hop = windowSize / 2
        let halfSize = windowSize / 2
        let nyquist = sampleRate / 2
        let binWidth = nyquist / Double(halfSize)
        let lowBin = max(Int(impactBand.lowerBound / binWidth), 1)
        let highBin = min(Int(impactBand.upperBound / binWidth), halfSize - 1)

        var results: [OfflineAudioImpactSample] = []
        var cursor = 0
        while cursor + windowSize <= samples.count {
            let frame = Array(samples[cursor..<(cursor + windowSize)])
            var windowed = [Float](repeating: 0, count: windowSize)
            vDSP_vmul(frame, 1, hann, 1, &windowed, 1, vDSP_Length(windowSize))

            var realp = [Float](repeating: 0, count: halfSize)
            var imagp = [Float](repeating: 0, count: halfSize)
            var rms: Float = 0
            vDSP_rmsqv(frame, 1, &rms, vDSP_Length(windowSize))
            realp.withUnsafeMutableBufferPointer { rBuf in
                imagp.withUnsafeMutableBufferPointer { iBuf in
                    var split = DSPSplitComplex(realp: rBuf.baseAddress!, imagp: iBuf.baseAddress!)
                    windowed.withUnsafeBufferPointer { wBuf in
                        wBuf.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: halfSize) { cPtr in
                            vDSP_ctoz(cPtr, 2, &split, 1, vDSP_Length(halfSize))
                        }
                    }
                    vDSP_fft_zrip(fftSetup, &split, 1, log2n, FFTDirection(FFT_FORWARD))
                    var magnitudes = [Float](repeating: 0, count: halfSize)
                    vDSP_zvmags(&split, 1, &magnitudes, 1, vDSP_Length(halfSize))

                    var band: Float = 0
                    var total: Float = 0
                    var peakMag: Float = 0
                    var peakIdx = 0
                    for i in 1..<halfSize {
                        total += magnitudes[i]
                        if i >= lowBin && i <= highBin {
                            band += magnitudes[i]
                            if magnitudes[i] > peakMag {
                                peakMag = magnitudes[i]
                                peakIdx = i
                            }
                        }
                    }
                    let ratio = total > 0 ? band / total : 0
                    let peakHz = Double(peakIdx) * binWidth
                    let timeSeconds = Double(cursor) / sampleRate
                    results.append(OfflineAudioImpactSample(
                        timeSeconds: timeSeconds,
                        rms: rms,
                        highBandRatio: ratio,
                        peakFrequencyHz: peakHz
                    ))
                }
            }
            cursor += hop
        }
        return results
    }
}
