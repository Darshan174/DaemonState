import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Upload, FileText, FileCode, FileJson, X, ChevronRight, ChevronDown, CheckCircle, Clock, Layers, MessageSquare, HardDrive, Bot, Video, FolderOpen, Clipboard, AlertTriangle, Search } from "lucide-react";
import { api } from "../api/client";

function GitHubIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
}

function GmailIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#EA4335" d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z" />
    </svg>
  );
}

function SlackIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 122.8 122.8" aria-hidden="true">
      <path fill="#E01E5A" d="M25.8 77.6c0 7.1-5.8 12.9-12.9 12.9S0 84.7 0 77.6s5.8-12.9 12.9-12.9h12.9v12.9zm6.5 0c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9v32.3c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V77.6z" />
      <path fill="#36C5F0" d="M45.2 25.8c-7.1 0-12.9-5.8-12.9-12.9S38.1 0 45.2 0s12.9 5.8 12.9 12.9v12.9H45.2zm0 6.5c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H12.9C5.8 58.1 0 52.3 0 45.2s5.8-12.9 12.9-12.9h32.3z" />
      <path fill="#2EB67D" d="M97 45.2c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9-5.8 12.9-12.9 12.9H97V45.2zm-6.5 0c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V12.9C64.7 5.8 70.5 0 77.6 0s12.9 5.8 12.9 12.9v32.3z" />
      <path fill="#ECB22E" d="M77.6 97c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9-12.9-5.8-12.9-12.9V97h12.9zm0-6.5c-7.1 0-12.9-5.8-12.9-12.9s5.8-12.9 12.9-12.9h32.3c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H77.6z" />
    </svg>
  );
}

