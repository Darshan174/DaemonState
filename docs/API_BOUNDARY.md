# Hosted API boundary

No production DaemonState endpoint, credential, or hosted client is bundled in
this staging export. Endpoint names, authentication, quotas, and commercial
entitlements remain under review.

When a hosted integration is published, the boundary should be:

1. A public client sends a versioned, minimal request.
2. The private service authenticates the caller and enforces entitlements.
3. The private engine performs extraction, compilation, ranking, and checks.
4. The service returns a documented public response or an explicit error.
5. The client validates the version and lets the user review the result.

The client must never treat a hidden button or local feature flag as an access
control. It must also avoid accepting executable commands in a returned bundle.

This document is a security and ownership boundary, not an API availability
claim. Add concrete URLs and request examples only after the private API contract
has been finalized and reviewed for information leakage.
