import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ChevronRight,
  FolderRoot,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import HarnessDeckBackdrop from "./HarnessDeckBackdrop";


export default function ExecuteBanner({
  workspaceName = "Selected workspace",
  status = "Workspace ready",
  busy = false,
  attention = false,
  showWorkspace = true,
  sessionControl = null,
  description = "Prepare verified workspace context and the Session Contexts you choose.",
  to = null,
  linkLabel = "Open Execute",
  headingLevel = 1,
  headingId = "execute-title",
  testId,
}) {
  const Heading = headingLevel === 1 ? "h1" : "h2";
  const bannerClassName = [
    "daemonstate-resume-header group relative min-h-56 overflow-hidden rounded-[2rem] border border-[#d8d8cf] bg-[#f7f7f1] px-5 py-7 text-[#171713] dark:border-[#292925] dark:bg-[#0c0c0a] dark:text-white sm:px-8 sm:py-9 lg:px-10",
    to
      ? "block shadow-[0_18px_54px_rgba(23,23,19,0.08)] transition hover:-translate-y-0.5 hover:border-[#aebf69] hover:shadow-[0_22px_62px_rgba(23,23,19,0.12)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#849633]/70 motion-reduce:hover:translate-y-0 dark:shadow-[0_18px_54px_rgba(0,0,0,0.20)] dark:hover:border-[#d9ff68]/45 dark:hover:shadow-[0_22px_62px_rgba(0,0,0,0.30)] dark:focus-visible:ring-[#d9ff68]/70"
      : "",
  ].filter(Boolean).join(" ");

  const content = (
    <>
      <div
        aria-hidden="true"
        className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-[#d9ff68]/25 blur-3xl dark:bg-[#d9ff68]/10"
      />
      <HarnessDeckBackdrop centered={Boolean(to)} />
      <div className={`relative flex items-start justify-between gap-4 ${to ? "pr-14 sm:pr-20" : ""}`}>
        <div className="min-w-0">
          <Heading
            id={headingId}
            className="text-3xl font-black tracking-[-0.055em] sm:text-4xl"
          >
            Execute
          </Heading>
          <p className="mt-2 max-w-3xl text-sm font-medium leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            {description}
          </p>
        </div>

        {sessionControl}
      </div>

      {to ? (
        <span
          aria-hidden="true"
          data-navigation-arrow
          className="pointer-events-none absolute right-4 top-1/2 z-20 -translate-y-1/2 text-[#65751d] drop-shadow-[0_0_12px_rgba(154,174,53,0.34)] transition-transform group-hover:translate-x-1 sm:right-6 lg:right-8 dark:text-[#d9ff68] dark:drop-shadow-[0_0_14px_rgba(217,255,104,0.42)] motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
        >
          <ChevronRight className="h-11 w-11" strokeWidth={3.25} />
        </span>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {showWorkspace ? (
          <span className="inline-flex min-h-8 items-center gap-2 rounded-full border border-[#d8d8cf] bg-white/60 px-3 text-xs font-semibold text-[#77776e] dark:border-[#292925] dark:bg-white/[0.04] dark:text-[#aaa9a0]">
            <FolderRoot className="h-4 w-4" aria-hidden="true" />
            {workspaceName}
          </span>
        ) : null}
        <span
          className={`inline-flex min-h-8 items-center gap-2 rounded-full border px-3 text-xs font-semibold ${
            attention
              ? "border-[#d0a946]/40 bg-[#d0a946]/10 text-[#5f4a12] dark:text-[#e4c875]"
              : "border-[#d8d8cf] bg-white/60 text-[#68685f] dark:border-[#292925] dark:bg-white/[0.04] dark:text-[#aaa9a0]"
          }`}
        >
          {busy
            ? <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            : attention
              ? <AlertTriangle className="h-3.5 w-3.5 text-attention" aria-hidden="true" />
              : <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />}
          {status}
        </span>
      </div>
    </>
  );

  if (to) {
    return (
      <Link
        to={to}
        aria-label={linkLabel}
        className={bannerClassName}
        data-testid={testId}
      >
        {content}
      </Link>
    );
  }

  return (
    <header
      aria-labelledby={headingId}
      className={bannerClassName}
      data-testid={testId}
    >
      {content}
    </header>
  );
}
