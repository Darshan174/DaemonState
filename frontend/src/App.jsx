import { Suspense, lazy } from "react";
import { Routes, Route, NavLink, Navigate, Link } from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";
import CeIcon from "./components/CeIcon";

const GraphView = lazy(() => import("./pages/GraphView"));
const QueryView = lazy(() => import("./pages/QueryView"));
const SourceManager = lazy(() => import("./pages/SourceManager"));
const Landing = lazy(() => import("./pages/Landing"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Connectors = lazy(() => import("./pages/Connectors"));
const Changes = lazy(() => import("./pages/Changes"));

const NAV_ITEMS = [
  { to: "/app", label: "Dashboard", end: true },
  { to: "/app/graph", label: "Graph" },
  { to: "/app/query", label: "Ask" },
  { to: "/app/sources", label: "Sources" },
  { to: "/app/connectors", label: "Connectors" },
  { to: "/app/changes", label: "Changes" },
];

function HeaderBrand() {
  return (
    <Link to="/" className="flex min-w-0 items-center gap-3 group">
      <span className="group-hover:scale-105 transition-transform">
        <CeIcon size={34} />
      </span>
      <span className="font-bold text-slate-900 dark:text-white text-sm tracking-wide">
        Context Engine
      </span>
    </Link>
  );
}

function PageLoader() {
  return (
    <div className="min-h-[300px] flex items-center justify-center">
      <div className="text-center flex flex-col items-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 dark:border-brand-800 border-t-brand-600 dark:border-t-brand-400 mb-4" />
        <p className="text-sm font-bold text-slate-800 dark:text-slate-200 tracking-tight">Loading...</p>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/app/*" element={<AdminShell />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}

function AdminShell() {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-50/50 dark:bg-slate-900 transition-colors duration-300">
      <header className="shrink-0 border-b border-slate-200/70 bg-white/90 backdrop-blur-xl dark:border-white/10 dark:bg-[#090b0d]/95">
        <div className="flex min-h-16 items-center justify-between px-4 md:px-6">
          <HeaderBrand />

          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/app"}
                className={({ isActive }) =>
                  `inline-flex h-10 items-center rounded-xl px-4 text-sm font-semibold transition-all duration-200 ${
                    isActive
                      ? "bg-slate-100 text-slate-950 ring-1 ring-slate-200 dark:bg-white/10 dark:text-white dark:ring-white/10"
                      : "text-slate-600 hover:bg-slate-100/80 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-white/10 dark:hover:text-white"
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>

          <ThemeToggle />
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-4 md:p-6 dark:text-slate-100">
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route index element={<Dashboard />} />
            <Route path="dashboard" element={<Navigate to="/app" replace />} />
            <Route path="graph" element={<GraphView />} />
            <Route path="query" element={<QueryView />} />
            <Route path="sources" element={<SourceManager />} />
            <Route path="connectors" element={<Connectors />} />
            <Route path="connectors/:connectorType/runs" element={<Connectors />} />
            <Route path="changes" element={<Changes />} />
            <Route path="*" element={<Navigate to="/app" replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}
