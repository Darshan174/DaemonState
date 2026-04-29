What It Is

Context Engine is an open-source structured context infrastructure for AI systems and fast-moving teams. It is purpose-built to be the trust and memory layer that sits alongside RAG frameworks like LangChain and LlamaIndex.

The Core Problem It Solves

Company knowledge is scattered across Slack, Notion, Zoom transcripts, GitHub issues, meeting notes, and local documents. Traditional RAG gives you retrieval, but it doesn't answer:

Where did this answer come from?
Is this still true?
What changed?
Has a human reviewed this?
Which decision superseded the old one?
Context Engine's philosophy is: facts should be structured, answers should cite sources, and stale/conflicting information should be visible—not silently averaged away.

Architecture & Tech Stack

Backend

Layer	Technology
Framework	FastAPI (async Python 3.12+)
ORM	SQLAlchemy 2.0 with asyncpg
Database	PostgreSQL 16 with pgvector extension
Task Queue	Redis + Celery
Migrations	Alembic
LLM Gateway	LiteLLM (provider-agnostic: OpenAI, Anthropic, etc.)
Embeddings	Configurable (default: OpenAI text-embedding-3-large, 1024 dims). Includes deterministic HashingEmbedder for tests and LocalEmbedder (sentence-transformers) for offline dev
Build	Hatchling
CLI	ctxe (custom Click/Typer-style CLI)
Frontend

Layer	Technology
Framework	React 18
Build Tool	Vite
Styling	Tailwind CSS
State/Data Fetching	TanStack React Query
Routing	React Router DOM v6
Testing	Vitest + React Testing Library
Animation	Framer Motion
Infrastructure

Docker Compose stack with 4 services: postgres, redis, api, worker
Multi-stage Dockerfile: Node 20 builds the frontend; Python 3.12 slim serves it via FastAPI
Safer-by-default networking: Postgres, Redis, and API bind to 127.0.0.1 by default (not exposed to the public internet)
Resource limits: Fits comfortably on a 2 vCPU / 4 GB VPS (~2.8 GB total RAM reservation)
Core Data Model

The system is built around a temporal knowledge graph with these key entities:

Workspace — Multi-tenant boundary
SourceDocument — Raw ingested content from connectors (Slack, Notion, Zoom, GitHub, GDrive, Gong, Local)
KnowledgeModel — Groupings of facts (auto-generated per connector or manual)
Component — The atomic structured fact (a decision, action item, blocker, or discussion). Each has:
Confidence (0–1)
Authority weight (per connector: Notion=0.95, Slack=0.75, etc.)
Temporal validity (valid_from, valid_to, superseded_by)
Staleness flag
Embedding vector (1024-dim pgvector)
Relationship — Typed graph edges: depends_on, blocked_by, enables, contradicts, supersedes, related_to
ComponentSource — Provenance junction table linking facts to source documents, with extraction metadata, content hash, and extractor fingerprinting
ReviewItem — Trust queue entries (approved, needs_review, rejected, superseded) with severity, rationale, and suggested action
ReviewDecision — Immutable audit trail of all status transitions
The Processing Pipeline

Ingestion Flow

Connectors pull raw documents into SourceDocument
Celery worker picks up unprocessed docs
IngestionService extracts facts via the Extractor hierarchy:
StructuredLLMExtractor — Pydantic schema-constrained extraction via LiteLLM, with connector-specific few-shot examples and overlapping chunking for long docs
RegexExtractor — Local deterministic fallback (no API needed). Pattern-matches decisions, action items, blockers, meeting outcomes
FallbackExtractor — Tries structured first, falls back to regex
Facts are deduplicated, linked to sources, and embedded in batches
Conflict resolution runs: higher-authority sources can auto-supersede lower-authority ones. Conflicts create ReviewItem entries.
Orphaned components (no supporting sources) are auto-retired
Query/Retrieval Engine

This is where the product differentiation lives. The scoring is multi-factor:

Factor	What It Does
Lexical	Token overlap on component name, value, authority source
Semantic	Cosine similarity of query embedding vs component embedding
Authority	Connector-specific weight (e.g., Notion > Slack)
Source Support	Bonus for facts backed by multiple documents
Review Status	Bonus for approved, penalty for needs_review
Freshness	Penalty for stale or aged facts; "current truth" bonus
Reranking	Post-scoring reranker adjusts final ordering
Relationships	If the query hints at dependencies/blockers, relevant edges are surfaced
The system also supports temporal queries (as_of date) so you can ask "What was true on March 1st?"

Product Workflows (Frontend)

View	Purpose
Founder Brief	Recent changes, blockers, conflicts, risk signals
Ask (Query)	Source-backed Q&A with citations
Decision Register	Current and historical decisions with rationale
Changes	Timeline of updates, ingests, reviews, failures
Launch Guard	Check outbound claims against current known truth
Sources	Browse source documents and imported evidence
Models	Browse extracted knowledge models and components
Knowledge Graph	Visual graph exploration
Review Queue	Human-in-the-loop review for low-confidence or conflicting facts
System Health	Operator status for self-hosted deployments
Evaluation & Quality Rigor

The project includes a deterministic startup-memory benchmark comparing Context Engine against a naive source-only RAG baseline:

Answer quality
Citation accuracy
Stale context detection
Context lift
The team maintains an honest Retrieval Quality Gaps document (RETRIEVAL_QUALITY_GAPS.md) cataloging known limitations:

Cross-chunk relationship loss
No reranker feedback loop into extraction confidence
Confidence scores not calibrated against empirical accuracy
No cross-document entity resolution (e.g., "Postgres migration" vs "migrate to Postgres")
Fixed few-shot examples (not domain-adaptive)
This level of self-awareness in an OSS project is a strong signal of engineering maturity.

Operations & DevOps Maturity

Tool	Purpose
scripts/bootstrap.sh	One-command idempotent full-stack setup
scripts/smoke.sh	Post-deploy verification
scripts/backup.sh / restore.sh	Validated pg_dump with rotation and TOC validation
scripts/diagnose.sh	Runtime triage tarball (logs, health, redacted config)
ctxe verify	Full maintainer release gate (backend + frontend tests + lint + build)
GitHub Actions	backend-accuracy.yml, release-gate.yml
Design Philosophy & Strategic Positioning

Self-host first, zero external dependencies — The default OSS path requires no API keys. It uses local deterministic embeddings and regex extraction. This is a deliberate product decision to reduce friction.
Trust over retrieval — The system is opinionated that citations, review state, conflict visibility, and temporal validity are first-class concerns, not afterthoughts.
Temporal awareness — Facts have validity windows. The system can answer "what was true then?" not just "what is true now?"
Fail-isolated batches — Per-document savepoints during ingestion so one malformed document doesn't poison a batch.
Complementary, not competitive — The docs explicitly state this is not a LangChain/LlamaIndex/Ragas replacement. It is designed to be called from those orchestrators via POST /api/query.
Overall Assessment

This is a production-minded, well-architected system built by people who have operated infrastructure at scale. The code shows strong patterns:

Async SQLAlchemy with proper session management
Pydantic schemas for API contracts
Configurable, pluggable extraction and embedding backends
Comprehensive operational tooling (backup, restore, diagnose, smoke tests)
Honest documentation of limitations
Clean separation between ingestion, query, and frontend concerns