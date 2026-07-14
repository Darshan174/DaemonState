from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.processing.extractor import ExtractedFact, ExtractedRelationship


def extract_local_repository(content: str, metadata: dict) -> list[ExtractedFact]:
    """Project source → deterministic repository and top-level area facts."""
    repository = metadata.get("repository") if isinstance(metadata, dict) else None
    areas = metadata.get("areas", []) if isinstance(metadata, dict) else []
    if not isinstance(repository, dict) or not isinstance(areas, list):
        return []
    root_name = str(repository.get("name") or "Project").strip() or "Project"
    root_summary = str(repository.get("summary") or "").strip()
    if not root_summary or root_summary not in content:
        return []
    provenance = json.dumps({
        "source_type": "local_repository",
        "repo_root": repository.get("repo_root"),
        "head_commit": repository.get("head_commit"),
        "extraction": "deterministic_inventory",
    }, sort_keys=True)
    root_fact_name = f"Repository: {root_name}"
    facts = [ExtractedFact(
        model_name="Repo",
        name=root_fact_name,
        value=root_summary,
        fact_type="repo_root",
        confidence=1.0,
        temporal="current",
        temporal_hint="current",
        provenance=provenance,
        excerpt=root_summary,
    )]
    for area in areas[:9]:
        if not isinstance(area, dict):
            continue
        label = str(area.get("label") or "").strip()
        summary = str(area.get("summary") or "").strip()
        if not label or not summary or summary not in content:
            continue
        facts.append(ExtractedFact(
            model_name="Repo",
            name=f"Area: {label}",
            value=summary,
            fact_type="code_area",
            confidence=1.0,
            temporal="current",
            temporal_hint="current",
            relationships=[ExtractedRelationship(
                target_name=root_fact_name,
                relationship_type="part_of",
                confidence=1.0,
                evidence=summary,
            )],
            provenance=provenance,
            excerpt=summary,
        ))
    return facts


@dataclass
class GitHubIssueData:
    title: str
    body: str = ""
    state: str = "open"
    number: int = 0
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    milestone: str | None = None
    comments: list[str] = field(default_factory=list)
    html_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    closed_at: str | None = None
    user: str | None = None


@dataclass
class GitHubPRData:
    title: str
    body: str = ""
    state: str = "open"
    number: int = 0
    merged: bool = False
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    milestone: str | None = None
    changed_files: list[str] = field(default_factory=list)
    review_comments: list[str] = field(default_factory=list)
    linked_issues: list[int] = field(default_factory=list)
    linked_issue_refs: list[GitHubIssueReference] = field(default_factory=list)
    html_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    closed_at: str | None = None
    merged_at: str | None = None
    draft: bool = False
    user: str | None = None


@dataclass(frozen=True)
class GitHubIssueReference:
    number: int
    repo_full_name: str | None = None


@dataclass
class AgentSessionData:
    session_id: str = ""
    tool: str = ""
    model: str = ""
    branch: str = ""
    commit: str = ""
    author: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    source_path: str | None = None
    source_url: str | None = None
    title: str = ""
    content: str = ""


