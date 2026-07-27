import AppKit

@main
struct DaemonStateOverlayMain {
    @MainActor
    static func main() {
        let application = NSApplication.shared
        let delegate = OverlayApplicationDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        application.run()
        _ = delegate
    }
}
