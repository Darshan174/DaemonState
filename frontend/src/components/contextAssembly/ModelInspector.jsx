import { AlertTriangle, Check, CircleDashed, ExternalLink, FileText, Lightbulb, Link2, ShieldCheck, X, XCircle } from "lucide-react";
import { useTheme } from "../../context/ThemeContext";
import {
  findAssemblyClaim,
  findAssemblyFragment,
  findAssemblyModelForNode,
  findAssemblyRelationship,
  MODEL_TYPE_META,
} from "../../graph/contextAssembly";
import AssembledModel from "./AssembledModel";
import ClaimPiece from "./ClaimPiece";
import FragmentBlock from "./FragmentBlock";
import RelationshipConnector from "./RelationshipConnector";

export default function ModelInspector({
  assembly,
  node,
  edge,
  onClose,
  onFocusNode,
  onReviewEdge,
  edgeReviewLoading,
  edgeReviewError,
}) {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  if (!node && !edge) return null;

  const relationship = edge ? findAssemblyRelationship(assembly, edge.id) : null;
  const model = node ? findAssemblyModelForNode(assembly, node) : null;
  const fragment = node?.type === "component" ? findAssemblyFragment(assembly, node.id) : null;
  const claim = node?.type === "component" ? findAssemblyClaim(assembly, node.id) : null;

  return (
    <aside
      className={`${isDark ? "dark border-white/[0.08] bg-neutral-950 text-neutral-100 shadow-[-18px_0_80px_rgba(0,0,0,0.42)]" : "border-slate-200/80 bg-white text-slate-950 shadow-[-18px_0_55px_rgba(15,23,42,0.08)]"} flex h-full min-h-0 w-[23rem] shrink-0 flex-col border-l backdrop-blur-xl`}
      aria-label="Context assembly inspector"
    >
      <div className={`${isDark ? "border-white/[0.08] bg-neutral-950" : "border-slate-200/80 bg-white"} flex items-start justify-between gap-3 border-b px-4 py-3`}>
        <div className="min-w-0">
          <p className={`${isDark ? "text-neutral-400" : "text-slate-500"} text-[10px] font-black uppercase tracking-wide`}>
            {edge ? "Relationship evidence" : node?.type === "model" ? "Model assembly" : "Evidence-backed claim"}
          </p>
          <h2 className={`${isDark ? "text-white" : "text-slate-950"} mt-0.5 line-clamp-2 text-sm font-black`}>
            {edge ? (edge.displayLabel || edge.label) : model?.name || node?.label}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className={`${isDark ? "text-neutral-400 hover:bg-white/[0.08] hover:text-white" : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"} rounded-md p-1`}
          aria-label="Close inspector"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {edge ? (
          <RelationshipInspector
            relationship={relationship}
            edge={edge}
            onFocusNode={onFocusNode}
            onReviewEdge={onReviewEdge}
            edgeReviewLoading={edgeReviewLoading}
            edgeReviewError={edgeReviewError}
          />
        ) : (
          <NodeAssemblyInspector
            assembly={assembly}
            model={model}
            fragment={fragment}
            claim={claim}
            node={node}
            onFocusNode={onFocusNode}
          />
        )}
      </div>
    </aside>
  );
}