def extract_github_issue(doc_content: str, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    try:
        data = json.loads(doc_content)
    except (json.JSONDecodeError, TypeError):
        return _extract_github_issue_text(doc_content, doc_metadata)

    if isinstance(data, list):
        results: list[ExtractedFact] = []
        for item in data:
            results.extend(_extract_single_github_issue(item, doc_metadata))
        return results

    return _extract_single_github_issue(data, doc_metadata)


def _extract_single_github_issue(data: dict, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    authoritative = doc_metadata or {}
    data = {**data, **{
        key: value for key, value in authoritative.items()
        if key in {
            "title", "body", "state", "number", "labels", "assignees",
            "created_at", "updated_at", "closed_at",
        } and value is not None
    }}
    issue = GitHubIssueData(
        title=data.get("title", ""),
        body=data.get("body", "") or "",
        state=data.get("state", "open"),
        number=data.get("number", 0),
        labels=data.get("labels", []),
        assignees=data.get("assignees", []),
        milestone=data.get("milestone", {}),
        comments=data.get("comments", []),
        html_url=data.get("html_url"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        closed_at=data.get("closed_at"),
        user=data.get("user", {}).get("login") if isinstance(data.get("user"), dict) else data.get("user"),
    )
    return _build_github_issue_facts(issue, doc_metadata)


def _extract_github_issue_text(content: str, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    meta = doc_metadata or {}
    title_match = re.search(r"(?:^|\n)#\s*(.+?)(?:\n|$)", content)
    title = title_match.group(1).strip() if title_match else content[:120].strip()

    state = str(meta.get("state") or ("closed" if re.search(r"\b(closed|resolved|fixed)\b", content, re.IGNORECASE) else "open"))
    issue = GitHubIssueData(
        title=str(meta.get("title") or title),
        body=content,
        state=state,
        number=_safe_int(meta.get("number")),
        labels=meta.get("labels", []),
        assignees=meta.get("assignees", []),
        html_url=meta.get("html_url") or meta.get("source_url"),
        created_at=meta.get("created_at"),
        updated_at=meta.get("updated_at"),
        closed_at=meta.get("closed_at"),
        user=meta.get("author"),
    )
    return _build_github_issue_facts(issue, doc_metadata)


def _build_github_issue_facts(issue: GitHubIssueData, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []

    state_temporal = "past" if issue.state == "closed" else "current"
    issue_name = f"Issue #{issue.number}: {issue.title}" if issue.number else f"Issue: {issue.title}"
    issue_value = issue.body[:500] if issue.body else issue.title

    provenance = json.dumps({"source_type": "github_issue", "number": issue.number, "url": issue.html_url, "state": issue.state, "updated_at": issue.updated_at, "closed_at": issue.closed_at})

    facts.append(ExtractedFact(
        model_name="Issue",
        name=issue_name,
        value=issue_value,
        fact_type="issue",
        confidence=0.92,
        temporal=state_temporal,
        temporal_hint=state_temporal,
        relationships=[],
        provenance=provenance,
        excerpt=issue.body[:300] if issue.body else issue.title,
    ))

    if issue.labels:
        label_names = (
            issue.labels
            if isinstance(issue.labels[0], str)
            else [label.get("name", "") for label in issue.labels if isinstance(label, dict)]
        )
        for label in label_names[:5]:
            lower_label = label.lower()
            if any(w in lower_label for w in ("bug", "error", "crash", "fail")):
                facts.append(ExtractedFact(
                    model_name="Issue",
                    name=f"Bug: {issue.title[:80]}",
                    value=f"Bug report labeled {label}: {issue.title}",
                    fact_type="blocker",
                    confidence=0.88,
                    temporal="current",
                    temporal_hint="current",
                    relationships=[ExtractedRelationship(
                        target_name=issue_name,
                        relationship_type="part_of",
                        confidence=0.95,
                        evidence=f"Issue #{issue.number} labeled as {label}",
                    )],
                    provenance=provenance,
                    excerpt=f"Label: {label}",
                ))
            elif any(w in lower_label for w in ("feature", "enhancement", "request")):
                facts.append(ExtractedFact(
                    model_name="Feature",
                    name=f"Feature request: {issue.title[:80]}",
                    value=f"Feature request labeled {label}: {issue.title}",
                    fact_type="feature",
                    confidence=0.85,
                    temporal="future",
                    temporal_hint="future",
                    relationships=[ExtractedRelationship(
                        target_name=issue_name,
                        relationship_type="part_of",
                        confidence=0.92,
                        evidence=f"Issue #{issue.number} labeled as {label}",
                    )],
                    provenance=provenance,
                    excerpt=f"Label: {label}",
                ))

    if issue.body:
        body_facts = _extract_issue_body_facts(issue, provenance)
        for bf in body_facts:
            bf.relationships.append(ExtractedRelationship(
                target_name=issue_name,
                relationship_type="part_of",
                confidence=0.9,
                evidence=f"Extracted from issue #{issue.number}",
            ))
        facts.extend(body_facts)

    return facts


def _extract_issue_body_facts(issue: GitHubIssueData, provenance: str) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    content = issue.body
    if not content:
        return facts
    issue_temporal = "past" if issue.state == "closed" or issue.closed_at else "current"

    for m in re.finditer(r"(?:decision|decided|we chose|we will use)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text:
            facts.append(ExtractedFact(
                model_name="Decision", name=f"Decision: {text[:120]}",
                value=text, fact_type="decision", confidence=0.82,
                temporal=issue_temporal, temporal_hint=issue_temporal,
                provenance=provenance, excerpt=text[:300],
            ))

    for m in re.finditer(r"(?:action item|todo|task|action|follow.?up)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text:
            facts.append(ExtractedFact(
                model_name="Task", name=f"Task: {text[:120]}",
                value=text, fact_type="task", confidence=0.78,
                temporal=issue_temporal, temporal_hint=issue_temporal,
                provenance=provenance, excerpt=text[:300],
            ))

    for m in re.finditer(r"(?:blocker|blocked by|risk|concern|dependency risk)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text:
            facts.append(ExtractedFact(
                model_name="Risk", name=f"Risk: {text[:120]}",
                value=text, fact_type="blocker", confidence=0.85,
                temporal=issue_temporal, temporal_hint=issue_temporal,
                provenance=provenance, excerpt=text[:300],
            ))

    return facts


def extract_github_pr(doc_content: str, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    try:
        data = json.loads(doc_content)
    except (json.JSONDecodeError, TypeError):
        return _extract_github_pr_text(doc_content, doc_metadata)

    if isinstance(data, list):
        results: list[ExtractedFact] = []
        for item in data:
            results.extend(_extract_single_github_pr(item, doc_metadata))
        return results

    return _extract_single_github_pr(data, doc_metadata)


def _extract_single_github_pr(data: dict, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    authoritative = doc_metadata or {}
    data = {**data, **{
        key: value for key, value in authoritative.items()
        if key in {
            "title", "body", "state", "number", "merged", "draft", "labels",
            "assignees", "created_at", "updated_at", "closed_at", "merged_at",
        } and value is not None
    }}
    changed_files_raw = data.get("changed_files", [])
    if isinstance(changed_files_raw, list) and changed_files_raw and isinstance(changed_files_raw[0], dict):
        changed_files = [f.get("filename", "") for f in changed_files_raw if f.get("filename")]
    else:
        changed_files = changed_files_raw if isinstance(changed_files_raw, list) else []

    body_text = data.get("body", "") or ""
    linked_issue_refs = _extract_github_issue_references(
        body_text,
        data.get("linked_issues", []),
    )
    linked_issues = list(dict.fromkeys(ref.number for ref in linked_issue_refs))

    pr = GitHubPRData(
        title=data.get("title", ""),
        body=body_text,
        state=data.get("state", "open"),
        number=data.get("number", 0),
        merged=data.get("merged", False),
        labels=data.get("labels", []),
        assignees=data.get("assignees", []),
        milestone=data.get("milestone"),
        changed_files=changed_files,
        review_comments=data.get("review_comments", []),
        linked_issues=linked_issues,
        linked_issue_refs=linked_issue_refs,
        html_url=data.get("html_url"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        closed_at=data.get("closed_at"),
        merged_at=data.get("merged_at"),
        draft=bool(data.get("draft", False)),
        user=data.get("user", {}).get("login") if isinstance(data.get("user"), dict) else data.get("user"),
    )
    return _build_github_pr_facts(pr, doc_metadata)


def _extract_github_pr_text(content: str, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    meta = doc_metadata or {}
    title_match = re.search(r"(?:^|\n)#\s*(.+?)(?:\n|$)", content)
    title = title_match.group(1).strip() if title_match else content[:120].strip()

    merged = bool(meta.get("merged", re.search(r"\b(merged|merged into)\b", content, re.IGNORECASE)))
    pr = GitHubPRData(
        title=str(meta.get("title") or title),
        body=content,
        state=str(meta.get("state") or "open"),
        number=_safe_int(meta.get("number")),
        merged=merged,
        labels=meta.get("labels", []),
        assignees=meta.get("assignees", []),
        html_url=meta.get("html_url") or meta.get("source_url"),
        created_at=meta.get("created_at"),
        updated_at=meta.get("updated_at"),
        closed_at=meta.get("closed_at"),
        merged_at=meta.get("merged_at"),
        draft=bool(meta.get("draft", False)),
        user=meta.get("author"),
    )
    pr.linked_issue_refs = _extract_github_issue_references(
        content,
        meta.get("linked_issues", []),
    )
    pr.linked_issues = list(dict.fromkeys(ref.number for ref in pr.linked_issue_refs))
    return _build_github_pr_facts(pr, doc_metadata)


def _build_github_pr_facts(pr: GitHubPRData, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []

    state_temporal = "past" if pr.merged or pr.state == "closed" else "current"
    pr_name = f"PR #{pr.number}: {pr.title}" if pr.number else f"PR: {pr.title}"
    pr_value = pr.body[:500] if pr.body else pr.title

    provenance = json.dumps({
        "source_type": "github_pr",
        "number": pr.number,
        "url": pr.html_url,
        "state": pr.state,
        "merged": pr.merged,
        "draft": pr.draft,
        "updated_at": pr.updated_at,
        "closed_at": pr.closed_at,
        "merged_at": pr.merged_at,
    })

    facts.append(ExtractedFact(
        model_name="PR",
        name=pr_name,
        value=pr_value,
        fact_type="pr",
        confidence=0.92,
        temporal=state_temporal,
        temporal_hint=state_temporal,
        relationships=[],
        provenance=provenance,
        excerpt=pr.body[:300] if pr.body else pr.title,
    ))

    pr_fact = facts[0]

    issue_refs = pr.linked_issue_refs or [
        GitHubIssueReference(number=issue_num) for issue_num in pr.linked_issues
    ]
    for issue_ref in issue_refs:
        issue_num = issue_ref.number
        qualified_ref = (
            f"{issue_ref.repo_full_name}#{issue_num}"
            if issue_ref.repo_full_name
            else f"#{issue_num}"
        )
        is_fix = _is_fix_reference(
            pr.body,
            issue_num,
            repo_full_name=issue_ref.repo_full_name,
        )
        if is_fix:
            pr_fact.relationships.append(ExtractedRelationship(
                target_name=f"Issue {qualified_ref}",
                relationship_type="fixes",
                confidence=0.95,
                evidence=_build_fixes_evidence(
                    pr.number,
                    issue_num,
                    pr.body,
                    repo_full_name=issue_ref.repo_full_name,
                ),
            ))
        else:
            pr_fact.relationships.append(ExtractedRelationship(
                target_name=f"Issue {qualified_ref}",
                relationship_type="mentions",
                confidence=0.75,
                evidence=f"PR #{pr.number} references {qualified_ref}",
            ))

    for filename in pr.changed_files[:10]:
        file_name = f"File: {filename}"
        facts.append(ExtractedFact(
            model_name="Repo",
            name=file_name,
            value=f"Changed in PR #{pr.number}: {pr.title}",
            fact_type="changed_file",
            confidence=0.90,
            temporal=state_temporal,
            temporal_hint=state_temporal,
            relationships=[],
            provenance=provenance,
            excerpt=f"Changed file: {filename}",
        ))
        pr_fact.relationships.append(ExtractedRelationship(
            target_name=file_name,
            relationship_type="touches_file",
            confidence=0.92,
            evidence=f"File {filename} changed in PR #{pr.number}",
        ))

    for comment in pr.review_comments[:5]:
        comment_text = comment if isinstance(comment, str) else str(comment)
        if not comment_text.strip():
            continue
        is_blocking = _is_explicit_block(comment_text)
        if is_blocking:
            facts.append(ExtractedFact(
                model_name="Risk",
                name=f"Review finding: {comment_text[:80]}",
                value=comment_text[:500],
                fact_type="review_finding",
                confidence=0.85,
                temporal="current",
                temporal_hint="current",
                relationships=[ExtractedRelationship(
                    target_name=pr_name,
                    relationship_type="blocks",
                    confidence=0.85,
                    evidence=f"Review on PR #{pr.number} explicitly requests changes: {comment_text[:100]}",
                )],
                provenance=provenance,
                excerpt=comment_text[:300],
            ))
        elif any(w in comment_text.lower() for w in ("bug", "issue", "problem", "fix", "broken", "concern")):
            facts.append(ExtractedFact(
                model_name="Risk",
                name=f"Review finding: {comment_text[:80]}",
                value=comment_text[:500],
                fact_type="review_finding",
                confidence=0.75,
                temporal="current",
                temporal_hint="current",
                relationships=[ExtractedRelationship(
                    target_name=pr_name,
                    relationship_type="mentions",
                    confidence=0.70,
                    evidence=f"Review comment on PR #{pr.number}",
                )],
                provenance=provenance,
                excerpt=comment_text[:300],
            ))

    if pr.body:
        body_facts = _extract_pr_body_facts(pr, provenance)
        for bf in body_facts:
            bf.relationships.append(ExtractedRelationship(
                target_name=pr_name,
                relationship_type="part_of",
                confidence=0.88,
                evidence=f"Extracted from PR #{pr.number}",
            ))
        facts.extend(body_facts)

    return facts


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_pr_body_facts(pr: GitHubPRData, provenance: str) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    content = pr.body
    if not content:
        return facts

    for m in re.finditer(r"(?:decision|decided|we chose|we will use)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text:
            facts.append(ExtractedFact(
                model_name="Decision", name=f"Decision: {text[:120]}",
                value=text, fact_type="decision", confidence=0.82,
                temporal="current", temporal_hint="current",
                provenance=provenance, excerpt=text[:300],
            ))

    for m in re.finditer(r"(?:todo|task|action|follow.?up)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text:
            facts.append(ExtractedFact(
                model_name="Task", name=f"Task: {text[:120]}",
                value=text, fact_type="task", confidence=0.78,
                temporal="current", temporal_hint="current",
                provenance=provenance, excerpt=text[:300],
            ))

    return facts


def extract_agent_session(content: str, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    meta = doc_metadata or {}
    session = AgentSessionData(
        session_id=meta.get("session_id", ""),
        tool=meta.get("tool", meta.get("agent_tool", "")),
        model=meta.get("model", meta.get("agent_model", "")),
        branch=meta.get("branch", ""),
        commit=meta.get("commit", ""),
        author=meta.get("author", ""),
        started_at=meta.get("started_at", meta.get("created_at")),
        ended_at=meta.get("ended_at", meta.get("updated_at")),
        source_path=meta.get("source_path", meta.get("file_path", meta.get("filename"))),
        source_url=meta.get("source_url"),
        title=meta.get("title", ""),
        content=content,
    )

    if not session.title:
        first_line = content.strip().split("\n")[0] if content.strip() else ""
        title_match = re.match(r"^#+\s*(.+?)(?:\n|$)", first_line)
        session.title = title_match.group(1).strip() if title_match else first_line[:120]

    facts: list[ExtractedFact] = []

    session_provenance = json.dumps({
        "source_type": "agent_session",
        "session_id": session.session_id,
        "tool": session.tool,
        "model": session.model,
        "branch": session.branch,
        "commit": session.commit,
        "author": session.author,
    })

    session_name = f"Session: {session.tool} {session.title[:60]}".strip()
    session_value = content[:500] if content else session.title

    facts.append(ExtractedFact(
        model_name="Agent Session",
        name=session_name,
        value=session_value,
        fact_type="session_root",
        confidence=0.93,
        temporal="current",
        temporal_hint="current",
        relationships=[],
        provenance=session_provenance,
        excerpt=content[:300] if content else session.title,
    ))

    extraction_content = _agent_session_signal_text(content)

    task_items = _extract_session_tasks(extraction_content, session_provenance)
    for task in task_items:
        task.relationships.append(ExtractedRelationship(
            target_name=session_name,
            relationship_type="generated_by_agent",
            confidence=0.90,
            evidence="Task extracted from agent session",
        ))
    facts.extend(task_items)

    decision_items = _extract_session_decisions(extraction_content, session_provenance)
    for dec in decision_items:
        dec.relationships.append(ExtractedRelationship(
            target_name=session_name,
            relationship_type="generated_by_agent",
            confidence=0.88,
            evidence="Decision extracted from agent session",
        ))
    facts.extend(decision_items)

    risk_items = _extract_session_risks(extraction_content, session_provenance)
    for risk in risk_items:
        risk.relationships.append(ExtractedRelationship(
            target_name=session_name,
            relationship_type="generated_by_agent",
            confidence=0.85,
            evidence="Risk/blocker extracted from agent session",
        ))
    facts.extend(risk_items)

    file_refs = _extract_session_file_refs(extraction_content, session_provenance)
    for ref in file_refs:
        ref.relationships.append(ExtractedRelationship(
            target_name=session_name,
            relationship_type="part_of",
            confidence=0.80,
            evidence="File reference in agent session",
        ))
    facts.extend(file_refs)

    return facts


def _extract_session_tasks(content: str, provenance: str) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    seen: set[str] = set()

    for m in re.finditer(r"^\s*[-*]\s+(.+?)$", content, re.MULTILINE):
        text = _clean_session_fact_text(m.group(1))
        if not _is_extractable_session_fact(text):
            continue
        first_word = text.split()[0].rstrip(":").lower() if text.split() else ""
        if first_word in ("next", "step", "todo", "action", "task", "follow"):
            cleaned = re.sub(r"^\s*\d+[\.\)]\s*", "", text).strip()
            if cleaned and len(cleaned) > 5 and cleaned not in seen:
                seen.add(cleaned)
                facts.append(ExtractedFact(
                    model_name="Task", name=f"Task: {cleaned[:120]}",
                    value=cleaned, fact_type="task", confidence=0.75,
                    temporal="future", temporal_hint="future",
                    provenance=provenance, excerpt=cleaned[:300],
                ))

    for m in re.finditer(r"^\s*(?:next step|todo|action item|task|follow.?up)\s*:?\s*(.+?)\s*$", content, re.MULTILINE | re.IGNORECASE):
        text = _clean_session_fact_text(m.group(1))
        if _is_extractable_session_fact(text) and text not in seen:
            seen.add(text)
            facts.append(ExtractedFact(
                model_name="Task", name=f"Task: {text[:120]}",
                value=text, fact_type="task", confidence=0.78,
                temporal="future", temporal_hint="future",
                provenance=provenance, excerpt=text[:300],
            ))

    return facts


def _extract_session_decisions(content: str, provenance: str) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    seen: set[str] = set()

    decision_patterns = [
        r"^\s*(?:decision|decided|we decided(?:\s+to)?|we chose|we will use|recommendation|verdict)\s*:?\s*(.+?)\s*$",
    ]
    for pattern in decision_patterns:
        for m in re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE):
            text = _clean_session_fact_text(m.group(1))
            if _is_extractable_session_fact(text) and text not in seen:
                seen.add(text)
                facts.append(ExtractedFact(
                    model_name="Decision", name=f"Decision: {text[:120]}",
                    value=text, fact_type="decision", confidence=0.82,
                    temporal="current", temporal_hint="current",
                    provenance=provenance, excerpt=text[:300],
                ))

    for m in re.finditer(r"^#+\s*(?:final|decision|summary|conclusion)\b(.*)$", content, re.MULTILINE | re.IGNORECASE):
        start = m.end()
        end = content.find("\n#", start)
        section = content[start:end].strip() if end != -1 else content[start:].strip()
        section = _clean_session_fact_text(section)
        summary = section[:200].strip()
        if _is_extractable_session_fact(summary) and summary not in seen:
            seen.add(summary)
            facts.append(ExtractedFact(
                model_name="Decision", name=f"Session decision: {summary[:80]}",
                value=section[:500], fact_type="decision", confidence=0.80,
                temporal="current", temporal_hint="current",
                provenance=provenance, excerpt=summary[:300],
            ))

    return facts


def _extract_session_risks(content: str, provenance: str) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    seen: set[str] = set()

    risk_patterns = [
        r"^\s*(blocker|blocked by|risk|concern|unresolved question|open question|failed)\s*:?\s*(.+?)\s*$",
    ]
    for pattern in risk_patterns:
        for m in re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE):
            label = m.group(1).lower()
            text = _clean_session_fact_text(m.group(2))
            if _is_extractable_session_fact(text) and text not in seen:
                seen.add(text)
                is_blocker = label in {"blocker", "blocked by", "failed"}
                temporal = "past" if label == "failed" or "failed" in text.lower() else "current"
                prefix = "Blocker" if is_blocker else "Risk"
                facts.append(ExtractedFact(
                    model_name="Risk", name=f"{prefix}: {text[:120]}",
                    value=text, fact_type="blocker" if is_blocker else "risk", confidence=0.82,
                    temporal=temporal, temporal_hint=temporal,
                    provenance=provenance, excerpt=text[:300],
                ))

    return facts


def _agent_session_signal_text(content: str) -> str:
    role_re = re.compile(r"^\[(?P<role>[A-Z_ -]+)\]\s*$")
    sections: list[tuple[str, list[str]]] = []
    current_role: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        marker = role_re.match(line.strip())
        if marker:
            if current_role is not None:
                sections.append((current_role, current_lines))
            current_role = marker.group("role").strip().lower()
            current_lines = []
            continue
        if current_role is not None:
            current_lines.append(line)

    if current_role is not None:
        sections.append((current_role, current_lines))
    if not sections:
        return content

    useful_roles = {"assistant", "ai", "codex", "claude", "opencode", "gpt", "session"}
    useful_sections = [
        "\n".join(lines).strip()
        for role, lines in sections
        if role in useful_roles and "\n".join(lines).strip()
    ]
    return "\n\n".join(useful_sections)


def _clean_session_fact_text(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"data:image/[a-z0-9.+-]+;base64,\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[A-Za-z0-9+/]{140,}={0,2}", " ", text)
    text = re.sub(r"[*_`#>\[\](){}\"]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^[./\\\s:;-]+|[./\\\s:;-]+$", "", text)


def _is_extractable_session_fact(text: str) -> bool:
    if len(text) <= 5:
        return False
    if _looks_like_session_fragment(text):
        return False
    if re.search(r"data:image/|base64|[A-Za-z0-9+/]{180,}={0,2}", text, re.IGNORECASE):
        return False
    if re.search(
        r"\b(base_instructions|permissions instructions|developer instructions|knowledge cutoff|"
        r"request escalation|prefix_rule|sandbox_permissions|function_call|function_call_output|"
        r"internal_chat_message_metadata|local_images|session_meta|tool_call|working with the user)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text)
    if len(words) < 2:
        return False
    compact = re.sub(r"\s+", "", text)
    noisy_chars = sum(1 for ch in compact if ch in "/.\\{}[]<>_=+:;|")
    return not (len(compact) >= 12 and len(words) < 3 and noisy_chars / max(1, len(compact)) > 0.34)


def _looks_like_session_fragment(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return True
    if re.match(r"^[,.;:]", clean):
        return True
    if re.match(r"^[A-Za-z]\b[,.;:]?", clean):
        return True
    if re.match(
        r"^(?:and|or|but|then|before|after|while|because|only because|once|when|whether|"
        r"which|that|is|are|was|were|appears)\b",
        clean,
        re.IGNORECASE,
    ):
        return True
    if re.match(r"^\w{1,12},\s+(?:and|then|but|so)\b", clean, re.IGNORECASE):
        return True
    if re.search(r"\b(?:I(?:'|’)m|I(?:'|’)ll|I am|I will)\b", clean):
        return True
    if re.search(r"\bnext pass will\b", clean, re.IGNORECASE):
        return True
    return False


def _extract_session_file_refs(content: str, provenance: str) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    seen: set[str] = set()

    file_patterns = [
        r"(?:^|\s)([\w/.-]+\.\w{1,10})(?::\d+)?(?:\s|$)",
    ]
    code_extensions = {
        "py", "js", "ts", "jsx", "tsx", "rs", "go", "java", "rb", "php",
        "c", "cpp", "h", "hpp", "cs", "swift", "kt", "scala", "sh", "bash",
        "yml", "yaml", "toml", "json", "xml", "sql", "md", "txt", "css",
        "html", "htm", "env", "cfg", "ini", "conf",
    }

    for pattern in file_patterns:
        for m in re.finditer(pattern, content):
            filepath = m.group(1).strip()
            if filepath in seen:
                continue
            ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
            if ext not in code_extensions:
                continue
            if len(filepath) < 3 or len(filepath) > 200:
                continue
            seen.add(filepath)
            facts.append(ExtractedFact(
                model_name="Repo", name=f"File: {filepath}",
                value=f"Referenced in agent session: {filepath}",
                fact_type="fact", confidence=0.70,
                temporal="current", temporal_hint="current",
                provenance=provenance, excerpt=f"File reference: {filepath}",
            ))

    return facts


_GITHUB_ISSUE_REFERENCE = re.compile(
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>\d+)\b"
)


def _extract_github_issue_references(
    body: str,
    supplied_references: object = None,
) -> list[GitHubIssueReference]:
    references: list[GitHubIssueReference] = []
    seen: set[tuple[str | None, int]] = set()

    def add(repo_full_name: str | None, number: int) -> None:
        normalized_repo = repo_full_name.strip() if repo_full_name else None
        key = (normalized_repo.casefold() if normalized_repo else None, number)
        if number <= 0 or key in seen:
            return
        seen.add(key)
        references.append(GitHubIssueReference(
            number=number,
            repo_full_name=normalized_repo,
        ))

    for match in _GITHUB_ISSUE_REFERENCE.finditer(body or ""):
        add(match.group("repo"), int(match.group("number")))

    body_reference_numbers = {reference.number for reference in references}
    if isinstance(supplied_references, list):
        for supplied in supplied_references:
            if isinstance(supplied, int):
                if supplied in body_reference_numbers:
                    continue
                add(None, supplied)
                continue
            if isinstance(supplied, str):
                match = _GITHUB_ISSUE_REFERENCE.fullmatch(supplied.strip())
                if match:
                    if match.group("repo") is None and int(match.group("number")) in body_reference_numbers:
                        continue
                    add(match.group("repo"), int(match.group("number")))

    return references


_FIX_KEYWORDS = re.compile(
    r"\b(?:fix(?:es)?|close(?:s)?|resolve(?:s)?)\s+"
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>\d+)\b",
    re.IGNORECASE,
)


def _is_fix_reference(
    body: str,
    issue_num: int,
    *,
    repo_full_name: str | None = None,
) -> bool:
    if not body:
        return False
    for m in _FIX_KEYWORDS.finditer(body):
        try:
            matched_repo = m.group("repo")
            repository_matches = (
                matched_repo.casefold() == repo_full_name.casefold()
                if matched_repo and repo_full_name
                else matched_repo is None and repo_full_name is None
            )
            if int(m.group("number")) == issue_num and repository_matches:
                return True
        except (ValueError, IndexError, AttributeError):
            continue
    return False


def _build_fixes_evidence(
    pr_number: int,
    issue_num: int,
    body: str,
    *,
    repo_full_name: str | None = None,
) -> str:
    for m in _FIX_KEYWORDS.finditer(body or ""):
        try:
            matched_repo = m.group("repo")
            repository_matches = (
                matched_repo.casefold() == repo_full_name.casefold()
                if matched_repo and repo_full_name
                else matched_repo is None and repo_full_name is None
            )
            if int(m.group("number")) == issue_num and repository_matches:
                return f"PR #{pr_number} {m.group(0).strip()}"
        except (ValueError, IndexError, AttributeError):
            continue
    qualified_ref = f"{repo_full_name}#{issue_num}" if repo_full_name else f"#{issue_num}"
    return f"PR #{pr_number} fixes {qualified_ref}"


_EXPLICIT_BLOCK_RE = re.compile(
    r"\b(?:block(?:s|ed|ing)?|request(?:ing)?\s+changes|changes\s+requested|"
    r"must\s+fix|needs\s+to\s+be\s+fixed|do\s+not\s+merge|"
    r"holding\b|reject(?:s|ed)?)\b",
    re.IGNORECASE,
)


def _is_explicit_block(review_text: str) -> bool:
    return bool(_EXPLICIT_BLOCK_RE.search(review_text))
