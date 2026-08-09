import {
  ArrowRight,
  ChevronRight,
  Loader2,
  LockKeyhole,
  Radio,
  ShieldAlert,
} from "lucide-react";

import {
  HarnessArtwork,
  HARNESS_META,
  harnessMeta,
} from "./HarnessBrand";

const HARNESS_FAN_POSITIONS = ["left", "center", "right"];
const HARNESS_FAN_ROTATIONS = [-7, 0, 7];
const HARNESS_FAN_Z_INDEX = [10, 20, 10];
const CONTINUATION_ARTWORK_GOLD = "#D4AF37";


function HarnessCardFrame({
  as: Root = "button",
  type,
  children,
  className = "",
  artworkClassName = "",
  artworkColor = "",
  artworkContainerClassName = "",
  accentActive = false,
  monochrome = false,
  surface = "light",
  style,
  ...rootProps
}) {
  const meta = harnessMeta(type);
  const accent = monochrome ? "#9a9a92" : meta.accent;
  const accentSoft = monochrome ? "rgba(154,154,146,0.11)" : meta.accentSoft;
  const glow = monochrome ? "rgba(255,255,255,0.08)" : meta.glow;
  const surfaceClass = surface === "dark"
    ? "bg-[#171715] text-white"
    : "bg-[#fbfbf6] dark:bg-[#141411]";
  const buttonProps = Root === "button" ? { type: "button" } : {};
  const focusClass = Root === "button"
    ? "focus-visible:ring-2 focus-visible:ring-offset-4 focus-visible:ring-offset-[#f7f7f2] dark:focus-visible:ring-offset-[#0d0d0b]"
    : "focus-within:ring-2 focus-within:ring-offset-4 focus-within:ring-offset-[#f7f7f2] dark:focus-within:ring-offset-[#171713]";
  return (
    <Root
      {...buttonProps}
      data-harness={type}
      data-monochrome={monochrome ? "true" : "false"}
      className={`group relative overflow-hidden border text-left outline-none transition-[transform,border-color,box-shadow,background-color] duration-500 ease-out motion-reduce:transition-none ${focusClass} ${surfaceClass} ${className}`}
      style={{ "--tw-ring-color": accent, ...style }}
      {...rootProps}
    >
      <span
        aria-hidden="true"
        className="absolute inset-0"
        style={{
          background: `linear-gradient(150deg, ${accentSoft} 0%, transparent 48%), radial-gradient(circle at 92% 8%, ${glow}, transparent 46%)`,
        }}
      />
      <span
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-1 origin-left scale-x-50 transition-transform duration-500 motion-reduce:transition-none group-hover:scale-x-100 group-focus-visible:scale-x-100 group-focus-within:scale-x-100"
        style={{ backgroundColor: accent, transform: accentActive ? "scaleX(1)" : undefined }}
      />
      <span
        aria-hidden="true"
        className={`absolute origin-center transition-all duration-700 motion-reduce:transition-none motion-reduce:transform-none group-hover:-translate-x-2 group-hover:scale-110 group-focus-visible:-translate-x-2 group-focus-visible:scale-110 group-focus-within:-translate-x-2 group-focus-within:scale-110 ${
          artworkColor
            ? "opacity-[0.38] group-hover:opacity-[0.54] group-focus-visible:opacity-[0.54] group-focus-within:opacity-[0.54]"
            : "opacity-[0.16] group-hover:opacity-[0.24] group-focus-visible:opacity-[0.24] group-focus-within:opacity-[0.24]"
        } ${artworkContainerClassName}`}
      >
        <HarnessArtwork
          type={type}
          className={artworkClassName}
          monochrome={monochrome}
          color={artworkColor}
        />
      </span>
      {children}
    </Root>
  );
}


