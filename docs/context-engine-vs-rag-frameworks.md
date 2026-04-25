# Context Engine vs RAG Frameworks

Context Engine is not a LangChain, LlamaIndex, Ragas, or vector-database
replacement. It is the trust and memory layer teams can put next to those tools
when plain retrieval is no longer enough.

## Use Context Engine When

- answers need source citations that a human can inspect
- old decisions are frequently superseded by newer evidence
- conflicting source documents should be visible, not silently averaged away
- review status matters before an answer reaches users
- teams need to ask "what changed?" and "is this still true?"

## Use Plain RAG When

- documents are mostly static
- approximate answers are acceptable
- citations and review state are not part of the product contract
- the system does not need to track decision history or stale facts

## With LangChain

Use LangChain for orchestration, tools, agents, and provider integrations. Use
Context Engine as a source-backed context API inside that chain.

Example flow:

1. LangChain receives a user request.
2. The chain calls `POST /api/query` with the workspace and question.
3. Context Engine returns an answer, confidence, freshness, components, and
   source citations.
4. LangChain uses that result as grounded context for the final assistant step.

Context Engine owns the memory, provenance, review, and freshness model.
LangChain owns the application orchestration.

## With LlamaIndex

Use LlamaIndex for document indexing, retrieval experiments, and advanced query
composition. Use Context Engine when those retrieved documents need to become
reviewable facts, decisions, blockers, and timelines.

Example flow:

1. LlamaIndex retrieves candidate documents or chunks.
2. Context Engine imports the raw documents through local import or connectors.
3. Context Engine extracts structured facts and stores provenance.
4. The app queries Context Engine for current, reviewed, source-backed context.

LlamaIndex can be the retrieval workbench. Context Engine becomes the operating
memory that tracks whether retrieved knowledge is current and supported.

## With Ragas

Use Ragas when you want LLM-based RAG evaluation metrics. Use Context Engine's
eval system when you need deterministic OSS regression checks that run offline
against a known startup-memory dataset.

They are complementary:

| Need | Use |
| --- | --- |
| LLM-graded faithfulness and answer relevancy | Ragas |
| Offline regression gate for known source-backed facts | Context Engine evals |
| Before/after comparison against plain RAG | Context Engine evals |
| Broader experiment analysis across generated answers | Ragas plus exported Context Engine results |

## Architecture Role

```text
sources -> extracted facts -> graph/decisions -> reviewed context -> answer
```

That is the lane Context Engine focuses on: not more retrieval plumbing, but
evidence-backed operational memory for AI systems.
