import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useSourceDocument,
  useSourceDocumentComponents,
  useSourceDocumentReviewItems,
  useSourceDocuments,
} from "../api/hooks";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";

const ENGINEERING_FILTERS = [
  { key: "all", label: "All activity" },
  { key: "decisions", label: "Decision signals" },
  { key: "refs", label: "Refs attached" },
  { key: "pending", label: "Pending extraction" },
];

export default function Engineering() {
  const navigate = useNavigate();
  const { documentId } = useParams();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const {
    data,
    isLoading,
    isError,
    isMock,
    hasMore,
    fetchNextPage,
    isFetchingNextPage,
    refetch,
  } = useSourceDocuments({ connector: "github", processed: "all", search: "" });
  const items = data ?? [];
  const visibleItems = useMemo(
    () => items.filter((item) => matchesEngineeringFilters(item, { search, filter })),
    [filter, items, search],
  );
  const selectedFromList = useMemo(
    () => visibleItems.find((doc) => doc.id === documentId) ?? null,
    [visibleItems, documentId],
  );
  const detailQuery = useSourceDocument(documentId && !selectedFromList ? documentId : null);

  useEffect(() => {
    if (items.length === 0 || visibleItems.length === 0) return;
    const inList = documentId ? visibleItems.some((doc) => doc.id === documentId) : false;
    if (!documentId) {
      navigate(`/app/engineering/${visibleItems[0].id}`, { replace: true });
      return;
    }
    if (!inList && !detailQuery.isLoading) {
      navigate(`/app/engineering/${visibleItems[0].id}`, { replace: true });
    }
  }, [detailQuery.isLoading, documentId, items.length, navigate, visibleItems]);

  const selectedItem = selectedFromList ?? detailQuery.data ?? null;
  const componentsQuery = useSourceDocumentComponents(selectedItem?.id ?? null);
  const reviewQuery = useSourceDocumentReviewItems(selectedItem?.id ?? null);

  if (isLoading || isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView query={{ isLoading, isError, refetch }} empty="No GitHub activity available yet." />
      </div>
    );
  }

  if (!items.length) {
    return (
      <div className="max-w-6xl mx-auto">
        <EngineeringEmptyState />
      </div>
    );
  }

  const showLoadMore = !isMock && hasMore;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">Engineering</h2>
            {isMock && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Pull requests, issues, review comments, and linked facts in one operating view so engineering rationale is source-backed instead of buried in threads.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Link to="/app/changes" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open timeline
          </Link>
          <Link to="/app/decisions" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open decision register
          </Link>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(340px,0.95fr)]">
        <section className="overflow-hidden rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800">
          <div className="flex items-start justify-between gap-4 border-b border-gray-100 dark:border-gray-800/30 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-400">GitHub activity</p>
              <p className="text-xs text-gray-400">
                {visibleItems.length}
                {items.length !== visibleItems.length ? ` of ${items.length}` : ""} loaded engineering item
                {visibleItems.length === 1 ? "" : "s"} from GitHub.
              </p>
            </div>
            <Link to="/app/connectors" className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Manage GitHub
            </Link>
          </div>
          <div className="border-b border-gray-100 dark:border-gray-800/30 px-4 py-3 space-y-3 bg-gray-50/70">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search repository, title, author, or discussion text..."
              aria-label="Search engineering activity"
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-gray-800 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
            <div className="flex flex-wrap gap-2">
              {ENGINEERING_FILTERS.map((item) => {
                const active = filter === item.key;
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setFilter(item.key)}
                    aria-pressed={active}
                    className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                      active
                        ? "bg-brand-600 text-white"
                        : "bg-white dark:bg-slate-800 text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-800/50 hover:bg-gray-100 dark:bg-gray-900/40"
                    }`}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="divide-y divide-gray-100">
            {visibleItems.length > 0 ? visibleItems.map((item) => {
              const summary = extractEngineeringSummary(item);
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigate(`/app/engineering/${item.id}`)}
                  aria-pressed={documentId === item.id}
                  className={`w-full px-4 py-4 text-left transition-colors ${
                    documentId === item.id ? "bg-brand-50 dark:bg-brand-900/30" : "hover:bg-gray-50 dark:bg-gray-900/30"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-slate-100 dark:bg-slate-900/40 px-2 py-0.5 text-[10px] font-medium text-slate-700 dark:text-slate-400">
                          {formatGitHubItemType(item.githubItemType)}
                        </span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                            item.processed
                              ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                              : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
                          }`}
                        >
                          {item.processed ? "Processed" : "Pending"}
                        </span>
                      </div>
                      <p className="mt-2 truncate text-sm font-medium text-gray-800 dark:text-gray-300">
                        {item.documentTitle || item.location || item.externalId || "Untitled GitHub item"}
                      </p>
                      <p className="mt-1 text-xs text-gray-500">
                        {item.repository || "Unknown repository"}
                        {item.author ? ` · ${item.author}` : ""}
                      </p>
                      <p className="mt-2 line-clamp-2 text-xs text-gray-500">{summary.preview}</p>
                    </div>
                    <div className="shrink-0 text-right text-[11px] text-gray-400">
                      <p>{formatDate(item.createdAtSource || item.ingestedAt)}</p>
                      <p className="mt-1">
                        {summary.references} refs · {summary.decisions} decisions
                      </p>
                    </div>
                  </div>
                </button>
              );
            }) : (
              <div className="px-4 py-8 text-center">
                <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">No engineering activity matches this view.</p>
                <p className="mt-2 text-xs text-gray-500">
                  Clear the search or switch filters to bring more GitHub context back into scope.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setSearch("");
                    setFilter("all");
                  }}
                  className="mt-4 rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30"
                >
                  Clear filters
                </button>
              </div>
            )}
          </div>
          {showLoadMore && (
            <div className="border-t border-gray-100 dark:border-gray-800/30 bg-gray-50 dark:bg-gray-900/30 px-4 py-3">
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:opacity-60"
              >
                {isFetchingNextPage ? "Loading more..." : "Load more engineering activity"}
              </button>
            </div>
          )}
        </section>

        <section className="space-y-4 rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5">
          {selectedItem ? (
            <EngineeringDetail
              item={selectedItem}
              components={componentsQuery.data ?? []}
              reviewItems={reviewQuery.data ?? []}
            />
          ) : visibleItems.length === 0 ? (
            <p className="text-sm text-gray-500">
              No engineering item is selected because the current filters removed every GitHub item from view.
            </p>
          ) : (
            <p className="text-sm text-gray-500">Select a GitHub item to inspect the code discussion, linked facts, and review pressure.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function EngineeringDetail({ item, components, reviewItems }) {
  const summary = extractEngineeringSummary(item);
  const { decisionComponents, blockerComponents, supportingComponents, historicalComponents } =
    categorizeEngineeringComponents(components);

  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">
            {item.documentTitle || item.location || "Engineering detail"}
          </h3>
          <p className="mt-1 text-xs text-gray-400">
            GitHub-backed implementation context with linked facts, review pressure, and source references.
          </p>
        </div>
        <Link
          to={`/app/sources/${item.id}`}
          className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
        >
          Open source
        </Link>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <DetailStat label="Repository" value={item.repository || "Unknown"} />
        <DetailStat label="Item type" value={formatGitHubItemType(item.githubItemType)} />
        <DetailStat label="Author" value={item.author || "Unknown"} />
        <DetailStat label="Captured" value={formatDate(item.createdAtSource || item.ingestedAt)} />
      </div>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Engineering signal snapshot</h4>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <OutcomeStat label="PR / commit refs" value={summary.references} tone="slate" />
          <OutcomeStat label="Linked decisions" value={decisionComponents.length} tone="emerald" />
          <OutcomeStat label="Open blockers" value={blockerComponents.length} tone="amber" />
          <OutcomeStat label="Review threads" value={reviewItems.length} tone="rose" />
        </div>
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Code references</h4>
        <div className="grid gap-3 md:grid-cols-2">
          <ReferencePanel
            title="Pull requests"
            items={item.pullRequestReferences ?? []}
            empty="No pull request references are attached to this item yet."
          />
          <ReferencePanel
            title="Commits"
            items={item.commitReferences ?? []}
            empty="No commit references are attached to this item yet."
          />
        </div>
        {item.parentExternalId ? (
          <p className="text-xs text-gray-500">
            Parent thread: <span className="font-mono text-gray-700 dark:text-gray-400">{item.parentExternalId}</span>
          </p>
        ) : null}
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Linked decisions</h4>
        {decisionComponents.length > 0 ? (
          <div className="space-y-3">
            {decisionComponents.map((component) => (
              <EngineeringComponentCard key={component.id} component={component} label="Decision" tone="emerald" />
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No decision facts are linked to this GitHub item yet.</p>
        )}
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Blocked or pending work</h4>
        {blockerComponents.length > 0 ? (
          <div className="space-y-3">
            {blockerComponents.map((component) => (
              <EngineeringComponentCard key={component.id} component={component} label="Blocker" tone="amber" />
            ))}
          </div>
        ) : supportingComponents.length > 0 ? (
          <div className="space-y-3">
            {supportingComponents.map((component) => (
              <EngineeringComponentCard key={component.id} component={component} label="Supporting fact" tone="slate" />
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No linked engineering facts are attached to this item yet.</p>
        )}
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Historical context</h4>
        {historicalComponents.length > 0 ? (
          <div className="space-y-3">
            {historicalComponents.map((component) => (
              <EngineeringComponentCard key={component.id} component={component} label="Historical" tone="slate" />
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No historical facts are linked to this GitHub item yet.</p>
        )}
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Review pressure</h4>
        {reviewItems.length > 0 ? (
          <div className="space-y-3">
            {reviewItems.map((review) => (
              <div key={review.id} className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-amber-800 dark:text-amber-300">{review.title}</p>
                    <p className="mt-1 text-sm text-amber-700 dark:text-amber-400">{review.summary}</p>
                  </div>
                  <Link to={`/app/review/${review.id}`} className="text-xs font-medium text-amber-800 dark:text-amber-300 underline underline-offset-2">
                    Open
                  </Link>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No review items are linked to this engineering item.</p>
        )}
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Source excerpt</h4>
        <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-3 text-sm leading-relaxed text-gray-700 dark:text-gray-400">
          {item.content || "No source content is available."}
        </div>
      </section>
    </>
  );
}

function DetailStat({ label, value }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-1 text-sm text-gray-700 dark:text-gray-400">{value}</p>
    </div>
  );
}

function OutcomeStat({ label, value, tone }) {
  const classes = {
    emerald: "border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-300",
    amber: "border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300",
    rose: "border-rose-200 dark:border-rose-800/50 bg-rose-50 dark:bg-rose-900/30 text-rose-800 dark:text-rose-300",
    slate: "border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 text-gray-800 dark:text-gray-300",
  };
  return (
    <div className={`rounded-lg border px-4 py-3 ${classes[tone] ?? classes.slate}`}>
      <p className="text-[11px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function ReferencePanel({ title, items, empty }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-3">
      <p className="text-sm font-medium text-gray-800 dark:text-gray-300">{title}</p>
      {items.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {items.map((item) => (
            <span key={`${title}-${item}`} className="rounded-full bg-white dark:bg-slate-800 px-2 py-1 text-[11px] font-medium text-gray-700 dark:text-gray-400">
              {item}
            </span>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-gray-500">{empty}</p>
      )}
    </div>
  );
}

function EngineeringComponentCard({ component, label, tone }) {
  const toneClasses = {
    emerald: "border-emerald-200 dark:border-emerald-800/50 bg-emerald-50/70",
    amber: "border-amber-200 dark:border-amber-800/50 bg-amber-50/70",
    slate: "border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30",
  };
  return (
    <div className={`rounded-lg border px-4 py-3 ${toneClasses[tone] ?? toneClasses.slate}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
              {label}
            </span>
            <p className="text-sm font-medium text-gray-800 dark:text-gray-300">{component.name}</p>
            {component.reviewStatus ? (
              <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
                {component.reviewStatus.replace(/_/g, " ")}
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{component.value}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
            {component.modelName ? (
              <span className="rounded-full bg-white/80 px-2 py-1">
                <span className="font-medium text-gray-700 dark:text-gray-400">Model:</span> {component.modelName}
              </span>
            ) : null}
            {component.authorityWeight != null ? (
              <span className="rounded-full bg-white/80 px-2 py-1">
                <span className="font-medium text-gray-700 dark:text-gray-400">Authority:</span> {component.authorityWeight.toFixed(2)}
              </span>
            ) : null}
            {component.validFrom ? (
              <span className="rounded-full bg-white/80 px-2 py-1">
                <span className="font-medium text-gray-700 dark:text-gray-400">Active from:</span> {formatDate(component.validFrom)}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          {component.modelId ? (
            <Link to={`/app/model/${component.modelId}`} className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Open model
            </Link>
          ) : null}
          {component.reviewItemId ? (
            <Link to={`/app/review/${component.reviewItemId}`} className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Open review
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function extractEngineeringSummary(item) {
  const content = String(item.content ?? "");
  const decisions = (content.match(/decision:/gi) ?? []).length;
  const blockers = (content.match(/blocker:|blocked by|waiting on/gi) ?? []).length;
  const references = (item.pullRequestReferences?.length ?? 0) + (item.commitReferences?.length ?? 0);
  const preview = content.split("\n").slice(0, 3).join(" ") || "No preview available.";
  return { decisions, blockers, references, preview };
}

function matchesEngineeringFilters(item, { search, filter }) {
  const summary = extractEngineeringSummary(item);
  const haystack = [
    item.repository,
    item.documentTitle,
    item.author,
    item.content,
    item.parentExternalId,
    ...(item.pullRequestReferences ?? []),
    ...(item.commitReferences ?? []),
  ]
    .filter(Boolean)
    .join("\n")
    .toLowerCase();
  const normalizedSearch = search.trim().toLowerCase();

  if (normalizedSearch && !haystack.includes(normalizedSearch)) {
    return false;
  }

  if (filter === "decisions") return summary.decisions > 0;
  if (filter === "refs") return summary.references > 0;
  if (filter === "pending") return !item.processed;
  return true;
}

function categorizeEngineeringComponents(components) {
  const decisionComponents = [];
  const blockerComponents = [];
  const supportingComponents = [];
  const historicalComponents = [];

  for (const component of components) {
    const haystack = [component.name, component.value].filter(Boolean).join(" ").toLowerCase();
    const isHistorical =
      component.temporalState === "historical" ||
      component.temporalState === "superseded" ||
      component.validTo != null;

    if (isHistorical) {
      historicalComponents.push(component);
      continue;
    }

    if (haystack.includes("decision")) {
      decisionComponents.push(component);
      continue;
    }

    if (haystack.includes("blocker") || haystack.includes("waiting on") || haystack.includes("blocked")) {
      blockerComponents.push(component);
      continue;
    }

    supportingComponents.push(component);
  }

  return { decisionComponents, blockerComponents, supportingComponents, historicalComponents };
}

function formatGitHubItemType(value) {
  if (!value) return "GitHub item";
  return String(value).replaceAll("_", " ");
}

function formatDate(value) {
  if (!value) return "Unknown";
  try {
    return new Date(value).toLocaleDateString();
  } catch {
    return value;
  }
}

function EngineeringEmptyState() {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-6 text-center">
      <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">No GitHub activity yet.</p>
      <p className="mt-2 text-xs text-gray-500 max-w-2xl mx-auto">
        Connect GitHub and sync issues, pull requests, and review comments so engineering rationale becomes part of the operating context.
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-4 text-xs">
        <Link to="/app/connectors" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          Connect GitHub
        </Link>
        <Link to="/app/sources?connector=github" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          Open sources
        </Link>
      </div>
    </div>
  );
}
