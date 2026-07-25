# Project Map

`/app/explain` is the selected workspace's project map. It is an inspection
surface around the continuation runtime, not the primary workflow. It projects
imported `SourceDocument` revisions and repository scope; it is not a provider
client and it does not invent project intent.

`/app` is the primary Continue surface. The old `/app/dashboard` URL redirects
there, while `/app/graph` redirects to `/app/explain`. Sources and Integrations
remain setup destinations; Library, History, Memory, and Evidence are grouped
as inspection surfaces.

## Observed behavior

- A workspace without a project boundary asks for one absolute local repository
  path. `POST /api/repo/index` validates and persists the repository index.
- A configured GitHub repository also establishes a project identity. The
  digest exposes normalized `project_paths` and `project_repositories` values.
- Local repository intake creates a trusted `local_repository` source revision
  with deterministic repository-root and top-level-area components. The System
  zone therefore appears before any external source or AI session is imported.
- Once the boundary exists, the map arranges source-backed records into AI
  sessions, system, direction, delivery, risks, checks, next steps, and supporting
  evidence. These zones are visual grouping, not factual relationships.
- The canvas draws only links returned by the backend digest. Selecting a node
  quiets unrelated records, labels its sourced one-hop links, and opens a single
  evidence inspector.
- AI-session relevance is conveyed on the canvas through saturation, opacity,
  and border style. Relevant sessions are solid and prominent; unknown sessions
  are quieter and dotted; different-project sessions are faint, grayscale, and
  dashed. The inspector exposes the deterministic reasons to assistive
  technology and users who select the session.
- Unknown or different-project session roots remain visible as imported
  evidence, but their derived components do not contribute to project health,
  recommendations, clusters, or factual links.
- Incremental refresh processes pending imported snapshots. Rebuild re-extracts
  current snapshots. Neither operation contacts GitHub or another provider;
  provider refresh remains a Connector action.
- Pull requests and issues are shown only when typed provider metadata supports
  the classification. Their state is an imported snapshot, not claimed live
  provider state.
- Decisions and blockers require typed components and exact source evidence.
  Agent suggestions remain supporting evidence unless explicitly confirmed.

## Interaction and accessibility

- Pointer drag pans; wheel or trackpad input zooms inside the map.
- The compact zoom controls and Fit action reset orientation without a minimap
  or layout-mode chooser.
- Search visually quiets non-matching records without hiding provenance.
- **Copy handoff** compiles and persists `context_pack.v2`, then copies its
  Markdown. Compiler prompt-injection, evidence, truth-state, and relevance
  exclusions remain in force. A system-generated project-snapshot purpose is
  recorded separately and is never surfaced as a user-supplied objective.
- Evidence nodes and actions are keyboard selectable. `Escape` clears the
  selected node or closes the action menu.
- Relevance remains available in accessible node names and the inspector even
  though no relevance labels clutter the canvas.

## Not implemented yet

- Semantic relevance for sessions that lack a deterministic repository, path,
  or commit match. Those sessions remain `unknown`.
- A canonical, human-approved project-intention model inferred from imported
  history.
- Capability mapping, product-gap detection, broken-component diagnosis, or a
  code-slop detector.
- A validated broken-document crawler.
- A live provider-state stream inside the map.
- Explicit capability-gap and broken-component nodes derived from verified
  implementation evidence.

## Anti-hallucination rules

- Do not classify zones from title keywords or URL patterns in the frontend.
- Do not draw decorative or inferred edges as facts.
- Do not call graph-row lifecycle status a GitHub provider state.
- Do not call a provider snapshot current without item-level observation proof.
- Do not infer an objective from sessions, issues, pull requests, topology, or
  attention ranking.
- Do not promote an assistant recommendation to a project decision without
  explicit confirmation.
