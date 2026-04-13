import { Link } from "react-router-dom";

/**
 * Shared loading / error / empty-state overlay.
 *
 * Drop this at the top of any page that uses a React Query hook:
 *
 *   const q = useSomething();
 *   if (q.isLoading || q.isError || !q.data) return <StatusView query={q} empty="No items yet." />;
 */
export default function StatusView({ query, empty = "Nothing here yet." }) {
  if (query.isLoading) {
    return (
      <div role="status" aria-live="polite" className="flex flex-col items-center justify-center py-24 text-gray-400">
        <Spinner />
        <p className="mt-3 text-sm">Loading...</p>
      </div>
    );
  }

  if (query.isError) {
    const rawMsg =
      query.error?.message || query.error?.detail || "Something went wrong.";
    const isNetworkError = rawMsg.toLowerCase().includes("failed to fetch") || rawMsg.toLowerCase().includes("network error");
    const actionableText = isNetworkError
      ? "Check if your Context Engine backend is running. The frontend cannot reach the API."
      : rawMsg;

    return (
      <div role="alert" className="flex flex-col items-center justify-center py-24 px-6 text-center">
        <div className="w-12 h-12 rounded-full bg-red-50 text-red-500 flex items-center justify-center mb-4 border border-red-100">
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <p className="text-base font-bold text-gray-900">Failed to load data</p>
        <p className="text-sm text-gray-500 mt-2 max-w-sm">{actionableText}</p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => query.refetch?.()}
            className="px-5 py-2.5 text-sm font-bold rounded-xl bg-gray-900 text-white hover:bg-gray-800 transition-colors shadow-sm"
          >
            Try again
          </button>
          <Link
            to="/app"
            className="px-5 py-2.5 text-sm font-bold rounded-xl bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
          >
            Return to dashboard
          </Link>
        </div>
      </div>
    );
  }

  // Empty state — data loaded but nothing there
  const data = query.data;
  const isEmpty =
    data == null ||
    (Array.isArray(data) && data.length === 0) ||
    (typeof data === "object" && !Array.isArray(data) && Object.keys(data).length === 0);

  if (isEmpty) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-gray-400">
        <EmptyIcon />
        <p className="text-sm mt-3">{empty}</p>
      </div>
    );
  }

  return null; // data is ready — caller renders it
}

function Spinner() {
  return (
    <svg className="animate-spin h-6 w-6 text-brand-600" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

function EmptyIcon() {
  return (
    <svg className="w-10 h-10 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
    </svg>
  );
}
