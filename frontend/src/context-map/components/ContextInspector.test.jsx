import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ContextInspector from "./ContextInspector";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { get: vi.fn() },
}));

const card = {
  id: "component:1",
  title: "Codex session · …08252",
  summary: "The user asked for a factual graph rebuild.",
  why_it_matters: "It defines the requested graph change.",
  next_action: "Inspect the source before relying on it.",
  status: "needs_review",
  confidence: 0.82,
  authority_weight: 0.6,
  attention_score: 80,
  category: "agent_session",
  classification: { reason: "Explicit session root from an imported AI-session source." },
  workspace_relevance: { status: "unknown", reasons: ["No repository match is available."] },
  session: {
    session_id: "019f4cfe-f6d7-7a80-b727-c3011aa08252",
    tool: "codex",
    model: "gpt-5",
    cwd: "/repo/context-engine",
    branch: "codex/graph-truth",
    message_count: 24,
  },
  source_ids: ["source-1"],
  provenance: [{
    source_document_id: "source-1",
    source_type: "Agent session",
    source_label: "Codex graph task",
    revision_number: 1,
    verification_status: "needs_review",
    excerpt: "User: make the graph factual and inspectable.",
  }],
};

describe("ContextInspector", () => {
  beforeEach(() => {
    api.get.mockReset();
    Object.defineProperty(globalThis.navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("explains why delivery evidence cannot be prepared as a task", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    render(
      <ContextInspector
        card={{ ...card, type: "task", category: "pull_request", session: null }}
        cards={[card]}
        onClose={() => {}}
        prepareUnavailableReason="Pull requests are delivery evidence. Prepare from a linked issue, task, decision, requirement, or blocker."
      />,
    );

    expect(screen.queryByRole("button", { name: "Prepare for agent" })).not.toBeInTheDocument();
    expect(screen.getByText(/Pull requests are delivery evidence/)).toBeInTheDocument();
  });

  it("shows session identity and loads the imported transcript", async () => {
    api.get.mockResolvedValue({ content: "[USER]\nMake the graph factual.\n\n[ASSISTANT]\nI will inspect every source." });
    render(
      <ContextInspector
        card={card}
        cards={[card]}
        workspaceId="00000000-0000-0000-0000-000000000001"
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(card.session.session_id)).toBeInTheDocument();
    expect(screen.getByText("/repo/context-engine")).toBeInTheDocument();
    expect(screen.getByText("No repository match is available.")).toBeInTheDocument();

    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      "/sources/source-1?workspace_id=00000000-0000-0000-0000-000000000001",
    ));
    expect(await screen.findByText(/Make the graph factual/)).toBeInTheDocument();
  });

  it("behaves as a keyboard-closeable modal inspector", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const onClose = vi.fn();
    render(
      <ContextInspector card={card} cards={[card]} workspaceId="workspace-1" onClose={onClose} />,
    );

    const dialog = screen.getByRole("dialog");
    expect(screen.getByRole("button", { name: "Close inspector" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("removes punctuation residue and keeps generic planning copy out of the primary view", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const malformedTask = {
      ...card,
      id: "task-1",
      category: "task",
      session: null,
      title: "Task: , provenance, review queue, evals, and temporal support",
      summary: ", provenance, review queue, evals, and temporal support",
      provenance: [{
        ...card.provenance[0],
        excerpt: ", provenance, review queue, evals, and temporal support",
      }],
    };

    render(<ContextInspector card={malformedTask} cards={[malformedTask]} onClose={() => {}} />);

    expect(screen.getByRole("heading", { name: "Provenance, review queue, evals, and temporal support" })).toBeInTheDocument();
    expect(screen.getByText("provenance, review queue, evals, and temporal support")).toBeInTheDocument();
    expect(screen.queryByText(malformedTask.summary)).not.toBeInTheDocument();
    expect(screen.queryByText("Why it matters")).not.toBeInTheDocument();
    expect(screen.queryByText("Suggested next action")).not.toBeInTheDocument();
    expect(screen.queryByText("Attention")).not.toBeInTheDocument();
    expect(screen.getByText("Raw imported source")).toBeInTheDocument();
  });

  it("shows a concise remote summary without empty provider rows", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const issue = {
      ...card,
      id: "issue-1",
      category: "issue",
      session: null,
      title: "Task: Issue #1: Rewrite README",
      summary: "Issue #1: Rewrite README State: open Labels: none The README undersells the shipped product. Acceptance criteria: explain the current surface.",
      remote_item: {
        kind: "issue",
        repository: "acme/context-engine",
        number: 1,
        title: "Rewrite README",
        observed_status: "open",
      },
      freshness: { status: "unknown" },
      provenance: [{
        ...card.provenance[0],
        source_type: "github",
        source_label: "Rewrite README",
        excerpt: "Exact issue evidence.",
      }],
    };

    render(<ContextInspector card={issue} cards={[issue]} onClose={() => {}} />);

    expect(screen.getByRole("heading", { name: "Issue #1 · Rewrite README" })).toBeInTheDocument();
    expect(screen.getByText("Open issue")).toBeInTheDocument();
    expect(screen.queryByText("Needs review")).not.toBeInTheDocument();
    expect(screen.queryByText(/% confidence/)).not.toBeInTheDocument();
    expect(screen.getByText("The README undersells the shipped product.")).toBeInTheDocument();
    expect(screen.queryByText(/State: open Labels:/)).not.toBeInTheDocument();
    expect(screen.getByText("Issue details")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("Last synced")).toBeInTheDocument();
    expect(screen.getByText("Not recently synced")).toBeInTheDocument();
    expect(screen.getByText("GitHub issue #1")).toBeInTheDocument();
    expect(screen.queryByText("unknown", { exact: false })).not.toBeInTheDocument();
  });

  it("prepares a selected task and exposes factual run scrutiny", async () => {
    api.get.mockResolvedValue({ content: "Structured verification evidence." });
    const onPrepareForAgent = vi.fn().mockResolvedValue({
      markdown: "# Focused agent pack",
      selected_context: [{ id: "one" }, { id: "two" }, { id: "three" }],
      manifest: {
        affected_code: {
          schema_version: "affected_code.v1",
          snapshot: { head_commit: "abc123456", dirty: true },
          files: [{
            path: "app/mcp/server.py",
            role: "likely_implementation",
            match_strength: "possible_match",
            why: "Matches the focused task through runtime, event, to.",
            line_ranges: [{ start_line: 1700, end_line: 1780 }],
            impact_paths: [{
              paths: ["app/mcp/server.py", "app/services/ingest.py"],
              why: "Exact local import.",
            }],
            related_tests: [{
              path: "tests/test_mcp.py",
              why: "Linked by the repository's exact test path.",
            }],
          }],
        },
      },
    });
    const focusedTask = {
      ...card,
      id: "component:00000000-0000-0000-0000-000000000010",
      type: "task",
      category: "task",
      session: null,
      title: "Make runtime writes retry-safe",
      summary: "Add stable runtime event identity.",
    };
    const timeline = {
      state: "verification_failed",
      latest_outcome: { summary: "Implementation claimed complete." },
      findings: [{
        id: "finding-1",
        severity: "critical",
        title: "Required verification failed",
        explanation: "pytest exited with code 1.",
        next_action: "Inspect and rerun the required command.",
        sources: [
          { source_document_id: "source-outcome-1", excerpt: "Claimed completion." },
          { source_document_id: "source-verification-1", excerpt: "Failed required check." },
        ],
      }],
      runs: [{
        run_id: "run-1",
        tool: "codex",
        status: "completed",
        state: "verification_failed",
        started_at: "2026-07-14T12:00:00Z",
        base_commit: "abc123",
        head_commit: "def456",
        events: [{
          event_key: "pytest-1",
          event_type: "verification",
          summary: "Focused tests failed.",
          command: "pytest -q tests/test_mcp.py",
          exit_code: 1,
          observed_at: "2026-07-14T12:10:00Z",
          source_document_id: "source-verification-1",
          verification_results: [{
            command: "pytest -q tests/test_mcp.py",
            status: "failed",
            exit_code: 1,
          }],
        }],
      }],
    };

    render(
      <ContextInspector
        card={focusedTask}
        cards={[focusedTask]}
        onClose={() => {}}
        canPrepareForAgent
        onPrepareForAgent={onPrepareForAgent}
        timeline={timeline}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Prepare for agent" }));
    await waitFor(() => expect(onPrepareForAgent).toHaveBeenCalledOnce());
    await waitFor(() => expect(globalThis.navigator.clipboard.writeText).toHaveBeenCalledWith("# Focused agent pack"));
    const briefStatus = screen.getByRole("status", { name: "Agent brief ready" });
    expect(briefStatus).toHaveTextContent("Copied to your clipboard");
    expect(briefStatus).toHaveTextContent("Nothing was sent to an agent automatically");
    expect(briefStatus).toHaveTextContent("Includes 3 source-backed context items");
    fireEvent.click(screen.getByRole("button", { name: "View brief" }));
    expect(screen.getByText("# Focused agent pack")).toBeInTheDocument();
    expect(screen.getByText(/paste it into the coding agent you want to use/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy again" }));
    await waitFor(() => expect(globalThis.navigator.clipboard.writeText).toHaveBeenCalledTimes(2));
    const affectedCode = screen.getByText("Files to inspect").closest("details");
    expect(affectedCode).not.toHaveAttribute("open");
    expect(screen.getByText("1 possible match · 1 linked test")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Files to inspect"));
    expect(screen.getByText("Suggestions from the task wording. Check them before deciding what to edit.")).toBeInTheDocument();
    expect(screen.getByText("Possible word match")).toBeInTheDocument();
    expect(screen.getByText("Checked against commit abc1234 plus your local changes")).toBeInTheDocument();
    expect(screen.getByText("app/mcp/server.py")).toBeInTheDocument();
    expect(screen.getByText("tests/test_mcp.py")).toBeInTheDocument();
    expect(screen.getByText("Task words found here: runtime, event.")).toBeInTheDocument();
    expect(screen.getByText("Matching code near lines 1700–1780")).toBeInTheDocument();
    expect(screen.getByText("Connected file: app/services/ingest.py")).toBeInTheDocument();
    expect(screen.getByText("Test to check")).toBeInTheDocument();
    expect(screen.getByText("Required verification failed")).toBeInTheDocument();
    expect(screen.getByText("Required verification failed").closest("[data-severity]"))
      .toHaveAttribute("data-severity", "critical");
    expect(screen.getByText("pytest -q tests/test_mcp.py · exit 1")).toBeInTheDocument();
    expect(screen.getByText("pytest -q tests/test_mcp.py · failed · exit 1")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "View evidence 2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View evidence 2" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/sources/source-verification-1"));
    expect((await screen.findAllByText("Structured verification evidence.")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Challenge agent" }));
    await waitFor(() => expect(globalThis.navigator.clipboard.writeText).toHaveBeenLastCalledWith(
      expect.stringContaining("Sources: source-outcome-1, source-verification-1"),
    ));
    expect(screen.getByRole("button", { name: "Challenge copied" })).toBeInTheDocument();
  });

  it("keeps prepare absent for ineligible evidence cards", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    render(<ContextInspector card={card} cards={[card]} onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: "Prepare for agent" })).not.toBeInTheDocument();
  });

  it("does not render an empty affected-code panel", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    render(
      <ContextInspector
        card={{ ...card, type: "task", category: "task" }}
        cards={[card]}
        onClose={() => {}}
        canPrepareForAgent
        timeline={{ runs: [], affected_code: { files: [] } }}
      />,
    );

    expect(screen.queryByText("Files to inspect")).not.toBeInTheDocument();
  });

  it("removes stale timeline affected code when a new pack has no supported match", async () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const onPrepareForAgent = vi.fn().mockResolvedValue({
      markdown: "# Pack with no affected code",
      manifest: {},
    });
    render(
      <ContextInspector
        card={{ ...card, type: "task", category: "task" }}
        cards={[card]}
        onClose={() => {}}
        canPrepareForAgent
        onPrepareForAgent={onPrepareForAgent}
        timeline={{
          runs: [],
          affected_code: {
            snapshot: {},
            files: [{
              path: "app/stale.py",
              role: "likely_implementation",
              why: "From an older pack.",
            }],
          },
        }}
      />,
    );

    expect(screen.getByText("Files to inspect")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Prepare for agent" }));
    await waitFor(() => expect(onPrepareForAgent).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByText("Files to inspect")).not.toBeInTheDocument());
  });

  it("counts a top-level related test as a linked test, not a likely implementation file", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    render(
      <ContextInspector
        card={{ ...card, type: "task", category: "task" }}
        cards={[card]}
        onClose={() => {}}
        canPrepareForAgent
        timeline={{
          runs: [],
          affected_code: {
            snapshot: {},
            files: [{
              path: "tests/test_mcp.py",
              role: "related_test",
              why: "Named explicitly in the focused task.",
            }],
          },
        }}
      />,
    );

    expect(screen.getByText("1 linked test")).toBeInTheDocument();
  });

  it("shows only the first three file suggestions until the user asks for more", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const files = Array.from({ length: 5 }, (_, index) => ({
      path: `app/file_${index + 1}.py`,
      role: "likely_implementation",
      match_strength: "possible_match",
      why: `Name match ${index + 1}.`,
    }));
    render(
      <ContextInspector
        card={{ ...card, type: "task", category: "task" }}
        cards={[card]}
        onClose={() => {}}
        canPrepareForAgent
        timeline={{ runs: [], affected_code: { snapshot: {}, files } }}
      />,
    );

    fireEvent.click(screen.getByText("Files to inspect"));
    expect(screen.getByText("app/file_1.py")).toBeInTheDocument();
    expect(screen.getByText("app/file_3.py")).toBeInTheDocument();
    expect(screen.queryByText("app/file_4.py")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show 2 more" }));
    expect(screen.getByText("app/file_4.py")).toBeInTheDocument();
    expect(screen.getByText("app/file_5.py")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.queryByText("app/file_4.py")).not.toBeInTheDocument();
  });

  it("keeps a prepared pack usable when clipboard access fails", async () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    globalThis.navigator.clipboard.writeText.mockRejectedValueOnce(new Error("denied"));
    const focusedTask = {
      ...card,
      id: "component:00000000-0000-0000-0000-000000000011",
      type: "task",
      category: "task",
      session: null,
    };
    render(
      <ContextInspector
        card={focusedTask}
        cards={[focusedTask]}
        onClose={() => {}}
        canPrepareForAgent
        onPrepareForAgent={vi.fn().mockResolvedValue({ markdown: "# Prepared pack" })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Prepare for agent" }));
    const briefStatus = await screen.findByRole("status", { name: "Agent brief ready" });
    expect(briefStatus).toHaveTextContent(/clipboard access was unavailable/i);
    expect(briefStatus).toHaveTextContent(/Nothing was sent automatically/i);

    globalThis.navigator.clipboard.writeText.mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Copy again" }));
    await waitFor(() => expect(briefStatus).toHaveTextContent("Copied to your clipboard"));
  });

  it("shows durable needs-attention loops even when no agent run exists", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const onUpdateOpenLoop = vi.fn().mockResolvedValue({ status: "resolved" });
    render(
      <ContextInspector
        card={{ ...card, type: "task", category: "task", session: null }}
        cards={[card]}
        onClose={() => {}}
        canPrepareForAgent
        onUpdateOpenLoop={onUpdateOpenLoop}
        timeline={{
          runs: [],
          open_loops: [{
            id: "loop-1",
            status: "open",
            severity: "critical",
            title: "Required verification failed",
            explanation: "The required test exited with code 1.",
          }],
        }}
      />,
    );

    expect(screen.getByText("Unresolved work")).toBeInTheDocument();
    expect(screen.getByText("Required verification failed")).toBeInTheDocument();
    expect(screen.getByText("No agent work recorded yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Challenge agent" })).not.toBeInTheDocument();
  });

  it("shows a compatible verified playbook collapsed after affected code", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    render(
      <ContextInspector
        card={{ ...card, type: "task", category: "task", session: null }}
        cards={[card]}
        onClose={() => {}}
        canPrepareForAgent
        timeline={{
          runs: [],
          affected_code: { snapshot: {}, files: [{ path: "app/service.py", role: "likely_implementation" }] },
          known_playbook: {
            id: "playbook-1",
            title: "Add a source-backed connector",
            status: "approved",
            verified_run_count: 2,
            last_verified_at: "2026-07-14T10:00:00Z",
            ordered_steps: ["Store the raw source revision first.", "Run the focused connector test."],
            verification_commands: ["pytest -q tests/test_connectors.py"],
          },
        }}
      />,
    );

    const affected = screen.getByText("Files to inspect").closest("details");
    const playbook = screen.getByText("Verified playbook").closest("details");
    expect(playbook).not.toHaveAttribute("open");
    expect(affected.compareDocumentPosition(playbook) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByText("Verified playbook"));
    expect(screen.getByText("Included in the latest agent pack")).toBeInTheDocument();
    expect(screen.getByText(/Verified from 2 successful runs · last checked/)).toBeInTheDocument();
    expect(screen.getByText("Store the raw source revision first.")).toBeInTheDocument();
    expect(screen.getByText("pytest -q tests/test_connectors.py")).toBeInTheDocument();
  });

  it("clears a prepared playbook when a newer context revision has none", async () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const focusedTask = { ...card, type: "task", category: "task", session: null };
    const onPrepareForAgent = vi.fn().mockResolvedValue({
      markdown: "# Pack",
      manifest: {
        known_playbook: {
          id: "playbook-old",
          title: "Old verified playbook",
          status: "approved",
        },
      },
    });
    const { rerender } = render(
      <ContextInspector
        card={focusedTask}
        cards={[focusedTask]}
        onClose={() => {}}
        canPrepareForAgent
        onPrepareForAgent={onPrepareForAgent}
        contextRevision="revision-1"
        timeline={{ runs: [] }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Prepare for agent" }));
    expect(await screen.findByText("Verified playbook")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Verified playbook"));
    expect(screen.getByText("Included in this agent pack")).toBeInTheDocument();
    rerender(
      <ContextInspector
        card={focusedTask}
        cards={[focusedTask]}
        onClose={() => {}}
        canPrepareForAgent
        onPrepareForAgent={onPrepareForAgent}
        contextRevision="revision-2"
        timeline={{ runs: [] }}
      />,
    );
    await waitFor(() => expect(screen.queryByText("Verified playbook")).not.toBeInTheDocument());
  });

  it("does not imply that an incompatible playbook was included", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    render(
      <ContextInspector
        card={{ ...card, type: "task", category: "task", session: null }}
        cards={[card]}
        onClose={() => {}}
        canPrepareForAgent
        timeline={{
          runs: [],
          known_playbook: {
            id: "playbook-stale",
            title: "Old repository procedure",
            status: "stale",
            compatible: false,
          },
        }}
      />,
    );

    expect(screen.getByText("Not included — last verified before the current code snapshot")).toBeInTheDocument();
  });
});
