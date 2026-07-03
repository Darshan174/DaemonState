import { Suspense, lazy } from "react";
import { Routes, Route, NavLink, Navigate, Link, useLocation } from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";
import CeIcon from "./components/CeIcon";
import WorkspaceSwitcher from "./components/WorkspaceSwitcher";
import { useWorkspaces } from "./api/hooks";
import {
  Activity,
  Cable,
  CircleDot,
  Database,
  GitBranch,
  LayoutDashboard,
  Search,
} from "lucide-react";

const ContextMapPage = lazy(() => import("./pages/ContextMapPage"));
const QueryView    = lazy(() => import("./pages/QueryView"));
const SourceManager = lazy(() => import("./pages/SourceManager"));
const Landing      = lazy(() => import("./pages/Landing"));
const Dashboard    = lazy(() => import("./pages/Dashboard"));
const Connectors   = lazy(() => import("./pages/Connectors"));
const Changes      = lazy(() => import("./pages/Changes"));
const AgentsView   = lazy(() => import("./pages/AgentsView"));

const NAV_ITEMS = [
  { to: "/app",             label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/app/graph",       label: "Graph", icon: GitBranch },
  { to: "/app/query",       label: "Ask", icon: Search },
  { to: "/app/sources",     label: "Sources", icon: Database },
  { to: "/app/connectors",  label: "Connectors", icon: Cable },
  { to: "/app/changes",     label: "Changes", icon: Activity },
];

function PageLoader() {
  return (
    <div className="min-h-[300px] flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="h-7 w-7 animate-spin rounded-full border-[3px] border-brand-200 dark:border-brand-800 border-t-brand-600 dark:border-t-brand-400" />
        <p className="text-xs font-semibold text-slate-400 tracking-wide">Loading…</p>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="/"      element={<Landing />} />
        <Route path="/app/*" element={<AdminShell />} />
        <Route path="*"      element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}

function AdminShell() {
  const location = useLocation();
  const isGraphPage = location.pathname === "/app/graph";
  const { data: workspaces } = useWorkspaces();
  const showWorkspaceSwitcher = (workspaces?.length ?? 0) > 1;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[#f5f6f8] text-slate-950 transition-colors duration-300 dark:bg-transparent dark:text-neutral-100">
      <header className="shrink-0 border-b border-black/[0.08] bg-white/78 backdrop-blur-2xl transition-colors dark:border-white/[0.08] dark:bg-[#050507]/82">
        <div className="mx-auto grid max-w-[1500px] grid-cols-[auto_1fr_auto] items-center gap-4 px-4 py-3 md:px-6">
          <Link to="/" className="group flex min-w-0 shrink-0 items-center gap-3">
            <span className="transition-transform duration-200 group-hover:scale-105">
              <CeIcon size={34} />
            </span>
            <span className="hidden sm:block">
              <span className="block text-sm font-bold leading-tight text-slate-950 dark:text-white">Context Engine</span>
              <span className="block text-[11px] leading-tight text-slate-500 dark:text-neutral-500">Project memory graph</span>
            </span>
          </Link>

          <nav className="mx-auto flex max-w-full items-center gap-1 overflow-x-auto rounded-lg border border-slate-200/80 bg-slate-100/80 p-1 no-scrollbar shadow-inner shadow-black/[0.03] dark:border-white/[0.08] dark:bg-white/[0.035]">
            {NAV_ITEMS.map(({ to, label, icon: Icon, end, badge }) => (
              <NavLink
                key={to}
                to={to}
                end={end || to === "/app"}
                className={({ isActive }) =>
                  `relative inline-flex h-8 items-center gap-2 rounded-md px-3 text-[12px] font-semibold transition-all duration-150 whitespace-nowrap ${
                    isActive
                      ? "bg-white text-slate-950 shadow-sm ring-1 ring-black/[0.04] dark:bg-white/[0.1] dark:text-white dark:ring-white/[0.08]"
                      : "text-slate-500 hover:bg-white/55 hover:text-slate-900 dark:text-neutral-500 dark:hover:bg-white/[0.05] dark:hover:text-neutral-200"
                  }`
                }
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
                {badge && (
                  <span className="text-[9px] font-black px-1 py-0.5 rounded bg-brand-500 text-white leading-none tracking-wide">
                    {badge}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          <div className="flex min-w-0 shrink-0 items-center justify-end gap-2">
            {showWorkspaceSwitcher ? <WorkspaceSwitcher /> : null}
            <div className="hidden items-center gap-1.5 rounded-lg border border-slate-200/80 bg-white/70 px-2.5 py-1.5 text-[11px] font-bold text-slate-500 dark:border-white/[0.08] dark:bg-white/[0.045] dark:text-neutral-400 md:flex">
              <CircleDot className="h-3 w-3 text-emerald-500" />
              Live
            </div>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className={`relative flex-1 min-h-0 dark:text-neutral-100 ${isGraphPage ? "overflow-hidden" : "overflow-y-auto px-4 py-7 md:px-6"}`}>
        {!isGraphPage ? (
          <div className="pointer-events-none absolute inset-x-0 top-0 h-40 border-b border-black/[0.04] bg-[linear-gradient(135deg,rgba(255,255,255,0.68),rgba(79,70,229,0.06),rgba(20,184,166,0.04))] dark:border-white/[0.04] dark:bg-[linear-gradient(135deg,rgba(255,255,255,0.055),rgba(94,106,210,0.10),rgba(20,184,166,0.045))]" />
        ) : null}
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route index                                  element={<Dashboard />} />
            <Route path="dashboard"                       element={<Navigate to="/app" replace />} />
            <Route path="graph"                           element={<ContextMapPage />} />
            <Route path="query"                           element={<QueryView />} />
            <Route path="sources"                         element={<SourceManager />} />
            <Route path="agents"                          element={<Navigate to="/app/graph" replace />} />
            <Route path="connectors"                      element={<Connectors />} />
            <Route path="connectors/:connectorType/runs"  element={<Connectors />} />
            <Route path="changes"                         element={<Changes />} />
            <Route path="*"                               element={<Navigate to="/app" replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}
