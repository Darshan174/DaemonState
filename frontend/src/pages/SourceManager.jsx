import { useState, useEffect, useRef, useCallback } from "react";

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
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSources();
  }, [fetchSources]);

  async function handleFiles(files) {
    if (!files?.length) return;
    setUploading(true);
    setUploadError(null);

    try {
      for (const file of files) {
        const content = await file.text();
        const ext = file.name.split(".").pop()?.toLowerCase() || "";
        const sourceType = {
          md: "markdown", markdown: "markdown",
          txt: "text", text: "text",
          json: "json", csv: "csv",
          html: "html", htm: "html",
          pdf: "pdf",
        }[ext] || "text";

        const res = await fetch("/api/sources", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_type: sourceType,
            external_id: file.name,
            content,
            metadata: { file_name: file.name, file_size: file.size },
          }),
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${res.status}: ${file.name}`);
      }
      }
      await fetchSources();
    } catch (err) {
      setUploadError(err.message);
    } finally {
      setUploading(false);
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  }

  function handleDragOver(e) {
    e.preventDefault();
    setDragOver(true);
  }

  async function handleSourceClick(source) {
    setSelectedSource(source);
    setSelectedComponents(null);
    setLoadingComponents(true);

    try {
      const res = await fetch(`/api/sources/${source.id}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedComponents(data.components || []);
      } else {
        setSelectedComponents([]);
      }
    } catch {
      setSelectedComponents([]);
    } finally {
      setLoadingComponents(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600 mx-auto mb-3" />
          <p className="text-sm font-bold text-slate-800 dark:text-slate-200">Loading sources...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full gap-4">
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">Source Manager</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Upload and manage source documents
            </p>
          </div>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-4 py-2 bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-xs font-bold rounded-xl hover:bg-slate-800 dark:hover:bg-slate-200 transition-all"
          >
            Upload Files
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".md,.txt,.json,.csv,.html,.htm,.pdf"
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />
        </div>

        {uploadError && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl">
            <p className="text-xs font-medium text-red-700 dark:text-red-300">{uploadError}</p>
          </div>
        )}

        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={() => setDragOver(false)}
          className={`mb-4 p-8 border-2 border-dashed rounded-2xl text-center transition-colors ${
            dragOver
              ? "border-brand-500 bg-brand-50 dark:bg-brand-900/20"
              : "border-slate-200 dark:border-slate-700"
          }`}
        >
          {uploading ? (
            <div className="flex items-center justify-center gap-2">
              <div className="w-4 h-4 border-2 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
              <span className="text-sm font-medium text-slate-600 dark:text-slate-400">Uploading...</span>
            </div>
          ) : (
            <>
              <svg className="w-8 h-8 text-slate-400 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              <p className="text-sm font-medium text-slate-600 dark:text-slate-400">
                Drag and drop files here, or{" "}
                <button onClick={() => fileInputRef.current?.click()} className="text-brand-600 dark:text-brand-400 underline">
                  browse
                </button>
              </p>
              <p className="text-xs text-slate-400 mt-1">MD, TXT, JSON, CSV, HTML, PDF</p>
            </>
          )}
        </div>

        {error && (
          <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl mb-4">
            <p className="text-xs font-medium text-red-700 dark:text-red-300">{error}</p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-2">
          {sources.length === 0 ? (
            <div className="text-center py-16">
              <svg className="w-10 h-10 text-slate-300 dark:text-slate-600 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400">No sources yet</p>
              <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">Upload files to get started</p>
            </div>
          ) : (
            sources.map((source) => (
              <button
                key={source.id}
                onClick={() => handleSourceClick(source)}
                className={`w-full text-left p-4 rounded-xl border transition-all ${
                  selectedSource?.id === source.id
                    ? "border-brand-300 dark:border-brand-700 bg-brand-50 dark:bg-brand-900/20"
                    : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600"
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-bold text-slate-800 dark:text-slate-200 truncate">
                    {source.external_id || source.id}
                  </span>
                  <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 ml-2 shrink-0">
                    {source.source_type}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                  {source.ingested_at && (
                    <span>{new Date(source.ingested_at).toLocaleDateString()}</span>
                  )}
                  {source.processed_at ? (
                    <span className="text-green-600 dark:text-green-400">processed</span>
                  ) : (
                    <span className="text-amber-600 dark:text-amber-400">pending</span>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {selectedSource && (
        <div className="w-80 shrink-0 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-5 overflow-y-auto">
          <button
            onClick={() => { setSelectedSource(null); setSelectedComponents(null); }}
            className="float-right text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xs font-bold"
          >
            close
          </button>
          <h3 className="text-sm font-bold text-slate-900 dark:text-white mb-1 pr-6 truncate">
            {selectedSource.external_id || selectedSource.id}
          </h3>
          <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 mb-3">
            {selectedSource.source_type}
          </span>

          {selectedSource.content && (
            <div className="mb-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Preview</p>
              <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900/50 text-xs text-slate-600 dark:text-slate-400 max-h-40 overflow-y-auto leading-relaxed whitespace-pre-wrap">
                {selectedSource.content.slice(0, 1000)}
                {selectedSource.content.length > 1000 && "..."}
              </div>
            </div>
          )}

          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
              Extracted Components
            </p>
            {loadingComponents ? (
              <div className="flex items-center gap-2 py-4 justify-center">
                <div className="w-4 h-4 border-2 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
                <span className="text-xs text-slate-500">Loading...</span>
              </div>
            ) : selectedComponents?.length > 0 ? (
              <div className="space-y-1.5">
                {selectedComponents.map((c, i) => (
                  <div
                    key={c.id || i}
                    className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900/50"
                  >
                    <p className="text-xs font-bold text-slate-700 dark:text-slate-300">{c.name}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">{c.value}</p>
                    {c.confidence != null && (
                      <span className="text-[10px] text-slate-400 mt-1 inline-block">
                        {Math.round(c.confidence * 100)}% conf
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-400 py-4 text-center">No components extracted</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
