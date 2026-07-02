import { AlertTriangle, FileText, GitPullRequest, MessageCircle, Bot, LockKeyhole, Link2 } from "lucide-react";
import { SOURCE_TEXTURE_META } from "../../graph/contextAssembly";

const SOURCE_ICON = {
  github: GitPullRequest,
  slack: MessageCircle,
  agent: Bot,
  local: FileText,
  gmail: FileText,
  other: FileText,
};

export default function FragmentBlock({ fragment, compact = false, selected = false }) {
  if (!fragment) return null;
  const source = SOURCE_TEXTURE_META[fragment.sourceType] || SOURCE_TEXTURE_META.other;
  const Icon = SOURCE_ICON[fragment.sourceType] || FileText;
  const confidence = fragment.confidence?.value ?? 0.5;
  const opacity = fragment.stale ? 0.42 : Math.max(0.42, 0.34 + confidence * 0.66);

  return (
    <div
      className={`relative overflow-hidden rounded-md border px-2 py-1.5 text-left shadow-sm ${
        selected
          ? "border-slate-900 bg-white dark:border-white dark:bg-white/[0.08]"
          : "border-slate-300/80 bg-white/90 dark:border-white/[0.1] dark:bg-white/[0.045]"
      }`}
      style={{ opacity }}
      title={`${source.label} evidence · ${fragment.confidence?.label || "unknown confidence"}`}
    >
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.08]"
        style={{
          backgroundImage:
            source.pattern === "stripe"
              ? "repeating-linear-gradient(135deg, currentColor 0 1px, transparent 1px 6px)"
              : source.pattern === "dot"
                ? "radial-gradient(currentColor 1px, transparent 1px)"
                : source.pattern === "split"
                  ? "linear-gradient(90deg, currentColor 0 36%, transparent 36%)"
                  : "none",
          backgroundSize: source.pattern === "dot" ? "7px 7px" : undefined,
          color: source.tone,
        }}
      />
      <div className="relative flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 shrink-0 text-slate-500 dark:text-neutral-400" />
        <span className={`min-w-0 truncate font-semibold text-slate-800 dark:text-neutral-100 ${compact ? "text-[10px]" : "text-xs"}`}>
          {fragment.summary}
        </span>
        {fragment.conflict ? <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-500" /> : null}
        {fragment.confidence?.level === "high" ? <LockKeyhole className="h-3 w-3 shrink-0 text-emerald-600" /> : <Link2 className="h-3 w-3 shrink-0 text-slate-400" />}
      </div>
      {!compact ? (
        <div className="relative mt-1 flex items-center justify-between gap-2 text-[10px] font-medium text-slate-500 dark:text-neutral-400">
          <span>{source.label}</span>
          <span>{fragment.confidence?.label || "n/a"}</span>
        </div>
      ) : null}
    </div>
  );
}
