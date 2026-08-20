"""Offline CLI for the deliberately simplified public demonstration bundle.

This module validates and renders already-created synthetic data. It does not
inspect repositories, discover sessions, execute commands, or call a service.
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "daemonstate.public.context_bundle.v1"


class BundleValidationError(ValueError):
    """Raised when a file does not match the public demonstration contract."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _check_exact_keys(
    value: dict[str, Any],
    required: set[str],
    path: str,
    errors: list[str],
) -> None:
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required)
    for key in missing:
        errors.append(f"{path}.{key}: missing required field")
    for key in unknown:
        errors.append(f"{path}.{key}: unknown field")


def _check_string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: expected a non-empty string")


def _check_string_list(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: expected an array")
        return
    for index, item in enumerate(value):
        _check_string(item, f"{path}[{index}]", errors)


def _check_object_list(
    value: Any,
    required: set[str],
    path: str,
    errors: list[str],
) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: expected an array")
        return
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path}: expected an object")
            continue
        _check_exact_keys(item, required, item_path, errors)
        for key in sorted(required & item.keys()):
            _check_string(item[key], f"{item_path}.{key}", errors)


def validate_bundle(bundle: Any) -> list[str]:
    """Return validation errors for the public demo bundle, or an empty list."""

    errors: list[str] = []
    if not isinstance(bundle, dict):
        return ["$: expected an object"]

    root_fields = {"schema_version", "bundle_id", "workspace", "session", "provenance"}
    _check_exact_keys(bundle, root_fields, "$", errors)

    if "schema_version" in bundle and bundle["schema_version"] != SCHEMA_VERSION:
        errors.append(f"$.schema_version: expected {SCHEMA_VERSION!r}")
    if "bundle_id" in bundle:
        _check_string(bundle["bundle_id"], "$.bundle_id", errors)

    workspace_fields = {
        "id",
        "name",
        "purpose",
        "capabilities",
        "architecture",
        "conventions",
        "commands",
        "verified_facts",
    }
    workspace = bundle.get("workspace")
    if not isinstance(workspace, dict):
        if "workspace" in bundle:
            errors.append("$.workspace: expected an object")
    else:
        _check_exact_keys(workspace, workspace_fields, "$.workspace", errors)
        for field in ("id", "name", "purpose"):
            if field in workspace:
                _check_string(workspace[field], f"$.workspace.{field}", errors)
        for field in ("capabilities", "conventions"):
            if field in workspace:
                _check_string_list(workspace[field], f"$.workspace.{field}", errors)
        if "architecture" in workspace:
            _check_object_list(
                workspace["architecture"],
                {"component", "responsibility"},
                "$.workspace.architecture",
                errors,
            )
        if "commands" in workspace:
            _check_object_list(
                workspace["commands"],
                {"name", "command", "evidence"},
                "$.workspace.commands",
                errors,
            )
        if "verified_facts" in workspace:
            _check_object_list(
                workspace["verified_facts"],
                {"statement", "evidence", "status"},
                "$.workspace.verified_facts",
                errors,
            )

    session_fields = {
        "id",
        "title",
        "goal",
        "status",
        "progress",
        "decisions",
        "changed_files",
        "verification",
        "blockers",
        "next_action",
    }
    session = bundle.get("session")
    if not isinstance(session, dict):
        if "session" in bundle:
            errors.append("$.session: expected an object")
    else:
        _check_exact_keys(session, session_fields, "$.session", errors)
        for field in ("id", "title", "goal", "status", "next_action"):
            if field in session:
                _check_string(session[field], f"$.session.{field}", errors)
        for field in ("progress", "decisions", "changed_files", "blockers"):
            if field in session:
                _check_string_list(session[field], f"$.session.{field}", errors)
        if "verification" in session:
            _check_object_list(
                session["verification"],
                {"command", "status", "evidence"},
                "$.session.verification",
                errors,
            )

    provenance_fields = {"synthetic", "notice", "source", "generated_at"}
    provenance = bundle.get("provenance")
    if not isinstance(provenance, dict):
        if "provenance" in bundle:
            errors.append("$.provenance: expected an object")
    else:
        _check_exact_keys(provenance, provenance_fields, "$.provenance", errors)
        if provenance.get("synthetic") is not True:
            errors.append("$.provenance.synthetic: must be true for the public demo contract")
        for field in ("notice", "source", "generated_at"):
            if field in provenance:
                _check_string(provenance[field], f"$.provenance.{field}", errors)

    return errors


def _validated(bundle: Any) -> dict[str, Any]:
    errors = validate_bundle(bundle)
    if errors:
        raise BundleValidationError(errors)
    return bundle


def load_bundle(path: str | Path) -> dict[str, Any]:
    """Load and validate a public demonstration bundle from disk."""

    source = Path(path)
    try:
        bundle = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleValidationError([f"{source}: {exc}"]) from exc
    return _validated(bundle)


