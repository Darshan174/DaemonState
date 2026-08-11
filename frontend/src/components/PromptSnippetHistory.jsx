import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Check,
  Copy,
  LoaderCircle,
  Plus,
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
  const [copiedPromptId, setCopiedPromptId] = useState(null);
  const [copyError, setCopyError] = useState("");
  const [editorError, setEditorError] = useState("");
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [recentlySavedPrompt, setRecentlySavedPrompt] = useState(null);
  const [removedPromptIds, setRemovedPromptIds] = useState(() => new Set());
  const [savedMessage, setSavedMessage] = useState("");
  const [selectedPromptId, setSelectedPromptId] = useState(null);
  const addPromptButtonRef = useRef(null);
  const copyResetTimerRef = useRef(null);
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
    if (copyResetTimerRef.current) {
      window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = null;
    }
    setContent("");
    setCopiedPromptId(null);
    setCopyError("");
    setEditorError("");
    setIsEditorOpen(false);
    setRecentlySavedPrompt(null);
    setRemovedPromptIds(new Set());
    setSavedMessage("");
    setSelectedPromptId(null);
  }, [workspaceId]);

  useEffect(() => () => {
    if (copyResetTimerRef.current) window.clearTimeout(copyResetTimerRef.current);
  }, []);

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
      if (copiedPromptId === promptId) setCopiedPromptId(null);
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

  const copySelectedPrompt = async () => {
    if (!selectedPrompt) return;
    setCopyError("");
    try {
      if (!globalThis.navigator?.clipboard?.writeText) {
        throw new Error("Clipboard access is unavailable.");
      }
      await globalThis.navigator.clipboard.writeText(selectedPrompt.content);
      setCopiedPromptId(selectedPrompt.id);
      if (copyResetTimerRef.current) window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = window.setTimeout(() => {
        setCopiedPromptId(null);
      }, 1600);
    } catch {
      setCopiedPromptId(null);
      setCopyError("The prompt could not be copied. Try again.");
    }
  };

  return (
    <>
      <section
        ref={libraryRef}
        aria-labelledby="prompt-library-title"
        className="overflow-hidden rounded-[14px] border border-[#d8d8cf] bg-[#fbfbf6] shadow-[0_8px_28px_rgba(23,23,19,0.05)] dark:border-[#2d2d28] dark:bg-[#12120f] dark:shadow-none"
      >
        <div
          className="border-b border-[#deded5] px-4 py-4 dark:border-[#292925] sm:px-5"
          data-testid="prompt-library-header"
        >
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2
                  id="prompt-library-title"
                  className="text-xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white"
                >
                  Prompt library
                </h2>
                <span className="text-xs font-medium text-[#77776f] dark:text-[#92928a]">
                  {prompts.length} {prompts.length === 1 ? "prompt" : "prompts"}
                </span>
              </div>
              <p className="mt-1 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">
                Saved instructions available from the floating paste menu.
              </p>
            </div>
            <button
              ref={addPromptButtonRef}
              type="button"
              aria-haspopup="dialog"
              aria-expanded={isEditorOpen}
              aria-label="Add prompt manually"
              title={workspaceId ? "Add prompt" : "Select a workspace to add a prompt"}
              disabled={!workspaceId}
              onClick={openPromptEditor}
              className="inline-flex h-9 w-fit shrink-0 items-center justify-center gap-2 rounded-lg border border-[#9aae35] bg-[#d9ff68] px-3 text-xs font-semibold text-[#171713] transition-colors hover:bg-[#e4ff94] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7e922a] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-45 dark:border-[#d9ff68]/65 dark:focus-visible:ring-[#d9ff68] dark:focus-visible:ring-offset-[#12120f]"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              New prompt
            </button>
          </div>
        </div>

        <div className="grid min-h-[27rem] gap-0 lg:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col border-b border-[#deded5] dark:border-[#292925] lg:border-b-0 lg:border-r">
            <div className="flex min-h-14 items-center justify-between gap-3 border-b border-[#deded5] px-4 py-3 dark:border-[#292925]">
              <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-[#55554e] dark:text-[#c8c8c0]">
                Saved prompts
              </h3>
              {promptsQuery.isFetching && prompts.length ? (
                <span className="inline-flex shrink-0 items-center gap-1.5 text-[10px] text-[#85857d]">
                  <LoaderCircle className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  Syncing
                </span>
              ) : null}
            </div>

            <div className="min-h-0 flex-1">
              {promptsQuery.isLoading && !prompts.length ? (
                <div role="status" className="m-4 flex min-h-32 items-center justify-center border border-dashed border-[#d4d4ca] text-sm text-[#77776f] dark:border-white/10 dark:text-[#92928a]">
                  Loading saved prompts…
                </div>
              ) : promptsQuery.isError && !prompts.length ? (
                <div className="m-4 border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-100">
                  <p className="font-semibold">Prompt history could not be loaded</p>
                  <p className="mt-1 text-xs leading-5 opacity-75">
                    {promptsQuery.error?.message || "Try refreshing the project."}
                  </p>
                </div>
              ) : !prompts.length ? (
                <div className="m-4 flex min-h-32 flex-col items-center justify-center border border-dashed border-[#d4d4ca] px-5 text-center dark:border-white/10">
                  <p className="text-sm font-semibold text-[#3e3e37] dark:text-[#e2e2da]">
                    No saved prompts yet
                  </p>
                  <p className="mt-1 max-w-xs text-xs leading-5 text-[#7b7b73] dark:text-[#8f8f87]">
                    Choose New prompt or paste one directly into the floating menu.
                  </p>
                </div>
              ) : (
                <ul
                  className="max-h-[22.5rem] overflow-y-auto"
                  aria-label="Saved reusable prompts"
                >
                  {prompts.map((prompt) => {
                    const isSelected = selectedPrompt?.id === prompt.id;
                    const preview = promptPreview(prompt.content);
                    return (
                      <li key={prompt.id}>
                        <button
                          type="button"
                          aria-label={`Select prompt: ${promptTitle(prompt.content)}`}
                          aria-pressed={isSelected}
                          onClick={() => {
                            setSelectedPromptId(prompt.id);
                            setSavedMessage("");
                            setCopyError("");
                            setCopiedPromptId(null);
                          }}
                          className={`group block w-full border-b border-[#e2e2d9] px-4 py-3 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#93aa34] dark:border-[#292925] dark:focus-visible:ring-[#d9ff68] ${
                            isSelected
                              ? "bg-[#f3f5e9] shadow-[inset_3px_0_0_#9aae35] dark:bg-[#d9ff68]/[0.07] dark:shadow-[inset_3px_0_0_#d9ff68]"
                              : "bg-transparent hover:bg-white dark:hover:bg-white/[0.035]"
                          }`}
                        >
                          <span className="block truncate text-sm font-semibold text-[#2f2f29] dark:text-[#f2f2eb]">
                            {promptTitle(prompt.content)}
                          </span>
                          {preview ? (
                            <span className="mt-1 line-clamp-1 whitespace-pre-wrap break-words text-xs leading-5 text-[#73736b] dark:text-[#9d9d95]">
                              {preview}
                            </span>
                          ) : null}
                          <span className="mt-1.5 block text-[10px] text-[#8d8d84] dark:text-[#7f7f77]">
                            {promptActivity(prompt)}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>

          <div className="flex min-w-0 flex-col">
            {savedMessage ? (
              <p role="status" className="mx-5 mt-5 border border-[#cbdc83] bg-[#f2f8dc] px-3 py-2 text-xs leading-5 text-[#536119] dark:border-[#d9ff68]/20 dark:bg-[#d9ff68]/[0.07] dark:text-[#d9ff68] sm:mx-6">
                {savedMessage}
              </p>
            ) : null}
            {deletePrompt.error ? (
              <p role="alert" className="mx-5 mt-5 border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-300 sm:mx-6">
                {deletePrompt.error.message || "The prompt could not be deleted."}
              </p>
            ) : null}
            {copyError ? (
              <p role="alert" className="mx-5 mt-5 border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-300 sm:mx-6">
                {copyError}
              </p>
            ) : null}

            {selectedPrompt ? (
              <article aria-label="Selected prompt" className="min-h-0 p-5 sm:p-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h3 className="text-lg font-semibold tracking-[-0.02em] text-[#24241f] dark:text-white">
                      {promptTitle(selectedPrompt.content)}
                    </h3>
                    <p className="mt-1 text-[11px] text-[#88887f] dark:text-[#85857d]">
                      {promptActivity(selectedPrompt)}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      aria-label={`Copy prompt: ${promptTitle(selectedPrompt.content)}`}
                      title="Copy prompt"
                      onClick={copySelectedPrompt}
                      className="inline-flex h-9 items-center gap-2 rounded-lg border border-[#d4d4ca] bg-white px-3 text-xs font-semibold text-[#42423b] transition-colors hover:border-[#a7a79d] hover:bg-[#f7f7f2] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#93aa34] dark:border-white/10 dark:bg-white/[0.04] dark:text-[#deded6] dark:hover:bg-white/[0.08] dark:focus-visible:ring-[#d9ff68]"
                    >
                      {copiedPromptId === selectedPrompt.id ? (
                        <Check className="h-3.5 w-3.5" aria-hidden="true" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                      )}
                      {copiedPromptId === selectedPrompt.id ? "Copied" : "Copy"}
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete prompt: ${promptTitle(selectedPrompt.content)}`}
                      title="Delete prompt"
                      disabled={deletePrompt.isPending}
                      onClick={() => removePrompt(selectedPrompt.id)}
                      className="inline-flex h-9 items-center gap-2 rounded-lg border border-[#d4d4ca] bg-transparent px-3 text-xs font-semibold text-[#68685f] transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 disabled:cursor-wait disabled:opacity-40 dark:border-white/10 dark:text-[#aaa9a0] dark:hover:border-red-900/60 dark:hover:bg-red-950/30 dark:hover:text-red-300"
                    >
                      {deletePrompt.isPending
                        && deletePrompt.variables?.promptId === selectedPrompt.id ? (
                          <LoaderCircle className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                        )}
                      Delete
                    </button>
                  </div>
                </div>
                <pre
                  tabIndex={0}
                  className="mt-4 max-h-[21rem] min-h-44 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[#d9d9d0] bg-[#f7f7f3] p-4 font-sans text-sm leading-6 text-[#33332d] outline-none focus-visible:ring-2 focus-visible:ring-[#93aa34] dark:border-white/10 dark:bg-black/20 dark:text-[#e7e7df] dark:focus-visible:ring-[#d9ff68]"
                >
                  {selectedPrompt.content}
                </pre>
              </article>
            ) : (
              <div className="m-5 flex min-h-48 flex-1 flex-col items-center justify-center border border-dashed border-[#d4d4ca] px-6 text-center dark:border-white/10 sm:m-6">
                <p className="text-sm font-semibold text-[#3e3e37] dark:text-[#e2e2da]">
                  Nothing selected yet
                </p>
                <p className="mt-1 max-w-sm text-xs leading-5 text-[#7b7b73] dark:text-[#8f8f87]">
                  Add a prompt to view its full text here.
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
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 px-4 py-6 backdrop-blur-[3px]"
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
        className="w-full max-w-2xl overflow-hidden rounded-[14px] border border-[#d8d8cf] bg-[#fbfbf6] shadow-[0_24px_70px_rgba(0,0,0,0.32)] dark:border-[#393934] dark:bg-[#0b0b09]"
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
              className="min-h-64 w-full resize-y rounded-lg border border-[#d4d4ca] bg-white px-4 py-3 text-sm leading-6 text-[#22221e] outline-none transition placeholder:text-[#9a9a91] focus:border-[#93aa34] focus:ring-2 focus:ring-[#d9ff68]/25 disabled:cursor-wait disabled:opacity-60 dark:border-white/10 dark:bg-black/20 dark:text-white dark:placeholder:text-white/35 dark:focus:border-[#d9ff68]/60"
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
                className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border border-[#9aae35] bg-[#d9ff68] px-3 text-xs font-semibold text-[#171713] transition-colors hover:bg-[#e4ff94] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7e922a] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-45 dark:border-[#d9ff68]/65 dark:focus-visible:ring-[#d9ff68] dark:focus-visible:ring-offset-[#0b0b09]"
              >
                {isPending ? (
                  <LoaderCircle className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                ) : (
                  <Check className="h-4 w-4" strokeWidth={2.5} aria-hidden="true" />
                )}
                {isPending ? "Saving" : "Save prompt"}
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

function promptPreview(content) {
  const lines = String(content || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length <= 1) return "";
  const preview = lines.slice(1).join(" ");
  return preview.length > 120 ? `${preview.slice(0, 117)}…` : preview;
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
