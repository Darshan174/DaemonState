# Changelog

## 0.3.0 - Unreleased

### Changed

- Changed the project license from MIT to the source-available Sustainable Use
  License 1.0 (`SUL-1.0`). The exact final MIT-licensed source is commit
  `45b7a6e653a1762bf91b99fae4c7adf3dafc55ce`.
- Added a supported, loopback-only personal Docker self-hosting flow with
  generated local secrets, an explicit database migration gate, readiness
  checks, PostgreSQL/pgvector, and the sync worker.
- Added self-hosting, backup, upgrade, security, and licensing guidance.
- The bare-metal start command now supervises both the API and sync worker.
