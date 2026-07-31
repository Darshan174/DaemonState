import AppKit
import DaemonStateOverlayCore

@MainActor
final class PromptDropdownController: NSObject, NSPopoverDelegate {
    var onRefresh: (() async throws -> [PromptSnippet])?
    var onSave: ((String) async throws -> PromptSnippet)?
    var onToggle: ((PromptSnippet) -> Void)?
    var selectedPromptIDs: (() -> Set<String>)?

    private let popover = NSPopover()
    private let contentController = PromptDropdownViewController()
    private var cachedPrompts: [PromptSnippet] = []
    private var previousApplication: NSRunningApplication?
    private var refreshTask: Task<Void, Never>?
    private var saveTask: Task<Void, Never>?

    override init() {
        super.init()
        popover.behavior = .applicationDefined
        popover.animates = true
        popover.contentSize = NSSize(width: 360, height: 466)
        popover.contentViewController = contentController
        popover.delegate = self

        contentController.onSave = { [weak self] content in
            self?.save(content)
        }
        contentController.onSelect = { [weak self] prompt in
            guard let self else { return }
            self.onToggle?(prompt)
            self.contentController.update(
                prompts: self.cachedPrompts,
                selectedIDs: self.selectedPromptIDs?() ?? []
            )
            self.close()
        }
    }

    deinit {
        refreshTask?.cancel()
        saveTask?.cancel()
    }

    func toggle(relativeTo button: NSView) {
        if popover.isShown {
            close()
            return
        }
        let current = NSWorkspace.shared.frontmostApplication
        if current?.processIdentifier != ProcessInfo.processInfo.processIdentifier {
            previousApplication = current
        } else {
            previousApplication = nil
        }
        contentController.update(
            prompts: cachedPrompts,
            selectedIDs: selectedPromptIDs?() ?? []
        )
        popover.show(
            relativeTo: button.bounds,
            of: button,
            preferredEdge: .maxY
        )
        NSApp.activate(ignoringOtherApps: true)
        refresh()
    }

    func close() {
        refreshTask?.cancel()
        saveTask?.cancel()
        if popover.isShown {
            popover.performClose(nil)
        } else {
            restorePreviousApplication()
        }
    }

    func selectionDidChange() {
        guard popover.isShown else { return }
        contentController.update(
            prompts: cachedPrompts,
            selectedIDs: selectedPromptIDs?() ?? []
        )
    }

    func popoverDidClose(_ notification: Notification) {
        restorePreviousApplication()
    }

    private func refresh() {
        refreshTask?.cancel()
        guard let onRefresh else {
            contentController.showListError("Prompt storage is unavailable.")
            return
        }
        contentController.setLoading(true)
        refreshTask = Task { [weak self] in
            guard let self else { return }
            do {
                let prompts = try await onRefresh()
                guard !Task.isCancelled else { return }
                self.cachedPrompts = prompts
                self.contentController.update(
                    prompts: prompts,
                    selectedIDs: self.selectedPromptIDs?() ?? []
                )
            } catch {
                guard !Task.isCancelled else { return }
                self.contentController.showListError(
                    self.conciseMessage(error)
                )
            }
        }
    }

    private func save(_ content: String) {
        saveTask?.cancel()
        guard let onSave else {
            contentController.showSaveError("Prompt storage is unavailable.")
            return
        }
        contentController.setSaving(true)
        saveTask = Task { [weak self] in
            guard let self else { return }
            do {
                let prompt = try await onSave(content)
                guard !Task.isCancelled else { return }
                if let index = self.cachedPrompts.firstIndex(where: {
                    $0.id == prompt.id
                }) {
                    self.cachedPrompts[index] = prompt
                } else {
                    self.cachedPrompts.insert(prompt, at: 0)
                }
                self.contentController.finishSaving(
                    prompts: self.cachedPrompts,
                    selectedIDs: self.selectedPromptIDs?() ?? []
                )
            } catch {
                guard !Task.isCancelled else { return }
                self.contentController.showSaveError(
                    self.conciseMessage(error)
                )
            }
        }
    }

