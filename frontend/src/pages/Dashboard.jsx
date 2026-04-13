import { Link } from "react-router-dom";
import {
  useDashboard,
} from "../api/hooks";
import Onboarding from "../components/Onboarding";
import { 
  Search, 
  MessageSquare, 
  ArrowRight,
  Database,
  CheckCircle2,
  AlertCircle,
  Clock
} from "lucide-react";

export default function Dashboard() {
  const query = useDashboard();
  
  if (query.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-4 border-brand-200 border-t-brand-600" />
      </div>
    );
  }

  const { stats = [], activity = [] } = query.data || {};
  const sourceCount = stats.find((stat) => stat.label === "Sources")?.value ?? 0;

  // Show onboarding if no sources connected
  if (sourceCount === 0) {
    return (
      <div className="max-w-4xl mx-auto">
        <Onboarding onComplete={() => query.refetch()} />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-10">
      {/* ── Founder Header ────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Workspace Overview</h2>
          <p className="text-slate-500 mt-2 text-lg">
            Your startup memory is grounded in <span className="font-bold text-slate-900">{sourceCount} source documents</span>.
          </p>
        </div>
        <Link 
          to="/app/brief" 
          className="inline-flex items-center gap-2 px-6 py-3 bg-brand-600 text-white rounded-2xl font-bold shadow-lg shadow-brand-600/20 hover:bg-brand-500 transition-all hover:-translate-y-0.5"
        >
          View Founder Brief
          <ArrowRight className="w-5 h-5" />
        </Link>
      </div>

      {/* ── Core Founder Actions ──────────────────── */}
      <div className="grid md:grid-cols-3 gap-6">
        <FounderCard 
          icon={<Search className="w-6 h-6 text-brand-600" />}
          title="Ask Context"
          description="Query your company's grounded truth with full provenance back to original sources."
          to="/app/query"
          cta="Ask a question"
        />
        <FounderCard 
          icon={<MessageSquare className="w-6 h-6 text-emerald-600" />}
          title="Decision Register"
          description="Review the history of key architectural and product decisions made across the team."
          to="/app/decisions"
          cta="Review decisions"
        />
        <FounderCard 
          icon={<Clock className="w-6 h-6 text-amber-600" />}
          title="Recent Changes"
          description="View a single timeline of all workspace context updates, source additions, and decisions."
          to="/app/changes"
          cta="View timeline"
        />
      </div>

      {/* ── Secondary Activity/Health ─────────────── */}
      <div className="grid lg:grid-cols-2 gap-8 pt-6">
        <div className="bg-white rounded-[32px] border border-slate-200 p-8 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-lg font-bold text-slate-900">Recent Activity</h3>
            <Link to="/app/sources" className="text-sm font-bold text-brand-600 hover:text-brand-500">View all sources</Link>
          </div>
          
          {activity.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-slate-400">
              <Clock className="w-12 h-12 mb-4 opacity-20" />
              <p className="text-sm font-medium">No recent activity found.</p>
            </div>
          ) : (
            <div className="space-y-6">
              {activity.slice(0, 5).map((a) => (
                <div key={a.id} className="flex items-start gap-4">
                  <div className={`mt-1 w-2 h-2 rounded-full shrink-0 ${
                    a.type === 'alert' ? 'bg-red-500' :
                    a.type === 'create' ? 'bg-emerald-500' :
                    'bg-brand-500'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 leading-snug">{a.text}</p>
                    <p className="text-xs text-slate-400 mt-1">{a.ts}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-slate-900 rounded-[32px] p-8 text-white shadow-xl">
          <h3 className="text-lg font-bold mb-6">Workspace Health</h3>
          <div className="grid grid-cols-2 gap-4">
            <HealthStat 
              label="Source Docs"
              value={sourceCount}
              icon={<Database className="w-4 h-4" />}
            />
            <HealthStat 
              label="Processed"
              value={stats.find(s => s.label === "Processed")?.value ?? "98%"}
              icon={<CheckCircle2 className="w-4 h-4" />}
            />
          </div>
          
          <div className="mt-8 p-6 bg-white/5 rounded-2xl border border-white/10">
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
            className="mt-8 w-full py-3 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl text-sm font-bold transition-all text-center block"
          >
            Explore workspace sources
          </Link>
        </div>
      </div>
    </div>
  );
}

function FounderCard({ icon, title, description, to, cta, alert }) {
  return (
    <Link 
      to={to} 
      className={`flex flex-col h-full p-8 bg-white border ${alert ? 'border-amber-200 bg-amber-50/30' : 'border-slate-200'} rounded-[32px] hover:border-brand-300 hover:shadow-xl hover:shadow-brand-500/5 transition-all group`}
    >
      <div className={`w-14 h-14 rounded-2xl ${alert ? 'bg-amber-100' : 'bg-slate-50'} flex items-center justify-center mb-6 group-hover:scale-110 transition-transform`}>
        {icon}
      </div>
      <h3 className="text-xl font-bold text-slate-900">{title}</h3>
      <p className="mt-3 text-slate-500 text-sm leading-relaxed flex-1">
        {description}
      </p>
      <div className="mt-8 flex items-center gap-2 text-sm font-bold text-slate-900">
        <span>{cta}</span>
        <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
      </div>
    </Link>
  );
}

function HealthStat({ label, value, icon }) {
  return (
    <div className="p-4 bg-white/5 rounded-2xl border border-white/5">
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
