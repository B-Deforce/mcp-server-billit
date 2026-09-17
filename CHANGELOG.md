# Changelog

All notable changes to this project will be documented here.

## 0.6.0 - 2026-09-17

- Add `mark_invoice_sent` to set `IsSent=true` on an outgoing sales invoice without email or
  Peppol delivery.
- Verify invoice type, direction, and the persisted sent state before returning success.

## 0.1.0 - 2026-09-03

- Add async Billit client with typed, redacted errors and conservative GET retries.
- Add normalized invoice models and mapping.
- Add `get_invoice`, `mark_invoice_paid`, and basic `create_invoice` MCP tools.
- Add read-only `find_invoices_by_payment_reference` with a safely escaped, fixed OData filter.
- Add production-write guard, write verification, and idempotent invoice creation.
- Add unit tests, read-only sandbox integration test, CI, and security documentation.
