# Implementation roadmap

## Phase 1 — Foundation (current)

- Inspect the starting workspace and preserve unrelated learning files.
- Document product scope, modular-monolith architecture, domain model, SAP/P10 contracts, security model, assumptions, and roadmap.
- Scaffold React/strict TypeScript/Vite, FastAPI/Pydantic, async SQLAlchemy/Alembic, PostgreSQL, Docker Compose, environment configuration, and CI.
- Add liveness/readiness, frontend-to-backend health connectivity, minimal tests, lint, type checks, and build commands.
- Add an overview prototype, aggregate dashboard/worklist/review API contracts, and synthetic fixtures. These are demonstration-only and do not count as real promotion, approval, financial, identity, or integration capabilities.
- Verify each service and record environmental blockers. No business workflows or invented SAP/P10 interfaces.

## Phase 2 — Core domain

- Add tenant/user/role/scope and master/reference models, migrations, repositories, services, and versioned APIs.
- Add development-only mock identity/RBAC and server-side data authorization.
- Add master-data read APIs and explicitly synthetic seed data.

## Phase 3 — Promotion planning

- Implement promotion worklist, header/items, draft persistence, rate/percentage/fixed spend, price calculation, validation, and promotion-level P&L.
- Add lifecycle, approval, audit, optimistic locking, and role/data-scope checks.
- Keep calculation rules centralized and tested.

## Phase 4 — Baseline and demand forecast

- Add baseline imports/templates, validation/error downloads, versioning, weekly planning, bulk changes, locks, and history.
- Calculate weekly uplift/total forecast and implement approved split-week configuration.

## Phase 5 — Integration

- Define versioned canonical SAP and P10 contracts from approved specifications.
- Add mock adapters clearly marked non-production; add outbox, idempotency, retries/backoff, quarantine, acknowledgment, monitoring, and safe reprocessing.
- Integrate only after enterprise endpoint, authentication, mappings, and contract owners confirm details.

## Phase 6 — Controls and reporting

- Add audit-history UX, integration dashboards, calendar/overlap alerts, validated reports/exports, reconciliation, and operational alerts.

## Phase 7 — Production readiness

- Complete security/privacy and accessibility reviews, performance tests, deployment and secrets design, backup/recovery verification, operational runbook, and production acceptance.

## First vertical slice (Phase 3 target)

1. Read Plan Accounts and active OSKUs from the master-data boundary.
2. Create a tenant-scoped draft promotion for an authorized Plan Account.
3. Add eligible OSKU items with UOM and effective price/cost inputs.
4. Enter per-case rate or promotion-level fixed lump sum.
5. Calculate estimated landed price, spend, gross/net sales, contribution, and ROI only where required inputs are present.
6. Save/retrieve the promotion, show validation and calculation results, and reject stale-version updates.

Acceptance tests include valid/missing/inactive master data, effective-date lookup, UOM mismatch, negative landed price, zero volume/spend, missing cost, lump-sum allocation, concurrent edit, tenant/scope denial, and calculation round trips. No accrual calculation, claims, settlement, SAP send, or P10 send is in this slice.

## Exit gates before business functionality

- Phase 1 service, health, frontend connectivity, test, lint, type-check, and build checks pass in CI.
- Product owners confirm calculation semantics, master-data contract owners, tenant model, and approval policy before Phase 2/3 scope is treated as executable requirements.
- Security and enterprise integration reviews approve real identity and interface details before production credentials/data are introduced.
