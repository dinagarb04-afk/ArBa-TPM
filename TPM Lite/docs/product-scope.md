# TPM Lite product scope

## Product goal

TPM Lite is a secured, multi-user application for commercial and demand-planning teams to plan promotions by Plan Account, OSKU, and ISO week; understand the planned promotion economics; obtain approval; and exchange approved planning information with enterprise systems through replaceable integration adapters.

The product is a planning and visibility layer. SAP S/4HANA remains the system of record for SAP-owned master data, pricing-condition processing, accruals, and settlement. P10 Arete remains an external demand-planning integration target.

## In scope

- Consume SAP-owned organization, customer, product, listing, price, cost, currency, UOM, and reference data.
- Plan a promotion header with multiple OSKU items and weekly volume phasing.
- Support rate, percentage-discount, per-case/unit, fixed-lump-sum, on-invoice, and off-invoice spend representations.
- Show planned price, baseline, promotion volume, uplift, forecast, spend, net sales, promotion contribution, and ROI where inputs support a meaningful result.
- Import and version baselines; plan forecasts at Plan Account x OSKU x ISO week.
- Provide configurable review, approval, lifecycle, and authorization rules.
- Send approved on-invoice and off-invoice promotion contracts to SAP-facing adapters, and baseline/uplift/forecast data to P10 Arete adapters.
- Expose audit, integration status, reports, and operational monitoring.
- Run as a multi-user SaaS web application with tenant-aware authorization and a documented local-development mode.

## Out of scope

- Accrual calculation, posting, or settlement in TPM Lite.
- Claims, deductions, customer P&L, customer annual business planning, and long-term contracts.
- Fund management unless separately approved.
- Creation or maintenance of SAP-owned master data.
- Guessing or hardcoding company-specific SAP APIs, middleware routes, condition types, pricing procedures, CCM configuration, P10 endpoints, or enterprise mappings.

Promotion-level planned financial visibility is in scope. Display of financial results returned by SAP is permitted but must not reproduce SAP financial processing.

## Personas and access

- Commercial Planner: maintain own authorized draft promotions and planning data.
- Demand Planner: maintain baselines and forecasts in assigned data scopes.
- Approver: review and act on promotions within assigned approval scope.
- Finance Viewer: read authorized promotion economics.
- Integration Support: inspect and, when authorized, retry integrations.
- Master Data Viewer: inspect synchronized SAP-owned reference data.
- Application Administrator: manage application configuration and access, not silently bypass audit.
- Read-Only Auditor: view authorized records and history.

All access is constrained by tenant, market, sales organization, and Plan Account scopes as applicable.

## First vertical slice (planned after Phase 1)

1. View seeded or synchronized Plan Accounts and OSKUs.
2. Create and retrieve a draft promotion.
3. Add one or more eligible OSKU items.
4. Enter a per-case rate or fixed lump-sum spend.
5. Calculate estimated landed price and promotion-level P&L in the backend.
6. Persist the draft, display the calculation, and enforce authorization and optimistic concurrency.

This slice does not transmit to SAP or P10 and does not calculate accruals.

## Phase 1 boundary

Phase 1 delivers architecture and domain documentation, project structure, local configuration, frontend/backend/database service scaffolding, health and readiness endpoints, a frontend-to-backend health check, and executable quality/test configuration. An additional overview prototype and aggregated dashboard API use clearly identified synthetic development fixtures only; the prototype has no tenant authentication, promotion persistence, approved P&L calculation, approval workflow, or live integration status. It must not be treated as operational business data. Production promotion planning, authentication, master-data APIs, and integrations remain later-phase work.