export function HarnessArchiveCard({
  item,
  index,
  hovered,
  selected,
  translateX,
  translateY,
  onHover,
  onSelect,
}) {
  const ready = item.adapter_state === "ready";
  const meta = HARNESS_META[item.connector_type] || harnessMeta(item.connector_type);
  const active = hovered || selected;
  const baseRotation = HARNESS_FAN_ROTATIONS[index] || 0;
  const cardNumber = String(index + 1).padStart(2, "0");
  return (
    <HarnessCardFrame
      type={item.connector_type}
      data-fan-position={HARNESS_FAN_POSITIONS[index] || "center"}
      aria-label={`Open ${item.name} sessions`}
      aria-pressed={selected}
      data-hovered={hovered ? "true" : "false"}
      onMouseEnter={onHover}
      onFocus={onHover}
      onClick={onSelect}
      accentActive={selected}
      className={`daemonstate-harness-fan-card aspect-[2/3] w-[190px] shrink-0 snap-center snap-always rounded-[26px] sm:w-[260px] sm:rounded-[32px] lg:w-[280px] ${selected ? "border-transparent" : "border-[#cecec3] dark:border-[#3a3a33]"}`}
      artworkContainerClassName="-right-[19%] top-[10%] h-[53%] w-[86%]"
      style={{
        zIndex: active ? 40 : HARNESS_FAN_Z_INDEX[index] || 10,
        "--daemonstate-card-x": `${translateX}px`,
        "--daemonstate-card-y": `${translateY}px`,
        "--daemonstate-card-rotation": `${active ? 0 : baseRotation}deg`,
        "--daemonstate-card-scale": active ? 1.045 : 1,
        borderColor: active ? meta.accent : undefined,
        boxShadow: active
          ? `0 28px 70px ${meta.glow}, 0 16px 34px rgba(23,23,19,0.18)`
          : "0 16px 34px rgba(23,23,19,0.12)",
        transitionDelay: hovered ? "0ms" : `${index * 35}ms`,
      }}
    >
      <span className="absolute inset-x-0 top-0 flex items-start justify-between px-4 pt-4 sm:px-5 sm:pt-5">
        <span>
          <span className="block font-mono text-lg font-black leading-none sm:text-2xl" style={{ color: meta.accent }}>{cardNumber}</span>
          <span className="mt-1 block text-[7px] font-black uppercase tracking-[0.18em] text-[#85857c] sm:text-[8px]">{item.company}</span>
        </span>
        <span className={`inline-flex items-center gap-1 rounded-full border border-[#d5d5cb] bg-white/65 px-2 py-1 text-[7px] font-black uppercase tracking-[0.14em] backdrop-blur-md dark:border-[#41413a] dark:bg-black/20 sm:text-[8px] ${ready ? "text-emerald-700 dark:text-emerald-300" : "text-[#85857c]"}`}>
          <Radio className="h-2.5 w-2.5" /> {ready ? "Live" : "Offline"}
        </span>
      </span>

      <span className="absolute inset-x-0 bottom-0 flex min-h-[49%] flex-col justify-end bg-gradient-to-t from-[#fbfbf6] via-[#fbfbf6]/95 to-[#fbfbf6]/35 px-4 pb-4 pt-10 dark:from-[#141411] dark:via-[#141411]/95 dark:to-[#141411]/30 sm:px-5 sm:pb-5">
        <span className="block text-lg font-black leading-tight tracking-[-0.035em] sm:text-2xl">{item.name}</span>
        <span className="mt-2 hidden text-[10px] font-semibold leading-[1.55] text-[#68685f] dark:text-[#aaa9a0] sm:line-clamp-2">{item.description}</span>
        <span className="mt-3 grid grid-cols-2 gap-2 border-t border-[#d8d8cf]/80 pt-3 dark:border-[#3a3a34] sm:mt-4">
          <span>
            <span className="block text-base font-black leading-none sm:text-xl">{item.session_count}</span>
            <span className="mt-1 block text-[7px] font-black uppercase tracking-[0.13em] text-[#85857c] sm:text-[8px]">Sessions</span>
          </span>
          <span>
            <span className="block text-base font-black leading-none sm:text-xl">{item.topic_count}</span>
            <span className="mt-1 block text-[7px] font-black uppercase tracking-[0.13em] text-[#85857c] sm:text-[8px]">Topics</span>
          </span>
        </span>
        <span className="mt-3 flex items-center justify-between text-[8px] font-black uppercase tracking-[0.14em] sm:mt-4 sm:text-[9px]" style={{ color: meta.accent }}>
          Open archive
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-current/30 bg-white/60 transition-transform duration-500 group-hover:translate-x-1 dark:bg-black/15 sm:h-8 sm:w-8">
            <ChevronRight className="h-3.5 w-3.5" />
          </span>
        </span>
      </span>

      <span aria-hidden="true" className="absolute bottom-3 right-3 rotate-180 font-mono text-sm font-black opacity-20 sm:bottom-4 sm:right-4 sm:text-base" style={{ color: meta.accent }}>
        {cardNumber}
      </span>
    </HarnessCardFrame>
  );
}


