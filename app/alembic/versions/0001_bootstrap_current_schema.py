from __future__ import annotations

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.models import Base
from app.services.vector_search import pgvector_index_dimension

revision = "0001_bootstrap_current_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    _setup_pgvector(bind)
    _setup_postgres_text_search(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _drop_postgres_text_search(bind)
    _drop_pgvector_helpers(bind)
    Base.metadata.drop_all(bind=bind)


def _setup_pgvector(bind: Connection) -> None:
    if bind.dialect.name != "postgresql" or not _pgvector_available(bind):
        return

    try:
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        bind.execute(text("ALTER TABLE components ADD COLUMN IF NOT EXISTS embedding_vector vector"))
        bind.execute(text("""
            CREATE OR REPLACE FUNCTION ce_try_vector(raw text) RETURNS vector AS $$
            BEGIN
                IF raw IS NULL OR btrim(raw) = '' THEN
                    RETURN NULL;
                END IF;
                RETURN raw::vector;
            EXCEPTION WHEN others THEN
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE
        """))
        bind.execute(text("""
            UPDATE components
            SET embedding_vector = ce_try_vector(embedding)
            WHERE embedding_vector IS NULL
              AND embedding IS NOT NULL
              AND embedding != ''
        """))
        bind.execute(text("""
            CREATE OR REPLACE FUNCTION ce_sync_component_embedding_vector()
            RETURNS trigger AS $$
            BEGIN
                NEW.embedding_vector = ce_try_vector(NEW.embedding);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """))
        bind.execute(text("DROP TRIGGER IF EXISTS trg_components_embedding_vector ON components"))
        bind.execute(text("""
            CREATE TRIGGER trg_components_embedding_vector
            BEFORE INSERT OR UPDATE OF embedding ON components
            FOR EACH ROW
            EXECUTE FUNCTION ce_sync_component_embedding_vector()
        """))

        dimension = pgvector_index_dimension()
        bind.execute(text(f"""
            CREATE INDEX IF NOT EXISTS ix_components_embedding_vector_hnsw
            ON components
            USING hnsw ((embedding_vector::vector({dimension})) vector_cosine_ops)
            WHERE embedding_vector IS NOT NULL
              AND vector_dims(embedding_vector) = {dimension}
        """))
    except Exception:
        # Keep Alembic usable on hosted Postgres plans where extension creation
        # requires elevated privileges. The app falls back to Python retrieval.
        return


def _drop_pgvector_helpers(bind: Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("DROP TRIGGER IF EXISTS trg_components_embedding_vector ON components"))
    bind.execute(text("DROP FUNCTION IF EXISTS ce_sync_component_embedding_vector()"))
    bind.execute(text("DROP FUNCTION IF EXISTS ce_try_vector(text)"))


def _setup_postgres_text_search(bind: Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    try:
        bind.execute(text("ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS metadata_jsonb jsonb"))
        bind.execute(text("ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS search_tsv tsvector"))
        bind.execute(text("ALTER TABLE components ADD COLUMN IF NOT EXISTS search_tsv tsvector"))
        bind.execute(text("""
            CREATE OR REPLACE FUNCTION ce_try_jsonb(raw text) RETURNS jsonb AS $$
            BEGIN
                IF raw IS NULL OR btrim(raw) = '' THEN
                    RETURN '{}'::jsonb;
                END IF;
                RETURN raw::jsonb;
            EXCEPTION WHEN others THEN
                RETURN '{}'::jsonb;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE
        """))
        bind.execute(text("""
            CREATE OR REPLACE FUNCTION ce_sync_source_document_search()
            RETURNS trigger AS $$
            BEGIN
                NEW.metadata_jsonb = ce_try_jsonb(NEW.metadata);
                NEW.search_tsv =
                    setweight(to_tsvector('english', coalesce(NEW.external_id, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(NEW.source_type, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(NEW.author, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(NEW.content, '')), 'D');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """))
        bind.execute(text("""
            CREATE OR REPLACE FUNCTION ce_sync_component_search()
            RETURNS trigger AS $$
            BEGIN
                NEW.search_tsv =
                    setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(NEW.fact_type, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(NEW.status, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(NEW.temporal, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(NEW.value, '')), 'D');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """))
        bind.execute(text("DROP TRIGGER IF EXISTS trg_source_documents_search ON source_documents"))
        bind.execute(text("""
            CREATE TRIGGER trg_source_documents_search
            BEFORE INSERT OR UPDATE OF metadata, content, external_id, source_type, author
            ON source_documents
            FOR EACH ROW
            EXECUTE FUNCTION ce_sync_source_document_search()
        """))
        bind.execute(text("DROP TRIGGER IF EXISTS trg_components_search ON components"))
        bind.execute(text("""
            CREATE TRIGGER trg_components_search
            BEFORE INSERT OR UPDATE OF name, value, fact_type, status, temporal
            ON components
            FOR EACH ROW
            EXECUTE FUNCTION ce_sync_component_search()
        """))
        bind.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_source_documents_metadata_jsonb_gin
            ON source_documents USING gin (metadata_jsonb)
        """))
        bind.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_source_documents_search_tsv_gin
            ON source_documents USING gin (search_tsv)
        """))
        bind.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_components_search_tsv_gin
            ON components USING gin (search_tsv)
        """))
    except Exception:
        return


def _drop_postgres_text_search(bind: Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    bind.execute(text("DROP TRIGGER IF EXISTS trg_source_documents_search ON source_documents"))
    bind.execute(text("DROP TRIGGER IF EXISTS trg_components_search ON components"))
    bind.execute(text("DROP FUNCTION IF EXISTS ce_sync_source_document_search()"))
    bind.execute(text("DROP FUNCTION IF EXISTS ce_sync_component_search()"))
    bind.execute(text("DROP FUNCTION IF EXISTS ce_try_jsonb(text)"))


def _pgvector_available(bind: Connection) -> bool:
    try:
        result = bind.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'vector'
            )
        """))
        return bool(result.scalar())
    except Exception:
        return False
