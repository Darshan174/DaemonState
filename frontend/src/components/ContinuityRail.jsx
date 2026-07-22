const STAGES = [
  { key: "connect", label: "Connect", detail: "Bring evidence in" },
  { key: "observe", label: "Observe", detail: "Inspect current truth" },
  { key: "prepare", label: "Prepare", detail: "Compile the handoff" },
  { key: "continue", label: "Continue", detail: "Resume safely" },
];

export default function ContinuityRail({ pathname, className = "" }) {
  const activeStage = stageForPath(pathname);

  return (
    <section aria-label="Continuity loop" className={`no-scrollbar overflow-x-auto rounded-2xl border border-[#d8d8cf]/90 bg-[#fbfbf6]/80 px-4 py-3 backdrop-blur-sm dark:border-[#292925] dark:bg-[#10100e]/86 ${className}`}>
      <div className="flex min-w-[560px] items-center gap-3">
        <p className="w-[92px] shrink-0 font-mono text-[8px] font-semibold uppercase tracking-[0.14em] text-[#77776e] dark:text-[#929289]">Continuity loop</p>
        <ol className="grid min-w-0 flex-1 grid-cols-4">
          {STAGES.map((stage, index) => {
            const active = stage.key === activeStage;
            return (
              <li key={stage.key} aria-current={active ? "step" : undefined} className="relative flex min-w-0 items-center">
                {index ? <span aria-hidden="true" className={`absolute right-1/2 top-[7px] h-px w-full ${active || STAGES[index - 1]?.key === activeStage ? "bg-[#afca54] dark:bg-[#7d9535]" : "bg-[#d8d8cf] dark:bg-[#34342f]"}`} /> : null}
                <div className="relative z-10 flex min-w-0 items-start gap-2 bg-[#fbfbf6] pr-2 dark:bg-[#10100e]">
                  <span aria-hidden="true" className={`mt-0.5 h-3.5 w-3.5 shrink-0 border ${active ? "border-[#171713] bg-[#d9ff68] shadow-[0_0_0_3px_rgba(217,255,104,0.16)] dark:border-[#d9ff68]" : "border-[#b9b9af] bg-[#f7f7f2] dark:border-[#4b4b44] dark:bg-[#171713]"}`} />
                  <span className="min-w-0">
                    <span className={`block truncate text-[10px] font-bold ${active ? "text-[#171713] dark:text-white" : "text-[#77776e] dark:text-[#929289]"}`}>{stage.label}</span>
                    <span className="hidden truncate text-[8px] text-[#929289] xl:block">{stage.detail}</span>
                  </span>
                </div>
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
  if (/\/app\/prepare(\/|$)/.test(pathname)) return "prepare";
  if (pathname === "/app" || pathname === "/app/") return "continue";
  return "observe";
}
