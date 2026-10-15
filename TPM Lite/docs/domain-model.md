# Preliminary domain model

This is a logical model for later implementation, not a deployed schema. Every tenant-owned row is tenant-scoped, and every mutable aggregate has a version for optimistic locking. SAP-owned master records are synchronized, effective-dated, source-attributed, and not editable by commercial users.

## Entities and relationships

```text
Tenant 1--* UserDataScope *--1 User
User *--* Role via UserRole
Tenant 1--* Market 1--* SalesOrganization
PlanAccount *--* Customer via account/customer assignment
Customer *--* Customer via CustomerHierarchy (effective-dated)
Material *--1 ProductHierarchy
Material 1--* ProductListing *--1 PlanAccount
Material 1--* PriceRecord
Material 1--* CostRecord
UnitOfMeasure 1--* UomConversion
PlanAccount 1--* Promotion 1--* PromotionItem *--1 Material
PromotionItem 1--* PromotionSpend
PromotionItem 1--* PromotionVolume
BaselineForecast and DemandForecast: PlanAccount x Material x ISO week
Promotion 1--* Approval
Promotion 1--* PromotionStatusHistory
All business aggregates 1--* AuditLog
MasterDataSyncRun 1--* IntegrationMessage
IntegrationRun 1--* IntegrationMessage
Promotion/outbox 1--* SapOutboundMessage or P10OutboundMessage
Tenant 1--* Configuration, ReferenceData, Notification
```

## Core entity fields

Use UUID primary keys unless an immutable external system key is explicitly required. Add `tenant_id` to tenant-owned data; include `created_at`, `created_by`, `updated_at`, `updated_by`, and `version` on mutable aggregates. Store UTC timestamps and dates/weeks as domain-specific values.

| Entity | Important fields and constraints |
|---|---|
| Tenant | UUID, stable code, display name, active state. Unique code. |
| User | UUID, tenant identity link/issuer subject, display name, email, active state. Do not use email as the immutable identity key. |
| Role / UserRole | Stable role code and assignment metadata. Unique tenant/user/role assignment. |
| UserDataScope | User, scope type, external or internal scope key, effective dates. Index tenant/user/scope. |
| Market / SalesOrganization | SAP external IDs, names, currency/calendar references, active/effective dates. Unique tenant/source/external ID. |
| PlanAccount / Customer / CustomerHierarchy | SAP-owned external IDs and assignments, hierarchy parent/child and validity. Preserve source lineage. |
| Material / ProductHierarchy / ProductListing | Material/OSKU external key, hierarchy references, UOM, lifecycle dates, listing eligibility by Plan Account. |
| UnitOfMeasure / UomConversion | Unit codes, numerator/denominator, effective dates. Unique source/unit pair and validity. |
| PriceRecord / CostRecord | Material and relevant sales/customer scope, value, currency, UOM, condition/source reference, validity. Never overwrite historical effective periods silently. |
| Promotion | UUID, human-readable number, market, sales organization, Plan Account, name/description, type, tactic, objective, invoice indicator, shipment/in-store/order dates, currency, owner, approval owner, status, version, external references, integration states. Unique tenant/promotion number. |
| PromotionItem | Promotion, OSKU/material, UOM, price basis, rate/discount inputs, allocated lump sum, baseline/promo/uplift/total volumes, gross/net sales, cost, contribution, ROI, validation state. Unique promotion/material/UOM where applicable. |
| PromotionSpend | Promotion/item, spend type, calculation basis, value, currency/UOM, invoice treatment, effective dates. Keep rate, percent, per-unit, and fixed amount semantically distinct. |
| PromotionVolume | Promotion item, ISO year/week, baseline, planned promotional volume, uplift, total, UOM, source/version/comment. Unique item/week/version. |
| BaselineForecast / DemandForecast | Tenant, Plan Account, material, ISO year/week, UOM, value, version, source/import lineage, locked state. Unique scope/week/version. |
| Approval / PromotionStatusHistory | Actor, action, from/to status, reason/comment, timestamp, correlation ID. Append-only history. |
| AuditLog | Actor, entity/key, action/field, prior/new values, reason, timestamp, correlation ID. Append-only, access restricted. |
| MasterDataSyncRun | Source, full/delta mode, cursor, start/end, counts, status, error summary. |
| IntegrationRun / IntegrationMessage | Adapter, direction, correlation/idempotency key, attempt, status, safe error summary, timestamps. Unique tenant/idempotency key per operation. |
| SapOutboundMessage / P10OutboundMessage | Canonical payload reference, contract version, status, correlation/idempotency key, attempts, acknowledgment. Encrypt/restrict payload storage and mask logs. |
| Configuration / ReferenceData | Tenant/scope, code, value/schema version, effective period, actor/version. Changes audited. |
| Notification | Tenant/user, type, safe summary, related entity, read state, created timestamp. |

## Constraints and indexing

- Foreign keys for all internal relationships; avoid embedding mutable display names as keys.
- Tenant-scoped unique constraints for human promotion number, external source identifiers, reference codes, and idempotency keys.
- Index promotion worklist dimensions: tenant/status, tenant/Plan Account/status, tenant/date range, owner/status, and material through promotion items.
- Index effective-dated reference lookup by tenant, external key, and validity interval.
- Index weekly forecast lookup by tenant/Plan Account/material/ISO year/week.
- Add checks for valid date ranges, nonnegative prices/volumes where domain-approved, and valid week values.
- Prefer explicit `is_active`/`deleted_at` over hard deletion for auditable master/reference data. Retain immutable event/outbox history per retention policy.
- Define exclusion/overlap constraints only after deciding whether overlapping promotions are warnings or blockers and at what scope.

## Calculation definitions to validate with business owners

- Percentage discount amount per unit = regular price x percentage / 100; landed price = regular price - discount.
- Per-case/unit rate spend = rate x promotional quantity in the matching UOM.
- Fixed lump sum remains fixed at promotion level; allocate across items only for analytical display using an agreed allocation basis.
- Uplift = max(promotional volume - baseline, 0), subject to confirmation for negative dips.
- Total forecast = baseline + approved promotion uplift, with explicit treatment for overlapping promotions.
- Gross sales = regular price x total volume in the applicable selling UOM.
- Net sales = gross sales - planned promotional spend, after confirming treatment of on-invoice price reductions to prevent double counting.
- Promotion contribution = net sales - cost of goods sold - configured variable costs.
- ROI = incremental contribution / promotional spend only when the numerator, cost basis, and denominator are valid. Zero/missing spend or cost yields unavailable, not a fabricated ratio.

All values use Decimal, explicit currency/UOM, effective-dated inputs, documented rounding, and separation of planned, approved, transmitted, and actual measures. SAP alone calculates/posts/settles accruals.
