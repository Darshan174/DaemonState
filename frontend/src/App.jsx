import { Suspense, lazy, useState } from "react";
import { Routes, Route, NavLink, Navigate, Link, useLocation } from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";
import CeIcon from "./components/CeIcon";
import ContinuityRail from "./components/ContinuityRail";
import ProductLoadingState from "./components/ProductLoadingState";
import WorkspaceSwitcher from "./components/WorkspaceSwitcher";
import { useWorkspaceSelection } from "./context/WorkspaceContext";
import {
  Activity,
  Cable,
  Database,
  LibraryBig,
  BrainCircuit,
  PanelLeftClose,
  PanelLeftOpen,
  PlayCircle,
  Waypoints,
} from "lucide-react";

const ContextMapPage = lazy(() => import("./pages/ContextMapPage"));
const NowPage        = lazy(() => import("./pages/NowPage"));
const PreparePage    = lazy(() => import("./pages/PreparePage"));
const RunsPage       = lazy(() => import("./pages/RunsPage"));
const SessionLibrary = lazy(() => import("./pages/SessionLibrary"));
const ProjectMemory  = lazy(() => import("./pages/ProjectMemory"));
const QueryView    = lazy(() => import("./pages/QueryView"));
const SourceManager = lazy(() => import("./pages/SourceManager"));
const Landing      = lazy(() => import("./pages/Landing"));
const Connectors   = lazy(() => import("./pages/Connectors"));
const Changes      = lazy(() => import("./pages/Changes"));
const WorkspacesPage = lazy(() => import("./pages/WorkspacesPage"));

const NAV_ITEMS = [
  { to: "/app", label: "Now", icon: Activity, end: true },
  { to: "/app/runs", label: "Runs", icon: PlayCircle },
  { to: "/app/library", label: "Library", icon: LibraryBig },
  { to: "/app/memory", label: "Memory", icon: BrainCircuit },
  { to: "/app/explain", label: "Explain", icon: Waypoints },
  { to: "/app/sources", label: "Sources", icon: Database },
  { to: "/app/connectors", label: "Connectors", icon: Cable },
];

