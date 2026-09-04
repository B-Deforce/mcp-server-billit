# Billit MCP

A small, local [Model Context Protocol](https://modelcontextprotocol.io/) server and async Python
client for invoice work in your own Billit account.

## Best used with a local MCP client

Billit MCP works best when it runs locally on the same computer as an MCP-capable assistant. A
local client can start this server as a private stdio process, so you do not need to host the
server or expose your Billit credentials over the internet. Good fits include the ChatGPT desktop
app, the Codex app and CLI, Claude Desktop, Claude Code, and other clients that support local stdio
MCP servers.

Codex clients share MCP configuration, so a server configured in `~/.codex/config.toml` can be
used from the desktop app, CLI, and IDE extension. See the [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp)
and [Claude Code MCP documentation](https://docs.anthropic.com/en/docs/claude-code/mcp) for
client-specific setup.

ChatGPT on the web does not read your local stdio configuration. It connects to remote MCP servers;
use [Secure MCP Tunnel](https://help.openai.com/en/articles/12584461) if you specifically need to
bridge a locally running server to a supported ChatGPT workspace.

It exposes twelve tools:

- `get_invoice`: retrieve one invoice by Billit's `OrderID`
- `find_invoices_by_payment_reference`: find outgoing invoices by an exact external/payment
  reference, such as a Shopify order number
- `find_invoices_by_customer_name`: find outgoing invoices using a verified, case-insensitive
  partial customer-name match
- `list_unpaid_invoices`: list up to 100 unpaid outgoing invoices, ordered by due date
- `check_peppol_recipient`: check whether an invoice customer is registered and supports an
  invoice document type on Peppol
- `mark_invoice_paid`: mark an outgoing sales invoice fully paid
- `create_invoice`: save a basic outgoing sales invoice without sending it
- `send_invoice`: send one existing outgoing invoice by email or Peppol; Peppol is preflighted
- `create_credit_note_from_invoice`: derive and save a full credit note from an existing outgoing
  sales invoice without sending it
- `mark_credit_note_paid`: mark an existing outgoing sales credit note paid
- `mark_credit_note_sent`: update a credit note's sent status without delivering it
- `send_credit_note`: send an existing credit note by email or Peppol; Peppol credit-note support
  is preflighted

The server deliberately does not expose arbitrary HTTP requests, batch invoice sending, automatic
transport fallback, fuzzy customer guesses, Peppol account management, partial payments, or hosted
transports.

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
- `create_credit_note_from_invoice` accepts only an outgoing sales invoice, derives a full credit
  with positive line amounts, links it through `AboutInvoiceNumber`, sends an idempotency key, and
  verifies the created credit note by reading it back. It does not copy the source payment
  reference, PDF, or attachments, and it does not send the result.
- Credit-note numbering is explicit. The tool does not consume Billit's number sequence, avoiding
  a hidden second write and unexplained sequence gaps after failed creation attempts.
- `mark_credit_note_sent` only patches `IsSent=true`; it does not transmit the document. Once
  marked sent, `send_credit_note` will not deliver it later, which prevents accidental duplicates.
- Credit-note Peppol sends require Billit to report a credit-note-capable document type; invoice
  capability alone is not enough.
- `send_invoice` first verifies the order is an unsent `Income` `Invoice`. Email delivery uses only
  the customer address already stored on the invoice. Before a Peppol send, Billit must report the
  recipient as both registered and capable of receiving an invoice document type. Peppol delivery
  is strict and never falls back to email.
- Customer-name invoice searches use Billit's customer full-text search, then locally verify a
  case-insensitive, accent-insensitive partial name match before querying orders by exact PartyID.
  Typo-fuzzy guesses are intentionally excluded to avoid mixing similarly named customers.
- Send commands are single-invoice operations and are never retried automatically after an unknown
  outcome. The tool reads the invoice back and tells the operator to inspect Billit before retrying
  if the sent state cannot be verified.
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

### 1. Get your Billit credentials

In MyBillit, find the PartyID for the company you want to manage and create or copy your personal
API key. Billit's [PartyID and API key guide](https://docs.billit.be/docs/partyid-and-key) shows
where to find both values.

- Treat the API key like a password. Do not paste it into chat, issues, source files, screenshots,
  or committed configuration.
- Sandbox and production have different PartyIDs. Use the PartyID belonging to the environment you
  select.
- If your Billit user can access multiple companies, select the PartyID for the specific company
  whose invoices the MCP should access.

### 2. Configure the server environment

Set these values in the environment of the process that starts the MCP server:

```dotenv
BILLIT_API_KEY=your-secret-api-key
BILLIT_PARTY_ID=123456
BILLIT_ENV=sandbox
```

Do not commit a populated `.env` file. The server does not load `.env` automatically; configure
the environment through your MCP host or a secret manager.

Use `BILLIT_ENV=production` with your production PartyID. Production reads then work normally, but
write tools remain disabled until you deliberately set `BILLIT_ALLOW_PRODUCTION_WRITES=true`.

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

### 3. Restart and test read-only first

Restart or refresh the MCP client after changing its configuration. Begin with a read-only tool
such as `list_unpaid_invoices`, `find_invoices_by_customer_name`, or `get_invoice`. Only enable
production writes after confirming that the returned company and invoice data are correct.

Repository-aware coding agents can also read [AGENTS.md](AGENTS.md) for the project architecture,
safety rules, development commands, and a credential-safe installation checklist.

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

List unpaid outgoing invoices, with the earliest due date first:

```json
{
  "max_results": 10
}
```

`max_results` defaults to 10 and is capped at 100, below Billit's 120-record OData page maximum.
The response distinguishes the number returned from `has_more`, so a capped result is not mistaken
for the total number of unpaid invoices.

Find invoices for a customer using a partial name:

```json
{
  "customer_name": "nao",
  "max_results": 25
}
```

The match is case- and accent-insensitive, but not fuzzy or typo-tolerant. The response reports how
many customer records matched and returns only invoices tied to those exact customer PartyIDs.

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

Create—but do not send—a full credit note from an existing invoice:

```json
{
  "invoice_id": 1194146,
  "credit_note_number": "CN-2026-001",
  "issue_date": "2026-09-04",
  "reason": "Invoice cancelled in full",
  "idempotency_key": "credit-invoice-1194146-attempt-1"
}
```

The source must be an outgoing (`Income`) invoice. The tool reuses its customer PartyID, currency,
and complete positive invoice lines and sets `AboutInvoiceNumber` to the source invoice number.
This is deliberately a full-credit operation; partial credit notes and free-form credit-note
creation are not exposed. `due_date` is optional and defaults to `issue_date` because Billit
requires an expiry date.

Billit documents a special accounting behavior for linked credit notes: when
`AboutInvoiceNumber` is present, the generated UBL represents the amount as fully prepaid with
zero payable, regardless of the credit note's `Paid` status. `mark_credit_note_paid` still updates
Billit's administrative status, but it does not change that UBL behavior.

Mark a saved credit note as sent without transmitting it:

```json
{
  "credit_note_id": 654
}
```

Use `mark_credit_note_sent` for that status-only operation. To actually deliver the document, use
`send_credit_note` instead:

```json
{
  "credit_note_id": 654,
  "transport": "peppol"
}
```

Email delivery requires an email address on the saved credit note. Peppol delivery first checks
the recipient's identifiers and requires explicit credit-note document support. It uses strict
transport and never falls back to email.

Send an existing invoice by email:

```json
{
  "invoice_id": 1194146,
  "transport": "email"
}
```

Or send it over Peppol:

```json
{
  "invoice_id": 1194146,
  "transport": "peppol"
}
```

You can run the same read-only Peppol capability check separately before deciding to send:

```json
{
  "invoice_id": 1194146
}
```

Use `check_peppol_recipient` for this call. It reads the customer VAT or Peppol identifier from the
invoice and reports registration, supported document types, and whether regular invoices can be
received. Billit checks the Peppol test network in sandbox and the live network in production.

This is an external side effect. Review the full invoice and its recipient before approving the
tool call. If Billit already marks the invoice as sent, the tool returns without sending it again.
Peppol delivery uses Billit's strict transport header, so it cannot silently fall back to email.
Registration by itself is not accepted: the participant lookup must also advertise an
invoice-capable document type. If the check is negative or inconclusive, nothing is sent.

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
- [Billit OData filtering](https://docs.billit.be/docs/odata)
- [Search parties](https://docs.billit.be/reference/party_getparties-1)
- [Retrieve one order](https://docs.billit.be/reference/order_getorders_orderid)
- [Patch one order](https://docs.billit.be/reference/order_patchorders-1)
- [Create an order](https://docs.billit.be/reference/order_postorders-1)
- [Create and send a credit note](https://docs.billit.be/docs/sending-a-credit-note)
- [Retrieve the next number sequence](https://docs.billit.be/docs/how-can-i-retrieve-the-next-sequence)
- [Send existing orders](https://docs.billit.be/reference/order_postsend-1)
- [Email and Peppol delivery behavior](https://docs.billit.be/docs/email-sending-enable-disable)
- [Check a Peppol participant](https://docs.billit.be/reference/peppol_getparticipantinformation-1)
- [Interpret Peppol capability checks](https://docs.billit.be/docs/check-via-api)
- [Peppol receiving capabilities](https://docs.billit.be/docs/peppol-receiving-capabilities)
- [Update payment information](https://docs.billit.be/docs/set-billit-payment-status-after-sending)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## Packaging note

The distribution name `mcp-server-billit` is provisional. Confirm package-name availability before
publishing it to a package index.