export function HarnessContinuationCard({
  provider,
  index = 0,
  hovered = false,
  translateX = 0,
  translateY = 0,
  pending = false,
  handoffRequested = false,
  workflowPending = false,
  taskReady = true,
  taskPending = false,
  taskRequirement = "",
  contextReady = true,
  compactionCount = 0,
  minimumCompactions = 2,
  sessionOrdinal = null,
  sessionTitle = "",
  onHover,
  onContinue,
}) {
  const type = provider.provider;
  const meta = HARNESS_META[type] || harnessMeta(type);
  const status = String(provider.status || "").trim().toLowerCase();
  const reportedReady = provider.ready === true;
  const ready = reportedReady;
  const checking = status === "checking";
  const taskBlocked = ready && !taskReady && !taskPending;
  const contextBlocked = !contextReady;
  const disabled = !ready || !taskReady || contextBlocked || workflowPending;
  const statusLabel = continuationProviderStatusLabel({
    pending,
    ready,
    status,
    code: provider.code,
  });
  const accountAttention = (
    status === "authentication_required"
    || status === "rate_limited"
    || provider.code === "desktop_account_sign_in_required"
    || provider.code === "desktop_account_rate_limited"
  );
  const statusTone = pending || (ready && !accountAttention)
    ? "border-emerald-800/25 bg-emerald-800/10 text-emerald-950 dark:border-emerald-200/20 dark:bg-emerald-200/10 dark:text-emerald-100"
    : accountAttention
      ? "border-amber-700/20 bg-amber-600/10 text-amber-950 dark:border-amber-200/20 dark:bg-amber-200/10 dark:text-amber-100"
    : checking
      ? "border-white/15 bg-white/[0.06] text-white/70"
      : "border-amber-200/20 bg-amber-200/10 text-amber-100";
  const message = provider.message || (
    ready
      ? `Request a visible ${meta.name} desktop composer. Nothing is submitted.`
      : `${meta.name} Desktop readiness could not be confirmed.`
  );
  const taskRequirementMessage = String(taskRequirement || "").trim()
    || "Choose a linked task before starting this provider.";
  const normalizedMinimumCompactions = Math.max(
    1,
    Number.isFinite(Number(minimumCompactions))
      ? Math.floor(Number(minimumCompactions))
      : 2,
  );
  const normalizedCompactionCount = Math.max(
    0,
    Number.isFinite(Number(compactionCount))
      ? Math.floor(Number(compactionCount))
      : 0,
  );
  const compactionRequirementLabel = (
    `${Math.min(normalizedCompactionCount, normalizedMinimumCompactions)}`
    + `/${normalizedMinimumCompactions} compactions`
  );
  const active = hovered || pending || handoffRequested;
  const baseRotation = HARNESS_FAN_ROTATIONS[index] || 0;
  const cardNumber = String(index + 1).padStart(2, "0");
  const accent = ready ? meta.accent : "#a0a098";
  const handleContinue = () => {
    onContinue(type);
  };

  return (
    <HarnessCardFrame
      as="article"
      type={type}
      data-fan-position={HARNESS_FAN_POSITIONS[index] || "center"}
      data-provider-ready={ready ? "true" : "false"}
      data-task-ready={taskReady ? "true" : "false"}
      data-context-ready={contextReady ? "true" : "false"}
      data-compaction-count={normalizedCompactionCount}
      data-selected-session-ordinal={sessionOrdinal || undefined}
      data-provider-pending={pending ? "true" : "false"}
      data-desktop-open-requested={handoffRequested ? "true" : "false"}
      aria-disabled={disabled ? "true" : undefined}
      aria-busy={pending ? "true" : "false"}
      onMouseEnter={onHover}
      onFocusCapture={onHover}
      monochrome={!ready}
      accentActive={pending || handoffRequested}
      artworkColor={ready ? CONTINUATION_ARTWORK_GOLD : ""}
      className={`daemonstate-harness-fan-card daemonstate-provider-card h-[23rem] min-h-[23rem] w-[calc(100vw-4rem)] max-w-[280px] shrink-0 snap-center snap-always rounded-[26px] sm:h-[24rem] sm:min-h-[24rem] sm:w-[280px] sm:rounded-[32px] ${ready ? "border-[#cecec3] text-[#171713] dark:border-[#3a3a33] dark:text-white" : "border-[#bcbcb3] text-[#34342f] dark:border-[#77776f] dark:text-white"} ${workflowPending ? "cursor-wait" : disabled ? "cursor-not-allowed" : ""} ${contextBlocked && ready ? "saturate-[0.72]" : ""}`}
      artworkContainerClassName="-right-[16%] top-[7%] h-[46%] w-[78%]"
      style={{
        zIndex: active ? 40 : HARNESS_FAN_Z_INDEX[index] || 10,
        "--daemonstate-card-x": `${translateX}px`,
        "--daemonstate-card-y": `${translateY}px`,
        "--daemonstate-card-rotation": `${active ? 0 : baseRotation}deg`,
        "--daemonstate-card-scale": active ? 1.035 : 1,
        borderColor: active ? accent : undefined,
        boxShadow: active
          ? `0 28px 70px ${ready ? meta.glow : "rgba(23,23,19,0.10)"}, 0 16px 34px rgba(0,0,0,0.18)`
          : "0 16px 34px rgba(0,0,0,0.24)",
        transitionDelay: hovered ? "0ms" : `${index * 35}ms`,
      }}
    >
      <button
        type="button"
        aria-label={`Open desktop handoff in ${meta.name}`}
        aria-describedby={`continuation-provider-${type}-detail`}
        aria-busy={pending ? "true" : "false"}
        data-provider-ready={ready ? "true" : "false"}
        data-task-ready={taskReady ? "true" : "false"}
        data-context-ready={contextReady ? "true" : "false"}
        data-compaction-count={normalizedCompactionCount}
        data-provider-pending={pending ? "true" : "false"}
        data-desktop-open-requested={handoffRequested ? "true" : "false"}
        data-monochrome={!ready ? "true" : "false"}
        disabled={disabled}
        onClick={handleContinue}
        className={`absolute inset-0 z-10 block w-full text-left outline-none focus-visible:ring-2 focus-visible:ring-inset disabled:pointer-events-none disabled:hover:translate-y-0 ${workflowPending ? "disabled:cursor-wait" : "disabled:cursor-not-allowed"}`}
        style={{ "--tw-ring-color": accent }}
      >
        <span className="absolute inset-x-0 top-0 flex items-start justify-between px-4 pt-4 sm:px-5 sm:pt-5">
          <span>
            <span className="block font-mono text-lg font-black leading-none sm:text-2xl" style={{ color: accent }}>
              {cardNumber}
            </span>
            <span className={`mt-1 block text-xs font-black uppercase tracking-[0.16em] ${ready ? "text-[#68685f] dark:text-[#b8b8af]" : "text-[#68685f] dark:text-white/65"}`}>
              {meta.company}
            </span>
          </span>
          <span className="flex flex-col items-end gap-1.5">
            {sessionOrdinal ? (
              <span
                title={sessionTitle ? `Selected session ${sessionOrdinal}: ${sessionTitle}` : `Selected session ${sessionOrdinal}`}
                className="inline-flex min-h-7 items-center gap-1.5 rounded-full border border-[#171713]/15 bg-white/80 px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.08em] text-[#171713] shadow-[0_5px_16px_rgba(23,23,19,0.10)] backdrop-blur-md dark:border-white/15 dark:bg-black/35 dark:text-white"
              >
                <span className="grid h-4 min-w-4 place-items-center rounded-full bg-[#171713] px-0.5 font-mono text-[8px] text-white dark:bg-[#d9ff68] dark:text-[#171713]">
                  {sessionOrdinal}
                </span>
                Session
              </span>
            ) : null}
            {contextBlocked ? (
              <span
                title={`${normalizedCompactionCount} of ${normalizedMinimumCompactions} provider compactions detected`}
                className="inline-flex min-h-7 items-center gap-1.5 rounded-full bg-[#d9ff68] px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.08em] text-[#171713] shadow-[0_5px_16px_rgba(217,255,104,0.22)]"
              >
                <LockKeyhole className="h-3 w-3" aria-hidden="true" />
                {compactionRequirementLabel}
              </span>
            ) : null}
            <span className={`inline-flex min-h-7 items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-black uppercase tracking-[0.12em] backdrop-blur-md sm:text-xs ${ready ? statusTone : "border-[#c8c8bf] bg-white/65 text-[#5f5f57] dark:border-white/20 dark:bg-white/[0.07] dark:text-white/75"}`}>
              {pending || checking
                ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                : ready && !accountAttention
                  ? <Radio className="h-3 w-3" aria-hidden="true" />
                  : <ShieldAlert className="h-3 w-3" aria-hidden="true" />}
              {statusLabel}
            </span>
          </span>
        </span>

        <span className={`absolute inset-x-0 bottom-0 flex min-h-[72%] flex-col justify-end px-4 pb-4 pt-8 sm:px-5 ${ready ? "bg-gradient-to-t from-[#fbfbf6] via-[#fbfbf6]/95 to-[#fbfbf6]/35 dark:from-[#141411] dark:via-[#141411]/95 dark:to-[#141411]/30" : "bg-gradient-to-t from-[#fbfbf6] via-[#fbfbf6]/95 to-[#fbfbf6]/35 dark:from-[#171715] dark:via-[#171715]/95 dark:to-[#171715]/35"}`}>
          <span className="block text-lg font-black leading-tight tracking-[-0.035em] sm:text-2xl">
            {meta.name}
          </span>
          <span
            id={`continuation-provider-${type}-detail`}
            className={`mt-1.5 block text-xs font-semibold leading-5 ${ready ? "text-[#68685f] dark:text-[#aaa9a0]" : "text-[#68685f] dark:text-white/75"}`}
          >
            <span className={contextBlocked ? "line-clamp-1" : "line-clamp-2"}>{message}</span>
            {taskBlocked ? (
              <span className="mt-1.5 line-clamp-2 rounded-lg border border-amber-700/20 bg-amber-600/10 px-2 py-1.5 text-amber-950 dark:border-amber-200/20 dark:bg-amber-200/10 dark:text-amber-100">
                <strong>Task required:</strong> {taskRequirementMessage}
              </span>
            ) : null}
          </span>
          {!ready && provider.action ? (
            <span className="mt-1.5 line-clamp-2 text-xs font-semibold leading-5 text-[#77776e] dark:text-white/60">
              Next: {provider.action}
            </span>
          ) : null}
          <span
            className={`mt-3 flex min-h-11 items-center justify-between border-t pt-2.5 text-xs font-black uppercase tracking-[0.12em] ${
              taskBlocked
                ? "border-amber-800/20 text-amber-900 dark:border-amber-200/20 dark:text-amber-100"
                : ready
                  ? "border-[#d8d8cf]/80 dark:border-[#3a3a34]"
                  : "border-[#d8d8cf]/80 text-[#68685f] dark:border-white/15 dark:text-white/55"
            }`}
            style={{ color: ready && taskReady ? accent : undefined }}
          >
            {pending
              ? `Requesting ${meta.name}…`
              : !ready
                ? "Not runnable"
                : !taskReady
                  ? (taskPending ? "Loading session…" : "Task required")
                  : contextBlocked
                    ? "Session Context locked"
                  : handoffRequested
                    ? "Request again"
                  : workflowPending
                    ? "Continuation busy"
                    : "Open desktop"}
            {pending
              ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              : ready && taskReady && contextReady && !workflowPending
                ? <ArrowRight className="h-4 w-4 transition-transform duration-500 motion-reduce:transition-none group-hover:translate-x-1" aria-hidden="true" />
                : contextBlocked
                  ? <LockKeyhole className="h-4 w-4" aria-hidden="true" />
                  : <ShieldAlert className="h-4 w-4" aria-hidden="true" />}
          </span>
        </span>

        <span aria-hidden="true" className="absolute bottom-3 right-3 rotate-180 font-mono text-sm font-black opacity-20 sm:bottom-4 sm:right-4 sm:text-base" style={{ color: accent }}>
          {cardNumber}
        </span>
      </button>
    </HarnessCardFrame>
  );
}


function continuationProviderStatusLabel({
  pending,
  ready,
  status,
  code,
}) {
  if (pending) return "Requesting";
  if (status === "checking") return "Checking";
  if (status === "staging_unsupported") return "No handoff";
  if (code === "desktop_account_access_verified") return "Account ready";
  if (code === "desktop_account_rate_limited") return "Limit reached";
  if (code === "desktop_account_sign_in_required") return "Sign in";
  if (status === "authentication_required") return "Sign in";
  if (status === "access_required") return "Access needed";
  if (
    status === "access_unverified"
    || code === "desktop_account_access_unverified"
  ) {
    return "Access unverified";
  }
  if (status === "configuration_required") return "Setup needed";
  if (ready) return "Ready";
  if (code === "desktop_app_missing") return "Desktop missing";
  if (
    status === "provider_cli_not_found"
    || code === "provider_cli_not_found"
  ) {
    return "Not installed";
  }
  return "Unavailable";
}
