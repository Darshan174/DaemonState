import { useState } from "react";
import {
  History,
  LoaderCircle,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";

import {
  useCreatePromptSnippet,
  useDeletePromptSnippet,
  usePromptSnippets,
} from "../api/hooks";

const MAX_PROMPT_CHARACTERS = 20_000;

export default function PromptSnippetHistory({ workspaceId }) {
  const [content, setContent] = useState("");
  const [savedMessage, setSavedMessage] = useState("");
  const promptsQuery = usePromptSnippets(workspaceId);
  const createPrompt = useCreatePromptSnippet();
  const deletePrompt = useDeletePromptSnippet();
  const prompts = promptsQuery.data?.prompts || [];
  const normalizedContent = content.trim();

  const savePrompt = async (event) => {
    event.preventDefault();
    if (!workspaceId || !normalizedContent || createPrompt.isPending) return;
    setSavedMessage("");
    createPrompt.reset?.();
    try {
      const saved = await createPrompt.mutateAsync({
        workspaceId,
        content: normalizedContent,
      });
      setContent("");
      setSavedMessage(`Saved “${promptTitle(saved.content)}” to the floating button.`);
    } catch {
      // The mutation exposes its accessible error below.
    }
  };

  const removePrompt = async (promptId) => {
    if (!workspaceId || deletePrompt.isPending) return;
    setSavedMessage("");
    deletePrompt.reset?.();
    try {
      await deletePrompt.mutateAsync({ workspaceId, promptId });
    } catch {
      // The mutation exposes its accessible error below.
    }
  };

  const requestError = createPrompt.error || deletePrompt.error;

  return (
    <section
      aria-labelledby="prompt-library-title"
      className="overflow-hidden rounded-[1.75rem] border border-[#d8d8cf] bg-[#fbfbf6] shadow-[0_20px_60px_rgba(23,23,19,0.06)] dark:border-[#2d2d28] dark:bg-[#12120f] dark:shadow-none"
    >
      <div className="border-b border-[#deded5] px-5 py-5 dark:border-[#292925] sm:px-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.18em] text-[#5b691d] dark:text-[#d9ff68]">
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              Floating prompt library
            </p>
            <h2
              id="prompt-library-title"
              className="mt-2 text-2xl font-semibold tracking-[-0.035em] text-[#171713] dark:text-white"
            >
              Reusable prompt history
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
              Save prompts once, select one or more from the floating dropdown, then use the logo to paste them into any focused AI editor.
            </p>
          </div>
          <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[#d3d3c8] bg-white px-3 py-1.5 text-xs font-semibold text-[#66665e] dark:border-white/10 dark:bg-white/[0.04] dark:text-[#b8b8af]">
            <History className="h-3.5 w-3.5" aria-hidden="true" />
            {prompts.length} saved
          </div>
        </div>
      </div>

      <div className="grid gap-0 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.35fr)]">
        <form
          onSubmit={savePrompt}
          className="border-b border-[#deded5] p-5 dark:border-[#292925] lg:border-b-0 lg:border-r sm:p-6"
        >
          <label
            htmlFor="prompt-snippet-content"
            className="text-sm font-semibold text-[#282822] dark:text-[#efefe8]"
          >
            Add a prompt
          </label>
          <p className="mt-1 text-xs leading-5 text-[#77776f] dark:text-[#92928a]">
            Paste one complete reusable instruction. Formatting and line breaks are preserved.
          </p>
          <textarea
            id="prompt-snippet-content"
            value={content}
            onChange={(event) => {
              setContent(event.target.value);
              setSavedMessage("");
            }}
            maxLength={MAX_PROMPT_CHARACTERS}
            rows={8}
            placeholder="Example: Review the current diff. Report only concrete regressions with file and line references."
            disabled={!workspaceId || createPrompt.isPending}
            className="mt-4 min-h-44 w-full resize-y rounded-2xl border border-[#d4d4ca] bg-white px-4 py-3 text-sm leading-6 text-[#22221e] outline-none transition placeholder:text-[#9a9a91] focus:border-[#93aa34] focus:ring-4 focus:ring-[#d9ff68]/20 disabled:cursor-not-allowed disabled:opacity-60 dark:border-white/10 dark:bg-black/20 dark:text-white dark:placeholder:text-white/35 dark:focus:border-[#d9ff68]/60"
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <span className="text-[11px] text-[#898980] dark:text-[#77776f]">
              {content.length.toLocaleString()} / {MAX_PROMPT_CHARACTERS.toLocaleString()}
            </span>
            <button
              type="submit"
              disabled={!workspaceId || !normalizedContent || createPrompt.isPending}
              className="inline-flex min-h-11 items-center gap-2 rounded-full bg-[#171713] px-4 text-xs font-bold text-white transition hover:bg-black focus:outline-none focus-visible:ring-2 focus-visible:ring-[#93aa34] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-[#d9ff68] dark:text-[#171713] dark:hover:bg-[#e4ff94] dark:focus-visible:ring-[#d9ff68] dark:focus-visible:ring-offset-[#12120f]"
            >
              {createPrompt.isPending ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {createPrompt.isPending ? "Saving…" : "Save prompt"}
            </button>
          </div>
          {savedMessage ? (
            <p role="status" className="mt-3 text-xs leading-5 text-[#536119] dark:text-[#d9ff68]">
              {savedMessage}
            </p>
          ) : null}
          {requestError ? (
            <p role="alert" className="mt-3 text-xs leading-5 text-red-700 dark:text-red-300">
              {requestError.message || "The prompt library could not be updated."}
            </p>
          ) : null}
        </form>

        <div className="min-w-0 p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-[#282822] dark:text-[#efefe8]">
              Prompt history
            </h3>
            {promptsQuery.isFetching && prompts.length ? (
              <span className="inline-flex items-center gap-1.5 text-[11px] text-[#85857d]">
                <LoaderCircle className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                Syncing
              </span>
            ) : null}
          </div>

          {promptsQuery.isLoading && !prompts.length ? (
            <div role="status" className="mt-4 flex min-h-40 items-center justify-center rounded-2xl border border-dashed border-[#d4d4ca] text-sm text-[#77776f] dark:border-white/10 dark:text-[#92928a]">
              Loading saved prompts…
            </div>
          ) : promptsQuery.isError && !prompts.length ? (
            <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-100">
              <p className="font-semibold">Prompt history could not be loaded</p>
              <p className="mt-1 text-xs leading-5 opacity-75">
                {promptsQuery.error?.message || "Try refreshing the project."}
              </p>
            </div>
          ) : !prompts.length ? (
            <div className="mt-4 flex min-h-40 flex-col items-center justify-center rounded-2xl border border-dashed border-[#d4d4ca] px-6 text-center dark:border-white/10">
              <Sparkles className="h-5 w-5 text-[#7e922a] dark:text-[#d9ff68]" aria-hidden="true" />
              <p className="mt-3 text-sm font-semibold text-[#3e3e37] dark:text-[#e2e2da]">No saved prompts yet</p>
              <p className="mt-1 max-w-sm text-xs leading-5 text-[#7b7b73] dark:text-[#8f8f87]">
                Save one here or paste one directly into the floating dropdown.
              </p>
            </div>
          ) : (
            <ol className="mt-4 max-h-[32rem] space-y-3 overflow-y-auto pr-1" aria-label="Saved reusable prompts">
              {prompts.map((prompt, index) => {
                const deleting = (
                  deletePrompt.isPending
                  && deletePrompt.variables?.promptId === prompt.id
                );
                return (
                  <li
                    key={prompt.id}
                    className="group rounded-2xl border border-[#d9d9d0] bg-white p-4 transition hover:border-[#b7c773] hover:shadow-[0_10px_30px_rgba(23,23,19,0.06)] dark:border-white/10 dark:bg-white/[0.035] dark:hover:border-[#d9ff68]/35 dark:hover:shadow-none"
                  >
                    <div className="flex items-start gap-3">
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#eef5d3] text-[10px] font-black text-[#536119] dark:bg-[#d9ff68]/12 dark:text-[#d9ff68]">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-[#2f2f29] dark:text-[#f2f2eb]">
                          {promptTitle(prompt.content)}
                        </p>
                        <p className="mt-2 max-h-28 overflow-y-auto whitespace-pre-wrap break-words text-xs leading-5 text-[#6f6f67] dark:text-[#aaa9a0]">
                          {prompt.content}
                        </p>
                        <p className="mt-3 text-[10px] font-medium uppercase tracking-[0.1em] text-[#999990] dark:text-[#6f6f68]">
                          {prompt.use_count
                            ? `Used ${prompt.use_count} ${prompt.use_count === 1 ? "time" : "times"} · ${formatPromptTime(prompt.last_used_at)}`
                            : `Saved ${formatPromptTime(prompt.created_at)}`}
                        </p>
                      </div>
                      <button
                        type="button"
                        aria-label={`Delete prompt: ${promptTitle(prompt.content)}`}
                        title="Delete prompt"
                        disabled={deletePrompt.isPending}
                        onClick={() => removePrompt(prompt.id)}
                        className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-transparent text-[#929289] transition hover:border-red-200 hover:bg-red-50 hover:text-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 disabled:cursor-wait disabled:opacity-40 dark:hover:border-red-900/60 dark:hover:bg-red-950/30 dark:hover:text-red-300"
                      >
                        {deleting ? (
                          <LoaderCircle className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                        ) : (
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        )}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}

function promptTitle(content) {
  const firstLine = String(content || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) || "Untitled prompt";
  return firstLine.length > 72 ? `${firstLine.slice(0, 69)}…` : firstLine;
}

function formatPromptTime(value) {
  if (!value) return "just now";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "recently";
  const elapsed = Math.max(0, Date.now() - timestamp);
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 14) return `${days}d ago`;
  return new Date(timestamp).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: new Date(timestamp).getFullYear() === new Date().getFullYear()
      ? undefined
      : "numeric",
  });
}
