import { Construction } from "lucide-react";

export default function UnderConstructionOverlay({ sectionName }) {
  const headingId = `under-construction-${sectionName.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  return (
    <section
      role="status"
      aria-live="polite"
      aria-label={`${sectionName} is under construction`}
      className="absolute inset-0 z-30 flex items-center justify-center overflow-hidden bg-[#f7f7f2]/45 px-4 py-8 backdrop-blur-[7px] dark:bg-black/45 sm:px-8"
    >
      <div
        aria-hidden="true"
        className="absolute left-[12%] top-[18%] h-48 w-48 rounded-full bg-accent/20 blur-3xl dark:bg-accent/10"
      />
      <div
        aria-hidden="true"
        className="absolute bottom-[12%] right-[10%] h-56 w-56 rounded-full bg-evidence/10 blur-3xl dark:bg-evidence/10"
      />

      <div className="relative w-full max-w-[34rem] overflow-hidden rounded-[2rem] border border-white/80 bg-white/70 px-6 py-10 text-center shadow-[0_24px_80px_rgba(23,23,19,0.16)] backdrop-blur-2xl dark:border-white/10 dark:bg-[#090909]/75 dark:shadow-[0_28px_90px_rgba(0,0,0,0.64)] sm:px-10 sm:py-12">
        <div
          aria-hidden="true"
          className="absolute inset-x-0 top-0 h-1 bg-[linear-gradient(90deg,transparent_0%,#d9ff68_24%,#d9ff68_76%,transparent_100%)]"
        />

        <div className="mx-auto flex h-20 w-20 animate-float items-center justify-center rounded-[1.65rem] bg-[#171713] shadow-[0_16px_32px_rgba(23,23,19,0.2)] motion-reduce:animate-none dark:bg-accent dark:shadow-[0_16px_36px_rgba(217,255,104,0.12)]">
          <Construction
            aria-hidden="true"
            className="h-9 w-9 text-accent dark:text-accent-ink"
            strokeWidth={1.8}
          />
        </div>

        <p className="mx-auto mt-7 w-fit rounded-full border border-line bg-surface/75 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-ink-muted">
          {sectionName}
        </p>
        <h1
          id={headingId}
          className="mt-4 text-3xl font-semibold tracking-[-0.045em] text-ink sm:text-4xl"
        >
          Under construction
        </h1>
        <p className="mx-auto mt-4 max-w-md text-sm leading-6 text-ink-muted sm:text-[15px]">
          We’re putting the finishing touches on this space. Everything already here is preserved underneath—check back soon.
        </p>

        <div className="mt-7 flex items-center justify-center gap-2 text-xs font-semibold text-ink-subtle">
          <span aria-hidden="true" className="h-2 w-2 rounded-full bg-accent shadow-[0_0_0_5px_rgba(217,255,104,0.2)]" />
          Work in progress
        </div>
      </div>
    </section>
  );
}
