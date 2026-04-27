import SwiftUI
import GolfAnalysisKit

struct SessionHistoryView: View {
    @StateObject private var viewModel = SessionHistoryViewModel()
    @State private var selectedClubFilter: ClubType?
    @State private var selectedSession: SwingSession?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            FilterChip(label: "全部", isSelected: selectedClubFilter == nil) {
                                selectedClubFilter = nil
                            }
                            ForEach(viewModel.usedClubs, id: \.self) { club in
                                FilterChip(
                                    label: club.displayName,
                                    isSelected: selectedClubFilter == club
                                ) {
                                    selectedClubFilter = club
                                }
                            }
                        }
                        .padding(.horizontal, 4)
                    }
                    .listRowInsets(EdgeInsets(top: 4, leading: 0, bottom: 4, trailing: 0))
                }

                if viewModel.isLoading {
                    ProgressView()
                } else if filteredSessions.isEmpty {
                    Section {
                        Text("暂无挥杆记录")
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Section("记录 (\(filteredSessions.count))") {
                        ForEach(filteredSessions) { session in
                            SessionRowView(session: session)
                                .contentShape(Rectangle())
                                .onTapGesture { selectedSession = session }
                        }
                        .onDelete { offsets in
                            let toDelete = offsets.map { filteredSessions[$0] }
                            for s in toDelete {
                                viewModel.delete(session: s)
                            }
                        }
                    }
                }
            }
            .navigationTitle("挥杆历史")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Text("\(viewModel.totalCount) 次")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .sheet(item: $selectedSession) { session in
                SessionDetailSheet(session: session)
            }
            .task { await viewModel.load() }
        }
    }

    private var filteredSessions: [SwingSession] {
        if let club = selectedClubFilter {
            return viewModel.sessions.filter { $0.club == club }
        }
        return viewModel.sessions
    }
}

struct FilterChip: View {
    let label: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.caption)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(isSelected ? Color.accentColor : Color(.systemGray5))
                .foregroundStyle(isSelected ? .white : .primary)
                .clipShape(Capsule())
        }
    }
}

struct SessionRowView: View {
    let session: SwingSession

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(session.club.displayName)
                        .font(.subheadline.bold())
                    shapeTag
                }
                Text(session.date, style: .date)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 3) {
                Text("\(String(format: "%.0f", session.carryDistanceYards)) 码")
                    .font(.subheadline.bold())
                Text("\(String(format: "%.0f", session.clubHeadSpeedMph)) mph")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    private var shapeTag: some View {
        let (label, color): (String, Color) = {
            switch session.trajectoryShape {
            case .hook: return ("Hook", .red)
            case .draw: return ("Draw", .orange)
            case .straight: return ("Straight", .green)
            case .fade: return ("Fade", .blue)
            case .slice: return ("Slice", .purple)
            }
        }()
        return Text(label)
            .font(.system(size: 9).bold())
            .padding(.horizontal, 5)
            .padding(.vertical, 1)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}

struct SessionDetailSheet: View {
    let session: SwingSession
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section("基本信息") {
                    row("球杆", session.club.displayName)
                    row("日期", session.date.formatted(date: .long, time: .shortened))
                    row("弹道", session.trajectoryShape.rawValue)
                    row("置信度", "\(Int(session.confidence * 100))%")
                }

                Section("速度") {
                    row("杆头速度", "\(String(format: "%.1f", session.clubHeadSpeedMph)) mph")
                    row("球速", "\(String(format: "%.1f", session.ballSpeedMph)) mph")
                    row("Smash Factor", String(format: "%.2f", session.ballSpeedMph / max(1, session.clubHeadSpeedMph)))
                }

                Section("距离") {
                    row("Carry", "\(String(format: "%.0f", session.carryDistanceYards)) 码")
                    row("总距离", "\(String(format: "%.0f", session.totalDistanceYards)) 码")
                }

                Section("弹道参数") {
                    row("发射角", "\(String(format: "%.1f", session.launchAngleDegrees))°")
                    row("最高点", "\(String(format: "%.1f", session.apexHeightMeters)) m")
                    row("飞行时间", "\(String(format: "%.1f", session.flightTimeSeconds)) s")
                    row("落地角", "\(String(format: "%.0f", session.landingAngleDegrees))°")
                    row("后旋", "\(String(format: "%.0f", session.backspinRPM)) rpm")
                    row("侧旋", "\(String(format: "%.0f", session.sidespinRPM)) rpm")
                }

                if !session.notes.isEmpty {
                    Section("备注") {
                        Text(session.notes)
                            .font(.footnote)
                    }
                }
            }
            .navigationTitle("挥杆详情")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("关闭") { dismiss() }
                }
            }
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
        }
        .font(.subheadline)
    }
}
