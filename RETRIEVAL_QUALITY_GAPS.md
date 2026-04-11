# Retrieval Quality Gaps — Post-Hardening Assessment

This document catalogs remaining retrieval-quality gaps after the extraction/ingestion pipeline hardening pass.

## Addressed in This Pass

| Gap | Resolution |
|-----|-----------|
| Raw `json_object` prompting | Upgraded to Pydantic schema-constrained `response_format` via LiteLLM |
| No few-shot guidance | Added connector-specific examples for Slack, Zoom, GitHub |
| Unlimited document size | Truncation at `extraction_max_input_chars` (default 16K) + overlapping chunk extraction |
| One-fact-at-a-time embeddings | Batch embedding via `embed_texts()` with configurable batch size |
| Ambiguous dev embedder | `HashingEmbedder` clearly marked as TEST-ONLY; `LocalEmbedder` (sentence-transformers) added for semantic offline dev |
| No failure isolation in batches | Per-document savepoints via `begin_nested()` |

## Remaining Gaps

### 1. Chunk Merging Loses Cross-Chunk Relationships
**Severity:** Medium

When a document is chunked, each chunk is extracted independently. Relationships that span chunk boundaries (e.g., a decision in chunk 1 referenced by a blocker in chunk 2) will not be detected.

**Mitigation:** Current deduplication prevents duplicate facts. Future improvement: a second-pass relationship resolution step that looks at all extracted facts together.

### 2. No Reranker Feedback Loop
**Severity:** Medium

The `enable_reranking` setting exists but the reranker output doesn't feed back into extraction confidence. Facts extracted with low confidence could benefit from reranker-informed adjustments.

### 3. Hashing Embedder in Tests Masks Embedding Quality Issues
**Severity:** Low

Tests use `HashingEmbedder` which produces deterministic but non-semantic vectors. This means integration tests can't catch embedding-model-specific retrieval regressions.

**Mitigation:** `LocalEmbedder` (sentence-transformers) is available for tests that need semantic vectors. Opt-in via `ENABLE_LOCAL_EMBEDDER=true`.

### 4. No Extraction Quality Telemetry
**Severity:** Low

There's no tracking of:
- How often the LLM extractor fails and falls back to regex
- Average confidence per connector type
- Chunk extraction yield (facts per chunk)

Adding telemetry would help identify which connectors or document types need prompt tuning.

### 5. Fixed Few-Shot Examples
**Severity:** Low

The few-shot examples are static strings. They don't adapt to:
- Domain-specific terminology (e.g., "SaaS" vs "on-premise")
- Language variations
- Connector-specific edge cases (e.g., Slack threaded replies vs. channel messages)

Future improvement: dynamically selected few-shot examples based on document metadata.

### 6. No Ground-Truth Evaluation Pipeline
**Severity:** Medium

There's no automated eval that measures extraction precision/recall against a labeled dataset. The `test_evals/` directory has harness scaffolding but no gold-set-based extraction quality metrics.

### 7. Confidence Scores Are Not Calibrated
**Severity:** Medium

Extractor confidence values (0.0–1.0) are not calibrated against actual correctness rates. A confidence of 0.8 from the LLM doesn't mean "80% correct" — it's a relative signal.

**Mitigation:** Future calibration against a gold set could map raw confidence to empirical accuracy rates.

### 8. No Cross-Document Entity Resolution
**Severity:** High

Facts like "Decision to migrate to Postgres" from a Slack message and "Postgres migration decision" from a Notion doc are treated as separate components because their names don't match. No entity resolution or name normalization beyond simple string matching.

### 9. Truncation May Drop Critical Context
**Severity:** Medium

When documents exceed `extraction_max_input_chars`, the tail is dropped with a truncation marker. Important decisions or action items near the end of long documents may be missed.

**Mitigation:** Chunk extraction helps, but chunks are processed independently and the final merge only deduplicates — it doesn't re-rank or prioritize which chunks' facts are most important.
