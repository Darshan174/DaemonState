# Xiaomi Task — Founder Oversight UX and Truth Review

## Role

You are Xiaomi MiMo V2.5 Pro, long-context repository reader and independent
UX/OSS truth reviewer. Review only after the focused loop and scrutiny slices are
integrated.

## Mission

Decide whether a non-technical founder can use the Project map to understand and
challenge AI-agent work without learning DaemonState internals.

## Review questions

1. Can the user find `Prepare for agent` from a relevant selected record?
2. Is generic project briefing clearly different from task preparation?
3. Can the user see what changed, what was checked, what failed, and what remains
   unsupported by completion evidence?
4. Does every warning link to exact evidence and use defensible wording?
5. Are current, stale, conflicting, unknown, and verified states distinguishable?
6. Are the Project map and narrow viewport calm when there are many runs/findings?
7. Are code/compiler/graph details progressively disclosed rather than promoted to
   navigation or permanent dashboard cards?
8. Do README and docs describe only implemented behavior?

## Required verification

- Read the final diff and all focused tests.
- Exercise the complete selected-focus -> prepare -> run -> observe -> scrutinize
  flow with a reproducible fixture.
- Run focused tests, the full frontend suite/build, and relevant backend suites.
- Check desktop and narrow widths in light and dark modes when browser tooling is
  available.

## Deliverable

Provide evidence-backed findings by severity, an application-demo readiness verdict,
and exact correction locations. Small documentation or clearly safe copy/test fixes
are allowed; broad implementation rewrites require Codex assignment.

The final report must include files read/changed, tests, evidence, risks, remaining
gaps, and Observed/Implemented/Proposed/Not implemented yet sections.
