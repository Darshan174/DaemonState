import { Suspense, lazy } from "react";
import { Routes, Route, NavLink, Navigate, Link } from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";

const GraphView = lazy(() => import("./pages/GraphView"));
const QueryView = lazy(() => import("./pages/QueryView"));
const SourceManager = lazy(() => import("./pages/SourceManager"));

const NAV_ITEMS = [
  { to: "/app/graph", label: "Graph" },
  { to: "/app/query", label: "Ask" },
  { to: "/app/sources", label: "Sources" },
];

function HeaderBrand() {
  return (
    <Link to="/app/graph" className="flex min-w-0 items-center gap-3 group">
      <span className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white font-bold text-[13px] shadow-[0_0_12px_rgba(79,70,229,0.4)] group-hover:scale-105 transition-transform">
        CE
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
    <div className="flex h-screen flex-col overflow-hidden bg-slate-50/50 dark:bg-slate-900 transition-colors duration-300">
      <header className="shrink-0 border-b border-slate-200/70 bg-white/90 backdrop-blur-xl dark:border-white/10 dark:bg-[#090b0d]/95">
        <div className="flex min-h-16 items-center justify-between px-4 md:px-6">
          <HeaderBrand />

          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
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

      <main className="flex-1 overflow-hidden p-4 md:p-6 dark:text-slate-100">
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/" element={<Navigate to="/app/graph" replace />} />
            <Route path="/app" element={<Navigate to="/app/graph" replace />} />
            <Route path="/app/graph" element={<GraphView />} />
            <Route path="/app/query" element={<QueryView />} />
            <Route path="/app/sources" element={<SourceManager />} />
            <Route path="*" element={<Navigate to="/app/graph" replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}
