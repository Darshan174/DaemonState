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
    <section aria-label="Continuity loop" className={`no-scrollbar w-fit max-w-full overflow-x-auto rounded-[14px] border border-[#d8d8cf]/90 bg-[#fbfbf6]/90 p-1.5 shadow-[0_8px_24px_rgba(23,23,19,0.04)] backdrop-blur-sm dark:border-[#292925] dark:bg-[#10100e]/90 dark:shadow-[0_10px_30px_rgba(0,0,0,0.2)] ${className}`}>
      <div className="flex min-w-max items-center gap-1">
        <p className="hidden h-8 shrink-0 items-center gap-2 border-r border-[#dfdfd7] px-2.5 pr-3 font-mono text-[8px] font-semibold uppercase tracking-[0.14em] text-[#77776e] dark:border-[#30302b] dark:text-[#929289] sm:flex">
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-[#afca54] shadow-[0_0_0_3px_rgba(175,202,84,0.14)] dark:bg-[#d9ff68]" />
          Continuity
        </p>
        <ol className="flex items-center gap-1">
          {STAGES.map((stage, index) => {
            const active = stage.key === activeStage;
            return (
              <li key={stage.key} aria-current={active ? "step" : undefined}>
                <Link
                  to={stage.to}
                  aria-label={stage.label}
                  title={stage.title}
                  className={`flex h-8 items-center gap-2 rounded-[9px] px-2.5 text-[10px] font-semibold outline-none transition-[background-color,color,box-shadow,transform] focus-visible:ring-2 focus-visible:ring-[#9bb83d] focus-visible:ring-offset-2 focus-visible:ring-offset-[#fbfbf6] dark:focus-visible:ring-[#d9ff68] dark:focus-visible:ring-offset-[#10100e] ${active ? "bg-[#171713] text-white shadow-[0_4px_12px_rgba(23,23,19,0.14)] dark:bg-[#d9ff68] dark:text-[#171713]" : "text-[#85857c] hover:bg-[#edede6] hover:text-[#30302b] active:scale-[0.98] dark:text-[#929289] dark:hover:bg-[#20201c] dark:hover:text-white"}`}
                >
                  <span className={`font-mono text-[8px] tabular-nums ${active ? "opacity-70" : "text-[#adada4] dark:text-[#5e5e57]"}`}>{String(index + 1).padStart(2, "0")}</span>
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
