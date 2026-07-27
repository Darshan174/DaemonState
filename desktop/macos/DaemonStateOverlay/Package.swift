// swift-tools-version: 5.10

import PackageDescription

let package = Package(
    name: "DaemonStateOverlay",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .library(
            name: "DaemonStateOverlayCore",
            targets: ["DaemonStateOverlayCore"]
        ),
        .executable(
            name: "DaemonStateOverlay",
            targets: ["DaemonStateOverlay"]
        ),
    ],
    targets: [
        .target(
            name: "DaemonStateOverlayCore"
        ),
        .executableTarget(
            name: "DaemonStateOverlay",
            dependencies: ["DaemonStateOverlayCore"]
        ),
        .testTarget(
            name: "DaemonStateOverlayCoreTests",
            dependencies: ["DaemonStateOverlayCore"]
        ),
        .testTarget(
            name: "DaemonStateOverlayTests",
            dependencies: ["DaemonStateOverlay"]
        ),
    ]
)