    private func restorePreviousApplication() {
        guard let application = previousApplication else { return }
        previousApplication = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.04) {
            application.activate(options: [.activateIgnoringOtherApps])
        }
    }

    private func conciseMessage(_ error: Error) -> String {
        let value = error.localizedDescription
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return value.count <= 120 ? value : "\(value.prefix(117))…"
    }
}

@MainActor
private final class PromptDropdownViewController: NSViewController, NSTextViewDelegate {
    var onSave: ((String) -> Void)?
    var onSelect: ((PromptSnippet) -> Void)?

    private let promptTextView = NSTextView()
    private let characterLabel = NSTextField(labelWithString: "0 / 20,000")
    private let saveButton = NSButton(title: "Save prompt", target: nil, action: nil)
    private let statusLabel = NSTextField(labelWithString: "")
    private let selectionLabel = NSTextField(labelWithString: "None selected")
    private let listScrollView = NSScrollView()
    private let listDocumentView = PromptListDocumentView()
    private var prompts: [PromptSnippet] = []
    private var selectedIDs = Set<String>()
    private var loading = false

    override func loadView() {
        let root = NSView(frame: NSRect(x: 0, y: 0, width: 360, height: 466))
        root.wantsLayer = true
        root.layer?.backgroundColor = NSColor(
            calibratedRed: 0.065,
            green: 0.067,
            blue: 0.055,
            alpha: 1
        ).cgColor
        view = root
        buildInterface()
    }

    func update(prompts: [PromptSnippet], selectedIDs: Set<String>) {
        _ = view
        self.prompts = prompts
        self.selectedIDs = selectedIDs
        loading = false
        statusLabel.isHidden = true
        setSaving(false)
        updateSelectionLabel()
        renderList()
    }

    func setLoading(_ value: Bool) {
        _ = view
        loading = value
        if value, prompts.isEmpty {
            renderList()
        }
    }

    func showListError(_ message: String) {
        _ = view
        loading = false
        listDocumentView.removeAllSubviews()
        let label = emptyLabel(message)
        label.textColor = NSColor(
            calibratedRed: 1,
            green: 0.56,
            blue: 0.48,
            alpha: 1
        )
        listDocumentView.addSubview(label)
        layoutDocument(height: 178)
        label.frame = NSRect(x: 12, y: 61, width: 304, height: 56)
    }

    func setSaving(_ saving: Bool) {
        _ = view
        saveButton.isEnabled = !saving && hasVisiblePrompt
        saveButton.title = saving ? "Saving…" : "Save prompt"
        promptTextView.isEditable = !saving
    }

    func finishSaving(
        prompts: [PromptSnippet],
        selectedIDs: Set<String>
    ) {
        promptTextView.string = ""
        characterLabel.stringValue = "0 / 20,000"
        statusLabel.stringValue = "Saved — click it below to activate prompt mode."
        statusLabel.textColor = NSColor(
            calibratedRed: 0.76,
            green: 1,
            blue: 0.36,
            alpha: 1
        )
        statusLabel.isHidden = false
        update(prompts: prompts, selectedIDs: selectedIDs)
        statusLabel.isHidden = false
        setSaving(false)
    }

    func showSaveError(_ message: String) {
        _ = view
        statusLabel.stringValue = message
        statusLabel.textColor = NSColor(
            calibratedRed: 1,
            green: 0.56,
            blue: 0.48,
            alpha: 1
        )
        statusLabel.isHidden = false
        setSaving(false)
    }

    func textDidChange(_ notification: Notification) {
        if promptTextView.string.count > 20_000 {
            promptTextView.string = String(promptTextView.string.prefix(20_000))
        }
        characterLabel.stringValue = "\(promptTextView.string.count.formatted()) / 20,000"
        saveButton.isEnabled = hasVisiblePrompt
        statusLabel.isHidden = true
    }

