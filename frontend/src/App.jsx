import { Suspense, lazy, useState } from "react";
import { Routes, Route, NavLink, Navigate, useLocation, Link } from "react-router-dom";
import WorkspaceBootstrap from "./components/WorkspaceBootstrap";
import WorkspaceSwitcher from "./components/WorkspaceSwitcher";
import ThemeToggle from "./components/ThemeToggle";

const Landing = lazy(() => import("./pages/Landing"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const FounderBrief = lazy(() => import("./pages/FounderBrief"));
const DecisionRegister = lazy(() => import("./pages/DecisionRegister"));
const Changes = lazy(() => import("./pages/Changes"));
const LaunchGuard = lazy(() => import("./pages/LaunchGuard"));
const Meetings = lazy(() => import("./pages/Meetings"));
const Engineering = lazy(() => import("./pages/Engineering"));
const SystemHealth = lazy(() => import("./pages/SystemHealth"));
const Accuracy = lazy(() => import("./pages/Accuracy"));
const Models = lazy(() => import("./pages/Models"));
const Connectors = lazy(() => import("./pages/Connectors"));
const ConnectorRuns = lazy(() => import("./pages/ConnectorRuns"));
const KnowledgeGraph = lazy(() => import("./pages/KnowledgeGraph"));
const ModelDetail = lazy(() => import("./pages/ModelDetail"));
const Query = lazy(() => import("./pages/Query"));
const ReviewQueue = lazy(() => import("./pages/ReviewQueue"));
const Sources = lazy(() => import("./pages/Sources"));

const PRIMARY_NAV = [
  { to: "/app", label: "Dashboard", icon: BarChartIcon, primary: true },
  { to: "/app/brief", label: "Founder Brief", icon: BriefIcon },
  { to: "/app/query", label: "Ask", icon: SearchIcon },
  { to: "/app/decisions", label: "Decisions", icon: DecisionIcon },
  { to: "/app/changes", label: "Changes", icon: ChangesIcon },
  { to: "/app/sources", label: "Sources", icon: DocumentStackIcon },
];

const ADMIN_NAV = [
  { to: "/app/status", label: "System Health", icon: PulseIcon },
  { to: "/app/graph", label: "Knowledge Graph", icon: GraphIcon },
  { to: "/app/launch-guard", label: "Launch Guard", icon: GuardIcon },
  { to: "/app/meetings", label: "Meetings", icon: MeetingIcon },
  { to: "/app/engineering", label: "Engineering", icon: CodeIcon },
  { to: "/app/accuracy", label: "Accuracy", icon: GaugeIcon },
  { to: "/app/models", label: "Models", icon: CubeIcon },
  { to: "/app/review", label: "Review Queue", icon: ShieldCheckIcon },
  { to: "/app/connectors", label: "Connectors", icon: PlugIcon },
];

function SidebarContent({ onNavigate }) {
  return (
    <>
      <nav className="flex-1 overflow-y-auto py-5 px-4 custom-scrollbar">
        <div>
          <p className="px-3 py-2 text-xs font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">
            Operator Tools
          </p>

          <div className="mt-2 space-y-1">
            {ADMIN_NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/app"}
                onClick={onNavigate}
                className={({ isActive }) =>
                  `group relative flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-300 ${isActive
                    ? "bg-slate-100 dark:bg-white/10 text-brand-700 dark:text-white shadow-inner"
                    : "text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-white/5 hover:text-slate-900 dark:hover:text-slate-300"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && <div className="absolute left-0 top-1.5 bottom-1.5 w-0.5 bg-brand-500 dark:bg-slate-300 rounded-r-full" />}
                    <Icon className={`w-4 h-4 shrink-0 transition-transform ${isActive ? "scale-110" : ""}`} />
                    <span className="relative z-10">{label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      <div className="px-6 py-5 border-t border-slate-200 dark:border-slate-800/60 flex items-center justify-between text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-600">
        <span>v1.0.0-oss</span>
        <span className="flex h-1.5 w-1.5"><span className="animate-ping absolute inline-flex h-1.5 w-1.5 rounded-full bg-brand-400 opacity-75"></span><span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-brand-500"></span></span>
      </div>
    </>
  );
}

function PrimaryNav() {
  return (
    <nav
      aria-label="Primary workspace navigation"
      className="flex min-w-0 items-center justify-start gap-1 overflow-x-auto custom-scrollbar md:justify-center lg:gap-2"
    >
      {PRIMARY_NAV.map(({ to, label, primary }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/app"}
          className={({ isActive }) => {
            if (primary) {
              return `inline-flex h-10 shrink-0 items-center rounded-xl px-4 text-sm font-bold transition-all duration-200 ${
                isActive
                  ? "bg-brand-600 text-white shadow-lg shadow-brand-500/20"
                  : "bg-slate-900 text-white shadow-sm hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
              }`;
            }

            return `inline-flex h-10 shrink-0 items-center rounded-xl px-3.5 text-sm font-semibold transition-all duration-200 ${
              isActive
                ? "bg-slate-100 text-slate-950 ring-1 ring-slate-200 dark:bg-white/10 dark:text-white dark:ring-white/10"
                : "text-slate-600 hover:bg-slate-100/80 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-white/10 dark:hover:text-white"
            }`;
          }}
        >
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

function HeaderBrand() {
  return (
    <Link to="/" className="flex min-w-0 items-center gap-3 group">
      <span className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white font-bold text-[13px] shadow-[0_0_12px_rgba(79,70,229,0.4)] group-hover:scale-105 transition-transform">
        CE
      </span>
      <span className="font-bold text-slate-900 dark:text-white text-sm tracking-wide">
        Context Engine
      </span>
    </Link>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader fullscreen />}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/app/*" element={<AdminShell />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}

function AdminShell() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const location = useLocation();

  let pageTitle;
  const modelMatch = location.pathname.match(/^\/app\/model\/(.+)/);
  if (modelMatch) {
    pageTitle = "Model Detail";
  } else {
    const allNav = [...PRIMARY_NAV, ...ADMIN_NAV];
    pageTitle =
      allNav.find((n) =>
        n.to === "/app" ? location.pathname === "/app" : location.pathname.startsWith(n.to),
      )?.label ?? "Dashboard";
  }

  return (
    <WorkspaceBootstrap>
      <div className="flex h-screen flex-col overflow-hidden bg-slate-50/50 dark:bg-slate-900 transition-colors duration-300">
        {/* ── Mobile overlay ──────────────────────── */}
        {mobileNavOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/50 md:hidden"
            onClick={() => setMobileNavOpen(false)}
          />
        )}

        <header className="relative z-30 shrink-0 border-b border-slate-200/70 bg-white/90 backdrop-blur-xl transition-colors duration-300 supports-[backdrop-filter]:bg-white/75 dark:border-white/10 dark:bg-[#090b0d]/95 dark:supports-[backdrop-filter]:bg-[#090b0d]/85">
          <div className="grid min-h-20 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 md:grid-cols-[16rem_minmax(0,1fr)_auto] md:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <button
                className="-ml-2 rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-white/10 md:hidden"
                onClick={() => setMobileNavOpen(true)}
                aria-label="Open operator tools"
              >
                <HamburgerIcon className="h-5 w-5" />
              </button>
              <HeaderBrand />
            </div>

            <div className="hidden min-w-0 justify-center md:flex">
              <PrimaryNav />
            </div>

            <div className="flex min-w-0 shrink-0 items-center justify-end gap-3">
              <WorkspaceSwitcher />
              <ThemeToggle />
            </div>

            <div className="col-span-3 min-w-0 md:hidden">
              <PrimaryNav />
            </div>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* ── Mobile drawer ───────────────────────── */}
        <aside
          className={`fixed inset-y-0 left-0 z-50 w-64 flex flex-col bg-white dark:bg-slate-950 text-slate-700 dark:text-slate-300 transform transition-transform duration-300 ease-in-out md:hidden shadow-2xl ${mobileNavOpen ? "translate-x-0" : "-translate-x-full"
            }`}
        >
          <SidebarContent onNavigate={() => setMobileNavOpen(false)} />
        </aside>

        {/* ── Desktop sidebar ─────────────────────── */}
        <aside className="hidden md:flex md:w-64 flex-col bg-white dark:bg-slate-950 border-r border-slate-200/60 dark:border-slate-900 shadow-xl z-20 transition-colors duration-300">
          <SidebarContent onNavigate={() => { }} />
        </aside>

        {/* ── Main area ───────────────────────────── */}
        <div className="flex-1 flex flex-col overflow-hidden bg-slate-50/50 dark:bg-slate-900 relative transition-colors duration-300">
          <div className="absolute inset-0 z-0 pointer-events-none bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-brand-100/40 via-transparent to-transparent dark:from-brand-900/20"></div>

          <main className="flex-1 overflow-y-auto p-6 md:p-8 dark:text-slate-100">
            <h1 className="sr-only">{pageTitle}</h1>
            <Suspense fallback={<PageLoader />}>
              <Routes>
                <Route index element={<Dashboard />} />
                <Route path="brief" element={<FounderBrief />} />
                <Route path="decisions" element={<DecisionRegister />} />
                <Route path="changes" element={<Changes />} />
                <Route path="launch-guard" element={<LaunchGuard />} />
                <Route path="meetings" element={<Meetings />} />
                <Route path="meetings/:documentId" element={<Meetings />} />
                <Route path="engineering" element={<Engineering />} />
                <Route path="engineering/:documentId" element={<Engineering />} />
                <Route path="status" element={<SystemHealth />} />
                <Route path="accuracy" element={<Accuracy />} />
                <Route path="models" element={<Models />} />
                <Route path="query" element={<Query />} />
                <Route path="review" element={<ReviewQueue />} />
                <Route path="review/:itemId" element={<ReviewQueue />} />
                <Route path="connectors" element={<Connectors />} />
                <Route path="connectors/:connectorType/runs" element={<ConnectorRuns />} />
                <Route path="sources" element={<Sources />} />
                <Route path="sources/:documentId" element={<Sources />} />
                <Route path="graph" element={<KnowledgeGraph />} />
                <Route path="model/:modelId" element={<ModelDetail />} />
                <Route path="*" element={<Navigate to="/app" replace />} />
              </Routes>
            </Suspense>
          </main>
        </div>
        </div>
      </div>
    </WorkspaceBootstrap>
  );
}

function PageLoader({ fullscreen = false }) {
  return (
    <div
      className={
        fullscreen
          ? "min-h-screen bg-slate-50 dark:bg-slate-900 flex items-center justify-center px-6 transition-colors"
          : "min-h-[300px] flex items-center justify-center rounded-2xl border border-slate-200/60 dark:border-slate-700/60 bg-white/50 dark:bg-slate-800/50 backdrop-blur-sm px-6 shadow-sm transition-colors"
      }
    >
      <div className="text-center flex flex-col items-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 dark:border-brand-800 border-t-brand-600 dark:border-t-brand-400 mb-4" />
        <p className="text-sm font-bold text-slate-800 dark:text-slate-200 tracking-tight">Loading view...</p>
        <p className="mt-1.5 text-xs font-medium text-slate-500 dark:text-slate-400">
          Pulling context into the shell
        </p>
      </div>
    </div>
  );
}

/* ── Inline SVG icons (keeps deps minimal) ──────────────────── */

function BarChartIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 12h4v9H3zm7-5h4v14h-4zm7-4h4v18h-4z" />
    </svg>
  );
}

function PlugIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 2v4m-4-2h8m-6 4v4a2 2 0 002 2h0a2 2 0 002-2V8m-4 6v4m0 0H8m4 0h4" />
    </svg>
  );
}

function PulseIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 12h4l2-6 4 12 2-6h6" />
    </svg>
  );
}

function GaugeIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.93 19a10 10 0 1114.14 0H4.93z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 13l3-3" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 17h.01" />
    </svg>
  );
}

function CodeIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l-4 3 4 3M16 9l4 3-4 3M14 5l-4 14" />
    </svg>
  );
}

function GraphIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <circle cx="5" cy="12" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path strokeLinecap="round" d="M7 11l10-4M7 13l10 4" />
    </svg>
  );
}

function SearchIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function ShieldCheckIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l7 4v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V7l7-4z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4" />
    </svg>
  );
}

function CubeIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12" />
    </svg>
  );
}

function HamburgerIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  );
}

function DocumentStackIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h8M8 11h8M8 15h5" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 3h9a2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5a2 2 0 012-2z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 21h9a2 2 0 002-2V8" />
    </svg>
  );
}

function BriefIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 6h10M8 10h10M8 14h6" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 4h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z" />
    </svg>
  );
}

function DecisionIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 4h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z" />
    </svg>
  );
}

function ChangesIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h8M8 12h8M8 17h5" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 7h.01M4 12h.01M4 17h.01" />
    </svg>
  );
}

function GuardIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3l7 4v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V7l7-4z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6" />
    </svg>
  );
}

function MeetingIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <rect x="4" y="6" width="12" height="10" rx="2" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M16 10l4-2v6l-4-2" />
    </svg>
  );
}
