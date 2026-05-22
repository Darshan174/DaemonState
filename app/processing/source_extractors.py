from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.processing.extractor import ExtractedFact, ExtractedRelationship


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
    html_url: str | None = None
    created_at: str | None = None
    merged_at: str | None = None
    user: str | None = None


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
        closed_at=data.get("closed_at"),
        user=data.get("user", {}).get("login") if isinstance(data.get("user"), dict) else data.get("user"),
    )
    return _build_github_issue_facts(issue, doc_metadata)


def _extract_github_issue_text(content: str, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    title_match = re.search(r"(?:^|\n)#\s*(.+?)(?:\n|$)", content)
    title = title_match.group(1).strip() if title_match else content[:120].strip()

    state = "closed" if re.search(r"\b(closed|resolved|fixed)\b", content, re.IGNORECASE) else "open"
    issue = GitHubIssueData(title=title, body=content, state=state)
    return _build_github_issue_facts(issue, doc_metadata)


def _build_github_issue_facts(issue: GitHubIssueData, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []

    state_temporal = "past" if issue.state == "closed" else "current"
    issue_name = f"Issue #{issue.number}: {issue.title}" if issue.number else f"Issue: {issue.title}"
    issue_value = issue.body[:500] if issue.body else issue.title

    provenance = json.dumps({"source_type": "github_issue", "number": issue.number, "url": issue.html_url, "state": issue.state})

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

    facts[0]

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

    for m in re.finditer(r"(?:decision|decided|we chose|we will use)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text:
            facts.append(ExtractedFact(
                model_name="Decision", name=f"Decision: {text[:120]}",
                value=text, fact_type="decision", confidence=0.82,
                temporal="current", temporal_hint="current",
                provenance=provenance, excerpt=text[:300],
            ))

    for m in re.finditer(r"(?:action item|todo|task|action|follow.?up)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text:
            facts.append(ExtractedFact(
                model_name="Task", name=f"Task: {text[:120]}",
                value=text, fact_type="task", confidence=0.78,
                temporal="current", temporal_hint="current",
                provenance=provenance, excerpt=text[:300],
            ))

    for m in re.finditer(r"(?:blocker|blocked by|risk|concern|dependency risk)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text:
            facts.append(ExtractedFact(
                model_name="Risk", name=f"Risk: {text[:120]}",
                value=text, fact_type="blocker", confidence=0.85,
                temporal="current", temporal_hint="current",
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
    changed_files_raw = data.get("changed_files", [])
    if isinstance(changed_files_raw, list) and changed_files_raw and isinstance(changed_files_raw[0], dict):
        changed_files = [f.get("filename", "") for f in changed_files_raw if f.get("filename")]
    else:
        changed_files = changed_files_raw if isinstance(changed_files_raw, list) else []

    linked_issues: list[int] = []
    body_text = data.get("body", "") or ""
    for m in re.finditer(r"#(\d+)", body_text):
        linked_issues.append(int(m.group(1)))
    for num in data.get("linked_issues", []):
        if num not in linked_issues:
            linked_issues.append(num)

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
        html_url=data.get("html_url"),
        created_at=data.get("created_at"),
        merged_at=data.get("merged_at"),
        user=data.get("user", {}).get("login") if isinstance(data.get("user"), dict) else data.get("user"),
    )
    return _build_github_pr_facts(pr, doc_metadata)


def _extract_github_pr_text(content: str, doc_metadata: dict[str, Any] | None = None) -> list[ExtractedFact]:
    title_match = re.search(r"(?:^|\n)#\s*(.+?)(?:\n|$)", content)
    title = title_match.group(1).strip() if title_match else content[:120].strip()

    merged = bool(re.search(r"\b(merged|merged into)\b", content, re.IGNORECASE))
    pr = GitHubPRData(title=title, body=content, merged=merged)
    pr.linked_issues = [int(m.group(1)) for m in re.finditer(r"#(\d+)", content)]
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

    for issue_num in pr.linked_issues:
        is_fix = _is_fix_reference(pr.body, issue_num)
        if is_fix:
            pr_fact.relationships.append(ExtractedRelationship(
                target_name=f"Issue #{issue_num}",
                relationship_type="fixes",
                confidence=0.95,
                evidence=_build_fixes_evidence(pr.number, issue_num, pr.body),
            ))
            pr_fact.relationships.append(ExtractedRelationship(
                target_name=f"Issue #{issue_num}",
                relationship_type="solves",
                confidence=0.95,
                evidence=_build_fixes_evidence(pr.number, issue_num, pr.body),
            ))
        else:
            pr_fact.relationships.append(ExtractedRelationship(
                target_name=f"Issue #{issue_num}",
                relationship_type="mentions",
                confidence=0.75,
                evidence=f"PR #{pr.number} references #{issue_num}",
            ))

    for filename in pr.changed_files[:10]:
        filename.replace("/", " > ").split(">")[-1] if "/" in filename else filename
        facts.append(ExtractedFact(
            model_name="Repo",
            name=f"File: {filename}",
            value=f"Changed in PR #{pr.number}: {pr.title}",
            fact_type="changed_file",
            confidence=0.90,
            temporal=state_temporal,
            temporal_hint=state_temporal,
            relationships=[ExtractedRelationship(
                target_name=pr_name,
                relationship_type="touches_file",
                confidence=0.92,
                evidence=f"File {filename} changed in PR #{pr.number}",
            )],
            provenance=provenance,
            excerpt=f"Changed file: {filename}",
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

    facts[0]

    task_items = _extract_session_tasks(content, session_provenance)
    for task in task_items:
        task.relationships.append(ExtractedRelationship(
            target_name=session_name,
            relationship_type="generated_by_agent",
            confidence=0.90,
            evidence="Task extracted from agent session",
        ))
    facts.extend(task_items)

    decision_items = _extract_session_decisions(content, session_provenance)
    for dec in decision_items:
        dec.relationships.append(ExtractedRelationship(
            target_name=session_name,
            relationship_type="generated_by_agent",
            confidence=0.88,
            evidence="Decision extracted from agent session",
        ))
    facts.extend(decision_items)

    risk_items = _extract_session_risks(content, session_provenance)
    for risk in risk_items:
        risk.relationships.append(ExtractedRelationship(
            target_name=session_name,
            relationship_type="generated_by_agent",
            confidence=0.85,
            evidence="Risk/blocker extracted from agent session",
        ))
    facts.extend(risk_items)

    file_refs = _extract_session_file_refs(content, session_provenance)
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
        text = m.group(1).strip()
        if not text:
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

    for m in re.finditer(r"(?:next step|todo|action item|follow.?up)\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE):
        text = m.group(1).strip()
        if text and len(text) > 5 and text not in seen:
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
        r"(?:decision|decided|we chose|we will use|recommendation|verdict)\s*:?\s*(.+?)(?:\n|$)",
    ]
    for pattern in decision_patterns:
        for m in re.finditer(pattern, content, re.IGNORECASE):
            text = m.group(1).strip()
            if text and len(text) > 5 and text not in seen:
                seen.add(text)
                facts.append(ExtractedFact(
                    model_name="Decision", name=f"Decision: {text[:120]}",
                    value=text, fact_type="decision", confidence=0.82,
                    temporal="current", temporal_hint="current",
                    provenance=provenance, excerpt=text[:300],
                ))

    for m in re.finditer(r"^#+\s*(?:final|decision|summary|conclusion)\b(.*)$", content, re.MULTILINE | re.IGNORECASE):
        m.group(0).strip()
        start = m.end()
        end = content.find("\n#", start)
        section = content[start:end].strip() if end != -1 else content[start:].strip()
        summary = section[:200].strip()
        if summary and summary not in seen:
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
        r"(?:blocker|blocked by|risk|concern|unresolved question|open question|failed)\s*:?\s*(.+?)(?:\n|$)",
    ]
    for pattern in risk_patterns:
        for m in re.finditer(pattern, content, re.IGNORECASE):
            text = m.group(1).strip()
            if text and len(text) > 5 and text not in seen:
                seen.add(text)
                temporal = "current"
                if "failed" in text.lower():
                    temporal = "past"
                facts.append(ExtractedFact(
                    model_name="Risk", name=f"Risk: {text[:120]}",
                    value=text, fact_type="blocker", confidence=0.82,
                    temporal=temporal, temporal_hint=temporal,
                    provenance=provenance, excerpt=text[:300],
                ))

    return facts


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


_FIX_KEYWORDS = re.compile(
    r"\b(?:fix(?:es)?|close(?:s)?|resolve(?:s)?|closes)\s+#(\d+)",
    re.IGNORECASE,
)


def _is_fix_reference(body: str, issue_num: int) -> bool:
    if not body:
        return False
    for m in _FIX_KEYWORDS.finditer(body):
        try:
            if int(m.group(1)) == issue_num:
                return True
        except (ValueError, IndexError):
            continue
    return False


def _build_fixes_evidence(pr_number: int, issue_num: int, body: str) -> str:
    for m in _FIX_KEYWORDS.finditer(body or ""):
        try:
            if int(m.group(1)) == issue_num:
                return f"PR #{pr_number} {m.group(0).strip()}"
        except (ValueError, IndexError):
            continue
    return f"PR #{pr_number} fixes #{issue_num}"


_EXPLICIT_BLOCK_RE = re.compile(
    r"\b(?:block(?:s|ed|ing)?|request(?:ing)?\s+changes|changes\s+requested|"
    r"must\s+fix|needs\s+to\s+be\s+fixed|do\s+not\s+merge|"
    r"holding\b|reject(?:s|ed)?)\b",
    re.IGNORECASE,
)


def _is_explicit_block(review_text: str) -> bool:
    return bool(_EXPLICIT_BLOCK_RE.search(review_text))
