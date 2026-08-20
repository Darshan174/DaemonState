# Floating Context Control for macOS

The floating control is a small native companion for the local DaemonState
service. At rest it shows only the DaemonState logo above other apps. It
uses the existing fail-closed Session Context and Project Context pipelines;
it does not create a third context format. Project Context is the durable
evidence-backed parent foundation for the workspace, and Session Context is the latest
individual task child under it. The switch selects one of these separate copy
artifacts; Session Context does not embed the Project Context payload.

## Interaction

| Gesture | Behavior |
|---|---|
| Single click | Prepares and verifies the selected context, copies it, and pastes it into the verified editor associated with the gesture. For the attested OpenCode 1.18.18 build, it uses the focused window's one visible, empty, normal chat composer and does not request or claim a new session or project. It never presses Return or submits the prompt. |
| Hover, then numbered session click | Unfolds the selected sessions around the control and immediately prepares and pastes that exact Session Context into the focused editor. No second logo click is required. |
| Triple click | Switches between Session Context and Workspace Context and immediately prepares and pastes the newly chosen context. Session Context is the default on every launch. |
| Double click | Resolves as one single-click action, never two insertions. |
| Right click | Provides direct **Paste Session Context**, **Paste Workspace Context**, and exact-session actions, plus workspace selection, recent error details, dashboard access, and Quit. |
| Drag | Moves the logo and remembers its position. |

The normal logo is Session Context. A lime halo indicates Workspace Context.
Transient animation and a small status bubble report preparation, success,
copy-only fallback, or failure; the bubble disappears when idle.

## Error diagnostics

The control retains the full text of the 20 most recent runtime failures in
memory. Right-click the logo and choose **Copy Recent Error Details** to copy
the newest-first diagnostic history, including the operation that failed and
its timestamp. The status bubble stays concise, but preserves a service request
ID when one is available.

OpenCode insertion also emits one content-free terminal event to the macOS
unified log. It records only a fixed result phase such as `sentinel_readback`
or `final_exact_readback`; it never records context, AX values, clipboard data,
repository paths, or session data.

Every non-successful `POST /api/context/prepare` compilation is also recorded
by the service with its error class, context mode, workspace identity, error
code, and the same request ID returned in the response. Invalid client input
is reported as HTTP 422. Repository-observation or compiler invariant failures
are server errors and are never mislabeled as invalid input.

For Workspace Context, the control calls `POST /api/context/prepare` in
`project_snapshot` mode and validates the returned `workspace_foundation.v2`
artifact. It inserts that quality-gated, workspace-wide durable parent rather
than a prompt-ranked projection, the task-oriented
`continuation_staging_context.v1` rendering, or an unfiltered workspace dump.
Session-only failures, rejected attempts, and transient blockers are not
promoted. Mechanically verified, human-confirmed, and corroborated durable
facts may appear; provisional and superseded/conflicting facts may not.

## Show or hide it from Continue

The Continue page has a **Floating button** switch beside the activity status:

- Turn it **On** to launch the native companion for the currently selected
  workspace, or to show it again if it is already running in the background.
- Turn it **Off** to remove the logo from the screen. The lightweight companion
  stays running so the same switch can restore it immediately.
- Session Contexts selected in Execute are durable workspace intent. While the
  companion is visible, Execute and Continue reconcile its numbered session
  blades to that saved selection. Direct navigation or a page reload must not
  clear them; removing the saved selections does.

The switch reports the native companion's confirmed state; it does not pretend
that the logo changed before macOS acknowledges the request. It is available
only from the local dashboard on macOS. Quitting the companion completely
remains available from the logo's right-click menu.

If the running logo belongs to a different workspace, the switch reads
**Other project** instead of **On**. Turning it on from the current Continue
page safely retargets the companion before reporting **On**.

## Run locally

The companion requires macOS 13 or newer and a Swift 5.10-or-newer command-line
toolchain.

Start DaemonState on `127.0.0.1:8000`, then run:

```bash
bash scripts/overlay.sh
```

On the first single click without permission, the control still copies the
verified context and asks for macOS Accessibility access. Enable the terminal
or packaged DaemonState control in:

`System Settings → Privacy & Security → Accessibility`

Then return to the focused chat editor and choose the context again to paste.

