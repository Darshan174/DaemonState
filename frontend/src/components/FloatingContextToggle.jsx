import { useId } from "react";

import {
  useDesktopOverlayStatus,
  useSetDesktopOverlayVisibility,
} from "../api/hooks";
import DaemonStateIcon from "./DaemonStateIcon";

export default function FloatingContextToggle({ workspaceId }) {
  const noticeId = useId();
  const statusQuery = useDesktopOverlayStatus(workspaceId);
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
  const requestError = visibilityMutation.error
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
    requestFailed: Boolean(requestError && !status),
    visible,
    visibleForAnotherWorkspace,
  });

  const changeVisibility = () => {
    if (disabled) return;
    visibilityMutation.mutate({
      visible: !visible,
      workspaceId,
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

function overlayStateLabel({
  available,
  loading,
  pending,
  requestFailed,
  visible,
  visibleForAnotherWorkspace,
}) {
  if (pending) return visible ? "Hiding…" : "Showing…";
  if (loading) return "Checking…";
  if (requestFailed || !available) return "Unavailable";
  if (visibleForAnotherWorkspace) return "Other project";
  return visible ? "On" : "Off";
}
