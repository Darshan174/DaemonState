import { Link } from "react-router-dom";

const CONNECTOR_STYLE = {
  slack: "bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-400",
  notion: "bg-gray-100 dark:bg-gray-900/40 text-gray-700 dark:text-gray-400",
  zoom: "bg-sky-100 dark:bg-sky-900/40 text-sky-700 dark:text-sky-400",
  gdrive: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400",
  gong: "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-400",
  unknown: "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400",
};

export default function SourceDocumentLinks({
  items,
  label = "Supporting documents",
  compact = false,
  showMeta = false,
}) {
  const documents = normalizeSourceDocumentRefs(items);

  if (documents.length === 0) {
    return null;
  }

  if (showMeta) {
    return (
      <div className={compact ? "space-y-2" : "space-y-3"}>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{label}</p>
        <div className="space-y-2">
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-3 py-3"
            >
              <div className="flex items-center gap-2">
                {doc.connectorType && (
                  <span
                    className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                      CONNECTOR_STYLE[doc.connectorType] ?? CONNECTOR_STYLE.unknown
                    }`}
                  >
                    {doc.connectorType}
                  </span>
                )}
                <Link
                  to={`/app/sources/${doc.id}`}
                  className="text-xs font-medium text-gray-700 dark:text-gray-400 hover:text-brand-700 dark:text-brand-400"
                >
                  {doc.label}
                </Link>
              </div>
              {(doc.author ||
                doc.extractionContext ||
                doc.createdAtSource ||
                doc.ingestedAt ||
                doc.extractorName ||
                doc.extractorKind ||
                doc.extractorSchemaVersion) && (
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500">
                  {doc.author && <span>Author: {doc.author}</span>}
                  {doc.extractionContext && <span>{doc.extractionContext}</span>}
                  {(doc.extractorName || doc.extractorKind || doc.extractorSchemaVersion) && (
                    <span>{formatExtractorMeta(doc)}</span>
                  )}
                  {doc.createdAtSource && <span>Created {formatDate(doc.createdAtSource)}</span>}
                  {doc.ingestedAt && <span>Ingested {formatDate(doc.ingestedAt)}</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">{label}</p>
      <div className="flex flex-wrap gap-2">
        {documents.map((doc) => (
          <Link
            key={doc.id}
            to={`/app/sources/${doc.id}`}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-2.5 py-1.5 text-xs text-gray-700 dark:text-gray-400 hover:border-brand-200 dark:border-brand-800/50 hover:bg-brand-50 dark:bg-brand-900/30 hover:text-brand-700 dark:text-brand-400 transition-colors"
          >
            {doc.connectorType && (
              <span
                className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                  CONNECTOR_STYLE[doc.connectorType] ?? CONNECTOR_STYLE.unknown
                }`}
              >
                {doc.connectorType}
              </span>
            )}
            <span>{doc.label}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function normalizeSourceDocumentRefs(items) {
  if (!Array.isArray(items)) return [];

  return items
    .map((item, index) => {
      if (!item) return null;
      if (typeof item === "string") {
        return {
          id: item,
          label: `Source ${index + 1}`,
          connectorType: null,
        };
      }

      const id = item.id ?? item.documentId ?? item.sourceDocumentId;
      if (!id) return null;

      return {
        id,
        label:
          item.label ??
          item.title ??
          item.location ??
          item.author ??
          item.externalId ??
          `Source ${index + 1}`,
        connectorType: item.connectorType ?? item.connector_type ?? null,
        author: item.author ?? null,
        extractionContext: item.extractionContext ?? item.extraction_context ?? null,
        createdAtSource: item.createdAtSource ?? item.created_at_source ?? null,
        ingestedAt: item.ingestedAt ?? item.ingested_at ?? null,
        extractorName: item.extractorName ?? item.extractor_name ?? null,
        extractorKind: item.extractorKind ?? item.extractor_kind ?? null,
        extractorSchemaVersion:
          item.extractorSchemaVersion ?? item.extractor_schema_version ?? null,
      };
    })
    .filter(Boolean);
}

function formatExtractorMeta(doc) {
  const extractor = doc.extractorName || doc.extractorKind;
  const schemaVersion = doc.extractorSchemaVersion;
  if (!extractor && !schemaVersion) return null;
  if (!schemaVersion) return `Extracted by ${extractor}`;
  if (!extractor) return `Schema v${schemaVersion}`;
  return `Extracted by ${extractor} · schema v${schemaVersion}`;
}

function formatDate(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString();
  } catch {
    return value;
  }
}
