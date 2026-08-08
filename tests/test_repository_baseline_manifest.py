from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from app.services.local_harness import (
    _baseline_file_preserved,
    _protected_index_state_preserved,
    capture_repository_snapshot,
)
from app.services.checkpoints import _repository_baseline_manifest, _session_handoff_files


def _git(root: Path, *args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_text,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "baseline@example.test")
    _git(root, "config", "user.name", "Baseline Test")
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "initial")
    return root


def _manifest_entries(snapshot) -> dict[str, dict[str, object]]:
    manifest = snapshot.protected_baseline
    assert manifest is not None
    assert manifest["schema_version"] == "protected_baseline.v1"
    assert manifest["complete"] is True
    assert len(str(manifest["manifest_sha256"])) == 64
    return {str(item["path"]): item for item in manifest["entries"]}


@pytest.mark.asyncio
async def test_protected_baseline_distinguishes_staged_unstaged_and_mm(
    tmp_path: Path,
) -> None:
    root = _repository(
        tmp_path,
        {
            "staged.txt": "base\n",
            "unstaged.txt": "base\n",
            "both.txt": "base\n",
        },
    )
    (root / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(root, "add", "staged.txt")
    (root / "unstaged.txt").write_text("unstaged\n", encoding="utf-8")
    (root / "both.txt").write_text("index version\n", encoding="utf-8")
    _git(root, "add", "both.txt")
    (root / "both.txt").write_text("worktree version\n", encoding="utf-8")

    snapshot = await capture_repository_snapshot(root)
    entries = _manifest_entries(snapshot)

    assert entries["staged.txt"]["xy"] == "M "
    assert entries["unstaged.txt"]["xy"] == " M"
    assert entries["both.txt"]["xy"] == "MM"
    assert (
        entries["staged.txt"]["index"]["stages"][0]["object_id"]
        != (entries["staged.txt"]["head"]["object_id"])
    )
    assert (
        entries["unstaged.txt"]["index"]["stages"][0]["object_id"]
        == (entries["unstaged.txt"]["head"]["object_id"])
    )
    assert (
        entries["both.txt"]["worktree"]["content_sha256"]
        == hashlib.sha256(b"worktree version\n").hexdigest()
    )


@pytest.mark.asyncio
async def test_protected_baseline_captures_untracked_and_both_deletion_layers(
    tmp_path: Path,
) -> None:
    root = _repository(
        tmp_path,
        {
            "unstaged-delete.txt": "base\n",
            "staged-delete.txt": "base\n",
        },
    )
    (root / "unstaged-delete.txt").unlink()
    _git(root, "rm", "-q", "staged-delete.txt")
    (root / "untracked.txt").write_text("new\n", encoding="utf-8")

    entries = _manifest_entries(await capture_repository_snapshot(root))

    assert entries["unstaged-delete.txt"]["xy"] == " D"
    assert entries["unstaged-delete.txt"]["index"]["state"] == "present"
    assert entries["unstaged-delete.txt"]["worktree"] == {"state": "absent"}
    assert entries["staged-delete.txt"]["xy"] == "D "
    assert entries["staged-delete.txt"]["index"] == {
        "state": "absent",
        "stages": [],
    }
    assert entries["staged-delete.txt"]["worktree"] == {"state": "absent"}
    assert entries["untracked.txt"]["xy"] == "??"
    assert entries["untracked.txt"]["head"] == {"state": "absent"}
    assert entries["untracked.txt"]["index"] == {"state": "absent", "stages": []}


@pytest.mark.asyncio
async def test_protected_baseline_keeps_dual_porcelain_records_for_one_path(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, {".env": "TOKEN=user-owned\n"})
    _git(root, "rm", "--cached", ".env")

    snapshot = await capture_repository_snapshot(root)
    manifest = snapshot.protected_baseline

    assert snapshot.status_truncated is False
    assert manifest is not None
    assert manifest["complete"] is True
    records = [item for item in manifest["entries"] if item["path"] == ".env"]
    assert [item["xy"] for item in records] == ["D ", "??"]
    assert all(item["index"] == {"state": "absent", "stages": []} for item in records)
    assert all(item["worktree"]["state"] == "present" for item in records)


@pytest.mark.asyncio
async def test_index_mutation_changes_fingerprint_with_same_xy_and_worktree(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, {"card.css": "base\n"})
    (root / "card.css").write_text("index one\n", encoding="utf-8")
    _git(root, "add", "card.css")
    (root / "card.css").write_text("worktree\n", encoding="utf-8")
    before = await capture_repository_snapshot(root)

    replacement_oid = _git(root, "hash-object", "-w", "--stdin", input_text="index two\n")
    _git(root, "update-index", "--cacheinfo", f"100644,{replacement_oid},card.css")
    after = await capture_repository_snapshot(root)

    before_entry = _manifest_entries(before)["card.css"]
    after_entry = _manifest_entries(after)["card.css"]
    assert before_entry["xy"] == after_entry["xy"] == "MM"
    assert before_entry["worktree"] == after_entry["worktree"]
    assert before_entry["index"] != after_entry["index"]
    assert before.status_fingerprint != after.status_fingerprint
    assert _protected_index_state_preserved(before, after) is False


@pytest.mark.asyncio
async def test_manifest_hashes_complete_large_worktree_bytes(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, {"large.bin": "A" * (1024 * 1024 + 64)})
    path = root / "large.bin"
    path.write_bytes((b"A" * (1024 * 1024 + 63)) + b"B")
    before = await capture_repository_snapshot(root)
    path.write_bytes((b"A" * (1024 * 1024 + 63)) + b"C")
    after = await capture_repository_snapshot(root)

    before_hash = _manifest_entries(before)["large.bin"]["worktree"]["content_sha256"]
    after_hash = _manifest_entries(after)["large.bin"]["worktree"]["content_sha256"]
    assert before_hash != after_hash
    assert before.status_fingerprint != after.status_fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    ["secret=foo", "a\\b.txt", ":(literal)foo", "[abc]*.txt"],
)
async def test_machine_git_paths_are_never_redacted_or_rewritten(
    tmp_path: Path,
    filename: str,
) -> None:
    if os.name == "nt" and "\\" in filename:
        pytest.skip("backslash is a path separator on Windows")
    root = _repository(tmp_path, {filename: "base\n"})
    (root / filename).unlink()

    snapshot = await capture_repository_snapshot(root)
    entries = _manifest_entries(snapshot)

    assert snapshot.status_truncated is False
    assert filename in entries
    assert entries[filename]["head"]["state"] == "present"
    assert entries[filename]["index"]["state"] == "present"


