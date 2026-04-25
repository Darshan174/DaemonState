import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";
import { useLaunchGuardCheck, useLaunchGuardContext } from "../api/hooks";

const EXAMPLES = [
  {
    label: "Pricing announcement",
    value:
      "We are launching enterprise pricing at $500 per seat next week once the pricing page is published.",
  },
  {
    label: "Roadmap update",
    value:
      "SSO is launching in Q2 and the blocker is mostly resolved, so the rollout is back on track.",
  },
  {
    label: "Meeting recap",
    value:
      "In the latest product review we decided to launch the pricing page next Tuesday.",
  },
];

export default function LaunchGuard() {
  const query = useLaunchGuardContext();
  const checkMutation = useLaunchGuardCheck();
  const [draft, setDraft] = useState("");
  const [report, setReport] = useState(null);

  const context = query.data;
  const hasContext =
    (context?.components?.length ?? 0) > 0 ||
    (context?.decisions?.length ?? 0) > 0 ||
    (context?.reviewItems?.length ?? 0) > 0;

  const summary = useMemo(() => summarizeGuardContext(context), [context]);

  const handleAnalyze = async (value) => {
    const nextDraft = value.trim();
    if (!nextDraft) return;
    try {
      const result = await checkMutation.mutateAsync(nextDraft);
      setReport(normalizeLaunchGuardApiReport(result));
    } catch {
      setReport(analyzeDraft(nextDraft, context));
    }
  };

  if (query.isLoading || query.isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView query={query} empty="No launch guard context is available yet." />
      </div>
    );
  }

  if (!hasContext) {
    return (
      <div className="max-w-6xl mx-auto">
        <LaunchGuardEmptyState />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">Launch Guard</h2>
            {query.isMock && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Paste a launch note, customer reply, or status update and check it against current decisions, review pressure, and historical facts before it ships.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Link to="/app/changes" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open timeline
          </Link>
          <Link to="/app/review" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open review queue
          </Link>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <SummaryCard label="Current decisions" value={summary.currentDecisions} />
        <SummaryCard label="Needs review" value={summary.needsReview} tone="amber" />
        <SummaryCard label="Historical facts" value={summary.historical} tone="slate" />
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5 space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Draft to check</h3>
          <p className="mt-1 text-xs text-gray-400">
            Use this before sending pricing updates, launch notes, roadmap statements, or founder/customer replies.
          </p>
        </div>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Paste the draft you want to verify against current company context..."
          aria-label="Launch guard draft"
          rows={7}
          className="w-full rounded-xl border border-gray-200 dark:border-gray-800/50 px-4 py-3 text-sm text-gray-800 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
        />
        <div className="flex flex-wrap items-center gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example.label}
              type="button"
              onClick={() => {
                setDraft(example.value);
                handleAnalyze(example.value);
              }}
              className="rounded-full bg-gray-100 dark:bg-gray-900/40 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-200"
            >
              {example.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => handleAnalyze(draft)}
            disabled={!draft.trim() || checkMutation.isPending}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {checkMutation.isPending ? "Analyzing..." : "Analyze draft"}
          </button>
          <p className="text-xs text-gray-500">
            Launch Guard uses current facts, historical context, and open review items to flag risky claims.
          </p>
        </div>
      </div>

      {report ? (
        <div className="space-y-6">
          <GuardBanner report={report} />

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <section className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Findings</h3>
                  <p className="mt-1 text-xs text-gray-400">
                    Claims that look risky, stale, or unsupported in the current trust graph.
                  </p>
                </div>
                <span className="text-xs text-gray-400">
                  {report.findings.length} finding{report.findings.length === 1 ? "" : "s"}
                </span>
              </div>
              {report.findings.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {report.findings.map((item) => (
                    <FindingCard key={item.id} item={item} />
                  ))}
                </div>
              ) : (
                <p className="mt-4 text-sm text-gray-500">
                  No obvious trust issues were found in this draft. You still need to inspect the evidence before sending it.
                </p>
              )}
            </section>

            <section className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Grounding evidence</h3>
                  <p className="mt-1 text-xs text-gray-400">
                    Matching decisions and facts the draft appears to rely on.
                  </p>
                </div>
                <span className="text-xs text-gray-400">
                  {report.evidence.length} match{report.evidence.length === 1 ? "" : "es"}
                </span>
              </div>
              {report.evidence.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {report.evidence.map((item) => (
                    <EvidenceCard key={item.id} item={item} />
                  ))}
                </div>
              ) : (
                <p className="mt-4 text-sm text-gray-500">
                  No grounded facts matched the draft closely enough. That usually means the draft is ahead of the context engine, or the source data is missing.
                </p>
              )}
            </section>
          </div>

          <section className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Recommended next steps</h3>
                <p className="mt-1 text-xs text-gray-400">
                  Where to go next before approving or shipping this draft.
                </p>
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {report.nextSteps.map((step) => (
                <Link
                  key={step.label}
                  to={step.to}
                  className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-3 text-sm text-gray-700 dark:text-gray-400 hover:border-brand-200 dark:border-brand-800/50 hover:text-brand-700 dark:text-brand-400"
                >
                  <p className="font-medium">{step.label}</p>
                  <p className="mt-1 text-xs text-gray-500">{step.detail}</p>
                </Link>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function analyzeDraft(draft, context) {
  const text = normalizeNarrative(draft);
  const decisions = (context?.decisions ?? []).filter((item) => matchesNarrative(text, [
    item.title,
    item.summary,
    item.sourceLabel,
    item.relatedBlocker,
  ]));
  const components = (context?.components ?? []).filter((item) => matchesNarrative(text, [
    item.name,
    item.value,
    item.modelName,
    item.reviewSummary,
  ]));
  const reviewItems = (context?.reviewItems ?? []).filter((item) => matchesNarrative(text, [
    item.title,
    item.summary,
    item.model,
  ]));

  const findings = [];
  const evidence = [];

  decisions.forEach((item) => {
    const decisionLinks = dedupeLinks([
      item.sourceDocumentId
        ? { to: `/app/sources/${item.sourceDocumentId}`, label: "View source" }
        : null,
      item.reviewItemIds?.[0]
        ? { to: `/app/review/${item.reviewItemIds[0]}`, label: "Open review thread" }
        : null,
      item.connectorType === "zoom"
        ? { to: "/app/meetings", label: "Open meetings" }
        : item.connectorType === "github"
          ? { to: "/app/engineering", label: "Open engineering" }
          : { to: "/app/decisions", label: "Open decisions" },
    ]);

    evidence.push({
      id: `decision-${item.id}`,
      title: item.title,
      summary: item.summary,
      status: item.status,
      to: `/app/sources/${item.sourceDocumentId}`,
      toLabel: "View source",
      links: decisionLinks,
    });

    if (item.status === "needs_review") {
      findings.push({
        id: `decision-risk-${item.id}`,
        severity: "high",
        title: `Decision still needs review: ${item.title}`,
        detail: "The draft relies on a decision that has not cleared the review queue yet.",
        to: item.reviewItemIds?.[0] ? `/app/review/${item.reviewItemIds[0]}` : "/app/review",
        toLabel: "Open review thread",
        links: dedupeLinks([
          item.reviewItemIds?.[0]
            ? { to: `/app/review/${item.reviewItemIds[0]}`, label: "Open review thread" }
            : { to: "/app/review", label: "Open review queue" },
          item.sourceDocumentId
            ? { to: `/app/sources/${item.sourceDocumentId}`, label: "View source" }
            : null,
          { to: "/app/decisions", label: "Open decisions" },
        ]),
      });
    } else if (item.status === "historical") {
      findings.push({
        id: `decision-history-${item.id}`,
        severity: "high",
        title: `Historical decision referenced: ${item.title}`,
        detail: "This looks like superseded or historical context, not current operating truth.",
        to: `/app/decisions?state=historical`,
        toLabel: "Review historical decisions",
        links: dedupeLinks([
          { to: `/app/decisions?state=historical`, label: "Review historical decisions" },
          item.sourceDocumentId
            ? { to: `/app/sources/${item.sourceDocumentId}`, label: "View source" }
            : null,
        ]),
      });
    }
  });

  components.forEach((item) => {
    const sourceLink = item.sourceDocuments?.[0]
      ? { to: `/app/sources/${item.sourceDocuments[0].id}`, label: "View source" }
      : null;
    const componentLinks = dedupeLinks([
      item.modelId ? { to: `/app/model/${item.modelId}`, label: "Open model" } : null,
      item.reviewItemId ? { to: `/app/review/${item.reviewItemId}`, label: "Open review thread" } : null,
      sourceLink,
    ]);

    evidence.push({
      id: `component-${item.id}`,
      title: item.name,
      summary: `${item.value}${item.modelName ? ` · ${item.modelName}` : ""}`,
      status: item.reviewStatus ?? item.temporalState ?? null,
      to: item.modelId ? `/app/model/${item.modelId}` : "/app/models",
      toLabel: "Open model",
      links: componentLinks,
    });

    if (item.reviewStatus === "needs_review") {
      findings.push({
        id: `component-review-${item.id}`,
        severity: "high",
        title: `Fact still needs review: ${item.name}`,
        detail: item.reviewSummary || "The draft relies on a fact that still needs a human trust decision.",
        to: item.reviewItemId ? `/app/review/${item.reviewItemId}` : "/app/review",
        toLabel: "Open review queue",
        links: dedupeLinks([
          item.reviewItemId
            ? { to: `/app/review/${item.reviewItemId}`, label: "Open review thread" }
            : { to: "/app/review", label: "Open review queue" },
          item.modelId ? { to: `/app/model/${item.modelId}`, label: "Inspect fact" } : null,
          sourceLink,
        ]),
      });
    } else if (
      item.temporalState === "historical" ||
      item.temporalState === "superseded" ||
      item.reviewStatus === "superseded"
    ) {
      findings.push({
        id: `component-history-${item.id}`,
        severity: "high",
        title: `Historical fact referenced: ${item.name}`,
        detail: "The draft appears to rely on superseded context rather than the current fact version.",
        to: item.modelId ? `/app/model/${item.modelId}` : "/app/models",
        toLabel: "Inspect fact history",
        links: dedupeLinks([
          item.modelId ? { to: `/app/model/${item.modelId}`, label: "Inspect fact history" } : null,
          sourceLink,
          { to: "/app/changes", label: "Open timeline" },
        ]),
      });
    } else if (typeof item.confidence === "number" && item.confidence < 0.75) {
      findings.push({
        id: `component-confidence-${item.id}`,
        severity: "medium",
        title: `Low-confidence fact: ${item.name}`,
        detail: "The draft depends on context that still has a weak extraction confidence signal.",
        to: item.modelId ? `/app/model/${item.modelId}` : "/app/models",
        toLabel: "Inspect fact",
        links: dedupeLinks([
          item.modelId ? { to: `/app/model/${item.modelId}`, label: "Inspect fact" } : null,
          item.reviewItemId ? { to: `/app/review/${item.reviewItemId}`, label: "Open review thread" } : null,
          sourceLink,
        ]),
      });
    }
  });

  reviewItems.forEach((item) => {
    if (item.status !== "needs_review") return;
    findings.push({
      id: `review-${item.id}`,
      severity: "high",
      title: `Open review item matched: ${item.title}`,
      detail: item.summary || "The draft overlaps with an unresolved review item.",
      to: `/app/review/${item.id}`,
      toLabel: "Open review thread",
      links: dedupeLinks([
        { to: `/app/review/${item.id}`, label: "Open review thread" },
        { to: "/app/review?status=needs_review", label: "Open review queue" },
      ]),
    });
  });

  const evalFinding = buildEvalFinding(text, context?.evalSummary);
  if (evalFinding) findings.push(evalFinding);

  if (!evidence.length) {
    findings.push({
      id: "no-evidence",
      severity: "medium",
      title: "No grounded evidence matched this draft",
      detail: "The context engine could not find a close match in current decisions or structured facts. The draft may be ahead of the data or missing source support.",
      to: "/app/sources",
      toLabel: "Inspect sources",
      links: dedupeLinks([
        { to: "/app/sources", label: "Inspect sources" },
        { to: "/app/query", label: "Try a query" },
        { to: "/app/connectors", label: "Check connectors" },
      ]),
    });
  }

  const dedupedEvidence = dedupeById(evidence).slice(0, 8);
  const dedupedFindings = dedupeById(findings);

  return {
    verdict: deriveVerdict(dedupedFindings, dedupedEvidence),
    findings: dedupedFindings,
    evidence: dedupedEvidence,
    nextSteps: buildNextSteps(dedupedFindings, dedupedEvidence),
  };
}

function summarizeGuardContext(context) {
  const decisions = context?.decisions ?? [];
  const components = context?.components ?? [];
  return {
    currentDecisions: decisions.filter((item) => item.status === "current").length,
    needsReview: components.filter((item) => item.reviewStatus === "needs_review").length,
    historical: components.filter(
      (item) =>
        item.temporalState === "historical" ||
        item.temporalState === "superseded" ||
        item.reviewStatus === "superseded",
    ).length,
  };
}

function normalizeLaunchGuardApiReport(data) {
  const claims = Array.isArray(data?.claims) ? data.claims : [];
  const evidence = dedupeById(
    claims.flatMap((claim) =>
      (claim.evidence ?? []).map((item, index) => ({
        id: `${claim.claim}-${item.source_document_id ?? item.label ?? index}`,
        title: claim.matched_component_name ?? item.label ?? "Supporting evidence",
        summary: [claim.matched_component_value, item.label].filter(Boolean).join(" · "),
        status: claim.status ?? null,
        to: item.source_document_id ? `/app/sources/${item.source_document_id}` : "/app/sources",
        toLabel: "View source",
        links: dedupeLinks([
          item.source_document_id
            ? { to: `/app/sources/${item.source_document_id}`, label: "View source" }
            : { to: "/app/sources", label: "Inspect sources" },
          claim.matched_component_id != null
            ? { to: "/app/models", label: "Inspect fact" }
            : null,
        ]),
      })),
    ),
  );

  const findings = dedupeById(
    claims.flatMap((claim, index) => {
      if (claim.status === "supported") return [];

      return [
        {
          id: `claim-${index}-${claim.status}`,
          severity: claim.status === "contradicted" || claim.status === "stale" ? "high" : "medium",
          title:
            claim.status === "contradicted"
              ? `Contradicted claim: ${claim.claim}`
              : claim.status === "stale"
                ? `Historical claim: ${claim.claim}`
                : `Unclear claim: ${claim.claim}`,
          detail: claim.reason ?? "Launch Guard could not confidently support this claim.",
          to:
            claim.matched_component_id != null
              ? "/app/models"
              : "/app/sources",
          toLabel:
            claim.matched_component_id != null ? "Inspect fact" : "Inspect sources",
          links: dedupeLinks([
            claim.matched_component_id != null
              ? { to: "/app/models", label: "Inspect fact" }
              : { to: "/app/sources", label: "Inspect sources" },
            ...((claim.evidence ?? [])
              .map((item) =>
                item.source_document_id
                  ? { to: `/app/sources/${item.source_document_id}`, label: "View source" }
                  : null,
              )
              .filter(Boolean)),
          ]),
        },
      ];
    }),
  );

  return {
    verdict: deriveVerdict(findings, evidence),
    findings,
    evidence,
    nextSteps: buildNextSteps(findings, evidence),
  };
}

function matchesNarrative(text, fields) {
  return fields.some((field) => {
    if (!field) return false;
    const normalizedField = normalizeNarrative(field);
    if (!normalizedField) return false;
    if (normalizedField.length > 10 && text.includes(normalizedField)) return true;
    const tokens = tokenize(normalizedField).filter((token) => token.length > 3);
    const matchedTokens = tokens.filter((token) => text.includes(token));
    return matchedTokens.length >= Math.min(2, tokens.length || 0);
  });
}

function buildEvalFinding(text, summary) {
  if (!summary?.domains?.length || summary.threshold == null) return null;

  const domainKeywords = {
    pricing: ["pricing", "seat", "package", "enterprise"],
    blocker: ["blocker", "blocked", "dependency", "delay"],
    roadmap: ["launch", "timeline", "roadmap", "ship", "rollout"],
    decision: ["decision", "decide", "choose", "approved"],
    meeting: ["meeting", "review", "transcript", "recap"],
  };

  const atRisk = summary.domains.find((domain) => {
    if (domain.passRate == null || domain.passRate >= summary.threshold) return false;
    return (domainKeywords[domain.domain] ?? []).some((keyword) => text.includes(keyword));
  });

  if (!atRisk) return null;

  return {
    id: `eval-${atRisk.domain}`,
    severity: "medium",
    title: `Accuracy is still weak for ${atRisk.domain} claims`,
    detail: `${atRisk.passed}/${atRisk.total} benchmark cases are passing in this domain, so this draft deserves extra review.`,
    to: `/app/accuracy?domain=${encodeURIComponent(atRisk.domain)}`,
    toLabel: "Open accuracy dashboard",
  };
}

function deriveVerdict(findings, evidence) {
  const hasHigh = findings.some((item) => item.severity === "high");
  const hasMedium = findings.some((item) => item.severity === "medium");

  if (hasHigh) {
    return {
      label: "High risk",
      detail: "This draft conflicts with current trust state or historical truth and should not ship without review.",
      tone: "rose",
    };
  }
  if (hasMedium || evidence.length === 0) {
    return {
      label: "Needs caution",
      detail: "The draft is partially grounded, but some claims still need stronger evidence or trust checks.",
      tone: "amber",
    };
  }
  return {
    label: "Looks grounded",
    detail: "The draft matches current context without obvious trust warnings, though a human spot-check is still recommended.",
    tone: "emerald",
  };
}

function buildNextSteps(findings, evidence) {
  const steps = [];
  const hasHigh = findings.some((item) => item.severity === "high");
  const hasMedium = findings.some((item) => item.severity === "medium");

  if (hasHigh) {
    steps.push({
      label: "Resolve trust issues",
      detail: "Clear review items and historical conflicts before using this copy.",
      to: "/app/review?status=needs_review",
    });
  }
  if (hasMedium || evidence.length === 0) {
    steps.push({
      label: "Inspect sources",
      detail: "Check the raw documents and make sure the draft is anchored in current evidence.",
      to: "/app/sources",
    });
  }
  steps.push({
    label: "Check decisions",
    detail: "Compare the draft against the latest approved and superseded decisions.",
    to: "/app/decisions",
  });
  steps.push({
    label: "Review timeline",
    detail: "Use the change timeline to see whether a recent update makes this draft stale.",
    to: "/app/changes",
  });

  return steps.slice(0, 3);
}

function dedupeById(items) {
  const seen = new Set();
  return items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function normalizeNarrative(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function tokenize(value) {
  return String(value ?? "")
    .toLowerCase()
    .match(/[a-z0-9$%./-]+/g) ?? [];
}

function SummaryCard({ label, value, tone = "default" }) {
  const tones = {
    default: "border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-300",
    amber: "border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300",
    slate: "border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 text-gray-800 dark:text-gray-300",
  };

  return (
    <div className={`rounded-xl border p-4 ${tones[tone] ?? tones.default}`}>
      <p className="text-[11px] uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function GuardBanner({ report }) {
  const styles = {
    emerald: "border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-300",
    amber: "border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300",
    rose: "border-rose-200 dark:border-rose-800/50 bg-rose-50 dark:bg-rose-900/30 text-rose-800 dark:text-rose-300",
  };

  return (
    <div className={`rounded-xl border p-5 ${styles[report.verdict.tone] ?? styles.amber}`}>
      <p className="text-sm font-semibold">{report.verdict.label}</p>
      <p className="mt-1 text-sm opacity-90">{report.verdict.detail}</p>
    </div>
  );
}

function FindingCard({ item }) {
  const styles = {
    high: "border-rose-200 dark:border-rose-800/50 bg-rose-50 dark:bg-rose-900/30 text-rose-800 dark:text-rose-300",
    medium: "border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300",
    low: "border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 text-gray-800 dark:text-gray-300",
  };
  return (
    <div className={`rounded-lg border px-4 py-3 ${styles[item.severity] ?? styles.low}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">{item.title}</p>
          <p className="mt-1 text-sm opacity-90">{item.detail}</p>
          {resolveCardLinks(item).length > 1 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {resolveCardLinks(item).map((link) => (
                <Link
                  key={`${item.id}-${link.to}-${link.label}`}
                  to={link.to}
                  className="rounded-full border border-current/20 px-2.5 py-1 text-[11px] font-medium hover:bg-white/40"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          )}
        </div>
        <Link to={item.to} className="shrink-0 text-xs font-medium underline underline-offset-2">
          {item.toLabel}
        </Link>
      </div>
    </div>
  );
}

function EvidenceCard({ item }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-300">{item.title}</p>
            {item.status && (
              <span className="rounded-full bg-gray-100 dark:bg-gray-900/40 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
                {String(item.status).replace(/_/g, " ")}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{item.summary}</p>
          {resolveCardLinks(item).length > 1 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {resolveCardLinks(item).map((link) => (
                <Link
                  key={`${item.id}-${link.to}-${link.label}`}
                  to={link.to}
                  className="rounded-full border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-2.5 py-1 text-[11px] font-medium text-gray-600 dark:text-gray-400 hover:border-brand-200 dark:border-brand-800/50 hover:text-brand-700 dark:text-brand-400"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          )}
        </div>
        <Link to={item.to} className="shrink-0 text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          {item.toLabel}
        </Link>
      </div>
    </div>
  );
}

function resolveCardLinks(item) {
  if (Array.isArray(item.links) && item.links.length > 0) {
    return dedupeLinks(item.links);
  }
  if (item.to && item.toLabel) {
    return [{ to: item.to, label: item.toLabel }];
  }
  return [];
}

function dedupeLinks(items) {
  const seen = new Set();
  return (items ?? []).filter((item) => {
    if (!item?.to || !item?.label) return false;
    const key = `${item.to}::${item.label}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function LaunchGuardEmptyState() {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-6 text-center">
      <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">Launch Guard does not have enough context yet.</p>
      <p className="mt-2 text-xs text-gray-500 max-w-2xl mx-auto">
        Sync sources and let the system extract current facts and review state before checking draft copy.
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-4 text-xs">
        <Link to="/app/connectors" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          Connect sources
        </Link>
        <Link to="/app/sources" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          Inspect sources
        </Link>
      </div>
    </div>
  );
}
