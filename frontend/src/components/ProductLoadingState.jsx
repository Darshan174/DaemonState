import { useEffect, useMemo, useState } from "react";

const DEFAULT_STAGES = [
  "Opening the workspace",
  "Reading source-backed activity",
  "Preparing the verified view",
];

export default function ProductLoadingState({
  label = "Loading your project…",
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
      className={`relative flex items-center justify-center overflow-hidden bg-black text-white ${
        fullScreen
          ? "min-h-screen px-6 py-12"
          : `rounded-[22px] ${compact ? "min-h-36 px-5 py-7" : "min-h-[260px] px-6 py-10"}`
      } ${className}`}
    >
      <span
        role="progressbar"
        aria-label="Loading progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
        aria-valuetext={`${progress}% — ${stage}`}
        className="text-lg font-medium tracking-[-0.03em] tabular-nums text-white"
      >
        {progress}%
      </span>
    </section>
  );
}