When exactly one project workspace is available, it is selected automatically.
With multiple workspaces, right-click the logo and choose one. A workspace can
also be pinned at launch:

```bash
bash scripts/overlay.sh --workspace-id <workspace-uuid>
```

If multiple sessions are still plausible inside that workspace, select the
exact active session in Library first. The companion refuses to guess which
conversation should be exposed to the focused app.

The API base defaults to `http://127.0.0.1:8000/api`. Override it with:

```bash
bash scripts/overlay.sh --api-url http://127.0.0.1:8000/api
```

The same settings can be supplied as `DAEMONSTATE_WORKSPACE_ID` and
`DAEMONSTATE_API_URL`.

## Safety boundary

- Session insertion first refreshes linked local session data, resolves the
  single active project-assigned session, captures its current immutable tip
  when needed, and verifies the exact provider, session, checkpoint, boundary,
  `copy_ready` flag, and SHA-256. Missing or ambiguous session identity fails
  closed.
- The central Session Context action labels its handoff as `current_active`
  only after that refresh and identity confirmation. The service independently
  verifies that it is the workspace's newest scoped root session and that the
  checkpoint boundary exactly matches both the direct provider transcript tip
  and the latest authorized persisted event. Only that exact current tip may
  bypass the historical two-compaction maturity gate. Numbered sessions and
  other explicitly selected checkpoints retain the gate.
- Checkpoint age is presentation metadata, not tip identity. A deliberately
  selected session remains eligible after its boundary is labeled
  `historical` when that boundary still equals the latest observed event and
  the service reports no newer events. `superseded` and unknown boundaries
  continue to fail closed or trigger recapture.
- Workspace insertion recompiles Workspace Context from all current evidence
  in the selected workspace, independent of the current lead, and verifies its
  `project_snapshot` scope, `workspace_foundation.v2` artifact, core-section
  completeness, evidence provenance, repository freshness, copy-ready state,
  rendering digest, semantic digest, and artifact digest.
- The control never silently falls back from Session Context to Workspace
  Context or vice versa.
- Verified content is written to the clipboard before insertion. If the
  original focused editor disappears, the content remains copied and the
  control reports that it was not pasted.
- When OpenCode is frontmost, the gesture captures the exact focused AX window
  together with the PID, bundle identifier, and canonical application path.
  The accessibility object must have role `AXWindow` and be distinct from the
  `AXApplication` root; an Electron app-global fallback is not accepted as
  window authority. DaemonState activates no OpenCode URL and makes no project
  or new-session claim.
- A bounded, role-pruned traversal requires exactly one visible, empty, normal
  OpenCode chat composer in that window. The candidate must own the captured
  window, have a bounded parent chain, expose a finite positive in-window frame,
  and pass an application-scoped center hit test. Terminal, shell, search,
  hidden, stale, nonempty, or duplicate editors fail closed. DaemonState may
  focus only that uniquely attested element, then rechecks the same app, PID,
  window, element, value, and normal-mode identity before every mutation.
- A temporary space/delete handshake and exact full-value readback prove that
  OpenCode synchronized its input state. When the requested context ends in a
  line feed, Chromium may serialize that one typed space immediately before its
  structural final line feed. DaemonState accepts only that exact transient
  value and UTF-16 range, deletes only the U+0020 sentinel, and still requires
  the final value to equal the original context exactly.
- Missing or ambiguous composer identity, app/PID/path/window/focus change,
  clipboard race, incomplete accessibility traversal, or timeout fails closed.
  The native control never guesses a target or sends a process-wide Command-V
  that could race into the terminal. The verified context stays copied for
  manual recovery.
- For providers that use Command-V, the control rechecks the exact editor, its
  owning process, and the clipboard change count and contents. The key events
  are delivered only to that captured process; a focus or clipboard race
  aborts insertion.
- Secure, disabled, read-only, and non-text accessibility targets are rejected.
- No Enter, Return, or submit event is sent. OpenCode's verified insertion
  synthesizes only its temporary space and matching backward delete; generic
  fallback routes synthesize only Command-V.
- Linked-session refresh reports the exact successfully refreshed identities,
  so the companion can prove the selected session was included even when a
  mature workspace reaches the bounded refresh batch size.

The browser dashboard keeps its existing boundary: browser buttons copy or
stage context but do not perform operating-system-level paste. System-wide
insertion belongs only to this explicitly launched native companion.
