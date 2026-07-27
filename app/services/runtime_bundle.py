from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.schemas.continuation_execution import ContinuationExecutionContract
from app.services.artifact_paths import artifact_bundle_relative_path
from app.services.execution_prompt_renderer import canonical_contract_json


RUNTIME_BUNDLE_SCHEMA_VERSION = "continuation_runtime_bundle.v1"
RUNTIME_ARTIFACTS_SCHEMA_VERSION = "continuation_runtime_artifacts.v1"
MAX_BUNDLE_FILE_BYTES = 64 * 1024 * 1024
RUNTIME_BUNDLE_ROOT_ENVIRONMENT = "DAEMONSTATE_EXECUTION_BUNDLE_PATH"


class RuntimeBundleIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeBundle:
    root: Path
    execution_path: Path
    contract_path: Path
    handoff_path: Path
    artifacts_path: Path
    verification_path: Path
    manifest_path: Path
    attachments_path: Path
    evidence_path: Path
    expected_hashes: dict[str, str]

    def environment(self) -> dict[str, str]:
        return {
            RUNTIME_BUNDLE_ROOT_ENVIRONMENT: str(self.root),
            "DAEMONSTATE_EXECUTION_PROMPT_PATH": str(self.execution_path),
            "DAEMONSTATE_EXECUTION_CONTRACT_PATH": str(self.contract_path),
            "DAEMONSTATE_EXECUTION_ARTIFACTS_MANIFEST_PATH": str(
                self.artifacts_path
            ),
            "DAEMONSTATE_EXECUTION_ATTACHMENTS_PATH": str(
                self.attachments_path
            ),
        }

    def verify_integrity(self) -> None:
        observed_paths = {
            str(path.relative_to(self.root))
            for path in self.root.rglob("*")
            if path.is_file()
        }
        expected_paths = set(self.expected_hashes)
        if observed_paths != expected_paths:
            missing = sorted(expected_paths - observed_paths)
            added = sorted(observed_paths - expected_paths)
            raise RuntimeBundleIntegrityError(
                "runtime bundle contents changed"
                + (f"; missing: {', '.join(missing)}" if missing else "")
                + (f"; added: {', '.join(added)}" if added else "")
            )
        for relative_path, expected_hash in self.expected_hashes.items():
            path = self.root / relative_path
            if path.is_symlink() or not path.is_file():
                raise RuntimeBundleIntegrityError(
                    f"runtime bundle file is not a regular file: {relative_path}"
                )
            if path.stat().st_mode & 0o222:
                raise RuntimeBundleIntegrityError(
                    f"runtime bundle file became writable: {relative_path}"
                )
            observed_hash = _sha256_file(path)
            if observed_hash != expected_hash:
                raise RuntimeBundleIntegrityError(
                    f"runtime bundle hash changed: {relative_path}"
                )


@contextmanager
def materialize_runtime_bundle(
    contract: ContinuationExecutionContract,
    *,
    prompt_markdown: str,
) -> Iterator[RuntimeBundle]:
    """Materialize a provider-readable, immutable execution bundle."""

    temporary = tempfile.TemporaryDirectory(
        prefix=f"daemonstate-execution-{_safe_name(str(contract.id))}-"
    )
    root = Path(temporary.name)
    attachments = root / "attachments"
    evidence = root / "evidence"
    attachments.mkdir(mode=0o700)
    evidence.mkdir(mode=0o700)

    execution_path = root / "execution.md"
    contract_path = root / "contract.json"
    handoff_path = root / "handoff.json"
    artifacts_path = root / "artifacts.json"
    verification_path = root / "verification.json"
    manifest_path = root / "bundle-manifest.json"

    artifact_entries: list[dict[str, Any]] = []
    for ordinal, artifact in enumerate(contract.artifacts, start=1):
        if not artifact.available:
            if artifact.required:
                raise RuntimeBundleIntegrityError(
                    f"required artifact {artifact.id} is unavailable"
                )
            artifact_entries.append({
                **artifact.model_dump(mode="json"),
                "source_path": None,
                "path": None,
                "bundle_path": None,
                "delivery": None,
            })
            continue
        if not artifact.sha256:
            raise RuntimeBundleIntegrityError(
                f"artifact {artifact.id} has no verified content hash"
            )
        source_path = Path(artifact.path).expanduser()
        relative_path = artifact_bundle_relative_path(
            artifact,
            ordinal=ordinal,
        )
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_verified_artifact(
            source_path,
            target,
            artifact_id=artifact.id,
            expected_sha256=artifact.sha256,
        )
        artifact_entries.append({
            **artifact.model_dump(mode="json"),
            "source_path": None,
            "path": relative_path,
            "bundle_path": relative_path,
            "delivery": {
                "kind": "runtime_bundle_relative",
                "bundle_root_environment_variable": (
                    RUNTIME_BUNDLE_ROOT_ENVIRONMENT
                ),
                "bundle_path": relative_path,
            },
        })

    _write_read_only(execution_path, prompt_markdown.encode("utf-8"))
    _write_read_only(
        contract_path,
        (canonical_contract_json(contract) + "\n").encode("utf-8"),
    )
    _write_read_only(
        handoff_path,
        _canonical_json(contract.handoff.model_dump(mode="json")),
    )
    artifact_manifest = {
        "schema_version": RUNTIME_ARTIFACTS_SCHEMA_VERSION,
        "portable": True,
        "bundle_root_environment_variable": (
            RUNTIME_BUNDLE_ROOT_ENVIRONMENT
        ),
        "attachment_directory": "attachments",
        "path_semantics": {
            "path": "bundle_relative",
            "bundle_path": "bundle_relative",
            "source_path": "omitted",
            "content_identity": "sha256_of_exact_bundled_bytes",
        },
        "artifacts": artifact_entries,
    }
    _write_read_only(artifacts_path, _canonical_json(artifact_manifest))
    _write_read_only(
        verification_path,
        _canonical_json([
            item.model_dump(mode="json") for item in contract.verification
        ]),
    )

    initial_files = [
        path
        for path in root.rglob("*")
        if path.is_file()
    ]
    content_hashes = {
        str(path.relative_to(root)): _sha256_file(path)
        for path in initial_files
    }
    manifest = {
        "schema_version": RUNTIME_BUNDLE_SCHEMA_VERSION,
        "execution_id": str(contract.id),
        "contract_schema_version": contract.schema_version,
        "portability": {
            "bundle_root_environment_variable": (
                RUNTIME_BUNDLE_ROOT_ENVIRONMENT
            ),
            "file_paths": "bundle_relative",
        },
        "attachments": {
            "manifest_path": str(artifacts_path.relative_to(root)),
            "directory_path": str(attachments.relative_to(root)),
            "artifact_count": len(artifact_entries),
            "available_count": sum(
                1 for item in artifact_entries if item["available"]
            ),
            "required_count": sum(
                1 for item in artifact_entries if item["required"]
            ),
            "content_identity": "sha256",
        },
        "files": content_hashes,
    }
    _write_read_only(manifest_path, _canonical_json(manifest))
    expected_hashes = {
        **content_hashes,
        str(manifest_path.relative_to(root)): _sha256_file(manifest_path),
    }

    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)

    bundle = RuntimeBundle(
        root=root,
        execution_path=execution_path,
        contract_path=contract_path,
        handoff_path=handoff_path,
        artifacts_path=artifacts_path,
        verification_path=verification_path,
        manifest_path=manifest_path,
        attachments_path=attachments,
        evidence_path=evidence,
        expected_hashes=expected_hashes,
    )
    try:
        bundle.verify_integrity()
        yield bundle
    finally:
        # TemporaryDirectory cleanup needs directory write permission. The
        # hashes above remain the authoritative before/after integrity proof.
        for directory in sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda item: len(item.parts),
        ):
            try:
                directory.chmod(0o700)
            except OSError:
                pass
        try:
            root.chmod(0o700)
        except OSError:
            pass
        temporary.cleanup()


