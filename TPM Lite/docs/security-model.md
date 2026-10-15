# Security and SaaS model

## Identity and authentication

Production authentication is designed for Microsoft Entra ID using OIDC. Local mock authentication is development-only, isolated from production configuration, and must not grant real enterprise identity. Prefer a backend BFF/secure, HttpOnly, Secure, SameSite cookie session for browser deployment; if a token architecture is selected, token storage, refresh, revocation, and CSRF/XSS controls require an explicit review.

Map the authenticated issuer/subject to an internal user UUID. Do not rely on display name or email as a stable identity key.

## Authorization

Use server-side RBAC plus data scopes for every protected read and write. Roles: Commercial Planner, Demand Planner, Approver, Finance Viewer, Integration Support, Master Data Viewer, Application Administrator, and Read-Only Auditor.

Authorization evaluates tenant, market, sales organization, Plan Account, role, promotion lifecycle, and action. Default deny; deny cross-tenant access; re-check on every API request. Frontend route hiding is usability only, never an access control.

## Tenant isolation

Default model: tenant-aware tables and tenant-scoped repository queries/unique constraints, with tenant identity sourced from validated server authentication context. Never accept a client-supplied tenant as proof of access. PostgreSQL row-level security may be added as defense in depth after migration/session-pooling behavior is designed and tested. Single-tenant deployment remains possible as a deployment profile, not as an excuse to omit tenant boundaries from the SaaS data model.

## Data, validation, and audit

- Pydantic request validation and parameterized SQLAlchemy statements.
- Enforce promotion state transitions, scope filters, optimistic locking, and idempotency server-side.
- Audit promotion, planning, approval, configuration, master-sync, and integration lifecycle events.
- Treat audit records as append-only, access restricted, and protected by a defined retention policy.
- Mask credentials, tokens, personal data, and sensitive payload fields in structured logs; do not emit complete integration payloads by default.
- Protect stored credentials and integration payloads with deployment encryption and managed secret storage.

## Web and service protections

- TLS at the ingress; secure response headers and a restrictive Content Security Policy.
- Explicit CORS allowlist and CSRF protections for cookie-authenticated unsafe requests.
- Rate-limit login, expensive report/export, and integration-trigger endpoints.
- Set body/upload limits and validate uploaded CSV/XLSX content, schema, and size in later phases.
- Use environment-based configuration, least-privilege database and service accounts, and never commit `.env`.
- Expose separate liveness/readiness checks without secrets, SQL, stack traces, or internal configuration.

## Supply chain and operations

CI should run frontend/backend lint, type checks, tests, builds, dependency vulnerability checks, and container/image scanning where available. Pin or lock release dependencies and build reproducible images. Production requires managed secrets, least privilege, backups with tested recovery, retention policy, alerting, incident response, and per-tenant/data-scope access reviews.

## Phase 1 security limits

The foundation's health endpoints are unauthenticated operational endpoints and return only service status. No business endpoint, mock login, secret, real customer data, or production integration is present. Production security controls must be implemented and tested before business data is enabled.
