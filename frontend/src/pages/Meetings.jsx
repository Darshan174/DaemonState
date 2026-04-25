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

const MEETING_FILTERS = [
  { key: "all", label: "All transcripts" },
  { key: "decisions", label: "Has decisions" },
  { key: "blockers", label: "Has blockers" },
  { key: "pending", label: "Pending extraction" },
];

export default function Meetings() {
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
  } = useSourceDocuments({ connector: "zoom", processed: "all", search: "" });
  const meetings = data ?? [];
  const visibleMeetings = useMemo(
    () => meetings.filter((meeting) => matchesMeetingFilters(meeting, { search, filter })),
    [filter, meetings, search],
  );
  const selectedFromList = useMemo(
    () => visibleMeetings.find((doc) => doc.id === documentId) ?? null,
    [visibleMeetings, documentId],
  );
  const detailQuery = useSourceDocument(documentId && !selectedFromList ? documentId : null);

  useEffect(() => {
    if (meetings.length === 0 || visibleMeetings.length === 0) return;
    const inList = documentId ? visibleMeetings.some((doc) => doc.id === documentId) : false;
    if (!documentId) {
      navigate(`/app/meetings/${visibleMeetings[0].id}`, { replace: true });
      return;
    }
    if (!inList && !detailQuery.isLoading) {
      navigate(`/app/meetings/${visibleMeetings[0].id}`, { replace: true });
    }
  }, [detailQuery.isLoading, documentId, meetings.length, navigate, visibleMeetings]);

  const selectedMeeting = selectedFromList ?? detailQuery.data ?? null;
  const componentsQuery = useSourceDocumentComponents(selectedMeeting?.id ?? null);
  const reviewQuery = useSourceDocumentReviewItems(selectedMeeting?.id ?? null);

  if (isLoading || isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView query={{ isLoading, isError, refetch }} empty="No meetings available yet." />
      </div>
    );
  }

  if (!meetings.length) {
    return (
      <div className="max-w-6xl mx-auto">
        <MeetingsEmptyState />
      </div>
    );
  }

  const showLoadMore = !isMock && hasMore;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">Meetings</h2>
            {isMock && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Review Zoom transcripts as first-class operating context: what was decided, what is blocked, and which facts still need review.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Link to="/app/changes" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open timeline
          </Link>
          <Link to="/app/launch-guard" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open launch guard
          </Link>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(340px,0.95fr)]">
        <section className="overflow-hidden rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800">
          <div className="flex items-start justify-between gap-4 border-b border-gray-100 dark:border-gray-800/30 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-400">Meeting transcripts</p>
              <p className="text-xs text-gray-400">
                {visibleMeetings.length}
                {meetings.length !== visibleMeetings.length ? ` of ${meetings.length}` : ""} loaded transcript
                {visibleMeetings.length === 1 ? "" : "s"} from Zoom.
              </p>
            </div>
            <Link to="/app/connectors" className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Manage Zoom
            </Link>
          </div>
          <div className="border-b border-gray-100 dark:border-gray-800/30 px-4 py-3 space-y-3 bg-gray-50/70">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search topic, host, participant, or transcript text..."
              aria-label="Search meetings"
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-gray-800 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
            <div className="flex flex-wrap gap-2">
              {MEETING_FILTERS.map((item) => {
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
            {visibleMeetings.length > 0 ? visibleMeetings.map((meeting) => {
              const highlights = extractMeetingHighlights(meeting.content);
              return (
                <button
                  key={meeting.id}
                  type="button"
                  onClick={() => navigate(`/app/meetings/${meeting.id}`)}
                  aria-pressed={documentId === meeting.id}
                  className={`w-full px-4 py-4 text-left transition-colors ${
                    documentId === meeting.id ? "bg-brand-50 dark:bg-brand-900/30" : "hover:bg-gray-50 dark:bg-gray-900/30"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-sky-100 dark:bg-sky-900/40 px-2 py-0.5 text-[10px] font-medium text-sky-700 dark:text-sky-400">
                          Zoom transcript
                        </span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                            meeting.processed
                              ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                              : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
                          }`}
                        >
                          {meeting.processed ? "Processed" : "Pending"}
                        </span>
                      </div>
                      <p className="mt-2 truncate text-sm font-medium text-gray-800 dark:text-gray-300">
                        {meeting.meetingTopic || meeting.location || "Untitled meeting"}
                      </p>
                      <p className="mt-1 text-xs text-gray-500">
                        {meeting.host ? `Host ${meeting.host}` : "Unknown host"}
                        {meeting.participants?.length > 0 ? ` · ${meeting.participants.length} participants` : ""}
                      </p>
                      <p className="mt-2 line-clamp-2 text-xs text-gray-500">
                        {highlights.summary}
                      </p>
                    </div>
                    <div className="shrink-0 text-right text-[11px] text-gray-400">
                      <p>{formatDate(meeting.recordingDate || meeting.createdAtSource)}</p>
                      <p className="mt-1">{highlights.decisions} decisions · {highlights.blockers} blockers</p>
                    </div>
                  </div>
                </button>
              );
            }) : (
              <div className="px-4 py-8 text-center">
                <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">No transcripts match this view.</p>
                <p className="mt-2 text-xs text-gray-500">
                  Change the filter or broaden the search to bring more meetings back into scope.
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
                {isFetchingNextPage ? "Loading more..." : "Load more transcripts"}
              </button>
            </div>
          )}
        </section>

        <section className="space-y-4 rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5">
          {selectedMeeting ? (
            <MeetingDetail
              meeting={selectedMeeting}
              components={componentsQuery.data ?? []}
              reviewItems={reviewQuery.data ?? []}
            />
          ) : visibleMeetings.length === 0 ? (
            <p className="text-sm text-gray-500">
              No meeting is selected because the current filters removed every transcript from view.
            </p>
          ) : (
            <p className="text-sm text-gray-500">Select a meeting to inspect its transcript, derived facts, and trust status.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function matchesMeetingFilters(meeting, { search, filter }) {
  const highlights = extractMeetingHighlights(meeting.content);
  const haystack = [
    meeting.meetingTopic,
    meeting.location,
    meeting.host,
    ...(meeting.participants ?? []),
    meeting.content,
  ]
    .filter(Boolean)
    .join("\n")
    .toLowerCase();
  const normalizedSearch = search.trim().toLowerCase();

  if (normalizedSearch && !haystack.includes(normalizedSearch)) {
    return false;
  }

  if (filter === "decisions") return highlights.decisions > 0;
  if (filter === "blockers") return highlights.blockers > 0;
  if (filter === "pending") return !meeting.processed;
  return true;
}

function MeetingDetail({ meeting, components, reviewItems }) {
  const highlights = extractMeetingHighlights(meeting.content);
  const { decisionComponents, blockerComponents, currentComponents, historicalComponents } =
    categorizeMeetingComponents(components);
  const openLoopComponents = blockerComponents.filter(
    (item) => item.temporalState !== "historical" && item.temporalState !== "superseded",
  );

  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">
            {meeting.meetingTopic || meeting.location || "Meeting detail"}
          </h3>
          <p className="mt-1 text-xs text-gray-400">
            Transcript-backed meeting context with derived facts and open trust issues.
          </p>
        </div>
        <Link
          to={`/app/sources/${meeting.id}`}
          className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
        >
          Open source
        </Link>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <DetailStat label="Host" value={meeting.host || "Unknown"} />
        <DetailStat label="Recorded" value={formatDate(meeting.recordingDate || meeting.createdAtSource)} />
        <DetailStat label="Participants" value={meeting.participants?.join(", ") || "Unknown"} />
        <DetailStat label="Transcript status" value={meeting.processed ? "Processed" : "Pending extraction"} />
      </div>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Meeting outcome snapshot</h4>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <OutcomeStat label="Current decisions" value={decisionComponents.length} tone="emerald" />
          <OutcomeStat label="Open loops" value={openLoopComponents.length} tone="amber" />
          <OutcomeStat label="Review threads" value={reviewItems.length} tone="rose" />
          <OutcomeStat label="Historical facts" value={historicalComponents.length} tone="slate" />
        </div>
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Meeting highlights</h4>
        <div className="grid gap-3 md:grid-cols-2">
          <HighlightPanel title="Decisions" items={highlights.decisionItems} empty="No explicit decision lines were found in the transcript." tone="emerald" />
          <HighlightPanel title="Blockers" items={highlights.blockerItems} empty="No explicit blocker lines were found in the transcript." tone="amber" />
        </div>
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Current decisions</h4>
        {decisionComponents.length > 0 ? (
          <div className="space-y-3">
            {decisionComponents.map((component) => (
              <OutcomeCard key={component.id} component={component} label="Decision" tone="emerald" />
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No current decision facts are linked to this meeting yet.</p>
        )}
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Open loops</h4>
        {openLoopComponents.length > 0 ? (
          <div className="space-y-3">
            {openLoopComponents.map((component) => (
              <OutcomeCard
                key={component.id}
                component={component}
                label="Open loop"
                tone={component.reviewStatus === "needs_review" ? "amber" : "slate"}
              />
            ))}
          </div>
        ) : currentComponents.length > 0 ? (
          <p className="text-sm text-gray-600 dark:text-gray-400">
            This meeting has current linked facts, but none are still open blockers or pending loops.
          </p>
        ) : (
          <p className="text-sm text-gray-500">No structured facts are linked to this meeting yet.</p>
        )}
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Historical context</h4>
        {historicalComponents.length > 0 ? (
          <div className="space-y-3">
            {historicalComponents.map((component) => (
              <OutcomeCard key={component.id} component={component} label="Historical" tone="slate" />
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">
            No superseded or historical facts are linked to this meeting yet.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Review pressure</h4>
        {reviewItems.length > 0 ? (
          <div className="space-y-3">
            {reviewItems.map((item) => (
              <div key={item.id} className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-amber-800 dark:text-amber-300">{item.title}</p>
                    <p className="mt-1 text-sm text-amber-700 dark:text-amber-400">{item.summary}</p>
                  </div>
                  <Link to={`/app/review/${item.id}`} className="text-xs font-medium text-amber-800 dark:text-amber-300 underline underline-offset-2">
                    Open
                  </Link>
                </div>
              </div>
            ))}
          </div>
        ) : blockerComponents.length > 0 ? (
          <p className="text-sm text-gray-600 dark:text-gray-400">
            This meeting produced blocker facts, but there are no explicit review items attached yet.
          </p>
        ) : (
          <p className="text-sm text-gray-500">No review items are linked to this meeting.</p>
        )}
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Transcript preview</h4>
        <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-3 text-sm leading-relaxed text-gray-700 dark:text-gray-400">
          {meeting.content || "No transcript content is available."}
        </div>
      </section>
    </>
  );
}

function HighlightPanel({ title, items, empty, tone }) {
  const toneClass = tone === "emerald" ? "border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30" : "border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30";
  const textClass = tone === "emerald" ? "text-emerald-800 dark:text-emerald-300" : "text-amber-800 dark:text-amber-300";
  return (
    <div className={`rounded-lg border px-4 py-3 ${toneClass}`}>
      <p className={`text-sm font-medium ${textClass}`}>{title}</p>
      {items.length > 0 ? (
        <ul className="mt-2 space-y-2">
          {items.map((item, index) => (
            <li key={`${title}-${index}`} className={`text-sm ${textClass}`}>
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className={`mt-2 text-sm ${textClass}`}>{empty}</p>
      )}
    </div>
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

function OutcomeCard({ component, label, tone }) {
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
            {component.reviewStatus && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                component.reviewStatus === "needs_review"
                  ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
                  : component.reviewStatus === "approved"
                    ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                    : component.reviewStatus === "historical"
                      ? "bg-gray-100 dark:bg-gray-900/40 text-gray-600 dark:text-gray-400"
                      : "bg-slate-100 dark:bg-slate-900/40 text-slate-700 dark:text-slate-400"
              }`}>
                {component.reviewStatus.replace(/_/g, " ")}
              </span>
            )}
            {component.temporalState && (
              <span className="rounded-full bg-gray-100 dark:bg-gray-900/40 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
                {component.temporalState.replace(/_/g, " ")}
              </span>
            )}
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
            {component.validTo ? (
              <span className="rounded-full bg-white/80 px-2 py-1">
                <span className="font-medium text-gray-700 dark:text-gray-400">Until:</span> {formatDate(component.validTo)}
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

function extractMeetingHighlights(content) {
  const lines = String(content ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const decisionItems = lines
    .filter((line) => line.toLowerCase().includes("decision:"))
    .map((line) => line.replace(/^.*decision:\s*/i, "").trim());
  const blockerItems = lines
    .filter((line) => line.toLowerCase().includes("blocker:"))
    .map((line) => line.replace(/^.*blocker:\s*/i, "").trim());
  const summary = lines.slice(0, 3).join(" ");
  return {
    decisions: decisionItems.length,
    blockers: blockerItems.length,
    decisionItems,
    blockerItems,
    summary: summary || "No transcript preview available.",
  };
}

function categorizeMeetingComponents(components) {
  const historicalComponents = [];
  const currentComponents = [];
  const decisionComponents = [];
  const blockerComponents = [];

  for (const component of components) {
    const haystack = [component.name, component.value].filter(Boolean).join(" ").toLowerCase();
    const isHistorical =
      component.temporalState === "historical" ||
      component.temporalState === "superseded" ||
      component.validTo != null;

    if (isHistorical) historicalComponents.push(component);
    else currentComponents.push(component);

    if (!isHistorical && haystack.includes("decision")) {
      decisionComponents.push(component);
    }
    if (haystack.includes("blocker") || haystack.includes("waiting on") || haystack.includes("blocked")) {
      blockerComponents.push(component);
    }
  }

  return { decisionComponents, blockerComponents, currentComponents, historicalComponents };
}

function formatDate(value) {
  if (!value) return "Unknown";
  try {
    return new Date(value).toLocaleDateString();
  } catch {
    return value;
  }
}

function MeetingsEmptyState() {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-6 text-center">
      <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">No Zoom meeting transcripts yet.</p>
      <p className="mt-2 text-xs text-gray-500 max-w-2xl mx-auto">
        Connect Zoom and run a transcript sync to turn meetings into source-backed context for decisions and blockers.
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-4 text-xs">
        <Link to="/app/connectors" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          Connect Zoom
        </Link>
        <Link to="/app/sources?connector=zoom" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          Open sources
        </Link>
      </div>
    </div>
  );
}
