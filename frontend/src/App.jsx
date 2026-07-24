import { Suspense, lazy, useEffect, useState } from "react";
import { Routes, Route, NavLink, Navigate, Link, useLocation } from "react-router-dom";
import ThemeToggle from "./components/ThemeToggle";
import CeIcon from "./components/CeIcon";
import ProductLoadingState from "./components/ProductLoadingState";
import WorkspaceSwitcher from "./components/WorkspaceSwitcher";
import { useWorkspaceSelection } from "./context/WorkspaceContext";
import {
  Activity,
  Database,
  LibraryBig,
  BrainCircuit,
  Ellipsis,
  History,
  PanelLeftClose,
  PanelLeftOpen,
  PlugZap,
  Waypoints,
  X,
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

const WORKSPACE_NAV_ITEMS = [
  { to: "/app", label: "Now", icon: Activity, end: true },
  { to: "/app/library", label: "Library", icon: LibraryBig },
  { to: "/app/runs", label: "Resume", icon: History },
  { to: "/app/memory", label: "Memory", icon: BrainCircuit },
  { to: "/app/explain", label: "Evidence", icon: Waypoints },
];

const MOBILE_PRIMARY_ITEMS = WORKSPACE_NAV_ITEMS.filter(({ to }) => to !== "/app/explain");

const SETUP_NAV_ITEMS = [
  { to: "/app/sources", label: "Sources", icon: Database },
  { to: "/app/connectors", label: "Integrations", icon: PlugZap },
];

const NAV_GROUPS = [
  {
    label: "Workspace",
    items: WORKSPACE_NAV_ITEMS,
  },
  {
    label: "Setup",
    items: SETUP_NAV_ITEMS,
  },
];
const MOBILE_MORE_ITEMS = [
  WORKSPACE_NAV_ITEMS.find(({ to }) => to === "/app/explain"),
  ...SETUP_NAV_ITEMS,
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
  const isLibraryPage = location.pathname === "/app/library" || location.pathname === "/app/library/";
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
    <div className="app-shell ce-app-shell flex h-screen h-[100dvh] overflow-hidden text-ink transition-colors duration-300">
      <aside
        id="desktop-sidebar"
        className={`ce-app-sidebar relative hidden shrink-0 flex-col border-r border-line p-3 transition-[width] duration-300 ease-out lg:flex ${sidebarCollapsed ? "w-[76px]" : "w-[248px]"}`}
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
        <Link to="/" title={sidebarCollapsed ? "Context Engine" : undefined} className={`group flex h-16 items-center rounded-2xl text-[#171713] transition-colors hover:bg-[#f6f6f3] dark:text-white dark:hover:bg-white/[0.04] ${sidebarCollapsed ? "justify-center px-0" : "gap-3 px-2"}`}>
          <span className="transition-transform duration-300 ease-out group-hover:-rotate-3 group-hover:scale-105"><CeIcon size={34} /></span>
          <span className={sidebarCollapsed ? "sr-only" : "min-w-0"}>
            <span className="block truncate text-[17px] font-semibold leading-none tracking-[-0.025em]">Context Engine</span>
          </span>
        </Link>

        <nav aria-label="Application" className={`${sidebarCollapsed ? "mt-6" : "mt-7"} flex-1`}>
          {NAV_GROUPS.map((group) => (
            <ShellNavGroup key={group.label} group={group} collapsed={sidebarCollapsed} />
          ))}
        </nav>

        <div className="space-y-3 border-t border-line pt-4">
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
        <header className="ce-mobile-header relative z-40 shrink-0 border-b border-line backdrop-blur-xl lg:hidden">
          <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <Link to="/" aria-label="Context Engine home" className="flex min-w-0 items-center gap-2.5">
              <CeIcon size={30} />
              <span className="hidden truncate text-sm font-semibold sm:block">Context Engine</span>
            </Link>
            <div className="flex min-w-0 items-center gap-2">
              <WorkspaceSwitcher />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main className={`app-main ${isLibraryPage ? "" : "ce-app-canvas"} relative min-h-0 flex-1 ${isProjectPage ? "overflow-hidden" : "overflow-y-auto px-4 py-6 sm:px-7 sm:py-8 xl:px-10 xl:py-10"}`}>
        {!isProjectPage ? (
          <div className={isLibraryPage
            ? "pointer-events-none absolute inset-x-0 top-0 h-48 border-b border-[#e7e7df]/70 bg-[radial-gradient(circle_at_75%_0%,rgba(217,255,104,0.14),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.7),rgba(247,247,242,0))] dark:border-[#171717] dark:bg-[radial-gradient(circle_at_75%_0%,rgba(217,255,104,0.035),transparent_32%),linear-gradient(180deg,rgba(255,255,255,0.018),rgba(0,0,0,0))]"
            : "ce-app-ambient pointer-events-none absolute inset-x-0 top-0 h-64"
          } />
        ) : null}
        <div
          className={`page-enter relative z-10 ${isProjectPage ? "h-full min-h-0" : ""}`}
          key={`${selectedId || "unselected-workspace"}:${location.pathname}`}
        >
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
        <MobileNavigation pathname={location.pathname} />
      </div>
    </div>
  );
}

