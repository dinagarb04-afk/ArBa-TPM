# Integration contracts and open mappings

## Principles

TPM Lite owns canonical application contracts, not assumptions about enterprise endpoints. Adapters translate canonical messages to the approved transport and SAP/P10 schemas. Base URLs, credentials, middleware routes, condition types, pricing procedures, contract types, and field mappings are external configuration and secret-manager concerns.

No production SAP or P10 interface is implemented in Phase 1. Future local mock adapters must be clearly labeled synthetic and must not be described as the final enterprise API.

## SAP S/4HANA inbound

Design inbound full and delta synchronization for organizational data; customers, partner roles, Plan Accounts, hierarchies and sales-area assignments; material/OSKU and product hierarchies; product listings; units/conversions; prices and conditions; costs; currencies/calendars; and configurable reference/mapping data.

Every inbound record carries source system, external identifier, effective-from/to, last-source-change/sync time, and inactive/deleted indication. The pipeline validates, reports rejected rows, supports safe reprocessing, reconciles counts, and retains lineage. Business users cannot create SAP-owned records.

Additional inbound actual sales, open orders, processing acknowledgments, external IDs, and status/results require business confirmation and approved contracts.

## SAP outbound canonical messages (future)

**On-invoice**: promotion ID, sales-area scope, Plan Account/customer mapping, OSKU/material, configurable condition mapping, calculation type/value, currency/UOM, validity dates, scales when applicable, promotion reference, idempotency key, and correlation ID.

**Off-invoice**: promotion ID, customer/product scope, spend type and rate/lump-sum value, currency/UOM, promotion and shipment/in-store validity dates where required, configurable CCM mapping attributes, reference, idempotency key, and correlation ID.

The integration sends approved promotion intent to a configured SAP/middleware adapter. SAP/CCM performs authoritative pricing-condition, accrual, and settlement processing. TPM Lite may track acknowledgments/statuses returned by the adapter.

## P10 Arete outbound canonical forecast

Support promotion reference, Plan Account/customer mapping, OSKU/material, sales organization, shipment dates, ISO week, baseline, uplift, total forecast, promotion status, UOM, currency/final price where agreed, run ID, source timestamp, correlation/idempotency key, and contract version.

Only approved or explicitly configured forecast-active promotions contribute uplift. Adapter choices include API or file transport; both require acknowledgments, full/delta mode, reconciliation, retries, quarantine, authorized resend, and downloadable safe payloads. Weekly buckets crossing months require a P10-configured split rule. P09-to-OSKU disaggregation is future/configuration-driven.

## Shared reliability and controls

- Transactional outbox written with the business state change.
- Stable idempotency key, correlation ID, schema/contract version, and explicit state for each message.
- Retry with bounded exponential backoff; terminal failures quarantined for authorized review and reprocessing.
- Validate before sending, retain acknowledgment and reconciliation totals, and mask secrets/sensitive data in logs.
- Integration status never implies that SAP posted accrual or that P10 accepted a forecast without an actual acknowledgment.
- Transport implementation is replaceable; core services depend on adapter ports.

## Decisions required before a real interface

Confirm SAP landscape/release, API/middleware owner, allowed transport and authentication, SAP business partner/material identifiers, sales-area rules, condition calculation types and mappings, scales, validity/date semantics, CCM contract and mandatory fields, acknowledgments and error codes, retry/replay ownership, and SAP status source.

Confirm P10 environment/API or file specification, account/material mappings, week/calendar conventions, timezone/cutoff, split-week algorithm, payload ownership, full/delta behavior, acknowledgment/reconciliation, and duplicate prevention.

Until confirmed, all schemas and examples are canonical TPM Lite contracts only; do not invent URLs, credentials, condition types, CCM fields, or P10 endpoints.
