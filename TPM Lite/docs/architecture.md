# TPM Lite architecture

## Architecture decision

Start with a modular monolith. Keep domain rules in backend modules and expose them through a versioned FastAPI API. The React client is a presentation layer and must not duplicate price, spend, volume, or P&L formulas.

```text
Browser
  React + TypeScript + Vite
       | HTTPS /api/v1
       v
  FastAPI application
    API -> authorization -> application services -> domain rules
                                      |             |
                                      v             v
                               repositories     integration ports
                                      |        SAP / P10 adapters
                                      v             |
                                  PostgreSQL   transactional outbox
                                                    |
                                            background worker (later)
```

The first implementation keeps these modules inside one deployable backend:

1. Identity and access management
2. Master data and customer/product listing
3. Baseline planning
4. Promotion planning, pricing/spend, volume phasing, and promotion P&L
5. Workflow and approvals
6. SAP S/4HANA integration
7. P10 Arete integration
8. Notifications
9. Audit and change history
10. Integration monitoring
11. Configuration and administration
12. Reporting and export

## Technology choices

- Frontend: React, strict TypeScript, Vite, React Router, TanStack Query, React Hook Form, Zod, Material UI, Axios, Recharts, Vitest, React Testing Library, and Playwright.
- Backend: Python, FastAPI, Pydantic v2, SQLAlchemy 2.x async, Alembic, PostgreSQL/asyncpg, pytest, pytest-asyncio, Ruff, and mypy.
- Operations: Docker Compose for local frontend/API/PostgreSQL, environment-driven configuration, structured logs, health/readiness endpoints, CI checks, and later a background worker for synchronization and outbox delivery.

Dependency versions should be locked when the actual runtime support policy and CI environment are agreed. Do not introduce API credentials into source, images, or logs.

## Repository layout

```text
TPM Lite/
  .github/workflows/ci.yml
  docs/
    product-scope.md
    architecture.md
    domain-model.md
    integration-contracts.md
    security-model.md
    assumptions-and-open-questions.md
    implementation-roadmap.md
  frontend/
    Dockerfile
    package.json
    vite.config.ts
    tsconfig*.json
    src/
      app/
      components/
      features/{auth,master-data,baseline,promotions,pricing,promo-pnl,approvals,integration-monitor,configuration,reports}/
      hooks/
      services/
      types/
      utils/
    tests/
  backend/
    Dockerfile
    alembic.ini
    alembic/{env.py,versions/}
    app/
      api/v1/
      audit/
      config/
      core/
      integrations/{sap,p10_arete}/
      jobs/
      models/
      repositories/
      schemas/
      security/
      services/
    tests/{unit,integration}/
  pyproject.toml
  docker-compose.yml
  .env.example
  README.md
```

The initial scaffold may create only the files needed to start services, verify connectivity, and run a minimal health test. Empty future modules are represented in this proposed structure, not advertised as implemented features.

## Backend boundaries and persistence

- `api`: HTTP routing, request/response schemas, pagination, error mapping, correlation IDs, and authorization dependencies.
- `services`: use cases and transaction boundaries.
- `domain`: pure calculation and lifecycle rules, introduced with core-domain work.
- `repositories`: SQLAlchemy persistence and tenant/data-scope filtering.
- `integrations`: canonical contracts and replaceable SAP/P10 transports.
- `audit`: append-only business and administrative event records.
- `jobs`: scheduled synchronization and outbox/retry processing.

Use PostgreSQL with async SQLAlchemy sessions. Migrations are the schema authority. Keep immutable external identifiers alongside internal UUIDs. Use tenant-scoped uniqueness and indexes, effective dating for SAP-sourced records, soft deletion for records that must remain auditable, and optimistic version columns for mutable business entities.

## API and client

Prefix APIs with `/api/v1`. The frontend uses a typed API service, TanStack Query for server state, and form schemas shared by user-facing validation where practical; the backend remains authoritative. A development proxy forwards `/api` to FastAPI. CORS is an explicit environment-configured allowlist, not wildcarded in deployed environments.

The Phase 1 aggregate endpoint `GET /api/v1/dashboard/overview` and its worklist/review routes return clearly tagged synthetic development fixtures. They demonstrate the dashboard response contract only; they do not establish identity, authorization, tenant scope, persisted promotions, business calculations, or live integration state. The operational health endpoint remains separate.

## Runtime and observability

Local Compose provides frontend, API, and PostgreSQL with health checks and persistent development data. The API exposes liveness and readiness separately; readiness verifies database connectivity. Configuration is loaded from environment, with `.env.example` containing placeholders only. Log structured events with correlation IDs and masked values. Never log credentials or full sensitive integration payloads.

Production hosting, identity provider, secrets manager, network topology, database availability, backup/restore objectives, and worker infrastructure require deployment-owner decisions before production release.

## Decision records

- Modular monolith first: preserves clear ownership without premature distributed-service operations.
- Canonical integration contracts: keeps business logic independent of SAP middleware/API and P10 transport choices.
- Database-owned calculations: provides a single authoritative result for UI, reports, and outbound payloads.
- Tenant/data scopes enforced server-side: UI filtering is never an authorization boundary.
- Financial accruals remain in SAP: TPM Lite only plans and displays permitted promotion-level estimates and returned statuses.
