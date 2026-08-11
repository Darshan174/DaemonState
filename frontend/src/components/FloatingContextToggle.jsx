import { useEffect, useId, useRef } from "react";

import {
  useDesktopOverlayStatus,
  useSetDesktopOverlayVisibility,
} from "../api/hooks";
import { HarnessLogo } from "./HarnessBrand";
import DaemonStateIcon from "./DaemonStateIcon";

export default function FloatingContextToggle({
  workspaceId,
  selectedSessions,
  showSessionSummary = true,
}) {
  const noticeId = useId();
  const {
    available,
    loading,
    pending,
    requestedSessions,
    selectedSessionCount,
    status,
    statusQuery,
    syncPending,
    visibilityMutation,
    visible,
    visibleForAnotherWorkspace,
  } = useDesktopOverlaySessionSync({ workspaceId, selectedSessions });
  const mutationRequestedSessions = normalizeOverlaySessions(
    visibilityMutation.variables?.selectedSessions,
  );
  const mutationMatchesCurrentSelection = (
    visibilityMutation.variables?.selectedSessions === undefined
    || requestedSessions === undefined
    || overlaySessionIdentityKey(mutationRequestedSessions)
      === overlaySessionIdentityKey(requestedSessions)
  );
  const requestError = (mutationMatchesCurrentSelection
    ? visibilityMutation.error
    : null)
    || (statusQuery.isError ? statusQuery.error : null);
  const unavailableMessage = (
    !loading
    && status
    && !available
    && String(status.message || "").trim()
  );
  const notice = requestError?.message || unavailableMessage || "";
  const disabled = !workspaceId || loading || pending || !available;
  const stateLabel = overlayStateLabel({
    available,
    loading,
    pending,
    pendingTargetVisible: visibilityMutation.variables?.visible,
    requestFailed: Boolean(requestError && !status),
    syncPending,
    visible,
    visibleForAnotherWorkspace,
  });

  const changeVisibility = () => {
    if (disabled) return;
    visibilityMutation.mutate({
      visible: !visible,
      workspaceId,
      ...(!visible && requestedSessions !== undefined
        ? { selectedSessions: requestedSessions }
        : {}),
    });
  };

  return (
    <div className="flex max-w-full flex-col items-end">
      <button
        type="button"
        role="switch"
        aria-checked={visible}
        aria-busy={pending}
        aria-describedby={notice ? noticeId : undefined}
        aria-label="Floating context control"
        title={
          visible
            ? "Hide floating context control"
            : visibleForAnotherWorkspace
              ? "Use floating context control for this project"
              : "Show floating context control"
        }
        disabled={disabled}
        onClick={changeVisibility}
        className="group inline-flex min-h-11 max-w-full items-center gap-2 rounded-full border border-[#c9c9c0] bg-white/70 px-2.5 py-1.5 text-left text-xs font-semibold text-[#52524b] shadow-[0_7px_22px_rgba(23,23,19,0.05)] backdrop-blur-md transition hover:border-[#9d9d93] hover:bg-white hover:text-[#171713] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#849633]/70 disabled:cursor-not-allowed disabled:opacity-60 dark:border-white/15 dark:bg-white/[0.06] dark:text-[#d0d0c8] dark:shadow-none dark:hover:border-[#d9ff68]/50 dark:hover:bg-white/[0.1] dark:hover:text-white dark:focus-visible:ring-[#d9ff68]/70"
      >
        <DaemonStateIcon size={24} className="shrink-0 transition-transform group-hover:scale-105" />
        <span className="hidden whitespace-nowrap sm:inline">Floating button</span>
        {showSessionSummary && selectedSessionCount ? (
          <span
            aria-label={`${selectedSessionCount} custom session${selectedSessionCount === 1 ? "" : "s"} synced`}
            className="flex -space-x-1.5"
          >
            {requestedSessions.map((session) => (
              <span key={`${session.provider}:${session.session_id}`} className="relative">
                <HarnessLogo
                  type={session.provider}
                  size="small"
                  decorative
                  anthropicFilled={session.provider === "claude"}
                  className="!h-6 !w-6 !rounded-lg"
                />
                <span
                  aria-hidden="true"
                  className="absolute -right-1 -top-1 grid h-3.5 min-w-3.5 place-items-center rounded-full bg-[#171713] px-0.5 font-mono text-[8px] font-black leading-none text-white ring-1 ring-white dark:bg-[#d9ff68] dark:text-[#171713] dark:ring-[#171713]"
                >
                  {session.ordinal}
                </span>
              </span>
            ))}
          </span>
        ) : null}
        <span className="whitespace-nowrap text-[11px] text-[#77776e] dark:text-white/65">{stateLabel}</span>
        <span
          aria-hidden="true"
          className={`relative h-5 w-9 shrink-0 rounded-full border transition-colors ${
            visible
              ? "border-[#8ca332]/70 bg-[#d9ff68]/45 dark:border-[#d9ff68]/70 dark:bg-[#d9ff68]/30"
              : "border-[#b8b8af] bg-[#e6e6df] dark:border-white/20 dark:bg-black/25"
          }`}
        >
          <span
            className={`absolute top-0.5 h-3.5 w-3.5 rounded-full shadow-sm transition-transform ${
              visible
                ? "translate-x-[18px] bg-[#66751f] dark:bg-[#d9ff68]"
                : "translate-x-0.5 bg-[#77776e] dark:bg-[#c5c5bc]"
            }`}
          />
        </span>
      </button>
      {notice ? (
        <p
          id={noticeId}
          role={requestError ? "alert" : "status"}
          className="mt-1 max-w-72 text-right text-[10px] leading-4 text-amber-700 dark:text-amber-200"
        >
          {notice}
        </p>
      ) : null}
    </div>
  );
}


