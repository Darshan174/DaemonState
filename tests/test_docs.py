from __future__ import annotations

import hashlib
from pathlib import Path
import json
import tomllib


README = Path("README.md")
ENV_EXAMPLE = Path(".env.example")
GITIGNORE = Path(".gitignore")
PYPROJECT = Path("pyproject.toml")
DOCKERFILE = Path("Dockerfile")
COMPOSE = Path("docker-compose.yml")
PRODUCTION_COMPOSE = Path("docker-compose.production.yml")
FRONTEND_PACKAGE = Path("frontend/package.json")
DOCTOR_SCRIPT = Path("scripts/doctor.sh")
SELF_HOST_SCRIPT = Path("scripts/self-host.sh")
SMOKE_SCRIPT = Path("scripts/smoke.sh")
LICENSE = Path("LICENSE")
NOTICE = Path("NOTICE")
THIRD_PARTY_NOTICES = Path("THIRD_PARTY_NOTICES.txt")
SELF_HOST_DOC = Path("docs/self-hosting.md")
LICENSING_DOC = Path("docs/licensing.md")
DEMO_DOC = Path("docs/demo.md")
MCP_DOC = Path("docs/mcp.md")
MCP_EXAMPLES_DIR = Path("examples/mcp")
BOARD_DEMO_IMAGE = Path("docs/assets/board-inspector-demo.jpg")
QUERY_DEMO_IMAGE = Path("docs/assets/query-trace-demo.jpg")


def test_readme_documents_honest_setup_deployment_and_contributing_paths():
    text = README.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
    gitignore = GITIGNORE.read_text(encoding="utf-8")

    assert "github.com/your-org/daemonstate.git" not in text
    assert "git clone https://github.com/Darshan174/DaemonState.git daemonstate" in text
    assert "bash scripts/self-host.sh" in text
    assert "bash scripts/doctor.sh --bare-metal" in text
    assert "bash scripts/setup.sh" in text
    assert "Node.js 20.19+ on the 20.x line" in text
    assert "22.13+ on the 22.x line, or 24+" in text
    assert "[CONTRIBUTING.md](CONTRIBUTING.md)" in text
    assert "It is not a production hardening guide" in text
    assert "There are no built-in Codex" not in text
    assert "requests a new composer" in text
    assert "not as a verified open" in text
    assert "There is no system-wide agent monitor" in text
    assert "local harness is the path that independently inspects Git state" in " ".join(text.split())
    assert "Continue automatically captures the selected session tip" in text
    assert "Explain and agent brief" in text
    assert "rather than every UI" in " ".join(text.split())
    assert "The API preserves revisions and enforces access scopes" in text
    assert "| Library |" in text
    assert "| Memory |" in text
    assert "source-available" in text
    assert "Sustainable Use License 1.0" in text
    assert "[Self-hosting](docs/self-hosting.md)" in text
    assert "fly launch" not in text

    assert "DATABASE_URL=sqlite+aiosqlite:///data/context.db" in env_example
    assert "POSTGRES_PASSWORD=daemonstate" in env_example
    assert "LITELLM_API_KEY=" in env_example
    assert "ENCRYPTION_KEY=" in env_example
    assert "GOOGLE_CLIENT_ID=" in env_example
    assert "SLACK_CLIENT_ID=" in env_example
    assert "!.env.example" in gitignore


def test_pyproject_exposes_source_available_metadata():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]

    assert project["license"] == "SUL-1.0"
    assert project["license-files"] == [
        "LICENSE",
        "NOTICE",
        "THIRD_PARTY_NOTICES.txt",
    ]
    assert project["version"] == "0.3.0"
    assert "DaemonState contributors" in {author["name"] for author in project["authors"]}
    assert "self-hosted" in project["keywords"]
    assert "knowledge-graph" in project["keywords"]
    assert "License :: OSI Approved :: MIT License" not in project["classifiers"]
    assert "Framework :: FastAPI" in project["classifiers"]
    assert project["urls"]["Repository"] == "https://github.com/Darshan174/DaemonState"
    assert project["urls"]["Issues"] == "https://github.com/Darshan174/DaemonState/issues"
    assert any(
        dependency.startswith("sqlalchemy[asyncio]")
        for dependency in project["dependencies"]
    )


def test_dockerfile_copies_license_before_package_install():
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    package = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))

    assert lines[1] == "FROM node:24-slim AS frontend-builder"
    assert package["engines"]["node"] == "^20.19.0 || ^22.13.0 || >=24.0.0"
    copy_line_number = next(
        index for index, line in enumerate(lines)
        if line.startswith("COPY ") and "pyproject.toml" in line
    )
    install_line_number = next(
        index for index, line in enumerate(lines)
        if line.strip() == "RUN pip install --no-cache-dir ."
    )

    assert copy_line_number < install_line_number
    assert "README.md" in lines[copy_line_number]
    assert "LICENSE" in lines[copy_line_number]


def test_compose_passes_the_session_handoff_experiment_variant():
    expected = (
        "SESSION_HANDOFF_BRIEF_VARIANT: "
        "${SESSION_HANDOFF_BRIEF_VARIANT:-compact_v2}"
    )

    assert expected in COMPOSE.read_text(encoding="utf-8")
    assert expected in PRODUCTION_COMPOSE.read_text(encoding="utf-8")


