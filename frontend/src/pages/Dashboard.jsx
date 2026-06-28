import { Link } from "react-router-dom";
import {
  useDashboard,
} from "../api/hooks";
import Onboarding from "../components/Onboarding";
import StatusView from "../components/StatusView";
import {
  Search,
  MessageSquare,
  ArrowRight,
  Database,
  CheckCircle2,
  AlertCircle,
  Clock,
  Bot,
} from "lucide-react";
import { motion } from "framer-motion";

export default function Dashboard() {
  const query = useDashboard();

  if (query.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-4 border-brand-200 dark:border-brand-800 border-t-brand-600 dark:border-t-brand-400" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="max-w-4xl mx-auto">
        <StatusView query={query} empty="Dashboard data is not available yet." />
      </div>
    );
  }

  const { stats = [], activity = [], io = null } = query.data || {};
  const sourceCount = stats.find((stat) => stat.label === "Sources")?.value ?? 0;
  const ioSummary = io ?? {
    feeds: [{ name: "Source documents", detail: `${sourceCount} source${sourceCount === 1 ? "" : "s"} preserved` }],
    feedFooter: "Connector status is sourced from the backend catalog",
    outputs: [
      { name: "MCP server", detail: "Agent tools read graph facts with source IDs and evidence" },
      { name: "Context packs", detail: "Selection or full-graph handoffs include neighbors" },
      { name: "Query API", detail: "Facts-used trace for grounded answers" },
      { name: "Graph UI", detail: "Board and Explore views for inspection" },
    ],
  };

  // Show onboarding if no sources connected
  if (sourceCount === 0) {
    return (
      <div className="max-w-4xl mx-auto">
        <Onboarding onComplete={() => query.refetch()} />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="app-page relative z-10"
    >
      <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
        <div>
          <p className="eyebrow">Workspace command center</p>
          <h2 className="mt-3 text-4xl font-semibold leading-tight text-slate-950 dark:text-white md:text-5xl">Context graph status</h2>
          <p className="mt-3 max-w-2xl text-base leading-relaxed text-slate-500 dark:text-neutral-400">
            Your workspace memory is grounded in{" "}
            <span className="rounded-md border border-brand-500/20 bg-brand-500/10 px-2 py-0.5 font-bold text-brand-700 dark:text-brand-300">
              {sourceCount} source documents
            </span>
            , with provenance preserved for agent handoffs and query traces.
          </p>
        </div>
        <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
          <Link
            to="/app/query"
            className="group relative inline-flex items-center gap-2 overflow-hidden rounded-lg bg-brand-600 px-5 py-3 text-sm font-bold text-white shadow-[0_18px_42px_rgba(79,70,229,0.32)] transition-all hover:bg-brand-500 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.08)]"
          >
            <div className="absolute inset-0 flex h-full w-full justify-center [transform:skew(-12deg)_translateX(-100%)] group-hover:duration-1000 group-hover:[transform:skew(-12deg)_translateX(100%)]">
              <div className="relative h-full w-8 bg-white/20" />
            </div>
            <span className="relative z-10">Ask Context</span>
            <ArrowRight className="w-5 h-5 relative z-10 transition-transform group-hover:translate-x-1" />
          </Link>
        </motion.div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <FounderCard
          icon={<Search className="w-6 h-6 text-brand-600 dark:text-brand-400" />}
          title="Ask Context"
          description="Query your company's grounded truth with full provenance back to the original source documents."
          to="/app/query"
          cta="Ask a question"
        />
        <FounderCard
          icon={<MessageSquare className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />}
          title="Knowledge Graph"
          description="Explore domain models, atomic facts, and the temporal relationships extracted from your sources."
          to="/app/graph"
          cta="Open graph"
        />
        <FounderCard
          icon={<Clock className="w-6 h-6 text-amber-600 dark:text-amber-400" />}
          title="Recent Changes"
          description="View a timeline of all context updates, source ingestions, and knowledge graph changes."
          to="/app/changes"
          cta="View timeline"
        />
      </div>

      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.08 }}
        className="panel overflow-hidden"
      >
        <div className="grid lg:grid-cols-[1fr_auto_1fr]">
          <DashboardIoColumn
            icon={<Database className="h-4 w-4" />}
            title="What feeds"
            items={ioSummary.feeds}
            footer={ioSummary.feedFooter}
            actionTo="/app/connectors"
            actionLabel="Connectors"
          />
          <div className="hidden w-px bg-slate-200/80 dark:bg-white/[0.08] lg:block" />
          <DashboardIoColumn
            icon={<Bot className="h-4 w-4" />}
            title="What agents consume"
            items={ioSummary.outputs}
            actionTo="/app/graph"
            actionLabel="Graph"
          />
        </div>
      </motion.section>

      <div className="grid gap-5 pt-1 lg:grid-cols-[1.1fr_0.9fr]">
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="panel p-6 transition-colors"
        >
          <div className="mb-6 flex items-center justify-between">
            <div>
              <p className="eyebrow">Timeline</p>
              <h3 className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">Recent Activity</h3>
            </div>
            <Link to="/app/sources" className="pill-control px-3 py-1.5 text-xs font-bold">View all</Link>
          </div>

          {activity.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-slate-400">
              <Clock className="w-12 h-12 mb-4 opacity-20" />
              <p className="text-sm font-medium">No recent activity found.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {activity.slice(0, 5).map((a) => (
                <div key={a.id} className="panel-subtle flex items-start gap-3 px-3 py-3">
                  <div className={`mt-1 w-2 h-2 rounded-full shrink-0 ${a.type === 'alert' ? 'bg-red-500' :
                      a.type === 'create' ? 'bg-emerald-500' :
                        'bg-brand-500'
                    }`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 dark:text-neutral-200 leading-snug">{a.text}</p>
                    <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">{a.ts}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </motion.div>

        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="relative overflow-hidden rounded-lg border border-white/[0.09] bg-[#07080a] p-6 text-white shadow-[0_24px_80px_rgba(0,0,0,0.42)]"
        >
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.045)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.045)_1px,transparent_1px)] bg-[size:32px_32px]" />
          <div className="relative z-10 mb-6">
            <p className="text-[11px] font-bold uppercase tracking-wider text-white/42">Health</p>
            <h3 className="mt-1 text-lg font-semibold">Workspace Health</h3>
          </div>
          <div className="relative z-10 grid grid-cols-2 gap-3">
            <HealthStat
              label="Source Docs"
              value={sourceCount}
              icon={<Database className="w-4 h-4" />}
            />
            <HealthStat
              label="Components"
              value={stats.find(s => s.label === "Components")?.value ?? 0}
              icon={<CheckCircle2 className="w-4 h-4" />}
            />
          </div>

          <div className="relative z-10 mt-6 rounded-lg border border-white/10 bg-white/[0.045] p-5">
            <div className="flex items-start gap-4">
              <AlertCircle className="w-5 h-5 text-brand-400 shrink-0" />
              <div>
                <p className="text-sm font-bold text-white">Trust Layer Note</p>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  Context Engine prioritizes "Current Truth". If you notice conflicting answers,
                  head to the Review Queue to resolve provenance overlaps.
                </p>
              </div>
            </div>
          </div>

          <Link
            to="/app/sources"
            className="relative z-10 mt-6 block w-full rounded-lg border border-white/10 bg-white/[0.08] py-3 text-center text-sm font-bold transition-all hover:bg-white/[0.14] focus:outline-none focus:ring-2 focus:ring-brand-500"
          >
            Explore workspace sources
          </Link>
        </motion.div>
      </div>
    </motion.div>
  );
}

