import { useState, useEffect, useRef, useCallback } from "react";
import { Upload, FileText, FileCode, FileJson, X, ChevronRight, CheckCircle, Clock, Layers, MessageSquare, Mail, HardDrive, Bot, Video, FolderOpen, Clipboard } from "lucide-react";

const TYPE_META = {
  markdown: { label: "Markdown", color: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400", icon: FileText },
  md:       { label: "Markdown", color: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400", icon: FileText },
  text:     { label: "Text", color: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300", icon: FileText },
  txt:      { label: "Text", color: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300", icon: FileText },
  json:     { label: "JSON", color: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400", icon: FileJson },
  csv:      { label: "CSV", color: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400", icon: FileCode },
  html:     { label: "HTML", color: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-400", icon: FileCode },
  pdf:      { label: "PDF", color: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400", icon: FileText },
  local:    { label: "Local File", color: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300", icon: FolderOpen },
  local_folder: { label: "Local Folder", color: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300", icon: FolderOpen },
  browser_upload: { label: "Browser Upload", color: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300", icon: Upload },
  paste:    { label: "Pasted Text", color: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300", icon: Clipboard },
  slack:    { label: "Slack", color: "bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300", icon: MessageSquare },
  github:   { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  github_issue: { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  github_pr: { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  github_pull_request: { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  github_pull_request_review_comment: { label: "GitHub", color: "bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900", icon: GitHubIcon },
  gmail:    { label: "Gmail", color: "bg-sky-100 dark:bg-sky-900/40 text-sky-700 dark:text-sky-400", icon: Mail },
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
  ai_context_opencode: { label: "OpenCode", color: "bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200", icon: Bot },
  codex:    { label: "Codex", color: "bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300", icon: Bot },
  claude:   { label: "Claude", color: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300", icon: Bot },
  opencode: { label: "OpenCode", color: "bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200", icon: Bot },
};

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
    color: known?.color || "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300",
    icon: known?.icon || FileText,
  };
}

function GitHubIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
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
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const fetchSources = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/sources");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSources(Array.isArray(data) ? data : data.items || data.sources || []);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchSources(); }, [fetchSources]);

  async function handleFiles(files) {
    if (!files?.length) return;
    setUploading(true);
    setUploadError(null);
    try {
      for (const file of files) {
        const content = await file.text();
        const ext = file.name.split(".").pop()?.toLowerCase() || "";
        const sourceType = { md: "markdown", markdown: "markdown", txt: "text", text: "text", json: "json", csv: "csv", html: "html", htm: "html", pdf: "pdf" }[ext] || "text";
        const res = await fetch("/api/sources", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_type: sourceType, external_id: file.name, content, metadata: { file_name: file.name, file_size: file.size } }),
        });
        if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(body.detail || `HTTP ${res.status}: ${file.name}`); }
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
      const res = await fetch(`/api/sources/${source.id}`);
      setSelectedComponents(res.ok ? (await res.json()).components || [] : []);
    } catch { setSelectedComponents([]); }
    finally { setLoadingComponents(false); }
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
    <div className="flex h-full gap-5 max-w-5xl mx-auto">
      {/* Left panel */}
      <div className="flex-1 flex flex-col min-w-0 gap-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">Source Manager</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
              {sources.length > 0 ? `${sources.length} document${sources.length !== 1 ? "s" : ""} ingested` : "Upload source documents to get started"}
            </p>
          </div>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-bold rounded-xl transition-colors shadow-sm shadow-brand-600/20"
          >
            <Upload className="w-4 h-4" />
            Upload
          </button>
          <input ref={fileInputRef} type="file" multiple accept=".md,.txt,.json,.csv,.html,.htm,.pdf" className="hidden" onChange={(e) => handleFiles(e.target.files)} />
        </div>

        {/* Errors */}
        {(uploadError || error) && (
          <div className="p-3.5 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40">
            <p className="text-sm text-red-700 dark:text-red-300">{uploadError || error}</p>
          </div>
        )}

        {/* Drop zone */}
        <div
          onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onClick={() => fileInputRef.current?.click()}
          className={`cursor-pointer p-8 border-2 border-dashed rounded-2xl text-center transition-all ${
            dragOver
              ? "border-brand-500 bg-brand-50 dark:bg-brand-900/20 scale-[1.01]"
              : "border-slate-200 dark:border-slate-700 hover:border-brand-300 dark:hover:border-brand-600 hover:bg-slate-50 dark:hover:bg-slate-800/50"
          }`}
        >
          {uploading ? (
            <div className="flex items-center justify-center gap-3">
              <div className="w-5 h-5 border-2 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
              <span className="text-sm font-medium text-slate-600 dark:text-slate-400">Uploading…</span>
            </div>
          ) : (
            <>
              <div className="w-10 h-10 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto mb-3">
                <Upload className="w-5 h-5 text-slate-400" />
              </div>
              <p className="text-sm font-medium text-slate-600 dark:text-slate-400">
                Drop files here or <span className="text-brand-600 dark:text-brand-400 font-semibold">browse</span>
              </p>
              <p className="text-xs text-slate-400 mt-1">MD · TXT · JSON · CSV · HTML · PDF</p>
            </>
          )}
        </div>

        {/* Source list */}
        <div className="flex-1 space-y-2 overflow-y-auto">
          {sources.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-14 h-14 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
                <Layers className="w-7 h-7 text-slate-300 dark:text-slate-600" />
              </div>
              <p className="text-sm font-semibold text-slate-500 dark:text-slate-400">No sources yet</p>
              <p className="text-xs text-slate-400 mt-1">Upload files to populate your knowledge graph</p>
            </div>
          ) : (
            sources.map((source) => {
              const meta = typeMeta(source);
              const Icon = meta.icon;
              const isSelected = selectedSource?.id === source.id;
              return (
                <button
                  key={source.id}
                  onClick={() => handleSourceClick(source)}
                  className={`w-full text-left p-4 rounded-xl border transition-all group ${
                    isSelected
                      ? "border-brand-300 dark:border-brand-700 bg-brand-50 dark:bg-brand-900/20 shadow-sm"
                      : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600 hover:shadow-sm"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${meta.color}`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate">
                          {source.external_id || source.id}
                        </span>
                        <ChevronRight className={`w-3.5 h-3.5 shrink-0 transition-transform ${isSelected ? "text-brand-500 rotate-90" : "text-slate-300 dark:text-slate-600 group-hover:text-slate-400"}`} />
                      </div>
                      <div className="flex items-center gap-3 mt-0.5">
                        {source.ingested_at && (
                          <span className="text-xs text-slate-400">{new Date(source.ingested_at).toLocaleDateString()}</span>
                        )}
                        {source.processed_at ? (
                          <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                            <CheckCircle className="w-3 h-3" /> processed
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                            <Clock className="w-3 h-3" /> pending
                          </span>
                        )}
                      </div>
                    </div>
                    <span className={`inline-flex items-center justify-center whitespace-nowrap text-[10px] font-bold px-2.5 py-0.5 rounded-lg shrink-0 ${meta.color}`}>{meta.label}</span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* Right panel — detail */}
      {selectedSource && (
        <div className="w-80 shrink-0 flex flex-col bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
          {/* Panel header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 dark:border-slate-700">
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
              className="w-7 h-7 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-5 space-y-5">
            {/* Preview */}
            {selectedSource.content && (
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Preview</p>
                <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-900/60 text-xs text-slate-600 dark:text-slate-400 max-h-36 overflow-y-auto leading-relaxed whitespace-pre-wrap font-mono border border-slate-100 dark:border-slate-700/50">
                  {selectedSource.content.slice(0, 800)}{selectedSource.content.length > 800 && "…"}
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
                    <div key={c.id || i} className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50">
                      <p className="text-xs font-semibold text-slate-700 dark:text-slate-300 leading-snug">{c.value || c.name}</p>
                      {c.value && c.name && c.value !== c.name && (
                        <p className="text-[11px] text-slate-400 mt-1">{c.name}</p>
                      )}
                      {c.confidence != null && (
                        <div className="mt-1.5 flex items-center gap-1.5">
                          <div className="flex-1 h-1 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
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