function PageLoader({ fullScreen = false }) {
  return (
    <ProductLoadingState
      label="Loading your project…"
      stages={["Opening the workspace", "Loading the product surface", "Preparing the verified view"]}
      fullScreen={fullScreen}
    />
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader fullScreen />}>
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
  const { selectedId } = useWorkspaceSelection();
  const isProjectPage = location.pathname === "/app/explain" || location.pathname === "/app/explain/";
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
    <div className="app-shell flex h-screen overflow-hidden text-[#171713] transition-colors duration-300 dark:text-[#f4f4ec]">
      <aside
        id="desktop-sidebar"
        className={`relative hidden shrink-0 flex-col border-r border-[#deded6]/90 bg-[#f1f1ea]/90 p-3 backdrop-blur-xl transition-[width] duration-300 ease-out dark:border-[#202020] dark:bg-[#030303]/95 lg:flex ${sidebarCollapsed ? "w-[76px]" : "w-[248px]"}`}
      >
        <button
          type="button"
          onClick={toggleSidebar}
          aria-controls="desktop-sidebar"
          aria-expanded={!sidebarCollapsed}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute -right-3 top-[72px] z-40 flex h-7 w-7 items-center justify-center rounded-full border border-[#d9d9d0] bg-[#fbfbf6] text-[#68685f] shadow-[0_4px_12px_rgba(23,23,19,0.08)] transition-all duration-200 hover:scale-105 hover:border-[#bdbdb4] hover:text-[#171713] focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-[#2b2b2b] dark:bg-[#0c0c0c] dark:text-[#a2a298] dark:hover:border-[#444444] dark:hover:text-white"
        >
          {sidebarCollapsed ? <PanelLeftOpen className="h-3.5 w-3.5" /> : <PanelLeftClose className="h-3.5 w-3.5" />}
        </button>
        <Link to="/" title={sidebarCollapsed ? "Context Engine" : undefined} className={`group flex h-12 items-center rounded-xl transition-colors hover:bg-white/60 dark:hover:bg-white/[0.03] ${sidebarCollapsed ? "justify-center px-0" : "gap-3 px-2"}`}>
          <span className="transition-transform duration-300 ease-out group-hover:-rotate-3 group-hover:scale-105"><CeIcon size={34} /></span>
          <span className={sidebarCollapsed ? "sr-only" : "min-w-0"}>
            <span className="block truncate text-sm font-bold leading-tight tracking-[-0.015em]">Context Engine</span>
            <span className="mt-0.5 block text-[9px] font-semibold uppercase tracking-[0.17em] text-[#77776e] dark:text-[#929289]">Project memory</span>
          </span>
        </Link>

        <p className={sidebarCollapsed ? "sr-only" : "mb-2 mt-7 px-3 text-[9px] font-bold uppercase tracking-[0.18em] text-[#8a8a80] dark:text-[#77776e]"}>Workspace</p>
        <nav aria-label="Application" className={`${sidebarCollapsed ? "mt-7" : ""} flex-1 space-y-1`}>
          {NAV_ITEMS.map((item) => <ShellNavLink key={item.to} collapsed={sidebarCollapsed} {...item} />)}
        </nav>

        <div className="space-y-3 border-t border-[#d9d9d0] pt-4 dark:border-[#202020]">
          {sidebarCollapsed ? (
            <button type="button" onClick={toggleSidebar} title="Expand to switch workspace" aria-label="Expand sidebar to switch workspace" className="flex h-9 w-full items-center justify-center rounded-md text-[#68685f] hover:bg-[#e8e8e0] dark:text-[#a2a298] dark:hover:bg-[#121212]">
              <Database className="h-4 w-4" />
            </button>
          ) : <WorkspaceSwitcher variant="sidebar" />}
          <div className={`flex items-center ${sidebarCollapsed ? "justify-center" : "justify-between px-2"}`}>
            <span className={sidebarCollapsed ? "sr-only" : "text-[11px] font-medium text-[#77776e] dark:text-[#929289]"}>Appearance</span>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="relative z-40 shrink-0 border-b border-[#d9d9d0]/90 bg-[#f7f7f2]/90 backdrop-blur-xl dark:border-[#202020] dark:bg-black/95 lg:hidden">
          <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <Link to="/" className="flex min-w-0 items-center gap-2.5">
              <CeIcon size={30} />
              <span className="truncate text-sm font-semibold">Context Engine</span>
            </Link>
            <div className="flex min-w-0 items-center gap-2">
              <WorkspaceSwitcher />
              <ThemeToggle />
            </div>
          </div>
          <nav aria-label="Application" className="no-scrollbar flex gap-1 overflow-x-auto border-t border-[#e5e5dd] px-4 py-2 dark:border-[#181818] sm:px-6">
            {NAV_ITEMS.map((item) => <ShellNavLink key={item.to} compact {...item} />)}
          </nav>
        </header>

        <main className={`app-main relative min-h-0 flex-1 dark:text-[#f4f4ec] ${isProjectPage ? "overflow-hidden" : "overflow-y-auto px-4 py-6 sm:px-7 sm:py-8 xl:px-10 xl:py-10"}`}>
        {!isProjectPage ? (
          <div className="pointer-events-none absolute inset-x-0 top-0 h-48 border-b border-[#e7e7df]/70 bg-[radial-gradient(circle_at_75%_0%,rgba(217,255,104,0.14),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.7),rgba(247,247,242,0))] dark:border-[#171717] dark:bg-[radial-gradient(circle_at_75%_0%,rgba(217,255,104,0.035),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.018),rgba(0,0,0,0))]" />
        ) : null}
        <div
          className={`page-enter relative z-10 ${isProjectPage ? "h-full min-h-0" : ""}`}
          key={`${selectedId || "unselected-workspace"}:${location.pathname}`}
        >
          {!isProjectPage ? <ContinuityRail pathname={location.pathname} className="mb-6" /> : null}
          <Suspense fallback={<PageLoader />}>
            <Routes>
              <Route index                                  element={<NowPage />} />
              <Route path="prepare"                         element={<PreparePage />} />
              <Route path="runs"                            element={<RunsPage />} />
              <Route path="library"                         element={<SessionLibrary />} />
              <Route path="memory"                          element={<ProjectMemory />} />
              <Route path="explain"                         element={<ContextMapPage />} />
              <Route path="dashboard"                       element={<Navigate to="/app" replace />} />
              <Route path="graph"                           element={<Navigate to="/app/explain" replace />} />
              <Route path="query"                           element={<QueryView />} />
              <Route path="sources"                         element={<SourceManager />} />
              <Route path="agents"                          element={<Navigate to="/app" replace />} />
              <Route path="connectors"                      element={<Connectors />} />
              <Route path="connectors/:connectorType/runs"  element={<Connectors />} />
              <Route path="changes"                         element={<Changes />} />
              <Route path="workspaces"                      element={<WorkspacesPage />} />
              <Route path="*"                               element={<Navigate to="/app" replace />} />
            </Routes>
          </Suspense>
        </div>
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
        `group relative flex items-center whitespace-nowrap rounded-xl text-[13px] font-semibold transition-all duration-200 ${collapsed ? "justify-center gap-0" : "gap-3"} ${
          compact ? "h-9 px-3" : collapsed ? "h-10 px-0" : "h-10 px-3"
        } ${
          isActive
            ? "bg-white text-[#171713] shadow-[0_1px_2px_rgba(23,23,19,0.06),0_4px_14px_rgba(23,23,19,0.04)] dark:bg-[#141414] dark:text-white dark:shadow-[inset_0_0_0_1px_rgba(217,255,104,0.06)]"
            : "text-[#68685f] hover:bg-white/65 hover:text-[#171713] dark:text-[#a2a298] dark:hover:bg-white/[0.045] dark:hover:text-[#f4f4ec]"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon className={`h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-105 ${isActive ? "text-[#171713] dark:text-[#d9ff68]" : ""}`} />
          <span className={collapsed ? "sr-only" : undefined}>{label}</span>
          {isActive ? <span className={`absolute h-1.5 w-1.5 rounded-full bg-[#b8dc45] dark:bg-[#d9ff68] ${collapsed ? "right-1.5" : "right-3"}`} /> : null}
        </>
      )}
    </NavLink>
  );
}