def _write_read_only(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    _make_read_only(path)


def _make_read_only(path: Path) -> None:
    path.chmod(stat.S_IRUSR)


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _copy_verified_artifact(
    source_path: Path,
    target_path: Path,
    *,
    artifact_id: str,
    expected_sha256: str,
) -> None:
    """Copy one artifact from one no-follow source descriptor.

    Opening, validating, reading, hashing, and copying all use the same source
    file descriptor. A path replacement after ``open`` therefore cannot switch
    the bytes being delivered, and the copied byte stream must still match the
    contract-bound SHA-256 before the bundle becomes usable.
    """

    source_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
    target_flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        target_flags |= os.O_NOFOLLOW
    source_fd: int | None = None
    target_fd: int | None = None
    target_created = False
    copied = False
    try:
        source_fd = os.open(source_path, source_flags)
        metadata = os.fstat(source_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeBundleIntegrityError(
                f"artifact {artifact_id} is not a regular file"
            )
        if metadata.st_size > MAX_BUNDLE_FILE_BYTES:
            raise RuntimeBundleIntegrityError(
                f"artifact {artifact_id} exceeds the runtime bundle file limit"
            )
        target_fd = os.open(target_path, target_flags, 0o600)
        target_created = True
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BUNDLE_FILE_BYTES:
                raise RuntimeBundleIntegrityError(
                    f"artifact {artifact_id} exceeds the runtime bundle file limit"
                )
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise OSError("artifact bundle write made no progress")
                view = view[written:]
        observed_sha256 = digest.hexdigest()
        if observed_sha256 != expected_sha256:
            raise RuntimeBundleIntegrityError(
                f"artifact {artifact_id} copied bytes do not match contract SHA-256"
            )
        os.fsync(target_fd)
        os.lseek(target_fd, 0, os.SEEK_SET)
        delivered_digest = hashlib.sha256()
        delivered_size = 0
        while True:
            delivered_chunk = os.read(target_fd, 1024 * 1024)
            if not delivered_chunk:
                break
            delivered_size += len(delivered_chunk)
            if delivered_size > MAX_BUNDLE_FILE_BYTES:
                raise RuntimeBundleIntegrityError(
                    f"artifact {artifact_id} exceeds the runtime bundle file limit"
                )
            delivered_digest.update(delivered_chunk)
        if delivered_digest.hexdigest() != expected_sha256:
            raise RuntimeBundleIntegrityError(
                f"artifact {artifact_id} delivered bytes do not match contract SHA-256"
            )
        copied = True
    except RuntimeBundleIntegrityError:
        raise
    except OSError as exc:
        raise RuntimeBundleIntegrityError(
            f"artifact {artifact_id} could not be copied safely"
        ) from exc
    finally:
        if target_fd is not None:
            os.close(target_fd)
        if source_fd is not None:
            os.close(source_fd)
        if target_created and not copied:
            try:
                target_path.unlink()
            except OSError:
                pass
    _make_read_only(target_path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip(".-")
    return normalized[:100] or "artifact"
