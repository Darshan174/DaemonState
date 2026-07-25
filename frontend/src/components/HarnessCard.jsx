import {
  ArrowRight,
  ChevronRight,
  Loader2,
  Radio,
  ShieldAlert,
} from "lucide-react";

import {
  HarnessArtwork,
  HARNESS_META,
  harnessMeta,
} from "./HarnessBrand";


function HarnessCardFrame({
  type,
  children,
  className = "",
  artworkClassName = "",
  artworkContainerClassName = "",
  accentActive = false,
  surface = "light",
  style,
  ...buttonProps
}) {
  const meta = harnessMeta(type);
  const surfaceClass = surface === "dark"
    ? "bg-white/[0.055] text-white"
    : "bg-[#fbfbf6] dark:bg-[#141411]";
  return (
    <button
      type="button"
      data-harness={type}
      className={`group relative overflow-hidden border text-left outline-none transition-[transform,border-color,box-shadow,background-color] duration-500 ease-out focus-visible:ring-2 focus-visible:ring-offset-4 focus-visible:ring-offset-[#f7f7f2] dark:focus-visible:ring-offset-[#0d0d0b] ${surfaceClass} ${className}`}
      style={style}
      {...buttonProps}
    >
      <span
        aria-hidden="true"
        className="absolute inset-0"
        style={{
          background: `linear-gradient(150deg, ${meta.accentSoft} 0%, transparent 48%), radial-gradient(circle at 92% 8%, ${meta.glow}, transparent 46%)`,
        }}
      />
      <span
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-1 origin-left scale-x-50 transition-transform duration-500 group-hover:scale-x-100 group-focus-visible:scale-x-100"
        style={{ backgroundColor: meta.accent, transform: accentActive ? "scaleX(1)" : undefined }}
      />
      <span
        aria-hidden="true"
        className={`absolute origin-center opacity-[0.16] transition-all duration-700 group-hover:-translate-x-2 group-hover:scale-110 group-hover:opacity-[0.24] group-focus-visible:-translate-x-2 group-focus-visible:scale-110 group-focus-visible:opacity-[0.24] ${artworkContainerClassName}`}
      >
        <HarnessArtwork type={type} className={artworkClassName} />
      </span>
      {children}
    </button>
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
  const baseRotation = [-7, 0, 7][index] || 0;
  const cardNumber = String(index + 1).padStart(2, "0");
  return (
    <HarnessCardFrame
      type={item.connector_type}
      aria-label={`Open ${item.name} sessions`}
      aria-pressed={selected}
      data-hovered={hovered ? "true" : "false"}
      onMouseEnter={onHover}
      onFocus={onHover}
      onClick={onSelect}
      accentActive={selected}
      className={`aspect-[2/3] w-[190px] shrink-0 rounded-[26px] sm:w-[260px] sm:rounded-[32px] lg:w-[280px] ${index ? "-ml-[88px] sm:-ml-[58px]" : ""} ${selected ? "border-transparent" : "border-[#cecec3] dark:border-[#3a3a33]"}`}
      artworkContainerClassName="-right-[19%] top-[10%] h-[53%] w-[86%]"
      style={{
        zIndex: hovered || selected ? 30 : 10 + index,
        transform: `translate3d(${translateX}px, ${translateY}px, 0) rotate(${hovered || selected ? 0 : baseRotation}deg) scale(${hovered || selected ? 1.045 : 1})`,
        borderColor: hovered || selected ? meta.accent : undefined,
        boxShadow: hovered || selected
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
  pending = false,
  workflowPending = false,
  taskReady = true,
  onContinue,
}) {
  const type = provider.provider;
  const meta = HARNESS_META[type] || harnessMeta(type);
  const ready = provider.ready === true;
  const disabled = !ready || !taskReady || workflowPending;
  const statusLabel = pending
    ? "Running"
    : provider.status === "checking"
      ? "Checking"
      : ready
        ? "Ready"
        : "Unavailable";
  const statusTone = pending || ready
    ? "border-emerald-200/20 bg-emerald-200/10 text-emerald-100"
    : "border-amber-200/20 bg-amber-200/10 text-amber-100";
  const message = provider.message || (
    ready
      ? `Start a fresh ${meta.name} session with this task’s reconciled context.`
      : `${meta.name} execution readiness could not be confirmed.`
  );

  return (
    <HarnessCardFrame
      type={type}
      aria-label={`Continue in ${meta.name}`}
      aria-describedby={`continuation-provider-${type}-detail`}
      disabled={disabled}
      data-provider-ready={ready ? "true" : "false"}
      data-provider-pending={pending ? "true" : "false"}
      onClick={() => onContinue(type)}
      surface="dark"
      className={`min-h-[13rem] w-full rounded-[1.4rem] border-white/10 shadow-[0_18px_42px_rgba(0,0,0,0.18)] backdrop-blur-sm hover:-translate-y-1 hover:border-white/25 disabled:cursor-not-allowed disabled:hover:translate-y-0 ${!ready ? "opacity-80" : ""}`}
      artworkContainerClassName="-right-[8%] top-[11%] h-32 w-32"
      style={{
        borderColor: ready ? `${meta.accent}66` : undefined,
        boxShadow: ready ? `0 20px 48px ${meta.glow}` : undefined,
      }}
    >
      <span className="relative flex min-h-[13rem] flex-col p-5">
        <span className="flex items-start justify-between gap-3">
          <span>
            <span className="block text-[9px] font-black uppercase tracking-[0.18em]" style={{ color: meta.accent }}>
              {meta.company}
            </span>
            <span className="mt-1.5 block text-xl font-black tracking-[-0.03em]">{meta.name}</span>
          </span>
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[8px] font-black uppercase tracking-[0.13em] ${statusTone}`}>
            {pending
              ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              : ready
                ? <Radio className="h-3 w-3" aria-hidden="true" />
                : <ShieldAlert className="h-3 w-3" aria-hidden="true" />}
            {statusLabel}
          </span>
        </span>

        <span id={`continuation-provider-${type}-detail`} className="mt-auto block">
          <span className={`block text-[11px] font-semibold leading-5 ${ready ? "text-[#cacac1]" : "text-amber-100"}`}>
            {message}
          </span>
          {!ready && provider.action ? (
            <span className="mt-2 block text-[10px] font-semibold leading-4 text-amber-200">
              Next: {provider.action}
            </span>
          ) : null}
          <span
            className={`mt-4 flex items-center justify-between border-t border-white/10 pt-3 text-[9px] font-black uppercase tracking-[0.14em] ${ready ? "" : "text-white/45"}`}
            style={{ color: ready ? meta.accent : undefined }}
          >
            {pending ? `Continuing in ${meta.name}…` : ready ? `Continue in ${meta.name}` : "Not runnable"}
            {pending
              ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              : ready
                ? <ArrowRight className="h-4 w-4 transition-transform duration-500 group-hover:translate-x-1" aria-hidden="true" />
                : <ShieldAlert className="h-4 w-4" aria-hidden="true" />}
          </span>
        </span>
      </span>
    </HarnessCardFrame>
  );
}
