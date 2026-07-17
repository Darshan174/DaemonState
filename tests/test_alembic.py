from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrade_bootstraps_current_sqlite_schema(tmp_path):
    db_path = tmp_path / "context.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "workspaces",
            "connectors",
            "source_documents",
            "components",
            "entity_aliases",
            "facts",
            "mentions",
            "relationships",
            "unresolved_relationships",
            "retrieval_events",
            "open_loops",
            "verified_playbooks",
            "workspace_goals",
            "alembic_version",
        } <= tables

        component_columns = {column["name"] for column in inspector.get_columns("components")}
        assert {
            "workspace_id",
            "entity_id",
            "identity_key",
            "embedding",
            "provenance",
            "excerpt",
        } <= component_columns

        source_columns = {column["name"] for column in inspector.get_columns("source_documents")}
        assert "workspace_id" in source_columns
        assert "metadata" in source_columns

        pack_columns = {column["name"] for column in inspector.get_columns("context_packs")}
        assert {
            "focus_component_id", "objective_origin", "objective_source_document_id",
            "objective_evidence_span_id",
        } <= pack_columns
        observation_columns = {
            column["name"] for column in inspector.get_columns("run_observations")
        }
        assert {"event_key", "payload_json", "observed_at"} <= observation_columns
        file_columns = {column["name"] for column in inspector.get_columns("code_files")}
        symbol_columns = {column["name"] for column in inspector.get_columns("code_symbols")}
        edge_columns = {column["name"] for column in inspector.get_columns("code_edges")}
        assert {"identity_key", "is_test"} <= file_columns
        assert "identity_key" in symbol_columns
        assert {
            "edge_key", "rule_id", "rule_version", "evidence_json",
            "evidence_sha256", "snapshot_fingerprint",
        } <= edge_columns

        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "0006_workspace_goals"
    finally:
        engine.dispose()
