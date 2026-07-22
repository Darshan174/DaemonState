import { useEffect, useMemo, useState } from "react";

const DEFAULT_STAGES = [
  "Opening the workspace",
  "Reading source-backed activity",
  "Preparing the verified view",
];

export default function ProductLoadingState({
  label = "Loading your project…",
  detail,
  stages = DEFAULT_STAGES,
  compact = false,
  fullScreen = false,
  className = "",
}) {
  const [progress, setProgress] = useState(8);
  const normalizedStages = useMemo(
    () => (stages?.length ? stages : DEFAULT_STAGES),
    [stages],
  );

  useEffect(() => {
    const timer = window.setInterval(() => {
      setProgress((current) => {
        if (current >= 94) return current;
        if (current < 36) return Math.min(94, current + 7);
        if (current < 68) return Math.min(94, current + 4);
        return Math.min(94, current + 2);
      });
    }, 360);

    return () => window.clearInterval(timer);
  }, []);

  const stageIndex = Math.min(
    normalizedStages.length - 1,
    Math.floor((progress / 100) * normalizedStages.length),
  );
  const stage = normalizedStages[stageIndex];

  return (
    <section
      role="status"
      aria-live="polite"
      aria-label={label}
      className={`relative overflow-hidden bg-[#171713] text-white ${fullScreen ? "flex min-h-screen items-center border-0 px-6 py-12" : `rounded-[22px] border border-[#d8d8cf] shadow-[0_24px_80px_rgba(23,23,19,0.08)] dark:border-[#292925] ${compact ? "px-5 py-7" : "min-h-[260px] px-6 py-10 sm:px-10 sm:py-12"}`} ${className}`}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-35 [background-image:linear-gradient(rgba(255,255,255,0.045)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.045)_1px,transparent_1px)] [background-size:42px_42px]"
      />
      <div className={`relative mx-auto flex h-full w-full max-w-2xl flex-col justify-center ${compact ? "gap-5" : "gap-8"}`}>
        <div className="flex items-end justify-between gap-6">
          <div>
            <p className="font-mono text-[9px] font-semibold uppercase tracking-[0.18em] text-[#d9ff68]">Context Engine</p>
            <p className={`${compact ? "mt-2 text-sm" : "mt-3 text-base sm:text-lg"} font-semibold tracking-[-0.02em] text-white`}>{label}</p>
          </div>
          <span className={`${compact ? "text-3xl" : "text-5xl sm:text-6xl"} shrink-0 font-medium tracking-[-0.07em] tabular-nums text-white`}>{progress}%</span>
        </div>

        <div>
          <div
            role="progressbar"
            aria-label="Loading progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
            aria-valuetext={`${progress}% — ${stage}`}
            className="relative h-px bg-white/15"
          >
            <span className="absolute inset-y-0 left-0 bg-[#d9ff68] transition-[width] duration-300 ease-out" style={{ width: `${progress}%` }} />
            <span className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 bg-[#d9ff68] transition-[left] duration-300 ease-out" style={{ left: `${progress}%` }} />
          </div>
          <div className="mt-4 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-5">
            <p className="text-[11px] font-semibold text-white/72">{stage}</p>
            {detail ? <p className="max-w-md text-[10px] leading-5 text-white/45 sm:text-right">{detail}</p> : null}
          </div>
        </div>
      </div>
    </section>
  );
}
