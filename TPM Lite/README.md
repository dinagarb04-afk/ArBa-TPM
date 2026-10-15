# ArBa Trade Promotion Plan capability

Foundation for a modular-monolith Trade Promotion Management Lite SaaS application. Scope, architecture, the preliminary domain model, integration constraints, security model, assumptions, and roadmap are in [`docs/`](docs/).

## Phase 1 status

The foundation contains a React/TypeScript/Vite frontend, FastAPI backend, async SQLAlchemy/Alembic configuration, PostgreSQL Compose service, and CI/test/lint configuration. The current Overview is backed by a single aggregated FastAPI dashboard contract with clearly marked synthetic development fixtures, a filtered worklist, and synthetic review-detail pages. These fixtures do not represent connected customer or enterprise data. Identity/RBAC, persistent promotion models, create/approval workflows, business-calculated promotion P&L, and SAP/P10 transports are not implemented.

## Promotion Overview development contract

`GET /api/v1/dashboard/overview` returns the dashboard KPIs, pending-review examples, attention items, six-week volume snapshot, promotion-level financial summary, integration-health summaries, and role-configuration availability in one response. `GET /api/v1/dashboard/worklist?filter=...` supplies the filtered worklist; `GET /api/v1/promotions/{promotion_id}` supplies synthetic review details. Every response is illustrative development data, not production or authorized user-scope data.

Set `DASHBOARD_UPCOMING_PERIOD_WEEKS` to a value from 1 to 52 to adjust the synthetic upcoming-promotion window; the default is 4 weeks.

The dashboard intentionally does not provide approval/rejection controls. The current Phase 1 project has no promotion creation persistence, identity, RBAC, approval workflow, integration transport, or approved promotion P&L calculation service. The **+ New Promotion** entry point explains that creation is not yet implemented. No customer P&L, accrual calculation, contract planning, credentials, raw integration payloads, or technical middleware errors are added.

Role-based widget ordering is represented as an API contract but reports `not_configured` until the application's real identity/RBAC implementation exists. Do not deploy this synthetic dashboard API as if it were tenant-authenticated business data.

## Local development with Docker Compose

Prerequisites: Docker Desktop with Compose, Node.js 22.12+ and npm for local frontend commands, and Python 3.12–3.15 for local backend commands.

1. Copy `.env.example` to `.env` and replace `POSTGRES_PASSWORD` with a nonempty, URL-safe local-only value. Never commit `.env`.
2. From this directory run:

   ```powershell
   docker compose up --build
   ```

3. Open <http://localhost:5173>. Select **Check backend connection** to exercise the Vite `/api` proxy and FastAPI liveness endpoint.
4. API docs are at <http://localhost:8000/docs>; liveness is <http://localhost:8000/api/v1/health/live>; readiness (including the database check) is <http://localhost:8000/api/v1/health/ready>.
5. Stop services with `docker compose down`. Add `-v` only when intentionally removing the local PostgreSQL data volume.

The Compose API uses the local database and must become healthy before the frontend starts. Liveness does not claim database readiness.

## Local quality checks

Backend:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check backend
python -m mypy
```

Frontend:

```powershell
cd frontend
npm install
npm run lint
npm run typecheck
npm run test
npm run build
```

## Configuration and integration safety

Runtime configuration comes from environment variables. `.env.example` is a template, not a credential source. SAP and P10 behavior must be added only after their enterprise owners confirm transport, schemas, identifiers, mappings, and authentication. Any local mock must be labeled synthetic and non-production. SAP remains responsible for financial accrual processing; TPM Lite must not calculate or post accruals.

## Deployment

The frontend Dockerfile has a production static-web stage; the API Dockerfile has a production stage. Place them behind a TLS-enabled ingress that routes `/api/` to the API, configures allowed origins and managed secrets, and connects to managed PostgreSQL. The exact cloud platform, identity provider, secret manager, backup objectives, and integration network paths remain open decisions.
