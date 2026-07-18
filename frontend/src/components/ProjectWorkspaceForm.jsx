import { useMemo, useState } from "react";
import { ArrowRight, FolderGit2, Loader2 } from "lucide-react";
import { useCreateProjectWorkspace } from "../api/hooks";

function projectNameFromPath(value) {
  const normalized = value.trim().replace(/[\\/]+$/, "");
  const segment = normalized.split(/[\\/]/).filter(Boolean).at(-1) || "";
  return segment.replace(/\.git$/i, "").replace(/[-_]+/g, " ");
}

export default function ProjectWorkspaceForm({ onCreated, compact = false }) {
  const createProject = useCreateProjectWorkspace();
  const [repoPath, setRepoPath] = useState("");
  const [name, setName] = useState("");
  const [nameEdited, setNameEdited] = useState(false);
  const [error, setError] = useState(null);
  const suggestedName = useMemo(() => projectNameFromPath(repoPath), [repoPath]);
  const projectName = (nameEdited ? name : suggestedName).trim();
  const pathValue = repoPath.trim();

  async function handleSubmit(event) {
    event.preventDefault();
    if (!pathValue || !projectName || createProject.isPending) return;
    setError(null);
    try {
      const result = await createProject.mutateAsync({
        name: projectName,
        repo_path: pathValue,
      });
      setRepoPath("");
      setName("");
      setNameEdited(false);
      onCreated?.(result.workspace, result.repository);
    } catch (mutationError) {
      const cleanupWarning = mutationError?.createdWorkspace
        ? ` An empty workspace named “${mutationError.createdWorkspace.name}” was created and could not be cleaned up.`
        : " No workspace was kept.";
      setError(`${mutationError?.message || "The repository could not be connected."}${cleanupWarning}`);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className={compact ? "space-y-4" : "rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-neutral-800 dark:bg-[#10100e] sm:p-5"}
    >
      {!compact ? (
        <div className="mb-4 flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-slate-700 ring-1 ring-slate-200 dark:bg-[#171713] dark:text-neutral-200 dark:ring-neutral-700">
            <FolderGit2 className="h-4.5 w-4.5" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-950 dark:text-white">Connect a real project</h3>
            <p className="mt-0.5 text-xs leading-5 text-slate-500 dark:text-neutral-400">
              Point Context Engine at a local repository. It creates the workspace and indexes project structure as source evidence.
            </p>
          </div>
        </div>
      ) : null}

      <div>
        <label htmlFor="project-repo-path" className="mb-1.5 block text-xs font-bold text-slate-600 dark:text-neutral-300">
          Local repository path <span className="text-red-500">*</span>
        </label>
        <input
          id="project-repo-path"
          value={repoPath}
          onChange={(event) => setRepoPath(event.target.value)}
          placeholder="/Users/you/code/your-project"
          autoComplete="off"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 font-mono text-sm text-slate-900 outline-none transition placeholder:font-sans placeholder:text-slate-400 focus:border-slate-400 focus:ring-4 focus:ring-slate-200/70 dark:border-neutral-700 dark:bg-black dark:text-white dark:focus:border-slate-500 dark:focus:ring-neutral-800"
        />
        <p className="mt-1.5 text-[11px] leading-4 text-slate-400 dark:text-neutral-500">
          Read locally by the running Context Engine instance. Files are not uploaded to a third party.
        </p>
      </div>

      <div>
        <label htmlFor="project-workspace-name" className="mb-1.5 block text-xs font-bold text-slate-600 dark:text-neutral-300">
          Project name
        </label>
        <input
          id="project-workspace-name"
          value={nameEdited ? name : suggestedName}
          onChange={(event) => {
            setNameEdited(true);
            setName(event.target.value);
          }}
          placeholder="Filled from the repository folder"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-4 focus:ring-slate-200/70 dark:border-neutral-700 dark:bg-black dark:text-white dark:focus:border-slate-500 dark:focus:ring-neutral-800"
        />
      </div>

      {error ? (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold leading-5 text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={!pathValue || !projectName || createProject.isPending}
        className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-45 dark:bg-[#d9ff68] dark:text-[#171713] dark:hover:bg-[#c9ef58] sm:w-auto"
      >
        {createProject.isPending ? (
          <><Loader2 className="h-4 w-4 animate-spin" /> Connecting and indexing</>
        ) : (
          <>Connect project <ArrowRight className="h-4 w-4" /></>
        )}
      </button>
    </form>
  );
}

export { projectNameFromPath };
