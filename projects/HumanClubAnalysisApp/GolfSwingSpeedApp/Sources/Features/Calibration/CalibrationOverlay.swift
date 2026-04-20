import SwiftUI

struct CalibrationOverlay: View {
    let calibrationData: CalibrationSnapshot?

    var body: some View {
        if let data = calibrationData {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 4) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text("Calibrated")
                        .fontWeight(.semibold)
                }
                Text("Scale: \(String(format: "%.0f", data.pixelsPerMetre)) px/m")
                    .font(.caption)
                if let clubLength = data.clubLength {
                    Text("Club: \(String(format: "%.0f", clubLength * 100)) cm")
                        .font(.caption)
                }
                if let lieAngle = data.lieAngle {
                    Text("Lie: \(String(format: "%.0f", lieAngle))°")
                        .font(.caption)
                }
            }
            .font(.caption)
            .foregroundStyle(.white)
            .padding(8)
            .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
        }
    }
}
