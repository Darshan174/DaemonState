import { Suspense, lazy, useState } from "react";
import { Routes, Route, NavLink, Navigate, Link, useLocation } from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";
import CeIcon from "./components/CeIcon";
import WorkspaceSwitcher from "./components/WorkspaceSwitcher";
import { useWorkspaces } from "./api/hooks";
import {
  Activity,
  Cable,
  Database,
  PackageCheck,
  PanelLeftClose,
  PanelLeftOpen,
  PlayCircle,
  Waypoints,
} from "lucide-react";

const ContextMapPage = lazy(() => import("./pages/ContextMapPage"));
const NowPage        = lazy(() => import("./pages/NowPage"));
const PreparePage    = lazy(() => import("./pages/PreparePage"));
const RunsPage       = lazy(() => import("./pages/RunsPage"));
const QueryView    = lazy(() => import("./pages/QueryView"));
const SourceManager = lazy(() => import("./pages/SourceManager"));
const Landing      = lazy(() => import("./pages/Landing"));
const Connectors   = lazy(() => import("./pages/Connectors"));
const Changes      = lazy(() => import("./pages/Changes"));

const NAV_ITEMS = [
  { to: "/app", label: "Now", icon: Activity, end: true },
  { to: "/app/prepare", label: "Prepare", icon: PackageCheck },
  { to: "/app/runs", label: "Runs", icon: PlayCircle },
  { to: "/app/explain", label: "Explain", icon: Waypoints },
  { to: "/app/sources", label: "Sources", icon: Database },
  { to: "/app/connectors", label: "Connectors", icon: Cable },
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
  const isProjectPage = location.pathname === "/app/explain" || location.pathname === "/app/explain/";
  const { data: workspaces } = useWorkspaces();
  const showWorkspaceSwitcher = (workspaces?.length ?? 0) > 1;
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem("ce_sidebar_collapsed") === "true"; }
    catch { return false; }
  });

  const toggleSidebar = () => {
    setSidebarCollapsed((current) => {
      const next = !current;
      try { localStorage.setItem("ce_sidebar_collapsed", String(next)); } catch {}
      window.setTimeout(() => window.dispatchEvent(new Event("resize")), 220);
      return next;
    });
  };

  return (
    <div className="flex h-screen overflow-hidden bg-[#f7f7f2] text-[#171713] transition-colors duration-300 dark:bg-transparent dark:text-[#f4f4ec]">
      <aside
        id="desktop-sidebar"
        className={`relative hidden shrink-0 flex-col border-r border-[#d9d9d0] bg-[#f2f2eb] p-4 transition-[width] duration-200 dark:border-[#292925] dark:bg-[#10100e] lg:flex ${sidebarCollapsed ? "w-[72px]" : "w-[232px]"}`}
      >
        <button
          type="button"
          onClick={toggleSidebar}
          aria-controls="desktop-sidebar"
          aria-expanded={!sidebarCollapsed}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute -right-3 top-[72px] z-40 flex h-7 w-7 items-center justify-center rounded-full border border-[#d9d9d0] bg-[#fbfbf6] text-[#68685f] shadow-sm transition hover:text-[#171713] focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-[#35352f] dark:bg-[#171713] dark:text-[#a2a298] dark:hover:text-white"
        >
          {sidebarCollapsed ? <PanelLeftOpen className="h-3.5 w-3.5" /> : <PanelLeftClose className="h-3.5 w-3.5" />}
        </button>
        <Link to="/" title={sidebarCollapsed ? "Context Engine" : undefined} className={`group flex items-center py-2 ${sidebarCollapsed ? "justify-center px-0" : "gap-3 px-2"}`}>
          <span className="transition-transform duration-200 group-hover:scale-105"><CeIcon size={34} /></span>
          <span className={sidebarCollapsed ? "sr-only" : "min-w-0"}>
            <span className="block truncate text-sm font-semibold leading-tight">Context Engine</span>
            <span className="mt-0.5 block text-[10px] uppercase tracking-[0.12em] text-[#77776e] dark:text-[#929289]">Context compiler</span>
          </span>
        </Link>

        <nav aria-label="Application" className="mt-8 flex-1 space-y-1">
          {NAV_ITEMS.map((item) => <ShellNavLink key={item.to} collapsed={sidebarCollapsed} {...item} />)}
        </nav>

        <div className="space-y-3 border-t border-[#d9d9d0] pt-4 dark:border-[#292925]">
          {showWorkspaceSwitcher ? (
            sidebarCollapsed ? (
              <button type="button" onClick={toggleSidebar} title="Expand to switch workspace" aria-label="Expand sidebar to switch workspace" className="flex h-9 w-full items-center justify-center rounded-md text-[#68685f] hover:bg-[#e8e8e0] dark:text-[#a2a298] dark:hover:bg-[#1f1f1b]">
                <Database className="h-4 w-4" />
              </button>
            ) : <WorkspaceSwitcher variant="sidebar" />
          ) : null}
          <div className={`flex items-center ${sidebarCollapsed ? "justify-center" : "justify-between px-2"}`}>
            <span className={sidebarCollapsed ? "sr-only" : "text-xs font-medium text-[#77776e] dark:text-[#929289]"}>Appearance</span>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-[#d9d9d0] bg-[#f7f7f2]/95 backdrop-blur-xl dark:border-[#292925] dark:bg-[#0d0d0b]/95 lg:hidden">
          <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <Link to="/" className="flex min-w-0 items-center gap-2.5">
              <CeIcon size={30} />
              <span className="truncate text-sm font-semibold">Context Engine</span>
            </Link>
            <div className="flex min-w-0 items-center gap-2">
              {showWorkspaceSwitcher ? <WorkspaceSwitcher /> : null}
              <ThemeToggle />
            </div>
          </div>
          <nav aria-label="Application" className="flex gap-1 overflow-x-auto border-t border-[#e5e5dd] px-4 py-2 no-scrollbar dark:border-[#1d1d1a] sm:px-6">
            {NAV_ITEMS.map((item) => <ShellNavLink key={item.to} compact {...item} />)}
          </nav>
        </header>

        <main className={`relative min-h-0 flex-1 dark:text-[#f4f4ec] ${isProjectPage ? "overflow-hidden" : "overflow-y-auto px-5 py-7 sm:px-8 sm:py-9"}`}>
        {!isProjectPage ? (
          <div className="pointer-events-none absolute inset-x-0 top-0 h-28 border-b border-[#e7e7df] bg-[linear-gradient(180deg,rgba(255,255,255,0.48),rgba(247,247,242,0))] dark:border-[#1d1d1a] dark:bg-[linear-gradient(180deg,rgba(255,255,255,0.025),rgba(13,13,11,0))]" />
        ) : null}
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route index                                  element={<NowPage />} />
            <Route path="prepare"                         element={<PreparePage />} />
            <Route path="runs"                            element={<RunsPage />} />
            <Route path="explain"                         element={<ContextMapPage />} />
            <Route path="dashboard"                       element={<Navigate to="/app" replace />} />
            <Route path="graph"                           element={<Navigate to="/app/explain" replace />} />
            <Route path="query"                           element={<QueryView />} />
            <Route path="sources"                         element={<SourceManager />} />
            <Route path="agents"                          element={<Navigate to="/app" replace />} />
            <Route path="connectors"                      element={<Connectors />} />
            <Route path="connectors/:connectorType/runs"  element={<Connectors />} />
            <Route path="changes"                         element={<Changes />} />
            <Route path="*"                               element={<Navigate to="/app" replace />} />
          </Routes>
        </Suspense>
        </main>
      </div>
    </div>
  );
}

function ShellNavLink({ to, label, icon: Icon, end, compact = false, collapsed = false }) {
  return (
    <NavLink
      to={to}
      end={end || to === "/app"}
      title={collapsed ? label : undefined}
      aria-label={collapsed ? label : undefined}
      className={({ isActive }) =>
        `group relative flex items-center whitespace-nowrap rounded-sm text-[13px] font-semibold transition-colors ${collapsed ? "justify-center gap-0" : "gap-3"} ${
          compact ? "h-9 px-3" : collapsed ? "h-10 px-0" : "h-10 px-3"
        } ${
          isActive
            ? "bg-[#171713] text-white dark:bg-[#d9ff68] dark:text-[#171713]"
            : "text-[#68685f] hover:bg-[#e8e8e0] hover:text-[#171713] dark:text-[#a2a298] dark:hover:bg-[#1f1f1b] dark:hover:text-[#f4f4ec]"
        }`
      }
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className={collapsed ? "sr-only" : undefined}>{label}</span>
    </NavLink>
  );
}
