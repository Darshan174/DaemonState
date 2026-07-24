import imgOpenAI from "../assets/openai-icon.png";
import imgOpenCode from "../assets/opencode-icon.png";


export const HARNESS_ORDER = ["codex", "claude", "opencode"];

export const HARNESS_META = {
  codex: {
    name: "Codex",
    label: "Codex",
    company: "OpenAI",
    description: "Implementation sessions, code decisions, plans, and verified outcomes.",
    accent: "#10a37f",
    accentSoft: "rgba(16,163,127,0.12)",
    soft: "rgba(16,163,127,0.12)",
    glow: "rgba(16,163,127,0.22)",
    launchText: "#ffffff",
  },
  claude: {
    name: "Claude Code",
    label: "Claude Code",
    company: "Anthropic",
    description: "Architecture explorations, codebase research, and long-running implementation threads.",
    accent: "#D97757",
    accentSoft: "rgba(217,119,87,0.13)",
    soft: "rgba(217,119,87,0.13)",
    glow: "rgba(217,119,87,0.22)",
    launchText: "#ffffff",
  },
  opencode: {
    name: "OpenCode",
    label: "OpenCode",
    company: "Open source",
    description: "Terminal-native coding sessions, model experiments, and project conversations.",
    accent: "#b9dc4a",
    accentSoft: "rgba(185,220,74,0.12)",
    soft: "rgba(185,220,74,0.13)",
    glow: "rgba(185,220,74,0.18)",
    launchText: "#171713",
  },
};

const FALLBACK_META = {
  name: "Agent",
  label: "Agent",
  company: "AI harness",
  description: "Imported agent session.",
  accent: "#9dbc47",
  accentSoft: "rgba(157,188,71,0.12)",
  soft: "rgba(157,188,71,0.12)",
  glow: "rgba(157,188,71,0.2)",
  launchText: "#171713",
};


export function harnessMeta(type) {
  return HARNESS_META[type] || FALLBACK_META;
}


export function HarnessArtwork({ type, className = "", monochrome = false }) {
  const filterClass = monochrome ? "grayscale" : "";
  if (type === "codex") {
    return (
      <img
        src={imgOpenAI}
        alt=""
        data-harness-artwork="codex"
        className={`h-full w-full scale-[1.18] object-contain dark:invert ${filterClass} ${className}`}
      />
    );
  }
  if (type === "claude") {
    return (
      <AnthropicIcon
        dataHarnessArtwork="claude"
        className={`h-full w-full scale-[1.12] ${filterClass} ${className}`}
        decorative
      />
    );
  }
  if (type === "opencode") {
    return (
      <span data-harness-artwork="opencode" className={`flex h-full w-full items-center justify-center overflow-hidden rounded-[30%] bg-[#171713] ${filterClass} ${className}`}>
        <img src={imgOpenCode} alt="" className="h-full w-full scale-[2.45] object-contain" />
      </span>
    );
  }
  return (
    <span data-harness-artwork={type || "unknown"} className={`flex h-full w-full items-center justify-center rounded-[30%] bg-[#171713] font-mono text-[22%] font-black text-white ${filterClass} ${className}`}>
      AI
    </span>
  );
}


export function HarnessLogo({
  type,
  size = "medium",
  decorative = false,
  className = "",
}) {
  const sizes = {
    small: "h-9 w-9 rounded-xl",
    medium: "h-11 w-11 rounded-xl",
    large: "h-14 w-14 rounded-2xl sm:h-16 sm:w-16",
  };
  const iconSizes = {
    small: "h-5 w-5",
    medium: "h-6 w-6",
    large: "h-8 w-8 sm:h-9 sm:w-9",
  };
  const meta = harnessMeta(type);
  const outerSize = sizes[size] || sizes.medium;
  const iconSize = iconSizes[size] || iconSizes.medium;
  return (
    <span
      role={decorative ? undefined : "img"}
      data-harness-logo={type || "unknown"}
      aria-label={decorative ? undefined : meta.name}
      aria-hidden={decorative || undefined}
      className={`relative flex shrink-0 items-center justify-center overflow-hidden border border-black/10 bg-white shadow-[0_8px_20px_rgba(23,23,19,0.09)] dark:border-white/10 ${outerSize} ${className}`}
      style={{ boxShadow: `0 10px 25px ${meta.glow}` }}
    >
      <span
        aria-hidden="true"
        className="absolute inset-0 opacity-20"
        style={{ background: `radial-gradient(circle at 24% 16%, ${meta.accent}, transparent 68%)` }}
      />
      {type === "codex" ? <img src={imgOpenAI} alt="" className={`relative ${iconSize} object-contain`} /> : null}
      {type === "claude" ? <AnthropicIcon className={`relative ${iconSize}`} decorative /> : null}
      {type === "opencode" ? <img src={imgOpenCode} alt="" className={`relative ${iconSize} object-contain`} /> : null}
      {!HARNESS_META[type] ? (
        <span className="relative font-mono text-xs font-black" style={{ color: meta.accent }}>AI</span>
      ) : null}
    </span>
  );
}


export function AnthropicIcon({ className, decorative = false, dataHarnessArtwork }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      fill="#D97757"
      data-harness-artwork={dataHarnessArtwork}
      aria-label={decorative ? undefined : "Claude Code"}
      aria-hidden={decorative || undefined}
    >
      <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017L3.674 20H0L6.57 3.52zm2.285 5.357l-2.07 5.675h4.14l-2.07-5.675z" />
    </svg>
  );
}