export function useDesktopOverlaySessionSync({
  workspaceId,
  selectedSessions,
  enabled = true,
}) {
  const statusQuery = useDesktopOverlayStatus(workspaceId, { enabled });
  const visibilityMutation = useSetDesktopOverlayVisibility();
  const status = statusQuery.data || null;
  const nativeVisible = status?.visible === true;
  const visible = (
    nativeVisible
    && status?.workspace_id === workspaceId
  );
  const visibleForAnotherWorkspace = nativeVisible && !visible;
  const available = status?.available === true;
  const loading = statusQuery.isLoading && !status;
  const pending = visibilityMutation.isPending;
  const requestedSessions = normalizeOverlaySessions(selectedSessions);
  const selectedSessionCount = requestedSessions?.length || 0;
  const serverSessions = normalizeOverlaySessions(status?.selected_sessions) || [];
  const requestedSessionsKey = requestedSessions === undefined
    ? "preserve"
    : overlaySessionIdentityKey(requestedSessions);
  const serverSessionsKey = overlaySessionIdentityKey(serverSessions);
  const syncAttemptKey = JSON.stringify([
    workspaceId || "",
    requestedSessionsKey,
    serverSessionsKey,
  ]);
  const lastSyncAttemptRef = useRef("");
  const syncPending = Boolean(
    pending
    && visible
    && visibilityMutation.variables?.visible === true
    && Array.isArray(visibilityMutation.variables?.selectedSessions),
  );
  useEffect(() => {
    if (
      !enabled
      || requestedSessions === undefined
      || !visible
      || !available
      || loading
      || pending
      || requestedSessionsKey === serverSessionsKey
    ) {
      if (!visible || requestedSessionsKey === serverSessionsKey) {
        lastSyncAttemptRef.current = "";
      }
      return;
    }
    if (lastSyncAttemptRef.current === syncAttemptKey) return;
    lastSyncAttemptRef.current = syncAttemptKey;
    visibilityMutation.mutate({
      visible: true,
      workspaceId,
      selectedSessions: requestedSessions,
    });
  }, [
    available,
    enabled,
    loading,
    pending,
    requestedSessionsKey,
    serverSessionsKey,
    syncAttemptKey,
    visibilityMutation.mutate,
    visible,
    workspaceId,
  ]);

  return {
    available,
    loading,
    pending,
    requestedSessions,
    selectedSessionCount,
    status,
    statusQuery,
    syncPending,
    visibilityMutation,
    visible,
    visibleForAnotherWorkspace,
  };
}

function normalizeOverlaySessions(value) {
  if (!Array.isArray(value)) return undefined;
  return value.slice(0, 3).map((session, index) => ({
    provider: String(session?.provider || "").trim().toLowerCase(),
    session_id: String(session?.session_id || session?.sessionId || "").trim(),
    title: String(session?.title || "Untitled session").trim() || "Untitled session",
    ordinal: Number.isInteger(Number(session?.ordinal))
      ? Number(session.ordinal)
      : index + 1,
  })).filter((session) => session.provider && session.session_id);
}

function overlaySessionIdentityKey(sessions) {
  return JSON.stringify((sessions || []).map((session) => [
    session.provider,
    session.session_id,
    session.ordinal,
  ]));
}

function overlayStateLabel({
  available,
  loading,
  pending,
  pendingTargetVisible,
  requestFailed,
  syncPending,
  visible,
  visibleForAnotherWorkspace,
}) {
  if (pending) {
    if (syncPending) return "Syncing…";
    return pendingTargetVisible === false ? "Hiding…" : "Showing…";
  }
  if (loading) return "Checking…";
  if (requestFailed || !available) return "Unavailable";
  if (visibleForAnotherWorkspace) return "Other project";
  return visible ? "On" : "Off";
}
