# Billit MCP agent guide

This file gives coding agents durable project guidance. Keep it concise, current, and free of
credentials.

## Project intent

This repository provides a small, local stdio MCP server and async Python client for one operator's
own Billit administration. It is not a hosted multi-tenant service and must not become an arbitrary
Billit HTTP proxy.

The supported public surface lives in `src/mcp_server_billit/server.py`. Business and safety rules
belong in `service.py`, raw HTTP behavior in `client.py`, public schemas in `models.py`, and Billit
response conversion in `mappers.py`.

## Help a user install it

1. Create a virtual environment and install the project:

   ```bash
   python3.12 -m venv .venv
   .venv/bin/python -m pip install -e .
   ```

2. Ask the user to retrieve their company PartyID and personal API key themselves using Billit's
   [PartyID and API key guide](https://docs.billit.be/docs/partyid-and-key). Do not ask them to paste
   the API key into chat.

3. Explain that sandbox and production use different PartyIDs. Configure exactly one environment:

   ```dotenv
   BILLIT_API_KEY=replace-locally
   BILLIT_PARTY_ID=replace-locally
   BILLIT_ENV=sandbox
   ```

   For production, use `BILLIT_ENV=production` and the production PartyID. Do not enable production
   writes merely to test the connection.

4. Configure those variables in the MCP host or its secret manager, not in this repository. A Codex
   stdio configuration has this shape:

   ```toml
   [mcp_servers.billit]
   command = "/absolute/path/to/billit-mcp/.venv/bin/mcp-server-billit"

   [mcp_servers.billit.env]
   BILLIT_API_KEY = "replace-locally"
   BILLIT_PARTY_ID = "replace-locally"
   BILLIT_ENV = "sandbox"
   ```

   The user should replace placeholders directly in their local MCP configuration. Never commit a
   populated config, `.env`, shell transcript, or screenshot.

5. Restart or refresh the MCP host. Validate with a read-only call first:

   - `list_unpaid_invoices(max_results=10)`
   - `find_invoices_by_customer_name(customer_name="known customer")`
   - `get_invoice(invoice_id=known_order_id)`

6. Only if the user explicitly wants production mutations, explain the additional
   `BILLIT_ALLOW_PRODUCTION_WRITES=true` gate. Review the exact invoice and operation before any
   write or delivery call.

When diagnosing configuration, report only whether each variable is present and which environment
is selected. Never print, echo, log, or return the API key. Avoid commands such as `env`, `printenv`,
or dumping an MCP configuration file when they could expose credentials.

## Safety invariants

- Credentials come from process environment variables, never MCP tool arguments.
- Billit base URLs are selected only by the typed sandbox/production setting.
- Production mutations require the explicit second opt-in.
- GET requests may retry transient failures; writes must not retry an unknown outcome.
- `create_invoice` saves but does not send.
- `create_credit_note_from_invoice` creates only a full credit from an outgoing `Income` invoice,
  preserves positive amounts, links `AboutInvoiceNumber`, and verifies the new order after creation.
  It requires an explicit credit-note number and does not consume a Billit sequence.
- Payment and delivery mutations apply only to the expected outgoing `Income` invoice or credit
  note type and are verified by a read after write.
- `mark_credit_note_sent` changes status only and must never call the send endpoint.
- Peppol delivery requires a successful participant and document-specific capability preflight;
  an invoice capability does not authorize a credit-note send. It must never fall back to email.
- Customer-name search must resolve verified customer PartyIDs before retrieving invoices. Do not
  introduce automatic fuzzy matching that can mix similarly named customers.
- Keep default tool responses compact and make privacy-heavy raw data opt-in.
- Never add batch-send behavior without an explicit, separately reviewed design.

## Development workflow

Use Python 3.11-compatible code and preserve the typed public models. Before committing, run:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src
.venv/bin/pytest --cov=mcp_server_billit --cov-report=term-missing
.venv/bin/python -m build
```

The live integration test is sandbox-only and must never be pointed at production. Unit tests must
mock Billit HTTP calls and assert request paths, filters, headers, retry behavior, and write-safety
rules.

When changing the MCP surface:

- Add or update public models and precise tool descriptions.
- State clearly whether a tool is read-only or causes an external side effect.
- Add service-level safety tests and client-level request tests.
- Update the README examples and API-reference links.
- Bump the package version for a published feature release.
- Check the staged diff for secrets before pushing.
