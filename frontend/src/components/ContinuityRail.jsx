import { Link } from "react-router-dom";

const STAGES = [
  { key: "connect", label: "Connect", to: "/app/connectors", title: "Connect sources and services" },
  { key: "observe", label: "Observe", to: "/app/memory", title: "Review project memory" },
  { key: "prepare", label: "Prepare", to: "/app/runs", title: "Review and verify checkpoints" },
  { key: "continue", label: "Continue", to: "/app", title: "Continue from the current project state" },
];

export default function ContinuityRail({ pathname, className = "" }) {
  const activeStage = stageForPath(pathname);

  return (
    <section aria-label="Continuity loop" className={`no-scrollbar w-fit max-w-full overflow-x-auto rounded-2xl border border-[#e1e1dc] bg-white p-1.5 shadow-[0_10px_32px_rgba(23,23,19,0.055)] dark:border-[#242424] dark:bg-black dark:shadow-none ${className}`}>
      <div className="flex min-w-max items-center">
        <p className="hidden h-9 shrink-0 items-center border-r border-[#e5e5e0] px-3 pr-4 text-[11px] font-semibold text-[#4f4f48] dark:border-[#292929] dark:text-[#c7c7bd] sm:flex">
          Continuity
        </p>
        <ol className="flex items-center gap-0.5 pl-1">
          {STAGES.map((stage, index) => {
            const active = stage.key === activeStage;
            return (
              <li key={stage.key} aria-current={active ? "step" : undefined}>
                <Link
                  to={stage.to}
                  aria-label={stage.label}
                  title={stage.title}
                  className={`flex h-9 items-center gap-2 rounded-xl px-3 text-[11px] font-semibold outline-none transition-[background-color,color,box-shadow,transform] focus-visible:ring-2 focus-visible:ring-[#77776e] focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-[#bdbdb4] dark:focus-visible:ring-offset-black ${active ? "bg-[#171713] text-white shadow-[0_5px_14px_rgba(23,23,19,0.16)] dark:bg-white dark:text-black dark:shadow-none" : "text-[#77776e] hover:bg-[#f3f3f0] hover:text-[#171713] active:scale-[0.98] dark:text-[#929289] dark:hover:bg-[#171717] dark:hover:text-white"}`}
                >
                  <span className={`font-mono text-[9px] tabular-nums ${active ? "opacity-60" : "text-[#adada4] dark:text-[#62625c]"}`}>{String(index + 1).padStart(2, "0")}</span>
                  {stage.label}
                </Link>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

export function stageForPath(pathname = "") {
  if (/\/app\/(sources|connectors)(\/|$)/.test(pathname)) return "connect";
  if (/\/app\/(prepare|runs)(\/|$)/.test(pathname)) return "prepare";
  if (pathname === "/app" || pathname === "/app/") return "continue";
  return "observe";
}
