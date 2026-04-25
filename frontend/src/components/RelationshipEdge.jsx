export default function RelationshipEdge({ sourceLabel, targetLabel, label }) {
  return (
    <div className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-gray-50 dark:bg-gray-900/30 transition-colors text-sm">
      <span className="font-medium text-gray-700 dark:text-gray-400 truncate max-w-[140px]">{sourceLabel}</span>
      <span className="flex items-center gap-1 text-xs text-gray-400 shrink-0">
        <span className="w-8 h-px bg-gray-300 inline-block" />
        <span className="italic">{label}</span>
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </span>
      <span className="font-medium text-gray-700 dark:text-gray-400 truncate max-w-[140px]">{targetLabel}</span>
    </div>
  );
}
