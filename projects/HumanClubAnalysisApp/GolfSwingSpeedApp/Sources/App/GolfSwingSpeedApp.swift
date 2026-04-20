import SwiftUI
import SwiftData

@main
struct GolfSwingSpeedApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(for: SwingRecord.self)
    }
}

struct ContentView: View {
    @AppStorage("hasCompletedOnboarding") private var hasCompletedOnboarding = false
    @State private var selectedTab: AppTab = .capture

    var body: some View {
        if !hasCompletedOnboarding {
            OnboardingView(hasCompletedOnboarding: $hasCompletedOnboarding)
        } else {
            TabView(selection: $selectedTab) {
                CaptureView()
                    .tabItem {
                        Label("Capture", systemImage: "camera.fill")
                    }
                    .tag(AppTab.capture)

                HistoryView()
                    .tabItem {
                        Label("History", systemImage: "clock.fill")
                    }
                    .tag(AppTab.history)

                SettingsView()
                    .tabItem {
                        Label("Settings", systemImage: "gearshape.fill")
                    }
                    .tag(AppTab.settings)
            }
        }
    }
}

enum AppTab {
    case capture, history, settings
}
