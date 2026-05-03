import { Suspense, lazy } from "react";
import { Routes, Route, NavLink, Navigate, Link, useLocation } from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";
import CeIcon from "./components/CeIcon";

const GraphView    = lazy(() => import("./pages/GraphView"));
const QueryView    = lazy(() => import("./pages/QueryView"));
const SourceManager = lazy(() => import("./pages/SourceManager"));
const Landing      = lazy(() => import("./pages/Landing"));
const Dashboard    = lazy(() => import("./pages/Dashboard"));
const Connectors   = lazy(() => import("./pages/Connectors"));
const Changes      = lazy(() => import("./pages/Changes"));
const AgentsView   = lazy(() => import("./pages/AgentsView"));

const NAV_ITEMS = [
  { to: "/app",             label: "Dashboard", end: true },
  { to: "/app/graph",       label: "Graph" },
  { to: "/app/agents",      label: "Agents",  badge: "AI" },
  { to: "/app/query",       label: "Ask" },
  { to: "/app/sources",     label: "Sources" },
  { to: "/app/connectors",  label: "Connectors" },
  { to: "/app/changes",     label: "Changes" },
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

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-50 dark:bg-[#0a0c0f] transition-colors duration-300">
      <header className="shrink-0 border-b border-slate-200/80 dark:border-white/[0.07] bg-white/95 dark:bg-[#0d1117]/95 backdrop-blur-xl">
        <div className="flex h-14 items-center justify-between px-4 md:px-6 gap-4">
          {/* Brand */}
          <Link to="/" className="flex items-center gap-2.5 group shrink-0">
            <span className="group-hover:scale-105 transition-transform duration-200">
              <CeIcon size={30} />
            </span>
            <span className="font-bold text-slate-900 dark:text-white text-sm tracking-tight hidden sm:block">
              Context Engine
            </span>
          </Link>

          {/* Nav */}
          <nav className="flex items-center gap-0.5 overflow-x-auto no-scrollbar">
            {NAV_ITEMS.map(({ to, label, end, badge }) => (
              <NavLink
                key={to}
                to={to}
                end={end || to === "/app"}
                className={({ isActive }) =>
                  `relative inline-flex items-center gap-1.5 h-9 px-3.5 text-[13px] font-medium rounded-lg transition-all duration-150 whitespace-nowrap ${
                    isActive
                      ? "bg-slate-100 dark:bg-white/10 text-slate-900 dark:text-white font-semibold"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-50 dark:hover:bg-white/5"
                  }`
                }
              >
                {label}
                {badge && (
                  <span className="text-[9px] font-black px-1 py-0.5 rounded bg-brand-500 text-white leading-none tracking-wide">
                    {badge}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          <ThemeToggle />
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6 md:px-6 dark:text-slate-100">
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route index                                  element={<Dashboard />} />
            <Route path="dashboard"                       element={<Navigate to="/app" replace />} />
            <Route path="graph"                           element={<GraphView />} />
            <Route path="query"                           element={<QueryView />} />
            <Route path="sources"                         element={<SourceManager />} />
            <Route path="agents"                          element={<AgentsView />} />
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
