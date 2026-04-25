import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useConnectorProcessingSummary,
  useDeleteSourceDocument,
  useReprocessSourceDocument,
  useRestoreSourceDocument,
  useSourceDocument,
  useSourceDocumentComponents,
  useSourceDocumentReviewItems,
  useSourceDocuments,
} from "../api/hooks";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";

const CONNECTOR_OPTIONS = [
  { value: "all", label: "All connectors" },
  { value: "slack", label: "Slack" },
  { value: "notion", label: "Notion" },
  { value: "zoom", label: "Zoom" },
  { value: "github", label: "GitHub" },
  { value: "gdrive", label: "Google Drive" },
  { value: "gong", label: "Gong" },
];

const PROCESSED_OPTIONS = [
  { value: "all", label: "All states" },
  { value: "processed", label: "Processed" },
  { value: "unprocessed", label: "Pending" },
];

const CONNECTOR_PILL = {
  slack: "bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-400",
  notion: "bg-gray-100 dark:bg-gray-900/40 text-gray-700 dark:text-gray-400",
  zoom: "bg-sky-100 dark:bg-sky-900/40 text-sky-700 dark:text-sky-400",
  github: "bg-slate-100 dark:bg-slate-900/40 text-slate-700 dark:text-slate-400",
  gdrive: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400",
  gong: "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-400",
  unknown: "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400",
};

