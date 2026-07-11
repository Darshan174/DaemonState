import { useState } from "react";
import { Link } from "react-router-dom";
import { useSeedDemoData, useUploadSourceFile } from "../api/hooks";
import { useWorkspaceSelection } from "../context/WorkspaceContext";
import { 
  PlayCircle, 
  UploadCloud, 
  Key, 
  CheckCircle2, 
  AlertCircle,
  Loader2,
  ArrowRight,
  FileText,
  X
} from "lucide-react";

export default function Onboarding({ onComplete }) {
  const [step, setStep] = useState("choice"); // choice, demo, import, token
  const [importStatus, setImportStatus] = useState(null); // { status: 'idle' | 'uploading' | 'success' | 'error', message: string }
  const [files, setFiles] = useState([]);
  const [demoStatus, setDemoStatus] = useState(null);
  
  const seedDemo = useSeedDemoData();
  const uploadFile = useUploadSourceFile();
  const { selectedId, setSelectedId } = useWorkspaceSelection();

  const handleRunDemo = () => {
    setStep("demo");
    setDemoStatus(null);
    seedDemo.mutate({ workspaceId: selectedId }, {
      onSuccess: (data) => {
        if (data?.workspaceId) {
          setSelectedId(data.workspaceId);
          setDemoStatus({
            status: "success",
            message:
              data.status === "ready"
                ? `${data.workspaceName || "Demo workspace"} is ready.`
                : `${data.workspaceName || "Demo workspace"} was seeded with demo context.`,
          });
          window.setTimeout(() => onComplete?.(), 700);
          return;
        }
        setDemoStatus({
          status: "error",
          message: "The demo seed finished, but the backend did not return a workspace ID.",
        });
      },
      onError: (err) => {
        setDemoStatus({
          status: "error",
          message: err?.message || "Failed to seed the demo workspace.",
        });
      },
    });
  };

  const handleFileUpload = (e) => {
    const selectedFiles = Array.from(e.target.files);
    setFiles(prev => [...prev, ...selectedFiles]);
  };

  const removeFile = (index) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const processFiles = async () => {
    setImportStatus({ status: 'uploading', message: `Uploading ${files.length} files...` });
    
    try {
      const result = await uploadFile.mutateAsync({
        files,
        workspaceId: selectedId,
      });

      if (result.failed_documents > 0) {
        setImportStatus({
          status: 'error',
          message: `${result.failed_documents} file${result.failed_documents === 1 ? '' : 's'} failed during import.`,
        });
        return;
      }

      const importedCount = result.created_documents + result.updated_documents + result.unchanged_documents;
      setImportStatus({
        status: 'success',
        message: `Imported ${importedCount} file${importedCount === 1 ? '' : 's'}. ${result.processed_documents} processed into context.`,
      });
      setTimeout(() => onComplete?.(), 1500);
    } catch (err) {
      setImportStatus({ status: 'error', message: err.message || 'Failed to upload files.' });
    }
  };

  if (step === "demo") {
    const isError = demoStatus?.status === "error";
    const isSuccess = demoStatus?.status === "success";

    return (
      <div className="panel flex flex-col items-center justify-center px-6 py-14 text-center">
        <div
          className={`w-16 h-16 rounded-full flex items-center justify-center mb-6 ${
            isError
              ? "bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-300"
              : isSuccess
                ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-300"
                : "bg-brand-50 text-brand-600 dark:bg-brand-900/30 dark:text-brand-400"
          }`}
        >
          {isError ? (
            <AlertCircle className="w-8 h-8" />
          ) : isSuccess ? (
            <CheckCircle2 className="w-8 h-8" />
          ) : (
            <Loader2 className="w-8 h-8 animate-spin" />
          )}
        </div>
        <h2 className="text-xl font-bold text-slate-900 dark:text-neutral-100">
          {isError ? "Demo seed failed" : isSuccess ? "Demo workspace ready" : "Seeding Demo Workspace"}
        </h2>
        <p className="mt-2 text-slate-500 dark:text-neutral-400 max-w-sm">
          {demoStatus?.message ||
            "We're setting up source-backed demo context from GitHub, Slack, Gmail, Google Drive, and Codex."}
        </p>
        {isError && (
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <button
              type="button"
              onClick={handleRunDemo}
              className="btn-primary"
            >
              Try again
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => setStep("choice")}
              className="pill-control inline-flex items-center gap-2 px-4 py-2.5 text-sm font-bold"
            >
              Back to options
            </button>
          </div>
        )}
      </div>
    );
  }

  if (step === "import") {
    return (
      <div className="panel p-5 sm:p-7">
        <button 
          onClick={() => setStep("choice")}
          className="mb-6 flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-slate-800 dark:text-neutral-300 transition-colors"
        >
          <ArrowRight className="w-4 h-4 rotate-180" />
          Back to options
        </button>

        <p className="eyebrow">Local evidence</p>
        <h2 className="mb-2 mt-2 text-2xl font-semibold text-slate-900 dark:text-neutral-200">Import your context</h2>
        <p className="mb-8 text-sm text-slate-500">Upload Markdown, text, JSON, CSV, or HTML files to ground your workspace truth.</p>

        <div className="space-y-6">
          <div 
            className="group flex cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-[#d9d9d0] bg-[#f7f7f2] p-10 transition-colors hover:border-brand-500 dark:border-[#35352f] dark:bg-[#10100e]"
            onClick={() => document.getElementById('file-upload').click()}
          >
            <input 
              id="file-upload" 
              type="file" 
              multiple 
              accept=".md,.markdown,.txt,.json,.csv,.html,.htm,.xml,.yaml,.yml,.log,text/*"
              className="hidden" 
              onChange={handleFileUpload}
            />
            <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-md border border-[#d9d9d0] bg-[#fbfbf6] dark:border-[#35352f] dark:bg-[#141411]">
              <UploadCloud className="w-6 h-6 text-brand-600 dark:text-brand-400" />
            </div>
            <p className="text-sm font-bold text-slate-900 dark:text-neutral-200">Click to select files</p>
            <p className="text-xs text-slate-500 mt-1">MD, TXT, JSON, CSV, HTML, YAML, XML, LOG (up to 10MB each)</p>
          </div>

          {files.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-2">Selected Files ({files.length})</p>
              {files.map((file, i) => (
                <div key={i} className="panel-subtle flex items-center justify-between p-3">
                  <div className="flex items-center gap-3">
                    <FileText className="w-4 h-4 text-slate-400" />
                    <span className="text-sm font-medium text-slate-700 dark:text-neutral-400 truncate max-w-[200px]">{file.name}</span>
                  </div>
                  <button onClick={(e) => { e.stopPropagation(); removeFile(i); }} className="p-1 text-slate-400 hover:text-red-500">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
              
              <button
                onClick={processFiles}
                disabled={importStatus?.status === 'uploading'}
                className="btn-primary mt-4 flex w-full justify-center py-3"
              >
                {importStatus?.status === 'uploading' ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    Start Import
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>
          )}

          {importStatus && (
            <div className={`p-4 rounded-xl flex items-start gap-3 ${
              importStatus.status === 'success' ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-300 border border-emerald-100 dark:border-emerald-800/30' :
              importStatus.status === 'error' ? 'bg-red-50 dark:bg-red-900/30 text-red-800 dark:text-red-300 border border-red-100 dark:border-red-800/30' :
              'bg-brand-50 dark:bg-brand-900/30 text-brand-800 dark:text-brand-300 border border-brand-100 dark:border-brand-800/30'
            }`}>
              {importStatus.status === 'success' ? <CheckCircle2 className="w-5 h-5 shrink-0" /> :
               importStatus.status === 'error' ? <AlertCircle className="w-5 h-5 shrink-0" /> :
               <Loader2 className="w-5 h-5 shrink-0 animate-spin" />}
              <p className="text-sm font-medium">{importStatus.message}</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-8">
        <p className="eyebrow">First run</p>
        <h2 className="mt-2 text-3xl font-semibold text-slate-950 dark:text-neutral-100">Add the first evidence</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-500">Choose the fastest path into a useful workspace. You can connect more sources at any time.</p>
      </div>

      <div className="grid items-stretch gap-4 lg:grid-cols-3">
        <OnboardingCard 
          icon={<PlayCircle className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />}
          title="Run Demo Workspace"
          description="Instant setup with source-backed demo data from GitHub, Slack, Gmail, Google Drive, and Codex."
          action="Start demo"
          onClick={handleRunDemo}
          color="emerald"
          recommended
        />

        <OnboardingCard 
          icon={<UploadCloud className="w-6 h-6 text-brand-600 dark:text-brand-400" />}
          title="Import Local Files"
          description="Upload your product specs, roadmap, or meeting notes directly into the engine."
          action="Upload files"
          onClick={() => setStep("import")}
          color="brand"
        />

        <OnboardingCard 
          icon={<Key className="w-6 h-6 text-amber-600 dark:text-amber-400" />}
          title="Connect Live Sources"
          description="Link Slack, GitHub, Gmail, or Google Drive credentials to start continuous ingestion."
          action="Configure tokens"
          to="/app/connectors"
          color="amber"
        />
      </div>
    </div>
  );
}

function OnboardingCard({ icon, title, description, action, onClick, to, color, recommended = false }) {
  const iconBackground = {
    emerald: "bg-emerald-50 dark:bg-emerald-950/40",
    brand: "bg-brand-50 dark:bg-brand-900/30",
    amber: "bg-amber-50 dark:bg-amber-950/40",
  }[color] ?? "bg-slate-50 dark:bg-black";

  const CardContent = (
    <div className="panel group flex h-full flex-col justify-between gap-7 p-5 transition-colors hover:border-[#8a8a80] dark:hover:border-[#57574f]">
      <div>
        <div className="mb-5 flex items-center justify-between gap-3">
          <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-md ${iconBackground}`}>
          {icon}
          </div>
          {recommended ? <span className="rounded-sm bg-[#d9ff68] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-[#171713]">Recommended</span> : null}
        </div>
        <h3 className="text-base font-semibold text-slate-950 dark:text-neutral-200">{title}</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">{description}</p>
      </div>
      {to ? (
        <Link to={to} className="pill-control inline-flex items-center justify-between gap-2 px-3 py-2.5 text-sm font-bold">
          {action}
          <ArrowRight className="w-4 h-4" />
        </Link>
      ) : (
        <button 
          onClick={onClick}
          className="pill-control flex items-center justify-between gap-2 px-3 py-2.5 text-sm font-bold"
        >
          {action}
          <ArrowRight className="w-4 h-4" />
        </button>
      )}
    </div>
  );

  return CardContent;
}
