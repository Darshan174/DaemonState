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


export function HarnessArtwork({
  type,
  className = "",
  monochrome = false,
  color = "",
}) {
  const filterClass = monochrome && !color ? "grayscale" : "";
  if (color) {
    const artworkProps = {
      className: `h-full w-full ${className}`,
      color,
      decorative: true,
    };
    if (type === "codex") {
      return (
        <OpenAIArtwork
          {...artworkProps}
          dataHarnessArtwork="codex"
        />
      );
    }
    if (type === "claude") {
      return (
        <AnthropicIcon
          {...artworkProps}
          dataHarnessArtwork="claude"
        />
      );
    }
    if (type === "opencode") {
      return (
        <OpenCodeArtwork
          {...artworkProps}
          dataHarnessArtwork="opencode"
        />
      );
    }
  }
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


function OpenAIArtwork({
  className,
  color,
  decorative = false,
  dataHarnessArtwork,
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      fill="currentColor"
      style={{ color }}
      data-harness-artwork={dataHarnessArtwork}
      aria-label={decorative ? undefined : "Codex"}
      aria-hidden={decorative || undefined}
    >
      <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.032.067L9.8 19.9a4.494 4.494 0 0 1-6.2-1.596zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.843-3.369 2.02-1.168a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.402-.681zm2.01-3.023l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08-4.778 2.758a.795.795 0 0 0-.392.681zm1.097-2.365l2.602-1.5 2.607 1.5v2.993l-2.607 1.5-2.602-1.5z" />
    </svg>
  );
}


function OpenCodeArtwork({
  className,
  color,
  decorative = false,
  dataHarnessArtwork,
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 30"
      xmlns="http://www.w3.org/2000/svg"
      style={{ color }}
      data-harness-artwork={dataHarnessArtwork}
      aria-label={decorative ? undefined : "OpenCode"}
      aria-hidden={decorative || undefined}
    >
      <path d="M18 24H6V12H18V24Z" fill="currentColor" opacity="0.55" />
      <path
        d="M18 6H6V24H18V6ZM24 30H0V0H24V30Z"
        fill="currentColor"
        fillRule="evenodd"
        clipRule="evenodd"
      />
    </svg>
  );
}


export function AnthropicIcon({
  className,
  color,
  decorative = false,
  dataHarnessArtwork,
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      fill={color ? "currentColor" : "#D97757"}
      style={color ? { color } : undefined}
      data-harness-artwork={dataHarnessArtwork}
      aria-label={decorative ? undefined : "Claude Code"}
      aria-hidden={decorative || undefined}
    >
      <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017L3.674 20H0L6.57 3.52zm2.285 5.357l-2.07 5.675h4.14l-2.07-5.675z" />
    </svg>
  );
}