function DashboardIoColumn({ icon, title, items = [], footer, actionTo, actionLabel }) {
  return (
    <div className="p-5 md:p-6">
      <div className="mb-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200/80 bg-slate-50 text-slate-600 dark:border-white/[0.08] dark:bg-white/[0.045] dark:text-neutral-300">
            {icon}
          </span>
          <h3 className="text-sm font-semibold text-slate-950 dark:text-white">{title}</h3>
        </div>
        <Link
          to={actionTo}
          className="pill-control inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-bold"
        >
          {actionLabel}
          <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
      <div className="space-y-3">
        {items.slice(0, 4).map((item) => (
          <div key={`${title}-${item.name}`} className="flex items-start gap-3">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-500" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-800 dark:text-neutral-200">{item.name}</p>
              <p className="text-xs leading-relaxed text-slate-500 dark:text-neutral-400">{item.detail}</p>
            </div>
          </div>
        ))}
      </div>
      {footer ? (
        <p className="mt-4 border-t border-slate-200/70 pt-3 text-[11px] font-medium text-slate-400 dark:border-white/[0.08]">
          {footer}
        </p>
      ) : null}
    </div>
  );
}

function FounderCard({ icon, title, description, to, cta, alert }) {
  return (
    <motion.div whileHover={{ y: -4, scale: 1.01 }} transition={{ duration: 0.2 }}>
      <Link
        to={to}
        className={`group relative flex h-full flex-col overflow-hidden rounded-lg border p-6 backdrop-blur-xl transition-all ${alert ? 'border-amber-300/70 bg-amber-50/75 dark:border-amber-500/35 dark:bg-amber-500/10' : 'border-slate-200/80 bg-white/[0.82] shadow-[0_16px_48px_rgba(15,23,42,0.06)] hover:border-slate-300 dark:border-white/[0.09] dark:bg-neutral-950/90 dark:shadow-[0_24px_80px_rgba(0,0,0,0.34)] dark:hover:border-white/[0.16]'}`}
      >
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/70 to-transparent opacity-0 transition-opacity group-hover:opacity-100 dark:via-white/30" />
        <div className="relative z-10 flex-col flex h-full">
          <div className={`mb-5 flex h-12 w-12 items-center justify-center rounded-lg ${alert ? 'bg-amber-100 dark:bg-amber-900/40' : 'border border-brand-500/20 bg-brand-500/10'} transition-transform duration-300 group-hover:scale-105`}>
            {icon}
          </div>
          <h3 className="text-lg font-semibold text-slate-950 dark:text-white">{title}</h3>
          <p className="mt-3 text-slate-500 dark:text-neutral-400 text-sm leading-relaxed flex-1">
            {description}
          </p>
          <div className="mt-7 flex items-center gap-2 text-sm font-bold text-brand-600 dark:text-brand-400">
            <span>{cta}</span>
            <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
          </div>
        </div>
      </Link>
    </motion.div>
  );
}

function HealthStat({ label, value, icon }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.055] p-4">
      <div className="flex items-center gap-2 text-slate-400 mb-1">
        {icon}
        <span className="text-[10px] font-bold uppercase tracking-widest">{label}</span>
      </div>
      <p className="text-2xl font-bold text-white">{value}</p>
    </div>
  );
}

const DOT_COLORS = {
  sync: "bg-blue-400",
  create: "bg-emerald-400",
  merge: "bg-brand-500",
  alert: "bg-amber-400",
  model: "bg-purple-400",
};

function ActivityDot({ type }) {
  return (
    <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${DOT_COLORS[type] || "bg-gray-300"}`} />
  );
}
