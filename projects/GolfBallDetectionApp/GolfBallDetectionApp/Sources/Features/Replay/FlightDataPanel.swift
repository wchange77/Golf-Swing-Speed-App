import SwiftUI
import GolfAnalysisKit

struct FlightDataPanel: View {
    let prediction: TrajectoryPrediction?
    let ballFlightMetrics: BallFlightMetrics?
    let isExpanded: Bool

    init(
        prediction: TrajectoryPrediction? = nil,
        ballFlightMetrics: BallFlightMetrics? = nil,
        isExpanded: Bool = true
    ) {
        self.prediction = prediction
        self.ballFlightMetrics = ballFlightMetrics
        self.isExpanded = isExpanded
    }

    var body: some View {
        if isExpanded {
            expandedPanel
        } else {
            compactPanel
        }
    }

    private var expandedPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let pred = prediction {
                HStack {
                    Text("弹道分析")
                        .font(.headline)
                    Spacer()
                    shapeTag(pred.trajectoryShape)
                    confidenceTag(pred.overallConfidence)
                }

                LazyVGrid(columns: [
                    GridItem(.flexible()),
                    GridItem(.flexible()),
                ], spacing: 8) {
                    metricCard(title: "球速", value: String(format: "%.0f", pred.launchConditions.ballSpeedMph), unit: "mph")
                    metricCard(title: "发射角", value: String(format: "%.1f", pred.launchConditions.launchAngleDegrees), unit: "°")
                    metricCard(title: "Carry", value: String(format: "%.0f", pred.carryDistanceYards), unit: "码")
                    metricCard(title: "总距离", value: String(format: "%.0f", pred.totalDistanceYards), unit: "码")
                    metricCard(title: "最高点", value: String(format: "%.1f", pred.apexHeightMeters), unit: "m")
                    metricCard(title: "飞行时间", value: String(format: "%.1f", pred.flightTimeSeconds), unit: "s")
                    metricCard(title: "落地角", value: String(format: "%.0f", pred.physicsResult.landingAngleDegrees), unit: "°")
                    metricCard(title: "旋转", value: String(format: "%.0f", pred.launchConditions.backspinRPM), unit: "rpm")
                }
            } else if let metrics = ballFlightMetrics {
                HStack {
                    Text("检测数据")
                        .font(.headline)
                    Spacer()
                    confidenceTag(metrics.confidence)
                }

                LazyVGrid(columns: [
                    GridItem(.flexible()),
                    GridItem(.flexible()),
                ], spacing: 8) {
                    metricCard(title: "球速", value: String(format: "%.0f", metrics.ballSpeedMph), unit: "mph")
                    metricCard(title: "发射角", value: String(format: "%.1f", metrics.launchAngleDegrees), unit: "°")
                    metricCard(title: "追踪帧数", value: "\(metrics.trackedFrameCount)", unit: "帧")
                }
            } else {
                Text("暂无弹道数据")
                    .foregroundStyle(.secondary)
                    .font(.footnote)
            }
        }
        .padding(12)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private var compactPanel: some View {
        HStack(spacing: 12) {
            if let pred = prediction {
                compactMetric(label: "球速", value: String(format: "%.0f", pred.launchConditions.ballSpeedMph), unit: "mph")
                compactMetric(label: "Carry", value: String(format: "%.0f", pred.carryDistanceYards), unit: "码")
                compactMetric(label: "最高点", value: String(format: "%.1f", pred.apexHeightMeters), unit: "m")
                shapeTag(pred.trajectoryShape)
            } else if let metrics = ballFlightMetrics {
                compactMetric(label: "球速", value: String(format: "%.0f", metrics.ballSpeedMph), unit: "mph")
                compactMetric(label: "发射角", value: String(format: "%.1f", metrics.launchAngleDegrees), unit: "°")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
    }

    private func metricCard(title: String, value: String, unit: String) -> some View {
        VStack(spacing: 2) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(value)
                    .font(.system(.title3, design: .rounded, weight: .semibold))
                Text(unit)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .background(.quaternary.opacity(0.3))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func compactMetric(label: String, value: String, unit: String) -> some View {
        VStack(spacing: 1) {
            Text(label).font(.system(size: 9)).foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 1) {
                Text(value).font(.system(size: 14, weight: .semibold, design: .rounded))
                Text(unit).font(.system(size: 9)).foregroundStyle(.secondary)
            }
        }
    }

    private func shapeTag(_ shape: TrajectoryShape) -> some View {
        let (label, color): (String, Color) = {
            switch shape {
            case .hook: return ("Hook", .red)
            case .draw: return ("Draw", .orange)
            case .straight: return ("Straight", .green)
            case .fade: return ("Fade", .blue)
            case .slice: return ("Slice", .purple)
            }
        }()
        return Text(label)
            .font(.caption2.bold())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.2))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    private func confidenceTag(_ confidence: Double) -> some View {
        let color: Color = confidence > 0.7 ? .green : confidence > 0.4 ? .yellow : .red
        return Text("\(Int(confidence * 100))%")
            .font(.caption2.bold())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.2))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}

#Preview {
    VStack(spacing: 20) {
        FlightDataPanel(
            prediction: TrajectoryPredictor.predict(
                clubHeadSpeedMph: 100, club: .driver),
            isExpanded: true
        )
        FlightDataPanel(
            prediction: TrajectoryPredictor.predict(
                clubHeadSpeedMph: 100, club: .driver),
            isExpanded: false
        )
    }
    .padding()
}
