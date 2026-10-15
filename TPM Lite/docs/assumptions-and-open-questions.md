# Assumptions and open questions

## Working assumptions

1. The dedicated `TPM Lite` project is separate from the existing Python learning scripts and baby-announcement website.
2. The provided brief is the product authority; implementation starts with Phase 1 only.
3. Start as a modular monolith with a tenant-aware data model and server-enforced market/sales-organization/Plan Account scopes.
4. SAP S/4HANA owns enterprise master data, pricing condition creation, accruals, and settlement. TPM Lite must not calculate, post, or settle accruals.
5. P10 Arete receives forecast-related information through an adapter. Its exact transport and schema are not known.
6. Local development may use clearly labeled synthetic sample data in a later phase; no company, customer, material, price, cost, credential, or employee data is copied into the project.
7. The first vertical slice is the supplied view/create draft/add OSKU/rate-or-lump-sum/calculate/save/retrieve workflow.
8. Promotion calculations belong in backend domain services and use Decimal, currency/UOM metadata, effective dates, and configured rounding.
9. The documented suggested folder layout is the target even where Phase 1 does not yet create every module.

## Product and domain decisions to confirm

- Which tenant/deployment boundaries are required, and is a single-tenant production option needed?
- Which markets, sales organizations, currencies, calendars, timezones, fiscal periods, and ISO-week rules apply?
- What precisely defines a Plan Account, its customer roles/hierarchy, and its relationship to sold-to/ship-to/bill-to/payer?
- Is "OSKU" identical to SAP material/order SKU, and which product hierarchy levels may be planned?
- What promotion type/tactic/objective/mechanic/activity/spend reference values and approval thresholds are valid?
- How do shipment, order, and in-store dates relate? Which periods are frozen, and who may override?
- How should overlapping promotions combine? Is uplift allowed to be negative, and how are duplicate/conflicting promotions classified?
- What is the authoritative baseline source/version and how are actual sales, forecast overrides, and missing baseline represented?
- How are fixed lump sums analytically allocated across items and weeks?
- How should on-invoice price reduction interact with gross/net sales and spend to avoid double counting?
- Which COGS and variable cost basis, contribution definition, ROI numerator, denominator, and rounding rules Finance approves?
- What are mandatory validation warnings versus blocking errors, and what elevated historical-period override is auditable?
- What audit and integration payload retention periods apply?

## SAP details requiring confirmation

SAP landscape/release, middleware (such as Integration Suite/CPI or another approved layer), API/IDoc/file routes, authentication, customer/Plan Account/material identifiers, sales-area and validity semantics, master-data full/delta markers and deletion handling, price/cost conditions, currencies/UOM, condition types/calculation types/scales, pricing procedure rules, CCM contract mappings and required fields, acknowledgment/status/error contracts, idempotency ownership, reprocessing controls, and source of actual sales/open orders are all unconfirmed.

No SAP endpoint, condition type, CCM mapping, GL/cost object, or company-specific master-data rule is invented here.

## P10 Arete details requiring confirmation

Confirm API or file transport, endpoint/owner, authentication, account/material mappings, forecast statuses, exact ISO-week/calendar/date convention, month-boundary split-week algorithm, timezone/cutoff, full/delta and disaggregation rules, currency/price/UOM fields, acknowledgment schema, reconciliation method, duplicate prevention, retry ownership, and authorized resend workflow.

No P10 endpoint, credentials, or mapping is invented here.

## Platform decisions

- Confirm minimum/maximum Python and Node versions and supported operating systems/CI runners.
- Select hosting platform, ingress, DNS/custom domain, deployment environments, managed PostgreSQL, secret manager, backup RPO/RTO, and observability stack.
- Confirm Entra ID tenant/app registration, claims/role mapping, logout/session lifetime, and local-auth policy.
- Select a background job framework and scheduler when the integration/outbox phase begins.
- Confirm data residency, privacy classification, encryption, retention, and access-review requirements.