@pytest.mark.asyncio
async def test_unstaged_delta_is_preserved_against_the_captured_index(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, {"card.css": "head\n"})
    path = root / "card.css"
    path.write_text("index\n", encoding="utf-8")
    _git(root, "add", "card.css")
    path.write_text("head\n", encoding="utf-8")

    baseline = await capture_repository_snapshot(root)
    proof = next(item for item in baseline._preservation_files if item.path == "card.css")
    path.write_text("index\n", encoding="utf-8")

    assert _baseline_file_preserved(root, proof) is False


@pytest.mark.asyncio
async def test_projection_rejects_mismatched_manifest_identity_and_head(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, {"card.css": "base\n"})
    (root / "card.css").write_text("changed\n", encoding="utf-8")
    repository = (await capture_repository_snapshot(root)).to_dict()

    valid = _repository_baseline_manifest(repository, captured_at="2026-08-08T00:00:00Z")
    assert valid["complete"] is True

    repository["protected_baseline"]["id"] = "PB-forged"
    forged_id = _repository_baseline_manifest(repository, captured_at="2026-08-08T00:00:00Z")
    assert forged_id["complete"] is False
    assert forged_id["id"] != "PB-forged"

    repository["protected_baseline"]["id"] = valid["id"]
    repository["head_commit"] = "f" * 40
    forged_head = _repository_baseline_manifest(repository, captured_at="2026-08-08T00:00:00Z")
    assert forged_head["complete"] is False


@pytest.mark.asyncio
async def test_projection_retains_dual_status_records_for_one_path(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, {".env": "TOKEN=user-owned\n"})
    _git(root, "rm", "--cached", ".env")
    repository = (await capture_repository_snapshot(root)).to_dict()
    repository["protected_baseline_manifest"] = _repository_baseline_manifest(
        repository,
        captured_at="2026-08-08T00:00:00Z",
    )

    files = _session_handoff_files((), (), repository=repository)
    protected = next(item for item in files["pre_existing_at_handoff"] if item["path"] == ".env")

    assert protected["statuses"] == ["D ", "??"]
    assert [item["xy"] for item in protected["records"]] == ["D ", "??"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    [" leading.txt", "trailing.txt ", " "],
)
async def test_projection_preserves_whitespace_in_git_path_identity(
    tmp_path: Path,
    filename: str,
) -> None:
    root = _repository(tmp_path, {filename: "base\n"})
    (root / filename).write_text("changed\n", encoding="utf-8")

    snapshot = await capture_repository_snapshot(root)
    assert snapshot.changed_files == (filename,)
    assert snapshot.protected_baseline is not None
    assert snapshot.protected_baseline["complete"] is True

    repository = snapshot.to_dict()
    repository["protected_baseline_manifest"] = _repository_baseline_manifest(
        repository,
        captured_at="2026-08-08T00:00:00Z",
    )
    assert repository["protected_baseline_manifest"]["complete"] is True

    protected = _session_handoff_files((), (), repository=repository)["pre_existing_at_handoff"]
    assert [item["path"] for item in protected] == [filename]
    assert protected[0]["statuses"] == [" M"]
    assert [item["xy"] for item in protected[0]["records"]] == [" M"]
