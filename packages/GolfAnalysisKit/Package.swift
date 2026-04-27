// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "GolfAnalysisKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "GolfAnalysisKit", targets: ["GolfAnalysisKit"]),
    ],
    targets: [
        .target(
            name: "GolfAnalysisKit",
            path: "Sources/GolfAnalysisKit"
        ),
        .testTarget(
            name: "GolfAnalysisKitTests",
            dependencies: ["GolfAnalysisKit"],
            path: "Tests/GolfAnalysisKitTests"
        ),
    ]
)