const TYPE_META = {
  markdown: { label: "Markdown", color: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400", icon: FileText },
  md:       { label: "Markdown", color: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400", icon: FileText },
  text:     { label: "Text", color: "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-300", icon: FileText },
  txt:      { label: "Text", color: "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-300", icon: FileText },
  json:     { label: "JSON", color: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400", icon: FileJson },
  csv:      { label: "CSV", color: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400", icon: FileCode },
  html:     { label: "HTML", color: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-400", icon: FileCode },
  pdf:      { label: "PDF", color: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400", icon: FileText },
  local:    { label: "Local File", color: "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-300", icon: FolderOpen },
  local_folder: { label: "Local Folder", color: "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-300", icon: FolderOpen },
  browser_upload: { label: "Browser Upload", color: "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-300", icon: Upload },
  paste:    { label: "Pasted Text", color: "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-300", icon: Clipboard },
  slack:    { label: "Slack", color: "bg-violet-50 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300", icon: SlackIcon },
  github:   { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  github_issue: { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  github_pr: { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  github_pull_request: { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  github_pull_request_review_comment: { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  gmail:    { label: "Gmail", color: "bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400", icon: GmailIcon },
  gdrive:   { label: "Google Drive", color: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300", icon: HardDrive },
  google_drive: { label: "Google Drive", color: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300", icon: HardDrive },
  zoom:     { label: "Zoom", color: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300", icon: Video },
  zoom_transcript: { label: "Zoom", color: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300", icon: Video },
  notion:   { label: "Notion", color: "bg-stone-100 dark:bg-stone-700 text-stone-700 dark:text-stone-200", icon: FileText },
  discord:  { label: "Discord", color: "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300", icon: MessageSquare },
  ai_context: { label: "AI Context", color: "bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300", icon: Bot },
  agent_session: { label: "AI Context", color: "bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300", icon: Bot },
  ai_context_codex: { label: "Codex", color: "bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300", icon: Bot },
  ai_context_claude_code: { label: "Claude", color: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300", icon: Bot },
  ai_context_opencode: { label: "OpenCode", color: "bg-slate-100 dark:bg-black text-slate-700 dark:text-neutral-200", icon: Bot },
  codex:    { label: "Codex", color: "bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300", icon: Bot },
  claude:   { label: "Claude", color: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300", icon: Bot },
  opencode: { label: "OpenCode", color: "bg-slate-100 dark:bg-black text-slate-700 dark:text-neutral-200", icon: Bot },
};

const GITHUB_TYPES = ["github", "github_issue", "github_pr", "github_pull_request", "github_pull_request_review_comment"];
const DOCUMENT_TYPES = [
  "markdown", "md", "text", "txt", "json", "csv", "html", "pdf",
  "local", "local_folder", "browser_upload", "paste",
  "gdrive", "google_drive", "document",
];
const UNSUPPORTED_PROVIDER_TYPES = ["notion", "zoom", "zoom_transcript"];

const SOURCE_GROUPS = [
  { id: "gmail", label: "Gmail", icon: GmailIcon, chip: "bg-red-50 dark:bg-red-900/30", types: ["gmail"] },
  { id: "slack", label: "Slack", icon: SlackIcon, chip: "bg-violet-50 dark:bg-violet-900/30", types: ["slack"] },
  { id: "documents", label: "Documents", icon: FileText, chip: "bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-300", types: DOCUMENT_TYPES },
  { id: "github", label: "GitHub", icon: GitHubIcon, chip: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", types: GITHUB_TYPES },
  { id: "unsupported", label: "Unsupported", icon: AlertTriangle, chip: "bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300", types: UNSUPPORTED_PROVIDER_TYPES },
  { id: "others", label: "Others", icon: Layers, chip: "bg-slate-100 dark:bg-black text-slate-500 dark:text-neutral-300", types: null },
];

function sourceTypeKey(source) {
  const rawType = typeof source === "string"
    ? source
    : source?.connector_type ?? source?.connectorType ?? source?.source_type ?? source?.sourceType;
  return String(rawType || "").trim().toLowerCase();
}

function humanizeSourceType(value) {
  const normalized = String(value || "unknown").trim().replace(/[-_]+/g, " ");
  if (!normalized) return "Unknown";
  return normalized
    .split(/\s+/)
    .map((word) => {
      const lower = word.toLowerCase();
      if (lower === "api") return "API";
      if (lower === "ai") return "AI";
      if (lower === "pr") return "PR";
      if (lower === "url") return "URL";
      if (lower === "id") return "ID";
      if (lower === "github") return "GitHub";
      if (lower === "gmail") return "Gmail";
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

function typeMeta(source) {
  const key = sourceTypeKey(source);
  const metadata = typeof source === "object" && source ? source.metadata ?? source.metadata_json ?? {} : {};
  const providedLabel =
    source?.connector_label ??
    source?.connectorLabel ??
    source?.provider_label ??
    source?.providerLabel ??
    metadata?.connector_label ??
    metadata?.connectorLabel ??
    metadata?.provider_label ??
    metadata?.providerLabel;
  const known = TYPE_META[key];

  return {
    label: providedLabel || known?.label || humanizeSourceType(key),
    color: known?.color || "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-300",
    icon: known?.icon || FileText,
  };
}

function groupIdForSource(source) {
  const key = sourceTypeKey(source);
  for (const group of SOURCE_GROUPS) {
    if (group.types && group.types.includes(key)) return group.id;
  }
  return "others";
}

export default function SourceManager() {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [selectedSource, setSelectedSource] = useState(null);
  const [selectedComponents, setSelectedComponents] = useState(null);
  const [loadingComponents, setLoadingComponents] = useState(false);
  const [expandedGroupId, setExpandedGroupId] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const fileInputRef = useRef(null);

  const fetchSources = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      // Paginate through every source document so nothing is hidden.
      const all = [];
      let cursor = null;
      for (let page = 0; page < 40; page++) {
        const params = new URLSearchParams({ limit: "100" });
        if (cursor) params.set("cursor", cursor);
        const data = await api.get(`/source-documents?${params}`);
        all.push(...(data.items || []));
        if (!data.has_more || !data.next_cursor) break;
        cursor = data.next_cursor;
      }
      setSources(all);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchSources(); }, [fetchSources]);

  const groupedSources = useMemo(() => {
    const buckets = Object.fromEntries(SOURCE_GROUPS.map((g) => [g.id, []]));
    for (const source of sources) buckets[groupIdForSource(source)].push(source);
    return SOURCE_GROUPS
      .map((group) => ({ ...group, items: buckets[group.id] }))
      .filter((group) => group.items.length > 0);
  }, [sources]);

  const visibleGroups = useMemo(() => {
    const needle = sourceQuery.trim().toLowerCase();
    if (!needle) return groupedSources;
    return groupedSources
      .map((group) => ({
        ...group,
        items: group.items.filter((source) => {
          const haystack = [
            source.external_id,
            source.author,
            source.content_preview,
            typeMeta(source).label,
          ].filter(Boolean).join(" ").toLowerCase();
          return haystack.includes(needle);
        }),
      }))
      .filter((group) => group.items.length > 0);
  }, [groupedSources, sourceQuery]);

  const pendingCount = useMemo(
    () => sources.filter((source) => !source.processed_at).length,
    [sources],
  );

  function toggleGroup(groupId) {
    setExpandedGroupId((current) => (current === groupId ? null : groupId));
  }

  async function handleFiles(files) {
    if (!files?.length) return;
    setUploading(true);
    setUploadError(null);
    try {
      for (const file of files) {
        const content = await file.text();
        const ext = file.name.split(".").pop()?.toLowerCase() || "";
        const sourceType = { md: "markdown", markdown: "markdown", txt: "text", text: "text", json: "json", csv: "csv", html: "html", htm: "html", pdf: "pdf" }[ext] || "text";
        await api.post("/sources", {
          source_type: sourceType,
          external_id: file.name,
          content,
          metadata: { file_name: file.name, file_size: file.size },
        });
      }
      await fetchSources();
    } catch (err) { setUploadError(err.message); }
    finally { setUploading(false); }
  }

  async function handleSourceClick(source) {
    setSelectedSource(source);
    setSelectedComponents(null);
    setLoadingComponents(true);
    try {
      const detail = await api.get(`/sources/${source.id}`);
      setSelectedSource({ ...source, ...detail });
      setSelectedComponents(detail.components || []);
    } catch { setSelectedComponents([]); }
    finally { setLoadingComponents(false); }
  }

  function renderSourceRow(source) {
    const meta = typeMeta(source);
    const Icon = meta.icon;
    const isSelected = selectedSource?.id === source.id;
    return (
      <button
        key={source.id}
        onClick={() => handleSourceClick(source)}
        className={`group w-full rounded-lg border px-3 py-2.5 text-left transition-all ${
          isSelected
            ? "border-brand-400/60 bg-brand-500/10 shadow-sm dark:border-brand-500/60"
            : "border-slate-200/80 bg-white/[0.84] hover:border-slate-300 hover:bg-white hover:shadow-sm dark:border-white/[0.08] dark:bg-white/[0.035] dark:hover:border-white/[0.16] dark:hover:bg-white/[0.055]"
        }`}
      >
        <div className="flex items-center gap-2.5">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${meta.color}`}>
            <Icon className="w-3.5 h-3.5" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold text-slate-800 dark:text-neutral-200 truncate">
                {source.external_id || source.id}
              </span>
              <ChevronRight className={`w-3.5 h-3.5 shrink-0 transition-transform ${isSelected ? "text-brand-500 rotate-90" : "text-slate-300 dark:text-slate-600 group-hover:text-slate-400"}`} />
            </div>
            {source.content_preview && (
              <p className="text-[11px] text-slate-400 dark:text-slate-500 truncate mt-0.5">{source.content_preview}</p>
            )}
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 mt-0.5">
              {source.author && (
                <span className="text-[11px] text-slate-400 truncate max-w-[10rem]">{source.author}</span>
              )}
              {source.ingested_at && (
                <span className="text-[11px] text-slate-400">{new Date(source.ingested_at).toLocaleDateString()}</span>
              )}
              {source.processed_at ? (
                <span className="flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400">
                  <CheckCircle className="w-3 h-3" /> processed
                </span>
              ) : (
                <span className="flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                  <Clock className="w-3 h-3" /> pending
                </span>
              )}
            </div>
          </div>
          <span className={`hidden shrink-0 items-center justify-center whitespace-nowrap rounded-md px-2 py-0.5 text-[10px] font-bold sm:inline-flex ${meta.color}`}>{meta.label}</span>
        </div>
      </button>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600 mx-auto mb-3" />
          <p className="text-sm font-medium text-slate-500">Loading sources…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative z-10 mx-auto flex min-h-full max-w-6xl flex-col gap-5 xl:flex-row">
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <p className="eyebrow">Ingestion</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight text-slate-950 dark:text-white">Sources</h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-500 dark:text-neutral-400">Inspect the raw evidence behind graph claims and context packs.</p>
          </div>
          <button
            onClick={() => setUploadOpen((current) => !current)}
            aria-expanded={uploadOpen}
            className="btn-primary"
          >
            <Upload className="w-4 h-4" />
            {uploadOpen ? "Close import" : "Import files"}
          </button>
          <input ref={fileInputRef} type="file" multiple accept=".md,.txt,.json,.csv,.html,.htm,.pdf" className="hidden" onChange={(e) => handleFiles(e.target.files)} />
        </div>

        <div className="grid grid-cols-3 overflow-hidden rounded-md border border-[#d9d9d0] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]">
          <SourceStat label="Evidence items" value={`${sources.length} total`} />
          <SourceStat label="Source types" value={`${groupedSources.length} types`} bordered />
          <SourceStat label="Processing" value={`${pendingCount} pending`} bordered />
        </div>

        {/* Errors */}
        {(uploadError || error) && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3.5 dark:border-red-800/40 dark:bg-red-900/20">
            <p className="text-sm text-red-700 dark:text-red-300">{uploadError || error}</p>
          </div>
        )}

        {/* File import is progressive disclosure, not permanent page chrome. */}
        {uploadOpen && <div
          onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onClick={() => fileInputRef.current?.click()}
          className={`cursor-pointer rounded-md border border-dashed p-7 text-center transition-all ${
            dragOver
              ? "scale-[1.01] border-brand-500 bg-brand-500/10"
              : "border-slate-200/90 bg-white/55 hover:border-brand-400/60 hover:bg-white/80 dark:border-white/[0.08] dark:bg-white/[0.025] dark:hover:border-brand-500/60 dark:hover:bg-white/[0.045]"
          }`}
        >
          {uploading ? (
            <div className="flex items-center justify-center gap-3">
              <div className="w-5 h-5 border-2 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
              <span className="text-sm font-medium text-slate-600 dark:text-neutral-400">Uploading…</span>
            </div>
          ) : (
            <>
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200/80 bg-white dark:border-white/[0.08] dark:bg-white/[0.045]">
                <Upload className="w-5 h-5 text-slate-400" />
              </div>
              <p className="text-sm font-medium text-slate-600 dark:text-neutral-400">
                Drop files here or <span className="font-semibold text-brand-600 dark:text-brand-400">browse</span>
              </p>
              <p className="text-xs text-slate-400 mt-1">MD · TXT · JSON · CSV · HTML · PDF</p>
            </>
          )}
        </div>}

        {/* Grouped source list */}
        <div className="panel overflow-hidden">
          <div className="flex flex-col gap-3 border-b border-[#e1e1d8] p-4 dark:border-[#292925] sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-[#171713] dark:text-[#f4f4ec]">Evidence library</h2>
              <p className="mt-0.5 text-xs text-[#77776e] dark:text-[#929289]">Open a source type, then select a document to inspect its extracted components.</p>
            </div>
            <label className="relative block sm:w-64">
              <span className="sr-only">Search sources</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8a80]" />
              <input
                value={sourceQuery}
                onChange={(event) => setSourceQuery(event.target.value)}
                placeholder="Search sources"
                className="input h-9 py-2 pl-9"
              />
            </label>
          </div>
          <div className="divide-y divide-[#e1e1d8] dark:divide-[#292925]">
          {sources.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-14 h-14 rounded-2xl bg-slate-100 dark:bg-black flex items-center justify-center mb-4">
                <Layers className="w-7 h-7 text-slate-300 dark:text-slate-600" />
              </div>
              <p className="text-sm font-semibold text-slate-500 dark:text-neutral-400">No sources yet</p>
              <p className="text-xs text-slate-400 mt-1">Upload files or sync a connector to populate your knowledge graph</p>
            </div>
          ) : visibleGroups.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <p className="text-sm font-semibold text-[#4f4f48] dark:text-[#d0d0c7]">No sources match “{sourceQuery}”</p>
              <button type="button" onClick={() => setSourceQuery("")} className="mt-2 text-xs font-semibold text-brand-700 dark:text-brand-400">Clear search</button>
            </div>
          ) : (
            visibleGroups.map((group) => {
              const GroupIcon = group.icon;
              const isExpanded = expandedGroupId === group.id;
              return (
                <div key={group.id} className={isExpanded ? "bg-[#f7f7f2] dark:bg-[#10100e]" : ""}>
                  <button
                    onClick={() => toggleGroup(group.id)}
                    aria-expanded={isExpanded}
                    className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-[#f2f2eb] dark:hover:bg-[#1b1b18]"
                  >
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${group.chip}`}>
                      <GroupIcon className="w-4 h-4" />
                    </div>
                    <span className="text-sm font-bold text-slate-800 dark:text-neutral-100">{group.label}</span>
                    <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-black text-slate-500 dark:text-neutral-300">
                      {group.items.length}
                    </span>
                    <span className="ml-auto text-xs font-medium text-[#8a8a80]">{isExpanded ? "Hide" : "Browse"}</span>
                    <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${isExpanded ? "rotate-0" : "-rotate-90"}`} />
                  </button>
                  {isExpanded && (
                    <div className="space-y-1.5 border-t border-[#e1e1d8] px-3 py-3 dark:border-[#292925]">
                      {group.items.map((source) => renderSourceRow(source))}
                    </div>
                  )}
                </div>
              );
            })
          )}
          </div>
        </div>
      </div>

      {/* Right panel — detail */}
      {selectedSource && (
        <div className="panel flex w-full shrink-0 self-start flex-col overflow-hidden xl:sticky xl:top-0 xl:w-80">
          <div className="flex items-center justify-between border-b border-slate-200/80 px-5 py-4 dark:border-white/[0.08]">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${typeMeta(selectedSource).color}`}>
                {(() => { const Icon = typeMeta(selectedSource).icon; return <Icon className="w-3.5 h-3.5" />; })()}
              </div>
              <p className="text-sm font-bold text-slate-900 dark:text-white truncate">
                {selectedSource.external_id || selectedSource.id}
              </p>
            </div>
            <button
              onClick={() => { setSelectedSource(null); setSelectedComponents(null); }}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-white/[0.055]"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-5 space-y-5">
            {/* Preview */}
            {(selectedSource.content || selectedSource.content_preview) && (
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Preview</p>
                <div className="panel-subtle max-h-36 overflow-y-auto p-3.5 font-mono text-xs leading-relaxed text-slate-600 whitespace-pre-wrap dark:text-neutral-400">
                  {(selectedSource.content || selectedSource.content_preview).slice(0, 800)}
                  {(selectedSource.content || "").length > 800 && "…"}
                </div>
              </div>
            )}

            {/* Extracted components */}
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
                Extracted Components
                {selectedComponents?.length > 0 && <span className="ml-1.5 text-brand-500">{selectedComponents.length}</span>}
              </p>
              {loadingComponents ? (
                <div className="flex items-center gap-2 py-6 justify-center">
                  <div className="w-4 h-4 border-2 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
                  <span className="text-xs text-slate-500">Extracting…</span>
                </div>
              ) : selectedComponents?.length > 0 ? (
                <div className="space-y-2">
                  {selectedComponents.map((c, i) => (
                    <div key={c.id || i} className="panel-subtle p-3">
                      <p className="text-xs font-semibold text-slate-700 dark:text-neutral-300 leading-snug">{c.value || c.name}</p>
                      {c.value && c.name && c.value !== c.name && (
                        <p className="text-[11px] text-slate-400 mt-1">{c.name}</p>
                      )}
                      {c.confidence != null && (
                        <div className="mt-1.5 flex items-center gap-1.5">
                          <div className="flex-1 h-1 rounded-full bg-slate-200 dark:bg-black overflow-hidden">
                            <div className="h-full bg-brand-400 rounded-full" style={{ width: `${Math.round(c.confidence * 100)}%` }} />
                          </div>
                          <span className="text-[10px] text-slate-400 shrink-0">{Math.round(c.confidence * 100)}%</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8">
                  <Layers className="w-8 h-8 text-slate-200 dark:text-slate-700 mx-auto mb-2" />
                  <p className="text-xs text-slate-400">No components extracted</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SourceStat({ label, value, bordered = false }) {
  return (
    <div className={`${bordered ? "border-l border-[#d9d9d0] dark:border-[#292925]" : ""} px-4 py-3.5`}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8a8a80] dark:text-[#77776e]">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-[#171713] dark:text-[#f4f4ec]">{value}</p>
    </div>
  );
}
