import {
  HarnessArtwork,
  harnessMeta,
} from "./HarnessBrand";


const BACKDROP_CARDS = [
  { type: "codex", left: "3.5rem", top: "4.5rem", rotation: "-10deg", delay: "0ms" },
  { type: "claude", left: "12.5rem", top: "1.25rem", rotation: "-1deg", delay: "750ms" },
  { type: "opencode", left: "21.5rem", top: "4rem", rotation: "9deg", delay: "1500ms" },
];


export default function HarnessDeckBackdrop() {
  return (
    <div
      aria-hidden="true"
      data-harness-deck-backdrop
      className="pointer-events-none absolute -right-8 -top-10 hidden h-[23rem] w-[37rem] select-none overflow-hidden sm:block"
      style={{
        maskImage: "linear-gradient(to right, transparent 0%, black 25%, black 100%)",
        WebkitMaskImage: "linear-gradient(to right, transparent 0%, black 25%, black 100%)",
      }}
    >
      {BACKDROP_CARDS.map(({ type, left, top, rotation, delay }) => {
        const meta = harnessMeta(type);
        return (
          <span
            key={type}
            data-backdrop-harness={type}
            className="daemonstate-resume-deck-card absolute block h-64 w-44 overflow-hidden rounded-[1.65rem] border border-black/30 bg-[#efefe9] text-[#171713] opacity-[0.13] shadow-2xl grayscale dark:border-white/35 dark:bg-[#d6d6cf] dark:opacity-[0.16]"
            style={{
              left,
              top,
              "--deck-rotation": rotation,
              "--deck-delay": delay,
            }}
          >
            <span className="absolute inset-x-0 top-0 h-1 bg-[#171713]" />
            <span className="absolute -right-[24%] top-[14%] h-[48%] w-[94%] opacity-45">
              <HarnessArtwork type={type} monochrome />
            </span>
            <span className="absolute inset-x-0 top-0 flex items-start justify-end px-4 pt-4">
              <span className="text-[7px] font-black uppercase tracking-[0.15em]">{meta.company}</span>
            </span>
            <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-[#efefe9] via-[#efefe9]/95 to-transparent px-4 pb-5 pt-16">
              <span className="block text-xl font-black tracking-[-0.04em]">{meta.name}</span>
              <span className="mt-2 block h-px w-full bg-black/35" />
              <span className="mt-3 grid grid-cols-2 gap-3">
                <span className="h-5 rounded-sm bg-black/15" />
                <span className="h-5 rounded-sm bg-black/10" />
              </span>
            </span>
          </span>
        );
      })}
    </div>
  );
}
