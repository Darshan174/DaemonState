# Waitlist storage

The public Cloudflare Pages deployment handles `POST /api/waitlist` through
`functions/api/waitlist.js`.

Create a Cloudflare D1 database and bind it to the Pages project as
`WAITLIST_DB` for both Preview and Production. The function creates the
`waitlist_signups` table and its timestamp index on first use, so no manual
schema migration is required.

The FastAPI deployment exposes the same endpoint and stores signups in its
configured SQL database.