    private func buildInterface() {
        let title = NSTextField(labelWithString: "PROMPT MODE")
        title.font = .systemFont(ofSize: 11, weight: .heavy)
        title.textColor = NSColor(
            calibratedRed: 0.76,
            green: 1,
            blue: 0.36,
            alpha: 1
        )

        selectionLabel.font = .monospacedDigitSystemFont(ofSize: 10, weight: .semibold)
        selectionLabel.alignment = .center
        selectionLabel.textColor = NSColor(calibratedWhite: 0.84, alpha: 1)
        selectionLabel.wantsLayer = true
        selectionLabel.layer?.backgroundColor = NSColor(
            calibratedWhite: 1,
            alpha: 0.075
        ).cgColor
        selectionLabel.layer?.cornerRadius = 9
        selectionLabel.setContentHuggingPriority(.required, for: .horizontal)
        selectionLabel.widthAnchor.constraint(greaterThanOrEqualToConstant: 86).isActive = true
        selectionLabel.heightAnchor.constraint(equalToConstant: 20).isActive = true

        let headerSpacer = NSView()
        headerSpacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let titleRow = horizontalStack([title, headerSpacer, selectionLabel])

        let subtitle = NSTextField(
            wrappingLabelWithString: "Paste a reusable instruction here, or select one already saved."
        )
        subtitle.font = .systemFont(ofSize: 12, weight: .regular)
        subtitle.textColor = NSColor(calibratedWhite: 0.66, alpha: 1)

        let editorScroll = NSScrollView()
        editorScroll.borderType = .noBorder
        editorScroll.drawsBackground = true
        editorScroll.backgroundColor = NSColor(calibratedWhite: 0, alpha: 0.24)
        editorScroll.wantsLayer = true
        editorScroll.layer?.cornerRadius = 11
        editorScroll.layer?.borderWidth = 1
        editorScroll.layer?.borderColor = NSColor(
            calibratedWhite: 1,
            alpha: 0.12
        ).cgColor
        editorScroll.hasVerticalScroller = true
        editorScroll.autohidesScrollers = true
        editorScroll.heightAnchor.constraint(equalToConstant: 82).isActive = true

        promptTextView.isRichText = false
        promptTextView.importsGraphics = false
        promptTextView.allowsUndo = true
        promptTextView.font = .systemFont(ofSize: 12.5)
        promptTextView.textColor = NSColor(calibratedWhite: 0.94, alpha: 1)
        promptTextView.backgroundColor = .clear
        promptTextView.insertionPointColor = NSColor(
            calibratedRed: 0.76,
            green: 1,
            blue: 0.36,
            alpha: 1
        )
        promptTextView.textContainerInset = NSSize(width: 10, height: 9)
        promptTextView.isHorizontallyResizable = false
        promptTextView.isVerticallyResizable = true
        promptTextView.autoresizingMask = [.width]
        promptTextView.delegate = self
        editorScroll.documentView = promptTextView

        characterLabel.font = .monospacedDigitSystemFont(ofSize: 9.5, weight: .regular)
        characterLabel.textColor = NSColor(calibratedWhite: 0.48, alpha: 1)

        saveButton.target = self
        saveButton.action = #selector(savePressed)
        saveButton.bezelStyle = .rounded
        saveButton.controlSize = .small
        saveButton.font = .systemFont(ofSize: 11, weight: .bold)
        saveButton.contentTintColor = .black
        saveButton.bezelColor = NSColor(
            calibratedRed: 0.76,
            green: 1,
            blue: 0.36,
            alpha: 1
        )
        saveButton.isEnabled = false
        saveButton.widthAnchor.constraint(equalToConstant: 94).isActive = true
        saveButton.heightAnchor.constraint(equalToConstant: 28).isActive = true

        let footerSpacer = NSView()
        footerSpacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let editorFooter = horizontalStack([
            characterLabel,
            footerSpacer,
            saveButton,
        ])

        statusLabel.font = .systemFont(ofSize: 10.5, weight: .medium)
        statusLabel.lineBreakMode = .byTruncatingTail
        statusLabel.isHidden = true

        let divider = NSBox()
        divider.boxType = .separator

        let historyTitle = NSTextField(labelWithString: "Saved prompts")
        historyTitle.font = .systemFont(ofSize: 12, weight: .semibold)
        historyTitle.textColor = NSColor(calibratedWhite: 0.94, alpha: 1)
        let historyHint = NSTextField(labelWithString: "Click to select · open again for more")
        historyHint.font = .systemFont(ofSize: 9.5, weight: .regular)
        historyHint.textColor = NSColor(calibratedWhite: 0.46, alpha: 1)
        let historySpacer = NSView()
        historySpacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let historyRow = horizontalStack([
            historyTitle,
            historySpacer,
            historyHint,
        ])

        listScrollView.borderType = .noBorder
        listScrollView.drawsBackground = false
        listScrollView.hasVerticalScroller = true
        listScrollView.autohidesScrollers = true
        listScrollView.documentView = listDocumentView
        listScrollView.heightAnchor.constraint(equalToConstant: 178).isActive = true

        let rootStack = NSStackView(views: [
            titleRow,
            subtitle,
            editorScroll,
            editorFooter,
            statusLabel,
            divider,
            historyRow,
            listScrollView,
        ])
        rootStack.orientation = .vertical
        rootStack.alignment = .leading
        rootStack.spacing = 9
        rootStack.setCustomSpacing(4, after: titleRow)
        rootStack.setCustomSpacing(6, after: editorScroll)
        rootStack.setCustomSpacing(7, after: editorFooter)
        rootStack.setCustomSpacing(10, after: divider)
        rootStack.setCustomSpacing(6, after: historyRow)
        rootStack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(rootStack)

        let fullWidthViews = [
            titleRow,
            subtitle,
            editorScroll,
            editorFooter,
            statusLabel,
            divider,
            historyRow,
            listScrollView,
        ]
        NSLayoutConstraint.activate(
            [
                rootStack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
                rootStack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),
                rootStack.topAnchor.constraint(equalTo: view.topAnchor, constant: 15),
                rootStack.bottomAnchor.constraint(lessThanOrEqualTo: view.bottomAnchor, constant: -15),
            ] + fullWidthViews.map {
                $0.widthAnchor.constraint(equalTo: rootStack.widthAnchor)
            }
        )
        renderList()
    }

    private func renderList() {
        listDocumentView.removeAllSubviews()
        if loading, prompts.isEmpty {
            let label = emptyLabel("Loading your prompt library…")
            listDocumentView.addSubview(label)
            layoutDocument(height: 178)
            label.frame = NSRect(x: 12, y: 68, width: 304, height: 42)
            return
        }
        guard !prompts.isEmpty else {
            let label = emptyLabel(
                "No saved prompts yet. Paste one above and it will also appear in Continue."
            )
            listDocumentView.addSubview(label)
            layoutDocument(height: 178)
            label.frame = NSRect(x: 18, y: 55, width: 292, height: 68)
            return
        }

        let rowHeight: CGFloat = 56
        let spacing: CGFloat = 7
        let height = CGFloat(prompts.count) * rowHeight
            + CGFloat(max(0, prompts.count - 1)) * spacing
        layoutDocument(height: max(height, 178))
        for (index, prompt) in prompts.enumerated() {
            let row = PromptRowButton(
                prompt: prompt,
                selected: selectedIDs.contains(prompt.id)
            )
            row.onPress = { [weak self] value in
                self?.onSelect?(value)
            }
            row.frame = NSRect(
                x: 0,
                y: CGFloat(index) * (rowHeight + spacing),
                width: 328,
                height: rowHeight
            )
            listDocumentView.addSubview(row)
        }
    }

    private func layoutDocument(height: CGFloat) {
        listDocumentView.frame = NSRect(x: 0, y: 0, width: 328, height: height)
    }

    private func updateSelectionLabel() {
        if selectedIDs.isEmpty {
            selectionLabel.stringValue = "None selected"
            selectionLabel.textColor = NSColor(calibratedWhite: 0.74, alpha: 1)
        } else {
            let noun = selectedIDs.count == 1 ? "prompt" : "prompts"
            selectionLabel.stringValue = "\(selectedIDs.count) \(noun) armed"
            selectionLabel.textColor = NSColor(
                calibratedRed: 0.76,
                green: 1,
                blue: 0.36,
                alpha: 1
            )
        }
    }

    private var hasVisiblePrompt: Bool {
        !promptTextView.string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    @objc private func savePressed() {
        let content = promptTextView.string
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { return }
        onSave?(content)
    }

    private func horizontalStack(_ views: [NSView]) -> NSStackView {
        let stack = NSStackView(views: views)
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 7
        return stack
    }

    private func emptyLabel(_ value: String) -> NSTextField {
        let label = NSTextField(wrappingLabelWithString: value)
        label.font = .systemFont(ofSize: 11.5, weight: .medium)
        label.textColor = NSColor(calibratedWhite: 0.52, alpha: 1)
        label.alignment = .center
        return label
    }
}