function ShellNavGroup({ group, collapsed }) {
  return (
    <div className="mb-6 last:mb-0">
      {collapsed ? (
        <div aria-hidden="true" className="mx-auto mb-3 h-px w-7 bg-[#d8d8cf] first:opacity-0 dark:bg-[#262626]" />
      ) : (
        <p className="mb-2 px-3 text-[11px] font-semibold text-[#8a8a80] dark:text-[#77776e]">{group.label}</p>
      )}
      <div className="space-y-1">
        {group.items.map((item) => <ShellNavLink key={item.to} collapsed={collapsed} {...item} />)}
      </div>
    </div>
  );
}

function ShellNavLink({ to, label, icon: Icon, end, collapsed = false }) {
  return (
    <NavLink
      to={to}
      end={end || to === "/app"}
      title={collapsed ? label : undefined}
      aria-label={collapsed ? label : undefined}
      className={({ isActive }) =>
        `group relative flex items-center whitespace-nowrap rounded-xl text-[13px] font-semibold transition-all duration-200 ${collapsed ? "justify-center gap-0" : "gap-3"} ${
          collapsed ? "h-10 px-0" : "h-10 px-3"
        } ${
          isActive
            ? "bg-ink text-canvas shadow-elevation-1"
            : "text-ink-muted hover:bg-surface-muted hover:text-ink"
        }`
      }
    >
      <Icon className="h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-105" />
      <span className={collapsed ? "sr-only" : undefined}>{label}</span>
    </NavLink>
  );
}

function MobileNavigation({ pathname }) {
  const [moreOpen, setMoreOpen] = useState(false);
  const moreRouteActive = MOBILE_MORE_ITEMS.some(({ to }) => pathname === to || pathname.startsWith(`${to}/`));

  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!moreOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setMoreOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [moreOpen]);

  return (
    <div className="relative z-50 shrink-0 lg:hidden">
      {moreOpen ? (
        <>
          <button
            type="button"
            aria-label="Close more menu"
            onClick={() => setMoreOpen(false)}
            className="fixed inset-0 z-0 cursor-default bg-black/30 backdrop-blur-[1px]"
          />
          <section
            id="mobile-more-destinations"
            aria-label="More destinations"
            className="ce-mobile-more-panel absolute inset-x-3 bottom-[calc(100%+0.75rem)] z-10 overflow-hidden rounded-stage border border-line bg-surface shadow-elevation-3"
          >
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-ink">More</p>
                <p className="mt-0.5 text-xs text-ink-muted">Evidence and setup</p>
              </div>
              <button
                type="button"
                onClick={() => setMoreOpen(false)}
                aria-label="Close more destinations"
                className="flex h-9 w-9 items-center justify-center rounded-control text-ink-muted transition hover:bg-surface-muted hover:text-ink"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid gap-1 p-2">
              {MOBILE_MORE_ITEMS.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={() => setMoreOpen(false)}
                  className={({ isActive }) =>
                    `flex min-h-12 items-center gap-3 rounded-control px-3 py-2.5 text-sm font-semibold transition ${
                      isActive
                        ? "bg-ink text-canvas"
                        : "text-ink-muted hover:bg-surface-muted hover:text-ink"
                    }`
                  }
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  <span>{label}</span>
                </NavLink>
              ))}
            </div>
          </section>
        </>
      ) : null}

      <nav aria-label="Mobile navigation" className="ce-mobile-navigation relative z-20 grid grid-cols-5 border-t border-line bg-surface">
        {MOBILE_PRIMARY_ITEMS.map((item) => (
          <MobileNavLink key={item.to} {...item} />
        ))}
        <button
          type="button"
          aria-label="More destinations"
          aria-controls="mobile-more-destinations"
          aria-expanded={moreOpen}
          aria-current={moreRouteActive ? "page" : undefined}
          onClick={() => setMoreOpen((current) => !current)}
          className={`group flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 px-1 text-[10px] font-semibold transition ${
            moreOpen || moreRouteActive ? "text-ink" : "text-ink-muted hover:text-ink"
          }`}
        >
          <span className={`flex h-7 w-9 items-center justify-center rounded-control transition ${
            moreOpen || moreRouteActive ? "bg-accent text-accent-ink" : "group-hover:bg-surface-muted"
          }`}>
            <Ellipsis className="h-[18px] w-[18px]" />
          </span>
          <span className="truncate">More</span>
        </button>
      </nav>
    </div>
  );
}

function MobileNavLink({ to, label, icon: Icon, end }) {
  return (
    <NavLink
      to={to}
      end={end || to === "/app"}
      className={({ isActive }) =>
        `group flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 px-1 text-[10px] font-semibold transition ${
          isActive ? "text-ink" : "text-ink-muted hover:text-ink"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span className={`flex h-7 w-9 items-center justify-center rounded-control transition ${
            isActive ? "bg-accent text-accent-ink" : "group-hover:bg-surface-muted"
          }`}>
            <Icon className="h-[18px] w-[18px]" />
          </span>
          <span className="max-w-full truncate">{label}</span>
        </>
      )}
    </NavLink>
  );
}
