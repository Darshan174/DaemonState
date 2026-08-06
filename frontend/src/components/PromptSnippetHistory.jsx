import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Check,
  History,
  LoaderCircle,
  Plus,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import {
  useCreatePromptSnippet,
  useDeletePromptSnippet,
  usePromptSnippets,
} from "../api/hooks";

const MAX_PROMPT_CHARACTERS = 20_000;

export default function PromptSnippetHistory({ workspaceId }) {
  const [content, setContent] = useState("");
  const [editorError, setEditorError] = useState("");
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [recentlySavedPrompt, setRecentlySavedPrompt] = useState(null);
  const [removedPromptIds, setRemovedPromptIds] = useState(() => new Set());
  const [savedMessage, setSavedMessage] = useState("");
  const [selectedPromptId, setSelectedPromptId] = useState(null);
  const addPromptButtonRef = useRef(null);
  const libraryRef = useRef(null);
  const promptsQuery = usePromptSnippets(workspaceId);
  const createPrompt = useCreatePromptSnippet();
  const deletePrompt = useDeletePromptSnippet();
  const serverPrompts = promptsQuery.data?.prompts || [];
  const normalizedContent = content.trim();

  const prompts = useMemo(() => {
    const visiblePrompts = serverPrompts.filter(
      (prompt) => !removedPromptIds.has(prompt.id),
    );
    if (
      recentlySavedPrompt
      && !removedPromptIds.has(recentlySavedPrompt.id)
      && !visiblePrompts.some((prompt) => prompt.id === recentlySavedPrompt.id)
    ) {
      return [recentlySavedPrompt, ...visiblePrompts];
    }
    return visiblePrompts;
  }, [recentlySavedPrompt, removedPromptIds, serverPrompts]);

  const selectedPrompt = prompts.find(
    (prompt) => prompt.id === selectedPromptId,
  ) || prompts[0] || null;

  useEffect(() => {
    setContent("");
    setEditorError("");
    setIsEditorOpen(false);
    setRecentlySavedPrompt(null);
    setRemovedPromptIds(new Set());
    setSavedMessage("");
    setSelectedPromptId(null);
  }, [workspaceId]);

  useEffect(() => {
    if (
      recentlySavedPrompt
      && serverPrompts.some((prompt) => prompt.id === recentlySavedPrompt.id)
    ) {
      setRecentlySavedPrompt(null);
    }
  }, [recentlySavedPrompt, serverPrompts]);

  useEffect(() => {
    if (!prompts.length) {
      if (selectedPromptId !== null) setSelectedPromptId(null);
      return;
    }
    if (!prompts.some((prompt) => prompt.id === selectedPromptId)) {
      setSelectedPromptId(prompts[0].id);
    }
  }, [prompts, selectedPromptId]);

  const openPromptEditor = () => {
    if (!workspaceId) return;
    setContent("");
    setEditorError("");
    setSavedMessage("");
    createPrompt.reset?.();
    setIsEditorOpen(true);
  };

  const closePromptEditor = () => {
    if (createPrompt.isPending) return;
    setIsEditorOpen(false);
    setContent("");
    setEditorError("");
    createPrompt.reset?.();
  };

  const savePrompt = async (event) => {
    event.preventDefault();
    if (!workspaceId || !normalizedContent || createPrompt.isPending) return;
    setEditorError("");
    setSavedMessage("");
    createPrompt.reset?.();
    try {
      const saved = await createPrompt.mutateAsync({
        workspaceId,
        content: normalizedContent,
      });
      const authoritativePrompt = {
        ...saved,
        content: saved?.content || normalizedContent,
      };
      setRecentlySavedPrompt(authoritativePrompt);
      setRemovedPromptIds((current) => {
        if (!current.has(authoritativePrompt.id)) return current;
        const next = new Set(current);
        next.delete(authoritativePrompt.id);
        return next;
      });
      setSelectedPromptId(authoritativePrompt.id);
      setContent("");
      setSavedMessage(
        `Saved “${promptTitle(authoritativePrompt.content)}” to the floating button.`,
      );
      setIsEditorOpen(false);
    } catch (error) {
      setEditorError(
        error?.message || "The prompt could not be saved. Please try again.",
      );
    }
  };

  const removePrompt = async (promptId) => {
    if (!workspaceId || deletePrompt.isPending) return;
    setSavedMessage("");
    deletePrompt.reset?.();
    try {
      await deletePrompt.mutateAsync({ workspaceId, promptId });
      const removedIndex = prompts.findIndex((prompt) => prompt.id === promptId);
      const remainingPrompts = prompts.filter((prompt) => prompt.id !== promptId);
      setRemovedPromptIds((current) => new Set(current).add(promptId));
      if (recentlySavedPrompt?.id === promptId) setRecentlySavedPrompt(null);
      if (selectedPrompt?.id === promptId) {
        const nextIndex = Math.min(
          Math.max(removedIndex, 0),
          Math.max(remainingPrompts.length - 1, 0),
        );
        setSelectedPromptId(remainingPrompts[nextIndex]?.id || null);
      }
    } catch {
      // The mutation exposes its accessible error in the detail pane.
    }
  };

  return (
    <>
      <section
        ref={libraryRef}
        aria-labelledby="prompt-library-title"
        className="overflow-hidden rounded-[1.75rem] border border-[#d8d8cf] bg-[#fbfbf6] shadow-[0_20px_60px_rgba(23,23,19,0.06)] dark:border-[#2d2d28] dark:bg-[#12120f] dark:shadow-none"
      >
        <div
          className="relative border-b border-[#deded5] px-5 py-5 dark:border-[#292925] sm:px-6"
          data-testid="prompt-library-header"
        >
          <button
            ref={addPromptButtonRef}
            type="button"
            aria-haspopup="dialog"
            aria-expanded={isEditorOpen}
            aria-label="Add prompt manually"
            title={workspaceId ? "Add prompt" : "Select a workspace to add a prompt"}
            disabled={!workspaceId}
            onClick={openPromptEditor}
            className="absolute right-5 top-5 grid h-10 w-10 place-items-center rounded-full border border-[#a8c342] bg-[#d9ff68] text-[#171713] shadow-[0_7px_18px_rgba(126,146,42,0.22)] transition hover:scale-105 hover:bg-[#e4ff94] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7e922a] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-45 dark:border-[#d9ff68]/65 dark:focus-visible:ring-[#d9ff68] dark:focus-visible:ring-offset-[#12120f] motion-reduce:hover:scale-100 sm:right-6"
          >
            <Plus className="h-5 w-5" aria-hidden="true" />
          </button>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="pr-14 sm:pr-16">
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
            <div className="inline-flex w-fit self-end items-center gap-2 rounded-full border border-[#d3d3c8] bg-white px-3 py-1.5 text-xs font-semibold text-[#66665e] dark:border-white/10 dark:bg-white/[0.04] dark:text-[#b8b8af]">
              <History className="h-3.5 w-3.5" aria-hidden="true" />
              {prompts.length} saved
            </div>
          </div>
        </div>

        <div className="grid min-h-[31rem] gap-0 lg:grid-cols-[minmax(17rem,0.82fr)_minmax(0,1.48fr)]">
          <div className="flex min-h-0 flex-col border-b border-[#deded5] dark:border-[#292925] lg:border-b-0 lg:border-r">
            <div className="flex min-h-[4.75rem] items-center justify-between gap-3 border-b border-[#deded5] px-5 py-4 dark:border-[#292925] sm:px-6">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-[#282822] dark:text-[#efefe8]">
                  Saved prompts
                </h3>
                <p className="mt-1 text-[11px] text-[#7b7b73] dark:text-[#8f8f87]">
                  Select one to read it in full.
                </p>
              </div>
              {promptsQuery.isFetching && prompts.length ? (
                <span className="inline-flex shrink-0 items-center gap-1.5 text-[10px] text-[#85857d]">
                  <LoaderCircle className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  Syncing
                </span>
              ) : null}
            </div>

            <div className="min-h-0 flex-1 p-3 sm:p-4">
              {promptsQuery.isLoading && !prompts.length ? (
                <div role="status" className="flex min-h-40 items-center justify-center rounded-2xl border border-dashed border-[#d4d4ca] text-sm text-[#77776f] dark:border-white/10 dark:text-[#92928a]">
                  Loading saved prompts…
                </div>
              ) : promptsQuery.isError && !prompts.length ? (
                <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-100">
                  <p className="font-semibold">Prompt history could not be loaded</p>
                  <p className="mt-1 text-xs leading-5 opacity-75">
                    {promptsQuery.error?.message || "Try refreshing the project."}
                  </p>
                </div>
              ) : !prompts.length ? (
                <div className="flex min-h-40 flex-col items-center justify-center rounded-2xl border border-dashed border-[#d4d4ca] px-5 text-center dark:border-white/10">
                  <Sparkles className="h-5 w-5 text-[#7e922a] dark:text-[#d9ff68]" aria-hidden="true" />
                  <p className="mt-3 text-sm font-semibold text-[#3e3e37] dark:text-[#e2e2da]">
                    No saved prompts yet
                  </p>
                  <p className="mt-1 max-w-xs text-xs leading-5 text-[#7b7b73] dark:text-[#8f8f87]">
                    Use the green + button or paste one directly into the floating dropdown.
                  </p>
                </div>
              ) : (
                <ol
                  className="max-h-[25.5rem] space-y-2 overflow-y-auto pr-1"
                  aria-label="Saved reusable prompts"
                >
                  {prompts.map((prompt, index) => {
                    const isSelected = selectedPrompt?.id === prompt.id;
                    return (
                      <li key={prompt.id}>
                        <button
                          type="button"
                          aria-label={`Select prompt: ${promptTitle(prompt.content)}`}
                          aria-pressed={isSelected}
                          onClick={() => {
                            setSelectedPromptId(prompt.id);
                            setSavedMessage("");
                          }}
                          className={`group flex w-full items-start gap-3 rounded-2xl border p-3 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-[#93aa34] dark:focus-visible:ring-[#d9ff68] ${
                            isSelected
                              ? "border-[#aabe56] bg-[#f1f8d7] shadow-[0_8px_22px_rgba(23,23,19,0.06)] dark:border-[#d9ff68]/45 dark:bg-[#d9ff68]/[0.09] dark:shadow-none"
                              : "border-transparent bg-transparent hover:border-[#d9d9d0] hover:bg-white dark:hover:border-white/10 dark:hover:bg-white/[0.035]"
                          }`}
                        >
                          <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-[10px] font-black ${
                            isSelected
                              ? "bg-[#d9ff68] text-[#36400e] dark:text-[#171713]"
                              : "bg-[#eeeee7] text-[#77776f] dark:bg-white/[0.07] dark:text-[#aaa9a0]"
                          }`}
                          >
                            {String(index + 1).padStart(2, "0")}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold text-[#2f2f29] dark:text-[#f2f2eb]">
                              {promptTitle(prompt.content)}
                            </span>
                            <span className="mt-1.5 line-clamp-2 whitespace-pre-wrap break-words text-xs leading-5 text-[#73736b] dark:text-[#9d9d95]">
                              {prompt.content}
                            </span>
                            <span className="mt-2 block text-[9px] font-semibold uppercase tracking-[0.1em] text-[#999990] dark:text-[#77776f]">
                              {promptActivity(prompt)}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              )}
            </div>
          </div>

          <div className="flex min-w-0 flex-col p-5 sm:p-6">
            <div className="flex min-h-10 items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.16em] text-[#7e922a] dark:text-[#d9ff68]">
                  Selected prompt
                </p>
                <h3 className="mt-1 text-sm font-semibold text-[#282822] dark:text-[#efefe8]">
                  Prompt details
                </h3>
              </div>
              {selectedPrompt ? (
                <button
                  type="button"
                  aria-label={`Delete prompt: ${promptTitle(selectedPrompt.content)}`}
                  title="Delete prompt"
                  disabled={deletePrompt.isPending}
                  onClick={() => removePrompt(selectedPrompt.id)}
                  className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-[#deded5] text-[#88887f] transition hover:border-red-200 hover:bg-red-50 hover:text-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 disabled:cursor-wait disabled:opacity-40 dark:border-white/10 dark:hover:border-red-900/60 dark:hover:bg-red-950/30 dark:hover:text-red-300"
                >
                  {deletePrompt.isPending
                    && deletePrompt.variables?.promptId === selectedPrompt.id ? (
                      <LoaderCircle className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                    ) : (
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    )}
                </button>
              ) : null}
            </div>

            {savedMessage ? (
              <p role="status" className="mt-4 rounded-xl border border-[#cbdc83] bg-[#f2f8dc] px-3 py-2 text-xs leading-5 text-[#536119] dark:border-[#d9ff68]/20 dark:bg-[#d9ff68]/[0.07] dark:text-[#d9ff68]">
                {savedMessage}
              </p>
            ) : null}
            {deletePrompt.error ? (
              <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-300">
                {deletePrompt.error.message || "The prompt could not be deleted."}
              </p>
            ) : null}

            {selectedPrompt ? (
              <article aria-label="Selected prompt" className="mt-5 flex min-h-0 flex-1 flex-col">
                <h4 className="text-xl font-semibold tracking-[-0.025em] text-[#24241f] dark:text-white">
                  {promptTitle(selectedPrompt.content)}
                </h4>
                <p className="mt-2 text-[10px] font-semibold uppercase tracking-[0.11em] text-[#909087] dark:text-[#77776f]">
                  {promptActivity(selectedPrompt)}
                </p>
                <pre
                  tabIndex={0}
                  className="mt-5 max-h-[20.5rem] min-h-52 flex-1 overflow-auto whitespace-pre-wrap break-words rounded-2xl border border-[#d9d9d0] bg-white p-5 font-sans text-sm leading-6 text-[#33332d] outline-none focus-visible:ring-2 focus-visible:ring-[#93aa34] dark:border-white/10 dark:bg-black/20 dark:text-[#e7e7df] dark:focus-visible:ring-[#d9ff68]"
                >
                  {selectedPrompt.content}
                </pre>
              </article>
            ) : (
              <div className="mt-5 flex min-h-64 flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-[#d4d4ca] px-6 text-center dark:border-white/10">
                <Sparkles className="h-6 w-6 text-[#7e922a] dark:text-[#d9ff68]" aria-hidden="true" />
                <p className="mt-3 text-sm font-semibold text-[#3e3e37] dark:text-[#e2e2da]">
                  Nothing selected yet
                </p>
                <p className="mt-1 max-w-sm text-xs leading-5 text-[#7b7b73] dark:text-[#8f8f87]">
                  Add a prompt and its complete text will be displayed here.
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      {isEditorOpen ? (
        <PromptEditorDialog
          backgroundRef={libraryRef}
          content={content}
          errorMessage={editorError || createPrompt.error?.message || ""}
          isPending={createPrompt.isPending}
          onChange={(nextContent) => {
            setContent(nextContent);
            setEditorError("");
          }}
          onClose={closePromptEditor}
          onSubmit={savePrompt}
          restoreFocusRef={addPromptButtonRef}
        />
      ) : null}
    </>
  );
}

function PromptEditorDialog({
  backgroundRef,
  content,
  errorMessage,
  isPending,
  onChange,
  onClose,
  onSubmit,
  restoreFocusRef,
}) {
  const dialogRef = useRef(null);
  const editorRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const pendingRef = useRef(isPending);
  onCloseRef.current = onClose;
  pendingRef.current = isPending;

  useEffect(() => {
    const appRoot = document.getElementById("root");
    const inertTarget = appRoot || backgroundRef.current;
    const targetWasInert = inertTarget?.hasAttribute("inert");
    const previousOverflow = document.body.style.overflow;
    const returnFocusTo = restoreFocusRef.current || document.activeElement;

    inertTarget?.setAttribute("inert", "");
    document.body.style.overflow = "hidden";
    const focusFrame = window.requestAnimationFrame(() => editorRef.current?.focus());

    const onKeyDown = (event) => {
      if (event.key === "Escape" && !pendingRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) || []).filter((element) => !element.hasAttribute("hidden"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const focusIsInside = dialogRef.current?.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || !focusIsInside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !focusIsInside)) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      window.removeEventListener("keydown", onKeyDown);
      if (!targetWasInert) inertTarget?.removeAttribute("inert");
      document.body.style.overflow = previousOverflow;
      window.requestAnimationFrame(() => returnFocusTo?.focus?.());
    };
  }, [backgroundRef, restoreFocusRef]);

  return createPortal(
    <div
      data-testid="prompt-editor-backdrop"
      role="presentation"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/65 px-4 py-6 backdrop-blur-[7px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isPending) onClose();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="prompt-editor-title"
        aria-describedby="prompt-editor-description"
        className="w-full max-w-2xl overflow-hidden rounded-[1.75rem] border border-[#d8d8cf] bg-[#fbfbf6] shadow-[0_36px_120px_rgba(0,0,0,0.48)] dark:border-[#393934] dark:bg-[#0b0b09]"
      >
        <form onSubmit={onSubmit}>
          <div className="border-b border-[#deded5] px-5 py-4 dark:border-[#292925] sm:px-6">
            <div className="flex items-start gap-4">
              <button
                type="button"
                aria-label="Close add prompt dialog"
                title="Close"
                disabled={isPending}
                onClick={onClose}
                className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center text-[#ff5f57] transition hover:text-[#ff766f] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ff5f57]/70 focus-visible:ring-offset-2 disabled:cursor-wait disabled:opacity-50 dark:focus-visible:ring-offset-[#0b0b09]"
              >
                <X className="h-5 w-5" strokeWidth={2.5} aria-hidden="true" />
              </button>
              <div className="min-w-0">
                <p className="text-[10px] font-black uppercase tracking-[0.18em] text-[#7e922a] dark:text-[#d9ff68]">
                  Prompt library
                </p>
                <h2
                  id="prompt-editor-title"
                  className="mt-1 text-xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white"
                >
                  Add a reusable prompt
                </h2>
                <p id="prompt-editor-description" className="mt-1 text-xs leading-5 text-[#77776f] dark:text-[#92928a]">
                  Paste or write one complete instruction. Formatting and line breaks are preserved.
                </p>
              </div>
            </div>
          </div>

          <div className="p-5 sm:p-6">
            <label htmlFor="prompt-snippet-content" className="sr-only">
              Prompt text
            </label>
            <textarea
              ref={editorRef}
              id="prompt-snippet-content"
              value={content}
              onChange={(event) => onChange(event.target.value)}
              maxLength={MAX_PROMPT_CHARACTERS}
              rows={10}
              placeholder="Paste or write your reusable prompt here…"
              disabled={isPending}
              className="min-h-64 w-full resize-y rounded-2xl border border-[#d4d4ca] bg-white px-4 py-3 text-sm leading-6 text-[#22221e] outline-none transition placeholder:text-[#9a9a91] focus:border-[#93aa34] focus:ring-4 focus:ring-[#d9ff68]/20 disabled:cursor-wait disabled:opacity-60 dark:border-white/10 dark:bg-black/20 dark:text-white dark:placeholder:text-white/35 dark:focus:border-[#d9ff68]/60"
            />

            {errorMessage ? (
              <p role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-300">
                {errorMessage}
              </p>
            ) : null}

            <div className="mt-4 flex items-center justify-between gap-4">
              <span className="text-[11px] text-[#898980] dark:text-[#77776f]">
                {content.length.toLocaleString()} / {MAX_PROMPT_CHARACTERS.toLocaleString()}
              </span>
              <button
                type="submit"
                aria-label="Save prompt"
                title="Save prompt"
                disabled={!content.trim() || isPending}
                className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-[#a8c342] bg-[#d9ff68] text-[#171713] shadow-[0_8px_20px_rgba(126,146,42,0.24)] transition hover:scale-105 hover:bg-[#e4ff94] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7e922a] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-45 dark:border-[#d9ff68]/65 dark:focus-visible:ring-[#d9ff68] dark:focus-visible:ring-offset-[#0b0b09] motion-reduce:hover:scale-100"
              >
                {isPending ? (
                  <LoaderCircle className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                ) : (
                  <Check className="h-5 w-5" strokeWidth={3} aria-hidden="true" />
                )}
              </button>
            </div>
          </div>
        </form>
      </section>
    </div>,
    document.body,
  );
}

function promptActivity(prompt) {
  return prompt.use_count
    ? `Used ${prompt.use_count} ${prompt.use_count === 1 ? "time" : "times"} · ${formatPromptTime(prompt.last_used_at)}`
    : `Saved ${formatPromptTime(prompt.created_at)}`;
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
