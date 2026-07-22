import { Link } from "react-router-dom";
import ProductLoadingState from "./ProductLoadingState";

/**
 * Shared loading / error / empty-state overlay.
 *
 * Drop this at the top of any page that uses a React Query hook:
 *
 *   const q = useSomething();
 *   if (q.isLoading || q.isError || !q.data) return <StatusView query={q} empty="No items yet." />;
 */
export default function StatusView({ query, empty = "Nothing here yet.", loading = "Loading product data…", loadingStages }) {
  if (query.isLoading) {
    return (
      <ProductLoadingState compact label={loading} stages={loadingStages} />
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
      <div role="alert" className="panel flex flex-col items-center justify-center px-6 py-20 text-center">
        <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-md border border-red-200 bg-red-50 text-red-500 dark:border-red-800/30 dark:bg-red-900/30">
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <p className="text-base font-bold text-gray-900 dark:text-gray-200">Failed to load data</p>
        <p className="text-sm text-gray-500 mt-2 max-w-sm">{actionableText}</p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => query.refetch?.()}
            className="btn-primary"
          >
            Try again
          </button>
          <Link
            to="/app"
            className="pill-control px-5 py-2.5 text-sm font-bold"
          >
            Return to workspace
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
      <div className="panel flex flex-col items-center justify-center px-6 py-20 text-[#77776e] dark:text-[#929289]">
        <EmptyIcon />
        <p className="text-sm mt-3">{empty}</p>
      </div>
    );
  }

  return null; // data is ready — caller renders it
}

function EmptyIcon() {
  return (
    <svg className="w-10 h-10 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
    </svg>
  );
}
