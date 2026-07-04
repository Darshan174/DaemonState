# Codex Run

Decision: keep GitHub pagination source-first by storing every fetched issue page
as SourceDocument evidence before extraction.

Task: update app/github_sync.py and add regression coverage in
tests/test_github_sync.py.

Risk: stale connector status copy must not imply unsupported providers are
connected.
