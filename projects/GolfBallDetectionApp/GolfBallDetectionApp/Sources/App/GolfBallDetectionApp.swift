import SwiftUI

@main
struct GolfBallDetectionApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                BallDetectionView()
                    .tabItem {
                        Label("检测", systemImage: "scope")
                    }

                SessionHistoryView()
                    .tabItem {
                        Label("历史", systemImage: "clock.arrow.circlepath")
                    }

                InsightsDashboardView()
                    .tabItem {
                        Label("洞察", systemImage: "chart.bar.xaxis")
                    }
            }
        }
    }
}