export default function Sources() {
  const navigate = useNavigate();
  const { documentId } = useParams();
  const [connector, setConnector] = useState("all");
  const [processed, setProcessed] = useState("all");
  const [search, setSearch] = useState("");
  const {
    data,
    total,
    hasMore,
    fetchNextPage,
    isFetchingNextPage,
    isMock,
    ...query
  } = useSourceDocuments({ connector, processed, search });
  const summaryQuery = useConnectorProcessingSummary();
  const reprocessMut = useReprocessSourceDocument();
  const deleteMut = useDeleteSourceDocument();
  const restoreMut = useRestoreSourceDocument();
  const documents = data ?? [];
  const [reprocessMessage, setReprocessMessage] = useState("");
  const [reprocessError, setReprocessError] = useState("");
  const [deleteMessage, setDeleteMessage] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [lastDeletedDocument, setLastDeletedDocument] = useState(null);
  const filtersActive = connector !== "all" || processed !== "all" || search.trim().length > 0;
  const selectedFromList = useMemo(
    () => documents.find((doc) => doc.id === documentId) ?? null,
    [documents, documentId],
  );
  const detailQuery = useSourceDocument(documentId && !selectedFromList ? documentId : null);

  useEffect(() => {
    if (documents.length === 0) {
      return;
    }
    const inList = documentId ? documents.some((doc) => doc.id === documentId) : false;
    if (!documentId) {
      navigate(`/app/sources/${documents[0].id}`, { replace: true });
      return;
    }
    if (!inList && !detailQuery.isLoading && !detailQuery.data) {
      navigate(`/app/sources/${documents[0].id}`, { replace: true });
    }
  }, [documents, documentId, detailQuery.data, detailQuery.isLoading, navigate]);

  const selectedDocument = useMemo(
    () => selectedFromList ?? detailQuery.data ?? null,
    [selectedFromList, detailQuery.data],
  );

  useEffect(() => {
    setReprocessMessage("");
    setReprocessError("");
    setDeleteError("");
  }, [selectedDocument?.id]);

  const componentRefsQuery = useSourceDocumentComponents(selectedDocument?.id ?? null);
  const reviewRefsQuery = useSourceDocumentReviewItems(selectedDocument?.id ?? null);

  if (query.isLoading || query.isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView query={query} empty="No source documents yet." />
      </div>
    );
  }

  const processedCount = documents.filter((doc) => doc.processed).length;
  const pendingCount = documents.length - processedCount;
  const summaries = summaryQuery.data?.items ?? [];
  const showLoadMore = !isMock && hasMore;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">Sources</h2>
            {isMock && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Inspect the raw documents that feed the knowledge graph before and after extraction.
          </p>
          {isMock && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-2">
              Showing demo source documents until the backend source-documents API is available.
            </p>
          )}
        </div>
        <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-4 py-3 text-right">
          <p className="text-[11px] uppercase tracking-wide text-gray-400">Pipeline</p>
          <p className="text-sm font-medium text-gray-700 dark:text-gray-400">
            {documents.length} stored · {processedCount} processed · {pendingCount} pending
          </p>
        </div>
      </div>

      {summaries.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {summaries.map((summary) => (
            <div
              key={summary.connectorType}
              className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-4 py-3"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-gray-700 dark:text-gray-400 capitalize">
                  {summary.connectorType}
                </p>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                    summary.status === "connected"
                      ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                      : summary.status === "error"
                        ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400"
                        : "bg-gray-100 dark:bg-gray-900/40 text-gray-600 dark:text-gray-400"
                  }`}
                >
                  {summary.status}
                </span>
              </div>
              <p className="mt-3 text-lg font-semibold text-gray-800 dark:text-gray-300">
                {summary.totalDocuments}
              </p>
              <p className="text-xs text-gray-500">
                {summary.processedDocuments} processed · {summary.unprocessedDocuments} pending
              </p>
              <p className="mt-2 text-[11px] text-gray-400">
                Last sync {summary.lastSyncAt}
              </p>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px_220px]">
        <label className="block">
          <span className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Search</span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search content, author, channel, page, or meeting..."
            aria-label="Search source documents"
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </label>

        <label className="block">
          <span className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Connector</span>
          <select
            value={connector}
            onChange={(e) => setConnector(e.target.value)}
            aria-label="Filter source documents by connector"
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          >
            {CONNECTOR_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Processing</span>
          <select
            value={processed}
            onChange={(e) => setProcessed(e.target.value)}
            aria-label="Filter source documents by processing state"
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          >
            {PROCESSED_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {documents.length === 0 ? (
        <SourceEmptyState filtersActive={filtersActive} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
          <section
            aria-label="Stored documents"
            className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 overflow-hidden"
          >
            <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-800/30 flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-gray-700 dark:text-gray-400">Stored documents</p>
                <p className="text-xs text-gray-400">
                  Showing {documents.length} loaded{typeof total === "number" ? ` of ${total}` : ""}. Select a document to inspect its raw content and lineage.
                </p>
              </div>
              <Link to="/app/connectors" className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
                Back to connectors
              </Link>
            </div>

            <div className="divide-y divide-gray-100">
              {documents.map((doc) => (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => navigate(`/app/sources/${doc.id}`)}
                  aria-pressed={documentId === doc.id}
                  className={`w-full text-left px-4 py-4 transition-colors ${
                    documentId === doc.id ? "bg-brand-50 dark:bg-brand-900/30" : "hover:bg-gray-50 dark:bg-gray-900/30"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                            CONNECTOR_PILL[doc.connectorType] ?? CONNECTOR_PILL.unknown
                          }`}
                        >
                          {doc.connectorType}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                            doc.processed
                              ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                              : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
                          }`}
                        >
                          {doc.processed ? "Processed" : "Pending"}
                        </span>
                        {doc.location && (
                          <span className="text-[11px] text-gray-400 truncate">{doc.location}</span>
                        )}
                      </div>
                      <p className="mt-2 text-sm font-medium text-gray-800 dark:text-gray-300 truncate">
                        {formatDocumentListTitle(doc)}
                      </p>
                      <p className="mt-1 text-xs text-gray-500 line-clamp-2">
                        {formatDocumentListSubtitle(doc)}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-[11px] text-gray-400">{formatDate(doc.createdAtSource)}</p>
                      <p className="text-[11px] text-gray-400 mt-1">Ingested {formatDate(doc.ingestedAt)}</p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
            {showLoadMore && (
              <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-800/30 bg-gray-50 dark:bg-gray-900/30">
                <button
                  type="button"
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                  className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:text-gray-400 disabled:cursor-not-allowed"
                >
                  {isFetchingNextPage ? "Loading more..." : "Load more documents"}
                </button>
              </div>
            )}
          </section>

          <section
            aria-label="Document detail"
            className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5 space-y-4"
          >
            {detailQuery.isError && !selectedDocument ? (
              <StatusView
                query={{ isLoading: false, isError: true, error: detailQuery.error, refetch: detailQuery.refetch }}
                empty=""
              />
            ) : detailQuery.isLoading && !selectedDocument ? (
              <StatusView query={{ isLoading: true, isError: false }} empty="" />
            ) : selectedDocument ? (
              <>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Document detail</h3>
                    <p className="mt-1 text-xs text-gray-400">
                      Inspect raw content, downstream usage, and re-run extraction when the source changes.
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Link
                      to={buildSourceGraphHref(
                        selectedDocument,
                        componentRefsQuery.data?.[0] ?? null,
                      )}
                      className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 transition-colors shadow-sm"
                    >
                      Explore graph
                    </Link>
                    <Link
                      to={`/app/decisions?source_id=${selectedDocument.id}`}
                      className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
                    >
                      Decisions
                    </Link>
                    <Link
                      to={`/app/changes?source_id=${selectedDocument.id}`}
                      className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
                    >
                      Changes
                    </Link>
                    {!isMock && (
                      <button
                        type="button"
                        onClick={() => {
                          setReprocessMessage("");
                          setReprocessError("");
                          reprocessMut.mutate(selectedDocument.id, {
                            onSuccess: (job) => {
                              setReprocessMessage(
                                `${job.jobType === "reprocess" ? "Reprocess" : "Processing"} queued as ${job.status}.`,
                              );
                            },
                            onError: (err) => {
                              setReprocessError(err?.message || "Failed to queue reprocess.");
                            },
                          });
                        }}
                        disabled={
                          reprocessMut.isPending &&
                          reprocessMut.variables === selectedDocument.id
                        }
                        className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {reprocessMut.isPending && reprocessMut.variables === selectedDocument.id
                          ? "Queueing..."
                          : selectedDocument.processed
                            ? "Reprocess"
                            : "Run extraction"}
                      </button>
                    )}
                    {!isMock && (
                      <button
                        type="button"
                        onClick={() => {
                          if (!window.confirm("Remove this source document from the workspace? You can undo this immediately after deletion.")) {
                            return;
                          }
                          setDeleteMessage("");
                          setDeleteError("");
                          deleteMut.mutate(selectedDocument.id, {
                            onSuccess: () => {
                              const label =
                                selectedDocument.documentTitle ||
                                selectedDocument.location ||
                                selectedDocument.author ||
                                selectedDocument.externalId;
                              const fallbackDocument = documents.find(
                                (doc) => doc.id !== selectedDocument.id,
                              );
                              setLastDeletedDocument({
                                id: selectedDocument.id,
                                label,
                              });
                              setDeleteMessage(`Removed ${label} from the workspace.`);
                              navigate(
                                fallbackDocument
                                  ? `/app/sources/${fallbackDocument.id}`
                                  : "/app/sources",
                              );
                            },
                            onError: (err) => {
                              setDeleteError(err?.message || "Failed to delete document.");
                            },
                          });
                        }}
                        disabled={
                          deleteMut.isPending &&
                          deleteMut.variables === selectedDocument.id
                        }
                        className="rounded-lg border border-red-200 dark:border-red-800/50 bg-white dark:bg-slate-800 px-3 py-1.5 text-xs font-medium text-red-700 dark:text-red-400 hover:bg-red-50 dark:bg-red-900/30 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {deleteMut.isPending && deleteMut.variables === selectedDocument.id
                          ? "Removing..."
                          : "Remove source"}
                      </button>
                    )}
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                        selectedDocument.processed
                          ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                          : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
                      }`}
                    >
                      {selectedDocument.processed ? "Processed" : "Pending extraction"}
                    </span>
                  </div>
                </div>

                {reprocessMessage && (
                  <p role="status" className="rounded-lg border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-400">
                    {reprocessMessage}
                  </p>
                )}
                {deleteMessage && (
                  <div
                    role="status"
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-400"
                  >
                    <span>{deleteMessage}</span>
                    {lastDeletedDocument && (
                      <button
                        type="button"
                        onClick={() => {
                          setDeleteError("");
                          restoreMut.mutate(lastDeletedDocument.id, {
                            onSuccess: (document) => {
                              setDeleteMessage(`Restored ${lastDeletedDocument.label}.`);
                              setLastDeletedDocument(null);
                              if (document?.id) {
                                navigate(`/app/sources/${document.id}`);
                              }
                            },
                            onError: (err) => {
                              setDeleteError(err?.message || "Failed to restore document.");
                            },
                          });
                        }}
                        disabled={restoreMut.isPending}
                        className="rounded-lg border border-emerald-300 bg-white dark:bg-slate-800 px-2.5 py-1 font-medium text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:bg-emerald-900/40 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {restoreMut.isPending ? "Restoring..." : "Undo"}
                      </button>
                    )}
                  </div>
                )}
                {reprocessError && (
                  <p role="alert" className="rounded-lg border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/30 px-3 py-2 text-xs text-red-700 dark:text-red-400">
                    {reprocessError}
                  </p>
                )}
                {deleteError && (
                  <p role="alert" className="rounded-lg border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/30 px-3 py-2 text-xs text-red-700 dark:text-red-400">
                    {deleteError}
                  </p>
                )}

                <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-y-2 text-xs">
                  <dt className="text-gray-400">Connector</dt>
                  <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.connectorType}</dd>
                  <dt className="text-gray-400">Author</dt>
                  <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.author || "Unknown"}</dd>
                  <dt className="text-gray-400">Location</dt>
                  <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.location || "—"}</dd>
                  {selectedDocument.repository && (
                    <>
                      <dt className="text-gray-400">Repository</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.repository}</dd>
                    </>
                  )}
                  {selectedDocument.documentTitle && (
                    <>
                      <dt className="text-gray-400">Title</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.documentTitle}</dd>
                    </>
                  )}
                  {selectedDocument.githubItemType && (
                    <>
                      <dt className="text-gray-400">GitHub item</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.githubItemType.replaceAll("_", " ")}</dd>
                    </>
                  )}
                  {selectedDocument.parentExternalId && (
                    <>
                      <dt className="text-gray-400">Parent</dt>
                      <dd className="text-gray-700 dark:text-gray-400 break-all">{selectedDocument.parentExternalId}</dd>
                    </>
                  )}
                  {selectedDocument.pullRequestReferences?.length > 0 && (
                    <>
                      <dt className="text-gray-400">PR refs</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.pullRequestReferences.join(", ")}</dd>
                    </>
                  )}
                  {selectedDocument.commitReferences?.length > 0 && (
                    <>
                      <dt className="text-gray-400">Commit refs</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.commitReferences.join(", ")}</dd>
                    </>
                  )}
                  {selectedDocument.meetingTopic && (
                    <>
                      <dt className="text-gray-400">Meeting</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.meetingTopic}</dd>
                    </>
                  )}
                  {selectedDocument.host && (
                    <>
                      <dt className="text-gray-400">Host</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.host}</dd>
                    </>
                  )}
                  {selectedDocument.participants?.length > 0 && (
                    <>
                      <dt className="text-gray-400">Participants</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.participants.join(", ")}</dd>
                    </>
                  )}
                  {selectedDocument.recordingDate && (
                    <>
                      <dt className="text-gray-400">Recording date</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{formatDate(selectedDocument.recordingDate)}</dd>
                    </>
                  )}
                  {selectedDocument.sourceType && (
                    <>
                      <dt className="text-gray-400">Source type</dt>
                      <dd className="text-gray-700 dark:text-gray-400">{selectedDocument.sourceType.replaceAll("_", " ")}</dd>
                    </>
                  )}
                  <dt className="text-gray-400">Created</dt>
                  <dd className="text-gray-700 dark:text-gray-400">{formatDate(selectedDocument.createdAtSource)}</dd>
                  <dt className="text-gray-400">Ingested</dt>
                  <dd className="text-gray-700 dark:text-gray-400">{formatDate(selectedDocument.ingestedAt)}</dd>
                  <dt className="text-gray-400">Processed</dt>
                  <dd className="text-gray-700 dark:text-gray-400">{formatDate(selectedDocument.processedAt)}</dd>
                  <dt className="text-gray-400">External ID</dt>
                  <dd className="text-gray-700 dark:text-gray-400 break-all">{selectedDocument.externalId}</dd>
                </dl>

                {selectedDocument.sourceUrl && (
                  <a
                    href={selectedDocument.sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
                  >
                    Open original source
                  </a>
                )}

                {(componentRefsQuery.data?.length > 0 || reviewRefsQuery.data?.length > 0) && (
                  <div className="grid gap-4 xl:grid-cols-2">
                    <div className="rounded-xl border border-gray-100 dark:border-gray-800/30 bg-gray-50 dark:bg-gray-900/30 p-4">
                      <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">Used in components</p>
                      {componentRefsQuery.data?.length ? (
                        <div className="space-y-2">
                          {componentRefsQuery.data.map((component) => (
                            <Link
                              key={`${component.modelId ?? "model"}:${component.id}`}
                              to={component.modelId ? `/app/model/${component.modelId}` : "/app/models"}
                              className="block rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 hover:border-brand-200 dark:border-brand-800/50 hover:bg-brand-50 dark:bg-brand-900/30 transition-colors"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="text-sm font-medium text-gray-800 dark:text-gray-300 truncate">{component.name}</p>
                                  <p className="mt-1 text-xs text-gray-500 truncate">
                                    {component.modelName} · {component.value || "No extracted value"}
                                  </p>
                                  {(component.temporalState || component.validFrom || component.validTo) && (
                                    <p className="mt-1 text-[11px] text-gray-400 truncate">
                                      {component.temporalState === "historical" || component.temporalState === "superseded"
                                        ? "Historical version"
                                        : "Current version"}
                                      {component.validFrom ? ` · Active from ${formatDate(component.validFrom)}` : ""}
                                      {component.validTo ? ` until ${formatDate(component.validTo)}` : ""}
                                    </p>
                                  )}
                                  {component.reviewSummary && (
                                    <p className="mt-1 text-[11px] text-gray-500 truncate">
                                      {component.reviewSummary}
                                    </p>
                                  )}
                                </div>
                                {component.reviewStatus && (
                                  <span
                                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                      component.reviewStatus === "approved"
                                        ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                                        : component.reviewStatus === "superseded"
                                          ? "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400"
                                          : component.reviewStatus === "rejected"
                                            ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400"
                                            : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
                                    }`}
                                  >
                                    {component.reviewStatus.replaceAll("_", " ")}
                                  </span>
                                )}
                              </div>
                            </Link>
                          ))}
                          {componentRefsQuery.data.map((component) => (
                            <Link
                              key={`graph:${component.id}`}
                              to={buildComponentGraphHref(component)}
                              className="inline-flex text-[11px] font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
                            >
                              Explore {component.name} in graph
                            </Link>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500">
                          No extracted components are linked to this source document yet.
                        </p>
                      )}
                    </div>

                    <div className="rounded-xl border border-gray-100 dark:border-gray-800/30 bg-gray-50 dark:bg-gray-900/30 p-4">
                      <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">Related review items</p>
                      {reviewRefsQuery.data?.length ? (
                        <div className="space-y-2">
                          {reviewRefsQuery.data.map((item) => (
                            <div
                              key={item.id}
                              className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-3"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <Link
                                    to={`/app/review/${item.id}`}
                                    className="text-sm font-medium text-gray-800 dark:text-gray-300 hover:text-brand-700 dark:text-brand-400"
                                  >
                                    {item.title}
                                  </Link>
                                  <p className="mt-1 text-xs text-gray-500 truncate">
                                    {item.kind.replaceAll("_", " ")} · {item.model || "Unscoped"}
                                  </p>
                                </div>
                                <span
                                  className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                    item.status === "approved"
                                      ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                                      : item.status === "superseded"
                                        ? "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400"
                                        : item.status === "rejected"
                                          ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400"
                                          : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
                                  }`}
                                >
                                  {item.status.replaceAll("_", " ")}
                                </span>
                              </div>
                              {item.decisionHistory?.length > 0 && (
                                <div className="mt-3 rounded-lg border border-gray-100 dark:border-gray-800/30 bg-gray-50 dark:bg-gray-900/30 px-3 py-3">
                                  <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">
                                    Decision history
                                  </p>
                                  <div className="mt-2 space-y-2">
                                    {item.decisionHistory.map((decision) => (
                                      <div key={decision.id ?? `${decision.createdAt}-${decision.newStatus}`} className="text-xs text-gray-600 dark:text-gray-400">
                                        <p className="font-medium text-gray-700 dark:text-gray-400">
                                          {formatReviewDecisionTransition(decision)}
                                        </p>
                                        <p className="mt-0.5 text-[11px] text-gray-500">
                                          {formatDecisionActor(decision.actorType)}
                                          {decision.createdAt ? ` · ${formatDate(decision.createdAt)}` : ""}
                                        </p>
                                        {decision.note && (
                                          <p className="mt-1 text-[11px] text-gray-500">{decision.note}</p>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500">
                          No review queue items reference this source document right now.
                        </p>
                      )}
                    </div>
                  </div>
                )}

                <div>
                  <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">Raw content</p>
                  <pre className="rounded-xl bg-gray-50 dark:bg-gray-900/30 border border-gray-100 dark:border-gray-800/30 p-4 text-xs text-gray-700 dark:text-gray-400 whitespace-pre-wrap break-words font-sans max-h-[420px] overflow-y-auto">
                    {selectedDocument.content}
                  </pre>
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                <p className="text-sm">Select a document to inspect it.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function SourceEmptyState({ filtersActive }) {
  return (
    <div className="rounded-[32px] border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-12 text-center shadow-sm">
      <div className="mx-auto w-16 h-16 bg-brand-50 dark:bg-brand-900/30 text-brand-600 dark:text-brand-400 rounded-full flex items-center justify-center mb-6">
        <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      </div>
      <h2 className="text-xl font-bold text-gray-900 dark:text-gray-200">
        {filtersActive ? "No source documents match the current filters." : "No source documents yet."}
      </h2>
      <p className="mt-3 text-sm text-gray-500 max-w-lg mx-auto leading-relaxed">
        {filtersActive
          ? "Widen the current filters or sync another source to bring more raw context into the workspace."
          : "Connect Slack, Notion, or Zoom first, run the first sync, then come back here to inspect the raw documents before extraction."}
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
        <Link to="/app" className="px-6 py-2.5 bg-brand-600 text-white text-sm font-bold rounded-xl hover:bg-brand-500 transition-colors shadow-lg shadow-brand-500/20">
          Add context
        </Link>
        <Link to="/app/review" className="px-6 py-2.5 bg-gray-100 dark:bg-gray-900/40 text-gray-700 dark:text-gray-400 text-sm font-bold rounded-xl hover:bg-gray-200 transition-colors">
          Open review queue
        </Link>
      </div>
    </div>
  );
}

function buildSourceGraphHref(document, primaryComponent = null) {
  const focus =
    primaryComponent?.name ||
    primaryComponent?.modelName ||
    document.location ||
    document.meetingTopic ||
    document.documentTitle ||
    document.repository ||
    document.author ||
    document.externalId;
  const params = new URLSearchParams();
  params.set("view", "local");
  params.set("focus", focus);
  params.set("q", focus);
  return `/app/graph?${params.toString()}`;
}

function buildComponentGraphHref(component) {
  const focus = component.name || component.modelName || "graph";
  const params = new URLSearchParams();
  params.set("view", "local");
  params.set("focus", focus);
  params.set("q", focus);
  return `/app/graph?${params.toString()}`;
}

function formatDate(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatDocumentListTitle(doc) {
  if (doc.connectorType === "github") {
    return doc.documentTitle || doc.location || doc.author || "GitHub item";
  }
  return doc.author || "Unknown author";
}

function formatDocumentListSubtitle(doc) {
  if (doc.connectorType === "github") {
    const parts = [
      doc.repository,
      doc.githubItemType ? doc.githubItemType.replaceAll("_", " ") : null,
      doc.author,
    ].filter(Boolean);
    const prefix = parts.join(" · ");
    return prefix ? `${prefix} · ${doc.preview}` : doc.preview;
  }
  return doc.preview;
}

function formatReviewDecisionTransition(decision) {
  const previous = decision?.previousStatus;
  const next = decision?.newStatus;
  if (previous && next) {
    return `${previous.replaceAll("_", " ")} -> ${next.replaceAll("_", " ")}`;
  }
  if (next) {
    return `Marked ${next.replaceAll("_", " ")}`;
  }
  return "State updated";
}

function formatDecisionActor(actorType) {
  if (!actorType) return "Unknown actor";
  if (actorType === "system") return "System";
  if (actorType === "human") return "Human reviewer";
  return actorType.replaceAll("_", " ");
}