function NodeAssemblyInspector({ assembly, model, fragment, claim, node, onFocusNode }) {
  if (!model) {
    return (
      <>
        <EmptyBlock title="No assembly model">
          This node is raw evidence until a claim/model association exists.
        </EmptyBlock>
        <Section title="Evidence">
          <RawNodeEvidence node={node} />
        </Section>
        <Section title="Claims">
          <Muted>No interpreted claim has been attached yet.</Muted>
        </Section>
        <Section title="Gaps">
          <GapRow>Attach this evidence to a model and claim.</GapRow>
        </Section>
        <Section title="Conflicts">
          <Muted>No conflicts detected for this raw node.</Muted>
        </Section>
        <Section title="Actions">
          <ActionList actions={[{ label: "Create or attach a model-backed claim for this evidence." }]} />
        </Section>
      </>
    );
  }

  const meta = MODEL_TYPE_META[model.type] || MODEL_TYPE_META.area;
  const relationships = assembly.relationships.filter((relationship) => (
    model.fragments.some((fragmentItem) => fragmentItem.id === relationship.sourceId || fragmentItem.id === relationship.targetId)
  ));
  const decisions = model.claims.filter((item) => /decision/.test(item.type));
  const selectedClaimFirst = claim
    ? [claim, ...model.claims.filter((item) => item.id !== claim.id)]
    : model.claims;
  const selectedEvidenceFirst = fragment
    ? [fragment, ...model.fragments.filter((item) => item.id !== fragment.id)]
    : model.fragments;
  const firstRelated = relationships.find((item) => item.sourceId === node?.id || item.targetId === node?.id) || relationships[0];
  const firstRelatedNodeId = firstRelated
    ? firstRelated.sourceId === node?.id ? firstRelated.targetId : firstRelated.sourceId
    : null;

  return (
    <>
      <ContextHealthStrip model={model} meta={meta} />
      <MetricGrid model={model} meta={meta} />

      <Section title={`Evidence (${model.fragments.length})`}>
        <div className="space-y-1.5">
          {selectedEvidenceFirst.slice(0, 5).map((item) => (
            <button key={item.id} type="button" onClick={() => onFocusNode?.(item.id)} className="block w-full text-left">
              <FragmentBlock fragment={item} compact={item.id !== fragment?.id} selected={item.id === fragment?.id} />
            </button>
          ))}
          {model.fragments.length === 0 ? <Muted>No source-backed evidence has been extracted yet.</Muted> : null}
        </div>
        {fragment?.raw?.source_url ? (
          <a href={fragment.raw.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1.5 text-xs font-bold text-slate-600 hover:text-slate-950 dark:text-neutral-300 dark:hover:text-white">
            Open provenance <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
      </Section>

      <Section title={`Claims (${model.claims.length})`}>
        <div className="space-y-2">
          {selectedClaimFirst.slice(0, 6).map((item) => (
            <ClaimPiece key={item.id} claim={item} compact={item.id !== claim?.id} />
          ))}
          {model.claims.length === 0 ? <Muted>No claims have been interpreted from this evidence.</Muted> : null}
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500 dark:text-neutral-400">
          Claims are interpretations backed by evidence fragments.
        </p>
      </Section>

      <Section title={`Gaps (${model.missingContext.length})`}>
        <div className="space-y-1.5">
          {model.missingContext.map((item) => (
            <GapRow key={item}>{item}</GapRow>
          ))}
          {model.missingContext.length === 0 ? <Muted>No obvious context gaps for this model.</Muted> : null}
        </div>
      </Section>

      <Section title={`Conflicts (${model.conflicts.length})`}>
        {model.conflicts.length ? (
          <div className="space-y-1.5">
            {model.conflicts.map((conflict) => (
              <div key={conflict.id} className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {conflict.summary}
              </div>
            ))}
          </div>
        ) : <Muted>No conflicts detected.</Muted>}
      </Section>

      <Section title="Actions">
        <ActionList
          actions={[
            { label: model.suggestedNextAction, icon: Lightbulb },
            model.conflicts.length ? { label: "Resolve conflicting evidence before relying on this model.", icon: AlertTriangle } : null,
            model.missingContext.length ? { label: `Fill missing context: ${model.missingContext[0]}.`, icon: CircleDashed } : null,
            relationships.some((item) => item.weak) ? { label: "Review weak or proposed relationships.", icon: Link2, targetId: firstRelatedNodeId } : null,
          ].filter(Boolean)}
          onFocusNode={onFocusNode}
        />
      </Section>

      <AssembledModel model={model} selectedFragmentId={fragment?.id || node?.id} onSelectFragment={onFocusNode} />

      <Section title={`Relationships (${relationships.length})`}>
        <div className="space-y-2">
          {relationships.slice(0, 6).map((item) => <RelationshipConnector key={item.id} relationship={item} />)}
          {relationships.length === 0 ? <Muted>No relationships have enough evidence to show yet.</Muted> : null}
        </div>
      </Section>

      <Section title={`Decisions (${decisions.length})`}>
        {decisions.length ? <div className="space-y-2">{decisions.slice(0, 4).map((item) => <ClaimPiece key={item.id} claim={item} compact />)}</div> : <Muted>No extracted decisions for this model.</Muted>}
      </Section>

      <Section title={`Blockers (${model.blockers.length})`}>
        {model.blockers.length ? <div className="space-y-1.5">{model.blockers.map((item) => <FragmentBlock key={item.id} fragment={item} compact />)}</div> : <Muted>No blockers detected.</Muted>}
      </Section>
    </>
  );
}

function RelationshipInspector({ relationship, edge, onFocusNode, onReviewEdge, edgeReviewLoading, edgeReviewError }) {
  const fallback = relationship || {
    id: edge.id,
    label: edge.displayLabel || edge.label,
    confidence: { label: edge.confidence != null ? `${Math.round(edge.confidence * 100)}%` : "n/a", value: edge.confidence || 0 },
    evidence: edge.evidence,
    weak: ["proposed", "ai_proposed"].includes(edge.origin || "proposed"),
    verified: edge.origin === "human_verified",
    conflict: /conflict|block/.test(`${edge.label || ""} ${edge.status || ""}`.toLowerCase()),
  };

  return (
    <>
      <RelationshipConnector
        relationship={fallback}
        loading={edgeReviewLoading}
        onAccept={() => onReviewEdge?.("accept")}
        onReject={() => onReviewEdge?.("reject")}
      />
      {edgeReviewError ? <p className="text-xs font-semibold text-red-600 dark:text-red-400">{edgeReviewError}</p> : null}

      <Section title="Endpoints">
        <div className="space-y-2">
          <button type="button" onClick={() => onFocusNode?.(edge.source)} className="w-full rounded-md border border-slate-200 px-2.5 py-2 text-left text-xs hover:bg-slate-50 dark:border-white/[0.08] dark:hover:bg-white/[0.04]">
            <span className="text-slate-400">From</span>
            <span className="mt-0.5 block font-semibold text-slate-800 dark:text-neutral-100">{edge.sourceName || edge.source}</span>
          </button>
          <button type="button" onClick={() => onFocusNode?.(edge.target)} className="w-full rounded-md border border-slate-200 px-2.5 py-2 text-left text-xs hover:bg-slate-50 dark:border-white/[0.08] dark:hover:bg-white/[0.04]">
            <span className="text-slate-400">To</span>
            <span className="mt-0.5 block font-semibold text-slate-800 dark:text-neutral-100">{edge.targetName || edge.target}</span>
          </button>
        </div>
      </Section>

      <Section title="Review">
        <div className="flex gap-2">
          <button
            type="button"
            disabled={edgeReviewLoading}
            onClick={() => onReviewEdge?.("accept")}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-emerald-700 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-800 disabled:opacity-50"
          >
            <Check className="h-3.5 w-3.5" />
            Accept
          </button>
          <button
            type="button"
            disabled={edgeReviewLoading}
            onClick={() => onReviewEdge?.("reject")}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-red-200 px-3 py-2 text-xs font-bold text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-900/60 dark:text-red-300 dark:hover:bg-red-950/30"
          >
            <XCircle className="h-3.5 w-3.5" />
            Reject
          </button>
        </div>
      </Section>

      <Section title="Why this exists">
        {edge.evidence ? (
          <blockquote className="rounded-md border-l-2 border-slate-300 bg-slate-50 px-3 py-2 text-xs italic text-slate-600 dark:border-white/[0.12] dark:bg-white/[0.035] dark:text-neutral-300">
            {edge.evidence}
          </blockquote>
        ) : (
          <Muted>No evidence text was returned by the backend for this relationship.</Muted>
        )}
      </Section>
    </>
  );
}

function ContextHealthStrip({ model, meta }) {
  const hasConflict = model.conflicts.length > 0;
  const hasGaps = model.missingContext.length > 0 || model.completeness.value < 0.62;
  const status = hasConflict ? "Conflict" : hasGaps ? "Needs review" : "Grounded";
  const tone = hasConflict
    ? "border-red-200 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300"
    : hasGaps
      ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300"
      : "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300";
  const Icon = hasConflict ? AlertTriangle : hasGaps ? CircleDashed : ShieldCheck;

  return (
    <div className={`rounded-lg border px-3 py-2 ${tone}`}>
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-black">{status}</p>
            <span className="rounded-full px-2 py-0.5 text-[10px] font-bold text-white" style={{ backgroundColor: meta.color }}>
              {meta.label}
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-snug opacity-85">
            {model.fragments.length} evidence · {model.claims.length} claims · {model.missingContext.length} gaps · {model.conflicts.length} conflicts
          </p>
        </div>
      </div>
    </div>
  );
}

function ActionList({ actions, onFocusNode }) {
  if (!actions?.length) return <Muted>No recommended actions right now.</Muted>;
  return (
    <div className="space-y-1.5">
      {actions.map((action, index) => {
        const Icon = action.icon || Lightbulb;
        const clickable = Boolean(action.targetId && onFocusNode);
        const content = (
          <>
            <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500 dark:text-neutral-400" />
            <span className="min-w-0 flex-1">{action.label}</span>
          </>
        );
        if (clickable) {
          return (
            <button
              key={`${action.label}-${index}`}
              type="button"
              onClick={() => onFocusNode?.(action.targetId)}
              className="flex w-full items-start gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-left text-xs font-semibold leading-snug text-slate-700 hover:border-slate-300 hover:bg-white dark:border-white/[0.08] dark:bg-white/[0.035] dark:text-neutral-200 dark:hover:bg-white/[0.06]"
            >
              {content}
            </button>
          );
        }
        return (
          <div
            key={`${action.label}-${index}`}
            className="flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs font-semibold leading-snug text-slate-700 dark:border-white/[0.08] dark:bg-white/[0.035] dark:text-neutral-200"
          >
            {content}
          </div>
        );
      })}
    </div>
  );
}

function GapRow({ children }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-dashed border-amber-300 bg-amber-50 px-2.5 py-2 text-xs font-semibold text-amber-800 dark:border-amber-900/70 dark:bg-amber-950/20 dark:text-amber-300">
      <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      {children}
    </div>
  );
}

function RawNodeEvidence({ node }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700 dark:border-white/[0.08] dark:bg-white/[0.035] dark:text-neutral-200">
      <div className="mb-1 flex items-center gap-1.5 font-bold">
        <FileText className="h-3.5 w-3.5 text-slate-400" />
        {node?.source_type || "Raw source"}
      </div>
      <p className="leading-relaxed">{node?.excerpt || node?.value || node?.label || "No evidence text available."}</p>
    </div>
  );
}

function MetricGrid({ model, meta }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <Metric label="Completeness" value={model.completeness.label} color={meta.color} />
      <Metric label="Confidence" value={model.confidence.label} color={model.confidence.level === "low" ? "#b45309" : meta.color} />
      <Metric label="Evidence" value={String(model.fragments.length)} />
      <Metric label="Claims" value={String(model.claims.length)} />
    </div>
  );
}

function Metric({ label, value, color = "#64748b" }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-white/[0.08] dark:bg-white/[0.035]">
      <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-lg font-black" style={{ color }}>{value}</p>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section>
      <p className="mb-2 text-[10px] font-black uppercase tracking-wide text-slate-400">{title}</p>
      {children}
    </section>
  );
}

function EmptyBlock({ title, children }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600 dark:border-white/[0.12] dark:bg-white/[0.03] dark:text-neutral-300">
      <p className="mb-1 font-bold text-slate-900 dark:text-white">{title}</p>
      {children}
    </div>
  );
}

function Muted({ children }) {
  return <p className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs text-slate-500 dark:border-white/[0.08] dark:bg-white/[0.03] dark:text-neutral-400">{children}</p>;
}
