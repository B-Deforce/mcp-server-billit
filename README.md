# Billit MCP

A small, local [Model Context Protocol](https://modelcontextprotocol.io/) server and async Python
client for invoice work in your own Billit account.

It exposes four tools:

- `get_invoice`: retrieve one invoice by Billit's `OrderID`
- `find_invoices_by_payment_reference`: find outgoing invoices by an exact external/payment
  reference, such as a Shopify order number
- `mark_invoice_paid`: mark an outgoing sales invoice fully paid
- `create_invoice`: save a basic outgoing sales invoice without sending it

The server deliberately does not expose arbitrary HTTP requests, invoice sending, Peppol account
management, partial payments, or hosted transports.

> [!IMPORTANT]
> Billit's current API-key documentation limits API keys to personal, non-commercial integrations
> used for one's own administration and says those integrations are not shared or distributed.
> This repository contains no credentials and requires every operator to supply their own. Confirm
> that your intended use complies with Billit's current terms and documentation.
> This project is unofficial and is not affiliated with or endorsed by Billit.

## Safety model

- Credentials come only from the server process environment, never from MCP tool arguments.
- The base URL is selected from `sandbox` or `production`; credentials cannot be redirected to an
  arbitrary host through configuration.
- Sandbox is the default.
- Production writes require both `BILLIT_ENV=production` and
  `BILLIT_ALLOW_PRODUCTION_WRITES=true`.
- `mark_invoice_paid` first verifies the order is an `Income` `Invoice`, returns without writing if
  it is already paid, and reads it back after the patch.
- `create_invoice` sends Billit's `Idempotent-Key` header, never retries a write after an unknown
  outcome, and never calls Billit's send endpoint.
- Raw invoice data is opt-in because it may add unnecessary personal data to model context.

## Requirements

- Python 3.11 or newer
- A Billit API key and company PartyID
- A sandbox account while developing or testing

Billit uses a different PartyID in sandbox and production.

## Install

From this repository:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
```

For development tools:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

## Configure

Set these in the environment of the process that starts the MCP server:

```dotenv
BILLIT_API_KEY=your-secret-api-key
BILLIT_PARTY_ID=123456
BILLIT_ENV=sandbox
```

Do not commit a populated `.env` file. The server does not load `.env` automatically; configure
the environment through your MCP host or a secret manager.

For a typical MCP client configuration:

```json
{
  "mcpServers": {
    "billit": {
      "command": "/absolute/path/to/billit-mcp/.venv/bin/mcp-server-billit",
      "env": {
        "BILLIT_API_KEY": "your-secret-api-key",
        "BILLIT_PARTY_ID": "123456",
        "BILLIT_ENV": "sandbox"
      }
    }
  }
}
```

Use your client's secure secret/configuration mechanism where one is available instead of storing
the API key in a plain-text configuration file.

## Run

Start the stdio server directly:

```bash
.venv/bin/mcp-server-billit
```

Or use the MCP development inspector:

```bash
.venv/bin/mcp dev src/mcp_server_billit/server.py
```

The server writes MCP protocol messages to stdout. Application code must never print diagnostics
there; use stderr if you add logging.

## Tool examples

Retrieve a normalized invoice:

```json
{
  "invoice_id": 1194146,
  "include_raw": false
}
```

Find invoices whose `PaymentReference` contains an external order identifier:

```json
{
  "payment_reference": "4319",
  "max_results": 10
}
```

The search is exact and restricted internally to outgoing invoices
(`OrderType=Invoice`, `OrderDirection=Income`). It can return zero, one, or multiple matches.

Mark an invoice paid:

```json
{
  "invoice_id": 1194146,
  "paid_at": "2026-09-03T12:30:00+02:00",
  "payment_method": "Wired",
  "note": "Matched bank transfer"
}
```

Create—but do not send—a basic invoice:

```json
{
  "invoice": {
    "invoice_number": "INV-2026-001",
    "issue_date": "2026-09-03",
    "due_date": "2026-10-03",
    "currency": "EUR",
    "customer": {
      "name": "Example Customer",
      "vat_number": "BE0123456789",
      "address": {
        "street": "Example Street",
        "street_number": "1",
        "zipcode": "1000",
        "city": "Brussels",
        "country_code": "BE"
      }
    },
    "lines": [
      {
        "description": "Consulting",
        "quantity": 1,
        "unit_price_excl": 100,
        "vat_percentage": 21
      }
    ]
  },
  "idempotency_key": "inv-2026-001-attempt-1"
}
```

`create_invoice` is intentionally a basic schema. Billit may require more fields for a particular
country, network, or tax situation and will return a typed validation error when it rejects a
payload.

## Python client

The HTTP layer is independently usable:

```python
import asyncio

from mcp_server_billit import BillitClient


async def main() -> None:
    async with BillitClient.from_env() as billit:
        invoice = await billit.get_invoice_raw(1194146)
        print(invoice["OrderNumber"])


asyncio.run(main())
```

## Development

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src
.venv/bin/pytest --cov=mcp_server_billit --cov-report=term-missing
.venv/bin/python -m build
```

The live integration test is read-only and skipped unless all three variables are present:

```bash
BILLIT_API_KEY=... \
BILLIT_PARTY_ID=... \
BILLIT_ENV=sandbox \
BILLIT_TEST_INVOICE_ID=... \
.venv/bin/pytest tests/integration
```

Never run integration tests against production.

## API references used

- [Billit PartyID and API key](https://docs.billit.be/docs/partyid-and-key)
- [Billit header values](https://docs.billit.be/docs/header-values)
- [Billit Orders API](https://docs.billit.be/reference/order-1)
- [Retrieve one order](https://docs.billit.be/reference/order_getorders_orderid)
- [Patch one order](https://docs.billit.be/reference/order_patchorders-1)
- [Update payment information](https://docs.billit.be/docs/set-billit-payment-status-after-sending)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## Packaging note

The distribution name `mcp-server-billit` is provisional. Confirm package-name availability before
publishing it to a package index.
