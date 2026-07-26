import { useState } from "react";
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
  as: Root = "button",
  type,
  children,
  className = "",
  artworkClassName = "",
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
    ? "bg-white/[0.055] text-white"
    : "bg-[#fbfbf6] dark:bg-[#141411]";
  const buttonProps = Root === "button" ? { type: "button" } : {};
  const focusClass = Root === "button"
    ? "focus-visible:ring-2 focus-visible:ring-offset-4 focus-visible:ring-offset-[#f7f7f2] dark:focus-visible:ring-offset-[#0d0d0b]"
    : "focus-within:ring-2 focus-within:ring-offset-4 focus-within:ring-offset-[#171713]";
  return (
    <Root
      {...buttonProps}
      data-harness={type}
      data-monochrome={monochrome ? "true" : "false"}
      className={`group relative overflow-hidden border text-left outline-none transition-[transform,border-color,box-shadow,background-color] duration-500 ease-out ${focusClass} ${surfaceClass} ${monochrome ? "grayscale saturate-0" : ""} ${className}`}
      style={style}
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
        className="absolute inset-x-0 top-0 h-1 origin-left scale-x-50 transition-transform duration-500 group-hover:scale-x-100 group-focus-visible:scale-x-100 group-focus-within:scale-x-100"
        style={{ backgroundColor: accent, transform: accentActive ? "scaleX(1)" : undefined }}
      />
      <span
        aria-hidden="true"
        className={`absolute origin-center opacity-[0.16] transition-all duration-700 group-hover:-translate-x-2 group-hover:scale-110 group-hover:opacity-[0.24] group-focus-visible:-translate-x-2 group-focus-visible:scale-110 group-focus-visible:opacity-[0.24] group-focus-within:-translate-x-2 group-focus-within:scale-110 group-focus-within:opacity-[0.24] ${artworkContainerClassName}`}
      >
        <HarnessArtwork
          type={type}
          className={artworkClassName}
          monochrome={monochrome}
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
  index = 0,
  hovered = false,
  translateX = 0,
  translateY = 0,
  pending = false,
  workflowPending = false,
  taskReady = true,
  onHover,
  onContinue,
}) {
  const type = provider.provider;
  const meta = HARNESS_META[type] || harnessMeta(type);
  const ready = provider.ready === true;
  const status = String(provider.status || "").trim().toLowerCase();
  const configured = ready && status === "configured";
  const checking = status === "checking";
  const disabled = !ready || !taskReady || workflowPending;
  const modelOptions = continuationModelOptions(provider);
  const defaultModel = (
    modelOptions.find((model) => model.default)
    || modelOptions[0]
    || null
  );
  const [selectedModelId, setSelectedModelId] = useState(defaultModel?.id || "");
  const selectedModel = (
    modelOptions.find((model) => model.id === selectedModelId)
    || defaultModel
  );
  const effortOptions = selectedModel?.reasoning_efforts || [];
  const fallbackEffort = (
    selectedModel?.default_reasoning_effort
    || (effortOptions.includes("medium") ? "medium" : effortOptions[0])
    || ""
  );
  const [selectedEffort, setSelectedEffort] = useState(fallbackEffort);
  const normalizedEffort = effortOptions.includes(selectedEffort)
    ? selectedEffort
    : fallbackEffort;
  const controlsVisible = type === "codex" && modelOptions.length > 0;
  const statusLabel = continuationProviderStatusLabel({
    pending,
    ready,
    status,
    code: provider.code,
  });
  const statusTone = pending || (ready && !configured)
    ? "border-emerald-200/20 bg-emerald-200/10 text-emerald-100"
    : checking
      ? "border-white/15 bg-white/[0.06] text-white/70"
      : "border-amber-200/20 bg-amber-200/10 text-amber-100";
  const message = provider.message || (
    ready
      ? `Start a fresh ${meta.name} session with this task’s reconciled context.`
      : `${meta.name} execution readiness could not be confirmed.`
  );
  const active = hovered || pending;
  const baseRotation = [-7, 0, 7][index] || 0;
  const cardNumber = String(index + 1).padStart(2, "0");
  const accent = ready ? meta.accent : "#a0a098";
  const handleModelChange = (event) => {
    const nextModel = modelOptions.find((model) => model.id === event.target.value);
    setSelectedModelId(event.target.value);
    const nextEfforts = nextModel?.reasoning_efforts || [];
    setSelectedEffort(
      nextModel?.default_reasoning_effort
      || (nextEfforts.includes("medium") ? "medium" : nextEfforts[0])
      || "",
    );
  };
  const handleContinue = () => {
    onContinue(type, {
      ...(selectedModel?.id ? { provider_model: selectedModel.id } : {}),
      ...(normalizedEffort ? { provider_effort: normalizedEffort } : {}),
    });
  };

  return (
    <HarnessCardFrame
      as="article"
      type={type}
      data-provider-ready={ready ? "true" : "false"}
      data-provider-pending={pending ? "true" : "false"}
      aria-busy={pending ? "true" : "false"}
      onMouseEnter={onHover}
      onFocusCapture={onHover}
      monochrome={!ready}
      accentActive={pending}
      className={`aspect-[2/3] w-[190px] shrink-0 rounded-[26px] text-[#171713] sm:w-[260px] sm:rounded-[32px] lg:w-[280px] ${index ? "-ml-[88px] sm:-ml-[58px]" : ""} ${ready ? "border-[#cecec3] dark:border-[#3a3a33]" : "border-[#77776f] bg-[#171715] text-white dark:border-[#77776f] dark:bg-[#171715]"} ${workflowPending ? "cursor-wait" : ""}`}
      artworkContainerClassName="-right-[19%] top-[10%] h-[53%] w-[86%]"
      style={{
        zIndex: active ? 30 : 10 + index,
        transform: `translate3d(${translateX}px, ${translateY}px, 0) rotate(${active ? 0 : baseRotation}deg) scale(${active ? 1.045 : 1})`,
        borderColor: active ? accent : undefined,
        boxShadow: active
          ? `0 28px 70px ${ready ? meta.glow : "rgba(255,255,255,0.08)"}, 0 16px 34px rgba(0,0,0,0.28)`
          : "0 16px 34px rgba(0,0,0,0.24)",
        transitionDelay: hovered ? "0ms" : `${index * 35}ms`,
      }}
    >
      <button
        type="button"
        aria-label={`Run task in ${meta.name}`}
        aria-describedby={`continuation-provider-${type}-detail`}
        aria-busy={pending ? "true" : "false"}
        data-provider-ready={ready ? "true" : "false"}
        data-provider-pending={pending ? "true" : "false"}
        data-monochrome={!ready ? "true" : "false"}
        disabled={disabled}
        onClick={handleContinue}
        className={`absolute inset-0 z-10 block w-full text-left outline-none focus-visible:ring-2 focus-visible:ring-inset disabled:hover:translate-y-0 ${workflowPending ? "disabled:cursor-wait" : "disabled:cursor-not-allowed"}`}
        style={{ "--tw-ring-color": accent }}
      >
        <span className="absolute inset-x-0 top-0 flex items-start justify-between px-4 pt-4 sm:px-5 sm:pt-5">
          <span>
            <span className="block font-mono text-lg font-black leading-none sm:text-2xl" style={{ color: accent }}>
              {cardNumber}
            </span>
            <span className={`mt-1 block text-[7px] font-black uppercase tracking-[0.18em] sm:text-[8px] ${ready ? "text-[#85857c]" : "text-white/55"}`}>
              {meta.company}
            </span>
          </span>
          <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[7px] font-black uppercase tracking-[0.14em] backdrop-blur-md sm:text-[8px] ${ready ? statusTone : "border-white/20 bg-white/[0.07] text-white/70"}`}>
            {pending || checking
              ? <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden="true" />
              : ready
                ? <Radio className="h-2.5 w-2.5" aria-hidden="true" />
                : <ShieldAlert className="h-2.5 w-2.5" aria-hidden="true" />}
            {statusLabel}
          </span>
        </span>

        <span className={`absolute inset-x-0 bottom-0 flex min-h-[55%] flex-col justify-end px-4 pb-4 pt-10 sm:px-5 sm:pb-5 ${ready ? "bg-gradient-to-t from-[#fbfbf6] via-[#fbfbf6]/95 to-[#fbfbf6]/35 dark:from-[#141411] dark:via-[#141411]/95 dark:to-[#141411]/30" : "bg-gradient-to-t from-[#171715] via-[#171715]/95 to-[#171715]/35"}`}>
          <span className="block text-lg font-black leading-tight tracking-[-0.035em] sm:text-2xl">
            {meta.name}
          </span>
          <span
            id={`continuation-provider-${type}-detail`}
            className={`mt-2 hidden text-[10px] font-semibold leading-[1.55] sm:line-clamp-2 ${ready ? "text-[#68685f] dark:text-[#aaa9a0]" : "text-white/65"}`}
          >
            {message}
          </span>
          {!ready && provider.action ? (
            <span className="mt-2 hidden text-[9px] font-semibold leading-4 text-white/50 sm:line-clamp-2">
              Next: {provider.action}
            </span>
          ) : null}
          {controlsVisible ? <span aria-hidden="true" className="h-[4.65rem] sm:h-[5rem]" /> : null}
          <span
            className={`mt-3 flex items-center justify-between border-t pt-3 text-[8px] font-black uppercase tracking-[0.14em] sm:mt-4 sm:text-[9px] ${ready ? "border-[#d8d8cf]/80 dark:border-[#3a3a34]" : "border-white/15 text-white/45"}`}
            style={{ color: ready ? accent : undefined }}
          >
            {pending ? `Running in ${meta.name}…` : ready ? "Continue" : "Not runnable"}
            {pending
              ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              : ready
                ? <ArrowRight className="h-4 w-4 transition-transform duration-500 group-hover:translate-x-1" aria-hidden="true" />
                : <ShieldAlert className="h-4 w-4" aria-hidden="true" />}
          </span>
        </span>

        <span aria-hidden="true" className="absolute bottom-3 right-3 rotate-180 font-mono text-sm font-black opacity-20 sm:bottom-4 sm:right-4 sm:text-base" style={{ color: accent }}>
          {cardNumber}
        </span>
      </button>

      {controlsVisible ? (
        <div className="absolute inset-x-4 bottom-[3.65rem] z-20 grid grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)] gap-1.5 sm:inset-x-5 sm:bottom-[4.2rem] sm:gap-2">
          <label className="min-w-0">
            <span className="mb-1 block text-[7px] font-black uppercase tracking-[0.13em] text-[#85857c] sm:text-[8px]">
              Model
            </span>
            <select
              aria-label="Codex model"
              value={selectedModel?.id || ""}
              disabled={workflowPending || pending || !ready}
              onChange={handleModelChange}
              className="h-8 w-full min-w-0 rounded-lg border border-[#d5d5cb] bg-white/80 px-1.5 text-[8px] font-black text-[#292922] outline-none transition focus:border-[#10a37f] focus:ring-2 focus:ring-[#10a37f]/20 disabled:cursor-not-allowed disabled:opacity-55 dark:border-[#41413a] dark:bg-[#20201d]/90 dark:text-white sm:h-9 sm:px-2 sm:text-[9px]"
            >
              {modelOptions.map((model) => (
                <option key={model.id} value={model.id}>{model.label}</option>
              ))}
            </select>
          </label>
          <label className="min-w-0">
            <span className="mb-1 block text-[7px] font-black uppercase tracking-[0.13em] text-[#85857c] sm:text-[8px]">
              Effort
            </span>
            <select
              aria-label="Codex reasoning effort"
              value={normalizedEffort}
              disabled={workflowPending || pending || !ready || !effortOptions.length}
              onChange={(event) => setSelectedEffort(event.target.value)}
              className="h-8 w-full min-w-0 rounded-lg border border-[#d5d5cb] bg-white/80 px-1.5 text-[8px] font-black capitalize text-[#292922] outline-none transition focus:border-[#10a37f] focus:ring-2 focus:ring-[#10a37f]/20 disabled:cursor-not-allowed disabled:opacity-55 dark:border-[#41413a] dark:bg-[#20201d]/90 dark:text-white sm:h-9 sm:px-2 sm:text-[9px]"
            >
              {effortOptions.map((effort) => (
                <option key={effort} value={effort}>{titleCase(effort)}</option>
              ))}
            </select>
          </label>
        </div>
      ) : null}
    </HarnessCardFrame>
  );
}


function continuationProviderStatusLabel({ pending, ready, status, code }) {
  if (pending) return "Running";
  if (status === "checking") return "Checking";
  if (status === "authentication_required") return "Sign in";
  if (status === "access_required") return "Access needed";
  if (status === "configuration_required") return "Setup needed";
  if (ready && status === "configured") return "Configured";
  if (ready) return "Ready";
  if (
    status === "provider_cli_not_found"
    || code === "provider_cli_not_found"
  ) {
    return "Not installed";
  }
  return "Unavailable";
}


const FALLBACK_CODEX_MODELS = [
  {
    id: "gpt-5.6-sol",
    label: "GPT-5.6 Sol",
    default: true,
    reasoning_efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
    default_reasoning_effort: "medium",
  },
  {
    id: "gpt-5.6-terra",
    label: "GPT-5.6 Terra",
    default: false,
    reasoning_efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
    default_reasoning_effort: "medium",
  },
];


function continuationModelOptions(provider) {
  const supplied = Array.isArray(provider.models) ? provider.models : [];
  const models = supplied
    .map((model) => {
      const id = String(model?.id || "").trim();
      if (!id) return null;
      const efforts = Array.isArray(model.reasoning_efforts)
        ? model.reasoning_efforts
          .map((effort) => String(effort || "").trim().toLowerCase())
          .filter(Boolean)
        : [];
      const defaultEffort = String(
        model.default_reasoning_effort || "",
      ).trim().toLowerCase();
      return {
        id,
        label: String(model.label || id).trim(),
        default: model.default === true,
        reasoning_efforts: efforts,
        default_reasoning_effort: efforts.includes(defaultEffort)
          ? defaultEffort
          : (efforts.includes("medium") ? "medium" : efforts[0] || ""),
      };
    })
    .filter(Boolean);
  if (models.length || provider.provider !== "codex") return models;
  return FALLBACK_CODEX_MODELS;
}


function titleCase(value) {
  const text = String(value || "").trim();
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}` : "";
}
