# Changelog

All notable changes to this project will be documented here.

## 0.1.0 - 2026-09-03

- Add async Billit client with typed, redacted errors and conservative GET retries.
- Add normalized invoice models and mapping.
- Add `get_invoice`, `mark_invoice_paid`, and basic `create_invoice` MCP tools.
- Add read-only `find_invoices_by_payment_reference` with a safely escaped, fixed OData filter.
- Add production-write guard, write verification, and idempotent invoice creation.
- Add unit tests, read-only sandbox integration test, CI, and security documentation.
