from __future__ import annotations

from pathlib import Path
import json
import tomllib


README = Path("README.md")
PYPROJECT = Path("pyproject.toml")
DOCKERFILE = Path("Dockerfile")
DOCTOR_SCRIPT = Path("scripts/doctor.sh")
SMOKE_SCRIPT = Path("scripts/smoke.sh")
DEMO_DOC = Path("docs/demo.md")
MCP_DOC = Path("docs/mcp.md")
MCP_EXAMPLES_DIR = Path("examples/mcp")
BOARD_DEMO_IMAGE = Path("docs/assets/board-inspector-demo.jpg")
QUERY_DEMO_IMAGE = Path("docs/assets/query-trace-demo.jpg")


def test_readme_marks_setup_and_deployment_as_coming_soon():
    text = README.read_text(encoding="utf-8")

    assert "github.com/your-org/context-engine.git" not in text
    assert "## Setup\n\nComing soon." in text
    assert "## Deployment\n\nComing soon." in text
    assert "## Contributing\n\nComing soon." in text
    assert "git clone https://github.com/Darshan174/Context-Engine.git context-engine" not in text
    assert "docker compose up --build" not in text
    assert "bash scripts/setup.sh" not in text
    assert "fly launch" not in text


def test_pyproject_exposes_oss_metadata():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]

    assert project["license"] == {"file": "LICENSE"}
    assert "Context Engine contributors" in {author["name"] for author in project["authors"]}
    assert "self-hosted" in project["keywords"]
    assert "knowledge-graph" in project["keywords"]
    assert "License :: OSI Approved :: MIT License" in project["classifiers"]
    assert "Framework :: FastAPI" in project["classifiers"]
    assert project["urls"]["Repository"] == "https://github.com/Darshan174/Context-Engine"
    assert project["urls"]["Issues"] == "https://github.com/Darshan174/Context-Engine/issues"


def test_dockerfile_copies_license_before_package_install():
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
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


def test_readme_links_real_demo_assets_and_walkthrough():
    readme = README.read_text(encoding="utf-8")
    demo_doc = DEMO_DOC.read_text(encoding="utf-8")

    assert "[Product Tour](#product-tour)" in readme
    assert "docs/assets/board-inspector-demo.jpg" in readme
    assert "docs/assets/query-trace-demo.jpg" in readme
    assert "[Demo Walkthrough](docs/demo.md)" in readme
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

    installed_server = installed["mcpServers"]["context-engine"]
    local_server = local["mcpServers"]["context-engine"]

    assert installed_server == {"command": "ctxe", "args": ["mcp"]}
    assert local_server["command"].endswith("/.venv/bin/ctxe")
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

    assert "public setup path will" in readme
    assert "Coming soon." in readme
    assert "bash scripts/doctor.sh --docker" in demo_doc

    assert "Usage:" in script
    assert "bash scripts/doctor.sh --docker" in script
    assert "bash scripts/doctor.sh --bare-metal" in script
    assert "docker compose up --build" in script
    assert "bash scripts/setup.sh" in script
    assert "bash scripts/smoke.sh --docker" in script
    assert "/api/seed-demo" in script

    assert "pip install" not in script
    assert "npm ci" not in script
    assert "npm install" not in script
    assert "python3 -m venv" not in script
    assert "scripts/doctor.sh" in smoke
