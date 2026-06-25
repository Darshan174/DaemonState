## Summary

-

## Product Contract Checklist

- [ ] Facts remain source-backed through `SourceDocument` provenance.
- [ ] Relationships include evidence, confidence, and origin where applicable.
- [ ] Connector states are honest; unsupported providers are not shown as
      working.
- [ ] Graph UI changes preserve Board-first source grouping and inspector-held
      trust metadata.
- [ ] MCP/query/context-pack responses keep source IDs and traceable evidence.

## Verification

- [ ] `bash scripts/smoke.sh`
- [ ] `python -m pytest tests/ -q`
- [ ] `ruff check app tests`
- [ ] `cd frontend && npm test`
- [ ] `cd frontend && npm run build`

If a check was skipped, explain why:

-

## Screenshots Or API Evidence

Add screenshots, request/response snippets, or trace output for user-facing
changes.
