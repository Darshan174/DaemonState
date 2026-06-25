import {
  AlertTriangle,
  Check,
  ExternalLink,
  FileText,
  GitPullRequest,
  Loader2,
  MessageCircle,
  X,
  XCircle,
} from "lucide-react";
import {
  formatMetaKey,
  githubSourceUrl,
  INSPECTOR_EDGE_ORIGIN,
  INSPECTOR_STATUS,
  INSPECTOR_TEMPORAL,
  isDeterministicMentionEdge,
  nodeWarnings,
  slackContextRows,
  slackPermalink,
  sourceDocumentPath,
  sourceMetaEntries,
} from "../graph/inspectorUtils";

function TrustBlock({ label, children }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-3 dark:border-slate-700 dark:bg-slate-800/50">
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      {children}
    </div>
  );
}

function ActionLink({ href, icon: Icon, children, external = true }) {
  if (!href) return null;
  return (
    <a
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener noreferrer" : undefined}
      className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      {children}
      {external ? <ExternalLink className="h-3 w-3 opacity-50" /> : null}
    </a>
  );
}

function NodeInspector({ node, onClose, onFocusNode }) {
  const statusMeta = INSPECTOR_STATUS[node.status] || INSPECTOR_STATUS.active;
  const temporalMeta = INSPECTOR_TEMPORAL[node.temporal] || INSPECTOR_TEMPORAL.current;
  const warnings = nodeWarnings(node);
  const slackLink = node.source_type === "slack" ? slackPermalink(node) : "";
  const githubLink = node.source_type === "github" ? githubSourceUrl(node) : "";
  const sourceDocPath = sourceDocumentPath(node.source_document_id);
  const metaEntries = sourceMetaEntries(node.source_metadata_summary);

  return (
    <>
      <div className="flex items-start justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Component</p>
          <h2 className="mt-0.5 line-clamp-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
            {node.label}
          </h2>
          <div className="mt-2 flex flex-wrap gap-1">
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusMeta.pill}`}>
              {statusMeta.label}
            </span>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${temporalMeta.pill}`}>
              {temporalMeta.label}
            </span>
            {node.model ? (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                {node.model}
              </span>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700"
          aria-label="Close inspector"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {warnings.length > 0 ? (
          <div className="space-y-1.5">
            {warnings.map((w) => (
              <div
                key={w.text}
                className={`flex items-start gap-2 rounded-md px-2.5 py-2 text-xs ${
                  w.tone === "red"
                    ? "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                    : "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
                }`}
              >
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {w.text}
              </div>
            ))}
          </div>
        ) : null}

        <section>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Value</p>
          <p className="text-sm leading-relaxed text-slate-800 dark:text-slate-200">{node.value || node.label}</p>
        </section>

        <TrustBlock label="Trust">
          <div className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
            {node.confidence != null ? (
              <p>
                Confidence: <span className="font-medium">{Math.round(node.confidence * 100)}%</span>
              </p>
            ) : null}
            {node.authority_weight != null ? (
              <p>
                Authority weight: <span className="font-medium">{Number(node.authority_weight).toFixed(2)}</span>
              </p>
            ) : null}
            {node.source_type ? (
              <p>
                Source: <span className="font-medium capitalize">{node.source_type}</span>
              </p>
            ) : null}
            {node.fact_type ? (
              <p>
                Fact type: <span className="font-medium">{node.fact_type}</span>
              </p>
            ) : null}
          </div>
        </TrustBlock>

        {(node.excerpt || node.provenance) ? (
          <section>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Provenance</p>
            {node.excerpt ? (
              <blockquote className="rounded-md border-l-2 border-slate-300 bg-slate-50 px-3 py-2 text-xs italic text-slate-600 dark:border-slate-600 dark:bg-slate-800/50 dark:text-slate-300">
                {node.excerpt}
              </blockquote>
            ) : null}
            {node.provenance ? (
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{node.provenance}</p>
            ) : null}
          </section>
        ) : null}

        <section>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Source links</p>
          <div className="flex flex-wrap gap-2">
            {slackLink ? <ActionLink href={slackLink} icon={MessageCircle}>Open in Slack</ActionLink> : null}
            {githubLink ? <ActionLink href={githubLink} icon={GitPullRequest}>Open on GitHub</ActionLink> : null}
            {sourceDocPath ? (
              <ActionLink href={sourceDocPath} icon={FileText} external={false}>
                View source document
              </ActionLink>
            ) : null}
          </div>
        </section>

        {node.source_type === "slack" && slackContextRows(node).length > 0 ? (
          <section>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Slack context</p>
            <dl className="space-y-1 text-xs">
              {slackContextRows(node).map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <dt className="w-24 shrink-0 text-slate-400">{key}</dt>
                  <dd className="text-slate-700 dark:text-slate-300">{String(value)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {metaEntries.length > 0 ? (
          <section>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Metadata</p>
            <dl className="space-y-1 text-xs">
              {metaEntries.map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <dt className="w-24 shrink-0 capitalize text-slate-400">{formatMetaKey(key)}</dt>
                  <dd className="break-all text-slate-700 dark:text-slate-300">{String(value)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {node.connected?.length > 0 ? (
          <section>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Connections ({node.connected.length})
            </p>
            <ul className="space-y-1">
              {node.connected.map((conn) => (
                <li key={`${conn.edgeId || conn.label}-${conn.nodeId}`}>
                  <button
                    type="button"
                    onClick={() => onFocusNode?.(conn.nodeId, conn.edgeId)}
                    className="w-full rounded-md border border-slate-200 px-2.5 py-2 text-left text-xs transition hover:border-sky-300 hover:bg-sky-50 dark:border-slate-600 dark:hover:border-sky-700 dark:hover:bg-sky-900/20"
                  >
                    <span className="font-medium text-sky-700 dark:text-sky-400">{conn.label}</span>
                    <span className="mt-0.5 block truncate text-slate-500 dark:text-slate-400">{conn.nodeLabel}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}

function EdgeInspector({ edge, onClose, onFocusNode, onReviewEdge, edgeReviewLoading, edgeReviewError }) {
  const originMeta = INSPECTOR_EDGE_ORIGIN[edge.origin] || INSPECTOR_EDGE_ORIGIN.proposed;
  const isProposed = edge.origin === "proposed" || edge.origin === "ai_proposed";
  const mentionEdge = isDeterministicMentionEdge(edge);

  return (
    <>
      <div className="flex items-start justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Relationship</p>
          <h2 className="mt-0.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
            {edge.displayLabel || edge.label}
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium text-white"
              style={{ backgroundColor: originMeta.color }}
            >
              {originMeta.label}
            </span>
            {edge.confidence != null ? (
              <span className="text-[10px] text-slate-500">
                {Math.round(edge.confidence * 100)}% confidence
              </span>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700"
          aria-label="Close inspector"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {mentionEdge ? (
          <div className="rounded-md bg-sky-50 px-2.5 py-2 text-xs text-sky-800 dark:bg-sky-900/20 dark:text-sky-300">
            Deterministic mention edge — derived from explicit @-reference in source text.
          </div>
        ) : null}

        <section>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Endpoints</p>
          <div className="space-y-2 text-xs">
            <button
              type="button"
              onClick={() => onFocusNode?.(edge.source)}
              className="block w-full rounded-md border border-slate-200 px-2.5 py-2 text-left transition hover:border-sky-300 hover:bg-sky-50 dark:border-slate-600 dark:hover:border-sky-700 dark:hover:bg-sky-900/20"
            >
              <span className="text-slate-400">From</span>
              <span className="mt-0.5 block font-medium text-slate-800 dark:text-slate-200">{edge.sourceName || edge.source}</span>
            </button>
            <button
              type="button"
              onClick={() => onFocusNode?.(edge.target)}
              className="block w-full rounded-md border border-slate-200 px-2.5 py-2 text-left transition hover:border-sky-300 hover:bg-sky-50 dark:border-slate-600 dark:hover:border-sky-700 dark:hover:bg-sky-900/20"
            >
              <span className="text-slate-400">To</span>
              <span className="mt-0.5 block font-medium text-slate-800 dark:text-slate-200">{edge.targetName || edge.target}</span>
            </button>
          </div>
        </section>

        {edge.evidence ? (
          <section>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Evidence</p>
            <blockquote className="rounded-md border-l-2 border-slate-300 bg-slate-50 px-3 py-2 text-xs italic text-slate-600 dark:border-slate-600 dark:bg-slate-800/50 dark:text-slate-300">
              {edge.evidence}
            </blockquote>
          </section>
        ) : null}

        <TrustBlock label="Origin & review">
          <p className="text-xs text-slate-600 dark:text-slate-300">
            Origin: <span className="font-medium">{originMeta.label}</span>
          </p>
          {edge.review_status ? (
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
              Review: <span className="font-medium capitalize">{edge.review_status}</span>
            </p>
          ) : null}
        </TrustBlock>

        {isProposed ? (
          <section>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Review edge</p>
            {edgeReviewError ? (
              <p className="mb-2 text-xs text-red-600 dark:text-red-400">{edgeReviewError}</p>
            ) : null}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={edgeReviewLoading}
                onClick={() => onReviewEdge("accept")}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-emerald-600 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {edgeReviewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                Accept
              </button>
              <button
                type="button"
                disabled={edgeReviewLoading}
                onClick={() => onReviewEdge("reject")}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:bg-slate-800 dark:hover:bg-red-900/20"
              >
                {edgeReviewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                Reject
              </button>
            </div>
          </section>
        ) : null}
      </div>
    </>
  );
}

export default function GraphInspector({
  node,
  edge,
  onClose,
  onFocusNode,
  onReviewEdge,
  edgeReviewLoading,
  edgeReviewError,
}) {
  if (!node && !edge) return null;

  return (
    <aside
      className="flex h-full min-h-0 w-80 shrink-0 flex-col border-l border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
      aria-label="Graph inspector"
    >
      {node ? (
        <NodeInspector node={node} onClose={onClose} onFocusNode={onFocusNode} />
      ) : (
        <EdgeInspector
          edge={edge}
          onClose={onClose}
          onFocusNode={onFocusNode}
          onReviewEdge={onReviewEdge}
          edgeReviewLoading={edgeReviewLoading}
          edgeReviewError={edgeReviewError}
        />
      )}
    </aside>
  );
}