def test_license_and_self_hosting_contracts_are_explicit():
    license_text = LICENSE.read_text(encoding="utf-8")
    licensing = LICENSING_DOC.read_text(encoding="utf-8")
    self_hosting = SELF_HOST_DOC.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    script = SELF_HOST_SCRIPT.read_text(encoding="utf-8")
    package = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))
    normalized_license = " ".join(license_text.split())

    assert hashlib.sha256(LICENSE.read_bytes()).hexdigest() == (
        "73a310b6732d14a636e10a5d6dcf9ca7122ff7870ef06dfa07a872ddb152752a"
    )
    assert "internal business purposes" in normalized_license
    assert "free of charge for non-commercial purposes" in normalized_license
    assert "Versions through 0.2.0" in licensing
    assert "45b7a6e653a1762bf91b99fae4c7adf3dafc55ce" in licensing
    assert "source-available" in licensing
    assert package["license"] == "SUL-1.0"
    assert "Darshan174" in NOTICE.read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in THIRD_PARTY_NOTICES.read_text(
        encoding="utf-8"
    )

    assert '${BIND_ADDRESS:-127.0.0.1}:${PORT:-8000}:8000' in compose
    assert 'command: ["daemonstate", "db", "deploy"]' in compose
    assert "condition: service_completed_successfully" in compose
    assert "GOOGLE_CLIENT_SECRET" in compose
    assert "SLACK_CLIENT_SECRET" in compose
    assert "/health/ready" in compose
    assert "SYNC_WORKER_HEALTH_FILE" in compose
    assert "docker compose up --build --detach --wait" in script
    assert "chmod 0600 .env" in script
    assert "SSH tunnel" in self_hosting
    assert "SERVE_FRONTEND=false" in self_hosting


def test_readme_is_short_plain_language_and_uses_the_product_logo():
    readme = README.read_text(encoding="utf-8")
    demo_doc = DEMO_DOC.read_text(encoding="utf-8")

    assert len(readme.splitlines()) <= 280
    assert '<img src="frontend/public/favicon.svg"' in readme
    assert "Founders and non-technical users" in readme
    assert "Developers" in readme
    assert "durable Project Context foundation" in readme
    assert "We have not proven that yet" in " ".join(readme.split())
    assert "DaemonState is not another coding agent" in readme
    assert "![" not in readme
    assert "docs/assets/board-inspector-demo.jpg" not in readme
    assert "docs/assets/query-trace-demo.jpg" not in readme
    assert "[Demo walkthrough](docs/demo.md)" in readme
    assert BOARD_DEMO_IMAGE.is_file()
    assert BOARD_DEMO_IMAGE.stat().st_size > 10_000
    assert QUERY_DEMO_IMAGE.is_file()
    assert QUERY_DEMO_IMAGE.stat().st_size > 10_000

    assert "/api/seed-demo" in demo_doc
    assert "SourceDocument" in demo_doc
    assert "fake connected state" in demo_doc
    assert "query.v1" in demo_doc


def test_mcp_examples_match_real_cli_entrypoint():
    readme = README.read_text(encoding="utf-8")
    mcp_doc = MCP_DOC.read_text(encoding="utf-8")

    assert "[MCP examples](examples/mcp/)" in readme
    assert "[examples/mcp](../examples/mcp/)" in mcp_doc

    installed = json.loads((MCP_EXAMPLES_DIR / "installed-cli.json").read_text(encoding="utf-8"))
    local = json.loads((MCP_EXAMPLES_DIR / "local-checkout.json").read_text(encoding="utf-8"))

    installed_server = installed["mcpServers"]["daemonstate"]
    local_server = local["mcpServers"]["daemonstate"]

    assert installed_server == {"command": "daemonstate", "args": ["mcp"]}
    assert local_server["command"].endswith("/.venv/bin/daemonstate")
    assert local_server["args"] == ["mcp"]

    prompt = (MCP_EXAMPLES_DIR / "agent-system-prompt.md").read_text(encoding="utf-8")
    assert "query_context" in prompt
    assert "trace.facts_used" in prompt
    assert "Coming-soon connectors" in prompt


def test_doctor_script_is_documented_and_read_only():
    readme = README.read_text(encoding="utf-8")
    demo_doc = DEMO_DOC.read_text(encoding="utf-8")
    script = DOCTOR_SCRIPT.read_text(encoding="utf-8")
    smoke = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "bash scripts/self-host.sh" in readme
    assert "bash scripts/doctor.sh --bare-metal" in readme
    assert "bash scripts/self-host.sh" in demo_doc

    assert "Usage:" in script
    assert "bash scripts/doctor.sh --docker" in script
    assert "bash scripts/doctor.sh --bare-metal" in script
    assert "bash scripts/self-host.sh" in script
    assert "bash scripts/setup.sh" in script
    assert "bash scripts/smoke.sh --docker" in script
    assert "/api/seed-demo" in script

    assert "pip install" not in script
    assert "npm ci" not in script
    assert "npm install" not in script
    assert "python3 -m venv" not in script
    assert "scripts/doctor.sh" in smoke
