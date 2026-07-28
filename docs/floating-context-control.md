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
| Single click | Prepares and verifies the selected context, copies it, and pastes it into the editable field that was focused when the gesture began. It never presses Return or submits the prompt. |
| Triple click | Switches between Session Context and Workspace Context. It does not copy or paste. Session Context is the default on every launch. |
| Double click | Resolves as one single-click action, never two insertions. |
| Right click | Provides an accessible alternative for scope and workspace selection, opens the dashboard, or quits the companion. |
| Drag | Moves the logo and remembers its position. |

The normal logo is Session Context. A lime halo indicates Workspace Context.
Transient animation and a small status bubble report preparation, success,
copy-only fallback, or failure; the bubble disappears when idle.

“Workspace Context” is the compact-control label for the existing
`continuation_staging_context.v1` Project Context. The control inserts the
quality-gated, workspace-wide durable parent foundation rather than a
prompt-ranked projection or an unfiltered workspace dump. Session-only
failures, rejected attempts, and transient blockers are not promoted.
Mechanically verified, human-confirmed, and corroborated durable facts may
appear; provisional and superseded/conflicting facts may not.

## Show or hide it from Continue

The Continue page has a **Floating button** switch beside the activity status:

- Turn it **On** to launch the native companion for the currently selected
  workspace, or to show it again if it is already running in the background.
- Turn it **Off** to remove the logo from the screen. The lightweight companion
  stays running so the same switch can restore it immediately.

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

Then return to the focused chat editor and click the logo again to paste.

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
- Workspace insertion recompiles Project Context from all current evidence in
  the selected workspace, independent of the current lead, and verifies its
  core-section completeness, evidence provenance, repository freshness,
  schema, scope, `copy_ready` flag, and SHA-256.
- The control never silently falls back from Session Context to Workspace
  Context or vice versa.
- Verified content is written to the clipboard before insertion. If the
  original focused editor disappears, the content remains copied and the
  control reports that it was not pasted.
- Before Command-V, the control rechecks the exact editor, its owning process,
  and the clipboard change count and contents. The key events are delivered
  only to that captured process; a focus or clipboard race aborts insertion.
- Secure, disabled, read-only, and non-text accessibility targets are rejected.
- Only Command-V is synthesized. No Enter, Return, or submit event is sent.
- Linked-session refresh reports the exact successfully refreshed identities,
  so the companion can prove the selected session was included even when a
  mature workspace reaches the bounded refresh batch size.

The browser dashboard keeps its existing boundary: browser buttons copy or
stage context but do not perform operating-system-level paste. System-wide
insertion belongs only to this explicitly launched native companion.
