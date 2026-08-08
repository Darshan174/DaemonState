import AppKit

@MainActor
enum OverlayApplicationMenu {
    static func install(on application: NSApplication) {
        let mainMenu = NSMenu()

        let applicationMenuItem = NSMenuItem()
        let applicationMenu = NSMenu(title: "DaemonState")
        applicationMenuItem.submenu = applicationMenu
        let quitItem = NSMenuItem(
            title: "Quit DaemonState Control",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        )
        quitItem.target = application
        applicationMenu.addItem(quitItem)
        mainMenu.addItem(applicationMenuItem)

        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenuItem.submenu = editMenu
        editMenu.addItem(
            withTitle: "Undo",
            action: Selector(("undo:")),
            keyEquivalent: "z"
        )
        let redoItem = editMenu.addItem(
            withTitle: "Redo",
            action: Selector(("redo:")),
            keyEquivalent: "z"
        )
        redoItem.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        editMenu.addItem(
            withTitle: "Cut",
            action: #selector(NSText.cut(_:)),
            keyEquivalent: "x"
        )
        editMenu.addItem(
            withTitle: "Copy",
            action: #selector(NSText.copy(_:)),
            keyEquivalent: "c"
        )
        editMenu.addItem(
            withTitle: "Paste",
            action: #selector(NSText.paste(_:)),
            keyEquivalent: "v"
        )
        editMenu.addItem(
            withTitle: "Select All",
            action: #selector(NSText.selectAll(_:)),
            keyEquivalent: "a"
        )
        mainMenu.addItem(editMenuItem)

        application.mainMenu = mainMenu
    }
}

@main
struct DaemonStateOverlayMain {
    @MainActor
    static func main() {
        let application = NSApplication.shared
        let delegate = OverlayApplicationDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        OverlayApplicationMenu.install(on: application)
        application.run()
        _ = delegate
    }
}
