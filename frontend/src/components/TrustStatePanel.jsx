import { Link } from "react-router-dom";

const REVIEW_STYLE = {
  approved: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400",
  needs_review: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400",
  superseded: "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400",
  rejected: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400",
};

const REVIEW_LABEL = {
  approved: "Approved",
  needs_review: "Needs review",
  superseded: "Superseded",
  rejected: "Rejected",
};

export default function TrustStatePanel({
  reviewStatus,
  reviewSummary,
  temporalState,
  reviewItemId,
  compact = false,
  className = "",
}) {
  const normalizedStatus = normalizeValue(reviewStatus);
  const normalizedTemporal = normalizeValue(temporalState);
  const showHistorical =
    normalizedTemporal === "historical" ||
    normalizedTemporal === "superseded" ||
    normalizedStatus === "superseded";

  if (!normalizedStatus && !showHistorical) {
    return null;
  }

  const showReviewLink =
    normalizedStatus === "needs_review" ||
    normalizedStatus === "superseded" ||
    normalizedStatus === "rejected";

  return (
    <div className={`${compact ? "space-y-2" : "space-y-2.5"} ${className}`.trim()}>
      <div className="flex flex-wrap items-center gap-2">
        {normalizedStatus && (
          <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
              REVIEW_STYLE[normalizedStatus] ?? "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400"
            }`}
          >
            {REVIEW_LABEL[normalizedStatus] ?? normalizedStatus.replaceAll("_", " ")}
          </span>
        )}
        {showHistorical && (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400">
            Historical context
          </span>
        )}
        {showReviewLink && (
          <Link
            to={reviewItemId ? `/app/review/${reviewItemId}` : "/app/review"}
            className="text-[11px] font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
          >
            {reviewItemId ? "Open review item" : "Open review queue"}
          </Link>
        )}
      </div>
      {reviewSummary && !compact && (
        <p className="text-xs text-gray-500">{reviewSummary}</p>
      )}
    </div>
  );
}

function normalizeValue(value) {
  return typeof value === "string" && value.trim() ? value.trim().toLowerCase() : null;
}
