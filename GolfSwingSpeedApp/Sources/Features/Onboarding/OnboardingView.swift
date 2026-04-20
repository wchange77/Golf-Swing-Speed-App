import SwiftUI

/// First-launch onboarding flow explaining the app's key features
/// and guiding the user through initial setup.
struct OnboardingView: View {
    @Binding var hasCompletedOnboarding: Bool
    @State private var currentPage = 0

    private let pages: [OnboardingPage] = [
        OnboardingPage(
            icon: "speedometer",
            title: "Measure Your Swing Speed",
            description: "Use your iPhone's camera to capture golf swings at 240 frames per second and calculate club head speed — no external hardware needed.",
            accent: .blue
        ),
        OnboardingPage(
            icon: "camera.fill",
            title: "High-Speed Camera",
            description: "The app records at 240fps to capture every detail of your swing. Position your phone 2-3 metres away, facing the golfer from the front.",
            accent: .green
        ),
        OnboardingPage(
            icon: "scope",
            title: "Quick Calibration",
            description: "Before measuring, tap two reference points on screen and enter the distance between them. This tells the app how to convert pixels to real-world distance.",
            accent: .orange
        ),
        OnboardingPage(
            icon: "ear.and.waveform",
            title: "Audio Feedback",
            description: "Hear your speed results through beeps or voice announcements — works with AirPods so you can hear results hands-free while training.",
            accent: .purple
        ),
    ]

    var body: some View {
        VStack(spacing: 0) {
            // Page content
            TabView(selection: $currentPage) {
                ForEach(Array(pages.enumerated()), id: \.offset) { index, page in
                    pageView(page)
                        .tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .indexViewStyle(.page(backgroundDisplayMode: .always))

            // Bottom button
            Button {
                if currentPage < pages.count - 1 {
                    withAnimation {
                        currentPage += 1
                    }
                } else {
                    hasCompletedOnboarding = true
                }
            } label: {
                Text(currentPage < pages.count - 1 ? "Next" : "Get Started")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(pages[currentPage].accent, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 40)

            // Skip button
            if currentPage < pages.count - 1 {
                Button("Skip") {
                    hasCompletedOnboarding = true
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .padding(.bottom, 20)
            }
        }
        .background(.black)
    }

    private func pageView(_ page: OnboardingPage) -> some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: page.icon)
                .font(.system(size: 80))
                .foregroundStyle(page.accent)

            Text(page.title)
                .font(.title)
                .fontWeight(.bold)
                .foregroundStyle(.white)
                .multilineTextAlignment(.center)

            Text(page.description)
                .font(.body)
                .foregroundStyle(.white.opacity(0.7))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)

            Spacer()
            Spacer()
        }
    }
}

private struct OnboardingPage {
    let icon: String
    let title: String
    let description: String
    let accent: Color
}

#Preview {
    OnboardingView(hasCompletedOnboarding: .constant(false))
}
