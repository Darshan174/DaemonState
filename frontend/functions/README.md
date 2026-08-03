# Public waitlist operations

The public Cloudflare Pages deployment handles `POST /api/waitlist` through
`functions/api/waitlist.js`. Its bound D1 database is the canonical store for
signups submitted on `daemonstate.com`. The FastAPI endpoint uses the same
request fields for local and self-hosted development, but it is not a replica
of the hosted D1 list.

## D1 setup and migrations

Create separate preview and production D1 databases, then bind the appropriate
database to each Pages environment using the variable name `WAITLIST_DB`.

Schema changes are versioned in `migrations/`. Apply migrations before deploying
a Function that depends on them:

```sh
npx wrangler d1 migrations apply <PREVIEW_DATABASE_NAME> --remote
npx wrangler d1 migrations apply <PRODUCTION_DATABASE_NAME> --remote
```

`0001_waitlist_tracking.sql` preserves rows created by the original email-only
Function while expanding them with attribution, lifecycle, consent, and provider
sync fields. The Function deliberately does not create or alter tables during a
signup request.

## Loops

Create a Loops event named `waitlistJoined` and use it to trigger the confirmation
workflow. Add these Cloudflare Pages variables for Preview and Production:

- `LOOPS_API_KEY`: encrypted secret containing the Loops API key.
- `LOOPS_WAITLIST_EVENT`: optional plain variable; defaults to `waitlistJoined`.

The Function commits D1 first, then sends the Loops event through `waitUntil()`.
Successful and failed attempts update `email_sync_status`; a duplicate submission
retries a record that has not synchronized. Provider failure never removes the
durable D1 signup.

## PostHog

Set `VITE_POSTHOG_KEY` and, when needed, `VITE_POSTHOG_HOST` in the Pages build
environment. The browser records only these manually defined events:

- `landing_viewed`
- `waitlist_cta_clicked`
- `waitlist_joined`

Autocapture, session replay, person profiles, and persistent browser storage are
disabled. Email addresses are not passed to PostHog.

## Abuse controls

The Function validates request size, origin, email, campaign fields, consent
version, and a hidden honeypot. Configure a Cloudflare rate-limiting rule for
`POST /api/waitlist` as an additional edge control; account-level WAF rules are
operational configuration and are not stored in this repository.