def load_bundled_example() -> dict[str, Any]:
    """Load the fictional example shipped inside the public package."""

    fixture = resources.files("daemonstate_public.examples").joinpath("synthetic_context.json")
    try:
        bundle = json.loads(fixture.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleValidationError([f"bundled fixture: {exc}"]) from exc
    return _validated(bundle)


def _one_line(value: Any) -> str:
    return " ".join(str(value).split())


def _bullet_lines(values: list[str], empty: str = "None") -> list[str]:
    if not values:
        return [f"- {empty}"]
    return [f"- {_one_line(value)}" for value in values]


def render_markdown(bundle: dict[str, Any]) -> str:
    """Render validated synthetic data without executing any embedded command."""

    bundle = _validated(bundle)
    workspace = bundle["workspace"]
    session = bundle["session"]
    provenance = bundle["provenance"]

    lines = [
        "# Synthetic DaemonState context demonstration",
        "",
        f"> **Synthetic data only.** {_one_line(provenance['notice'])}",
        "> The private DaemonState engine is not included and no command below is executed.",
        "",
        "## Workspace Context",
        "",
        f"**Workspace:** {_one_line(workspace['name'])} (`{_one_line(workspace['id'])}`)",
        "",
        f"**Purpose:** {_one_line(workspace['purpose'])}",
        "",
        "### Capabilities",
        "",
        *_bullet_lines(workspace["capabilities"]),
        "",
        "### Architecture",
        "",
    ]
    lines.extend(
        f"- **{_one_line(item['component'])}:** {_one_line(item['responsibility'])}"
        for item in workspace["architecture"]
    )
    lines.extend(["", "### Conventions", "", *_bullet_lines(workspace["conventions"])])
    lines.extend(["", "### Declared commands (not executed)", ""])
    lines.extend(
        f"- **{_one_line(item['name'])}:** `{_one_line(item['command'])}` — "
        f"{_one_line(item['evidence'])}"
        for item in workspace["commands"]
    )
    lines.extend(["", "### Synthetic verified facts", ""])
    lines.extend(
        f"- {_one_line(item['statement'])} "
        f"(**{_one_line(item['status'])}**; evidence: {_one_line(item['evidence'])})"
        for item in workspace["verified_facts"]
    )
    lines.extend(
        [
            "",
            "## Session Context",
            "",
            f"**Session:** {_one_line(session['title'])} (`{_one_line(session['id'])}`)",
            "",
            f"**Goal:** {_one_line(session['goal'])}",
            "",
            f"**Status:** {_one_line(session['status'])}",
            "",
            "### Progress",
            "",
            *_bullet_lines(session["progress"]),
            "",
            "### Decisions",
            "",
            *_bullet_lines(session["decisions"]),
            "",
            "### Changed files",
            "",
            *_bullet_lines(session["changed_files"]),
            "",
            "### Verification (reported synthetic evidence; not executed)",
            "",
        ]
    )
    lines.extend(
        f"- `{_one_line(item['command'])}` — **{_one_line(item['status'])}**: "
        f"{_one_line(item['evidence'])}"
        for item in session["verification"]
    )
    lines.extend(
        [
            "",
            "### Blockers",
            "",
            *_bullet_lines(session["blockers"]),
            "",
            "### Exact next action",
            "",
            _one_line(session["next_action"]),
            "",
            "## Provenance",
            "",
            f"- Bundle: `{_one_line(bundle['bundle_id'])}`",
            f"- Source: {_one_line(provenance['source'])}",
            f"- Generated at: {_one_line(provenance['generated_at'])}",
            f"- Synthetic: `{str(provenance['synthetic']).lower()}`",
            "",
        ]
    )
    return "\n".join(lines)


def _write_bundle(bundle: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(bundle, indent=2, sort_keys=True))
    else:
        print(render_markdown(bundle), end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daemonstate-demo",
        description="Validate and render DaemonState's offline synthetic public demo.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="Render the bundled synthetic example.")
    demo.add_argument("--format", choices=("markdown", "json"), default="markdown")

    validate = subparsers.add_parser("validate", help="Validate a public demo JSON bundle.")
    validate.add_argument("path", type=Path)

    render = subparsers.add_parser("render", help="Render a validated public demo JSON bundle.")
    render.add_argument("path", type=Path)
    render.add_argument("--format", choices=("markdown", "json"), default="markdown")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            _write_bundle(load_bundled_example(), args.format)
        elif args.command == "validate":
            bundle = load_bundle(args.path)
            print(f"VALID {bundle['schema_version']} {bundle['bundle_id']}")
        elif args.command == "render":
            _write_bundle(load_bundle(args.path), args.format)
        else:  # pragma: no cover - argparse guarantees the command set.
            parser.error("unknown command")
    except BundleValidationError as exc:
        for error in exc.errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