private final class PromptListDocumentView: NSView {
    override var isFlipped: Bool { true }

    func removeAllSubviews() {
        subviews.forEach { $0.removeFromSuperview() }
    }
}

@MainActor
private final class PromptRowButton: NSButton {
    let prompt: PromptSnippet
    let selected: Bool
    var onPress: ((PromptSnippet) -> Void)?

    init(prompt: PromptSnippet, selected: Bool) {
        self.prompt = prompt
        self.selected = selected
        super.init(frame: .zero)
        title = ""
        isBordered = false
        focusRingType = .none
        target = self
        action = #selector(pressed)
        toolTip = prompt.content
        setAccessibilityRole(.button)
        setAccessibilityLabel(prompt.content)
        setAccessibilityValue(selected ? "Selected" : "Not selected")
        setAccessibilityHelp(
            selected
                ? "Remove this prompt from prompt mode."
                : "Add this prompt to prompt mode."
        )
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }

    override func draw(_ dirtyRect: NSRect) {
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let background = NSBezierPath(roundedRect: rect, xRadius: 11, yRadius: 11)
        let green = NSColor(
            calibratedRed: 0.76,
            green: 1,
            blue: 0.36,
            alpha: 1
        )
        (selected
            ? green.withAlphaComponent(0.13)
            : NSColor(calibratedWhite: 1, alpha: isHighlighted ? 0.095 : 0.052)
        ).setFill()
        background.fill()
        (selected
            ? green.withAlphaComponent(0.72)
            : NSColor(calibratedWhite: 1, alpha: isHighlighted ? 0.24 : 0.11)
        ).setStroke()
        background.lineWidth = 1
        background.stroke()

        let selectorRect = NSRect(x: 12, y: bounds.midY - 8, width: 16, height: 16)
        let selector = NSBezierPath(ovalIn: selectorRect)
        if selected {
            green.setFill()
            selector.fill()
            let check = NSBezierPath()
            check.move(to: NSPoint(x: 16, y: bounds.midY))
            check.line(to: NSPoint(x: 19, y: bounds.midY + 3))
            check.line(to: NSPoint(x: 24, y: bounds.midY - 3))
            check.lineWidth = 1.6
            check.lineCapStyle = .round
            check.lineJoinStyle = .round
            NSColor.black.setStroke()
            check.stroke()
        } else {
            NSColor(calibratedWhite: 1, alpha: 0.34).setStroke()
            selector.lineWidth = 1.2
            selector.stroke()
        }

        let title = prompt.content
            .split(separator: "\n", omittingEmptySubsequences: true)
            .first
            .map(String.init) ?? prompt.content
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byTruncatingTail
        let titleAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11.5, weight: .semibold),
            .foregroundColor: NSColor(calibratedWhite: 0.93, alpha: 1),
            .paragraphStyle: paragraph,
        ]
        (title as NSString).draw(
            in: NSRect(x: 38, y: 11, width: 222, height: 17),
            withAttributes: titleAttributes
        )

        let meta = prompt.useCount == 0
            ? "Never used"
            : "Used \(prompt.useCount)×"
        let metaAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 9.2, weight: .medium),
            .foregroundColor: selected
                ? green.withAlphaComponent(0.9)
                : NSColor(calibratedWhite: 0.45, alpha: 1),
        ]
        (meta as NSString).draw(
            in: NSRect(x: 38, y: 32, width: 128, height: 14),
            withAttributes: metaAttributes
        )

        let actionText = selected ? "REMOVE" : "SELECT"
        let actionAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 8.5, weight: .heavy),
            .foregroundColor: selected
                ? green
                : NSColor(calibratedWhite: 0.56, alpha: 1),
        ]
        let actionSize = actionText.size(withAttributes: actionAttributes)
        actionText.draw(
            at: NSPoint(x: 314 - actionSize.width, y: 20),
            withAttributes: actionAttributes
        )
    }

    @objc private func pressed() {
        onPress?(prompt)
    }
}
