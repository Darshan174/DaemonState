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
  
  const seedDemo = useSeedDemoData();
  const uploadFile = useUploadSourceFile();
  const { setSelectedId } = useWorkspaceSelection();

  const handleRunDemo = () => {
    setStep("demo");
    seedDemo.mutate(null, {
      onSuccess: (data) => {
        if (data?.workspaceId) {
          setSelectedId(data.workspaceId);
          onComplete?.();
        }
      }
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
      for (const file of files) {
        await uploadFile.mutateAsync(file);
      }
      setImportStatus({ status: 'success', message: 'All files imported successfully! Your context is being processed.' });
      setTimeout(() => onComplete?.(), 2000);
    } catch (err) {
      setImportStatus({ status: 'error', message: err.message || 'Failed to upload files.' });
    }
  };

  if (step === "demo") {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="w-16 h-16 rounded-full bg-brand-50 flex items-center justify-center mb-6">
          <Loader2 className="w-8 h-8 text-brand-600 animate-spin" />
        </div>
        <h2 className="text-xl font-bold text-slate-900">Seeding Demo Workspace</h2>
        <p className="mt-2 text-slate-500 max-w-sm">
          We're setting up a realistic startup environment with Slack threads, Notion docs, and Zoom transcripts.
        </p>
      </div>
    );
  }

  if (step === "import") {
    return (
      <div className="py-6">
        <button 
          onClick={() => setStep("choice")}
          className="mb-6 flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-slate-800 transition-colors"
        >
          <ArrowRight className="w-4 h-4 rotate-180" />
          Back to options
        </button>

        <h2 className="text-xl font-bold text-slate-900 mb-2">Import your context</h2>
        <p className="text-slate-500 mb-8">Upload PDF, Markdown, or Text files to ground your workspace truth.</p>

        <div className="space-y-6">
          <div 
            className="border-2 border-dashed border-slate-200 rounded-2xl p-10 flex flex-col items-center justify-center bg-slate-50/50 hover:bg-slate-50 transition-colors cursor-pointer group"
            onClick={() => document.getElementById('file-upload').click()}
          >
            <input 
              id="file-upload" 
              type="file" 
              multiple 
              className="hidden" 
              onChange={handleFileUpload}
            />
            <div className="w-12 h-12 rounded-full bg-white shadow-sm flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
              <UploadCloud className="w-6 h-6 text-brand-600" />
            </div>
            <p className="text-sm font-bold text-slate-900">Click to select files</p>
            <p className="text-xs text-slate-500 mt-1">PDF, MD, TXT (up to 10MB each)</p>
          </div>

          {files.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-2">Selected Files ({files.length})</p>
              {files.map((file, i) => (
                <div key={i} className="flex items-center justify-between p-3 bg-white border border-slate-200 rounded-xl">
                  <div className="flex items-center gap-3">
                    <FileText className="w-4 h-4 text-slate-400" />
                    <span className="text-sm font-medium text-slate-700 truncate max-w-[200px]">{file.name}</span>
                  </div>
                  <button onClick={(e) => { e.stopPropagation(); removeFile(i); }} className="p-1 text-slate-400 hover:text-red-500">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
              
              <button
                onClick={processFiles}
                disabled={importStatus?.status === 'uploading'}
                className="w-full mt-4 py-3 bg-brand-600 text-white rounded-xl font-bold shadow-lg shadow-brand-600/20 hover:bg-brand-500 transition-all flex items-center justify-center gap-2"
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
              importStatus.status === 'success' ? 'bg-emerald-50 text-emerald-800 border border-emerald-100' :
              importStatus.status === 'error' ? 'bg-red-50 text-red-800 border border-red-100' :
              'bg-brand-50 text-brand-800 border border-brand-100'
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
    <div className="py-6">
      <div className="mb-10">
        <h2 className="text-2xl font-bold text-slate-900">Welcome to Context Engine</h2>
        <p className="text-slate-500 mt-2">Get started by seeding your workspace with initial truth.</p>
      </div>

      <div className="grid gap-4">
        <OnboardingCard 
          icon={<PlayCircle className="w-6 h-6 text-emerald-600" />}
          title="Run Demo Workspace"
          description="Instant setup with high-quality mock data from Slack, Notion, and Zoom. Best for exploration."
          action="Start demo"
          onClick={handleRunDemo}
          color="emerald"
        />

        <OnboardingCard 
          icon={<UploadCloud className="w-6 h-6 text-brand-600" />}
          title="Import Local Files"
          description="Upload your product specs, roadmap, or meeting notes directly into the engine."
          action="Upload files"
          onClick={() => setStep("import")}
          color="brand"
        />

        <OnboardingCard 
          icon={<Key className="w-6 h-6 text-amber-600" />}
          title="Connect Live Sources"
          description="Link Slack, GitHub, or Notion tokens to start continuous ingestion of live company data."
          action="Configure tokens"
          to="/app/connectors"
          color="amber"
        />
      </div>
    </div>
  );
}

function OnboardingCard({ icon, title, description, action, onClick, to, color }) {
  const CardContent = (
    <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 bg-white border border-slate-200 rounded-[24px] hover:border-brand-300 hover:shadow-xl hover:shadow-brand-500/5 transition-all group">
      <div className="flex items-start gap-5">
        <div className={`w-14 h-14 rounded-2xl bg-${color}-50 flex items-center justify-center shrink-0 group-hover:scale-110 transition-transform`}>
          {icon}
        </div>
        <div>
          <h3 className="text-lg font-bold text-slate-900">{title}</h3>
          <p className="mt-1 text-sm text-slate-500 max-w-md">{description}</p>
        </div>
      </div>
      {to ? (
        <Link to={to} className={`px-6 py-2.5 rounded-xl bg-slate-900 text-white text-sm font-bold hover:bg-slate-800 transition-colors inline-flex items-center gap-2`}>
          {action}
          <ArrowRight className="w-4 h-4" />
        </Link>
      ) : (
        <button 
          onClick={onClick}
          className={`px-6 py-2.5 rounded-xl bg-slate-900 text-white text-sm font-bold hover:bg-slate-800 transition-colors flex items-center gap-2`}
        >
          {action}
          <ArrowRight className="w-4 h-4" />
        </button>
      )}
    </div>
  );

  return CardContent;
}
