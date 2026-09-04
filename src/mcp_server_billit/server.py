"""Typed stdio MCP tool registrations for Billit."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from pydantic import Field

from .client import BillitClient
from .models import (
    CreatedCreditNote,
    CreatedInvoice,
    CreateInvoiceInput,
    CreditNoteSendStatus,
    CreditNoteStatus,
    CustomerInvoiceSearchResult,
    InvoiceDeliveryMethod,
    InvoiceReferenceSearchResult,
    InvoiceSendStatus,
    InvoiceView,
    PaymentMethod,
    PaymentStatus,
    PeppolRecipientCapability,
    UnpaidInvoiceList,
)
from .service import BillitService


@dataclass
class AppContext:
    service: BillitService


@asynccontextmanager
async def app_lifespan(_server: MCPServer[AppContext]) -> AsyncIterator[AppContext]:
    async with BillitClient.from_env() as client:
        yield AppContext(service=BillitService(client))


mcp = MCPServer[AppContext](
    "Billit Personal",
    description="Small, local tools for retrieving and updating invoices in one Billit account.",
    instructions=(
        "Use get_invoice before proposing a payment-state change, delivery, or credit note. "
        "Never claim create_invoice sends an invoice: it only saves the invoice in Billit. "
        "Creating a credit note saves a full credit derived from an invoice but does not send it. "
        "Peppol sends require a successful document-specific recipient capability preflight."
    ),
    lifespan=app_lifespan,
)


@mcp.tool()
async def get_invoice(
    invoice_id: Annotated[int, Field(gt=0)],
    ctx: Context[AppContext],
    include_raw: bool = False,
) -> InvoiceView:
    """Retrieve one Billit invoice by its Billit OrderID.

    The default response is normalized and omits the large, privacy-heavy raw order object.
    """
    return await ctx.request_context.lifespan_context.service.get_invoice(
        invoice_id, include_raw=include_raw
    )


@mcp.tool()
async def find_invoices_by_payment_reference(
    payment_reference: Annotated[str, Field(min_length=1, max_length=250)],
    ctx: Context[AppContext],
    max_results: Annotated[int, Field(ge=1, le=50)] = 10,
) -> InvoiceReferenceSearchResult:
    """Find outgoing Billit invoices with an exact payment reference.

    This read-only lookup is useful when an external order number, such as a Shopify order number,
    is stored in Billit's PaymentReference field. Zero, one, or multiple matches may be returned.
    """
    return await ctx.request_context.lifespan_context.service.find_invoices_by_payment_reference(
        payment_reference,
        max_results=max_results,
    )


@mcp.tool()
async def list_unpaid_invoices(
    ctx: Context[AppContext],
    max_results: Annotated[int, Field(ge=1, le=100)] = 10,
) -> UnpaidInvoiceList:
    """List unpaid outgoing sales invoices, ordered by due date.

    This is read-only. Results default to 10 invoices and are capped at 100.
    """
    return await ctx.request_context.lifespan_context.service.list_unpaid_invoices(
        max_results=max_results
    )


@mcp.tool()
async def find_invoices_by_customer_name(
    customer_name: Annotated[str, Field(min_length=1, max_length=250)],
    ctx: Context[AppContext],
    max_results: Annotated[int, Field(ge=1, le=100)] = 10,
) -> CustomerInvoiceSearchResult:
    """Find outgoing invoices by a case-insensitive partial customer-name match.

    This read-only lookup searches Billit customers first, verifies the partial name match locally,
    then returns invoices belonging to those customer IDs. It intentionally does not make fuzzy or
    typo-tolerant guesses that could mix invoices from similarly named customers.
    """
    return await ctx.request_context.lifespan_context.service.find_invoices_by_customer_name(
        customer_name,
        max_results=max_results,
    )


@mcp.tool()
async def check_peppol_recipient(
    invoice_id: Annotated[int, Field(gt=0)],
    ctx: Context[AppContext],
) -> PeppolRecipientCapability:
    """Check whether an invoice customer can receive invoices through Peppol.

    This is read-only. Registration alone is not treated as sufficient: Billit must also report an
    invoice-capable document type for the recipient identifier stored on the invoice.
    """
    return await ctx.request_context.lifespan_context.service.check_peppol_recipient(invoice_id)


@mcp.tool()
async def mark_invoice_paid(
    invoice_id: Annotated[int, Field(gt=0)],
    paid_at: datetime,
    ctx: Context[AppContext],
    note: Annotated[str | None, Field(max_length=1000)] = None,
    payment_method: PaymentMethod | None = None,
) -> PaymentStatus:
    """Mark an outgoing Billit sales invoice fully paid.

    This changes Billit data. Supply the actual accounting payment date/time and review the
    invoice ID before approving the call. Already-paid invoices are left unchanged.
    """
    return await ctx.request_context.lifespan_context.service.mark_invoice_paid(
        invoice_id,
        paid_at=paid_at,
        note=note,
        payment_method=payment_method,
    )


@mcp.tool()
async def create_invoice(
    invoice: CreateInvoiceInput,
    ctx: Context[AppContext],
    idempotency_key: Annotated[
        str | None,
        Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ] = None,
) -> CreatedInvoice:
    """Create and save a basic outgoing sales invoice in Billit without sending it.

    This changes Billit data. Country-specific tax and e-invoicing requirements remain Billit's
    responsibility. Reuse the same idempotency key when safely repeating the same attempt.
    """
    return await ctx.request_context.lifespan_context.service.create_invoice(
        invoice, idempotency_key=idempotency_key
    )


@mcp.tool()
async def create_credit_note_from_invoice(
    invoice_id: Annotated[int, Field(gt=0)],
    credit_note_number: Annotated[str, Field(min_length=1, max_length=100)],
    issue_date: date,
    ctx: Context[AppContext],
    due_date: date | None = None,
    reason: Annotated[str | None, Field(max_length=1000)] = None,
    idempotency_key: Annotated[
        str | None,
        Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ] = None,
) -> CreatedCreditNote:
    """Create and save a full credit note derived from an existing sales invoice.

    This changes Billit data but does not send the credit note. The customer, currency, and full
    positive line data are copied from the source invoice, which is linked through
    AboutInvoiceNumber. Supply a deliberate credit-note number: this tool does not consume Billit's
    sequence. The due date defaults to the issue date. Reuse the same idempotency key only when
    safely repeating the same attempt.
    """
    return await ctx.request_context.lifespan_context.service.create_credit_note_from_invoice(
        invoice_id,
        credit_note_number=credit_note_number,
        issue_date=issue_date,
        due_date=due_date,
        reason=reason,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
async def mark_credit_note_paid(
    credit_note_id: Annotated[int, Field(gt=0)],
    paid_at: datetime,
    ctx: Context[AppContext],
    note: Annotated[str | None, Field(max_length=1000)] = None,
    payment_method: PaymentMethod | None = None,
) -> CreditNoteStatus:
    """Mark an existing outgoing sales credit note paid in Billit.

    This changes Billit data. Supply the actual accounting payment date/time and review the credit
    note before approving the call. Already-paid credit notes are left unchanged.
    """
    return await ctx.request_context.lifespan_context.service.mark_credit_note_paid(
        credit_note_id,
        paid_at=paid_at,
        note=note,
        payment_method=payment_method,
    )


@mcp.tool()
async def mark_credit_note_sent(
    credit_note_id: Annotated[int, Field(gt=0)],
    ctx: Context[AppContext],
) -> CreditNoteStatus:
    """Mark an existing outgoing sales credit note sent without delivering it.

    This only sets Billit's IsSent status. It does not email the customer or transmit anything over
    Peppol. A credit note marked sent will not later be sent by send_credit_note, which protects
    against accidental duplicate delivery.
    """
    return await ctx.request_context.lifespan_context.service.mark_credit_note_sent(credit_note_id)


@mcp.tool()
async def send_credit_note(
    credit_note_id: Annotated[int, Field(gt=0)],
    transport: InvoiceDeliveryMethod,
    ctx: Context[AppContext],
) -> CreditNoteSendStatus:
    """Send one existing outgoing sales credit note by email or Peppol.

    This is an external side effect. Review the credit note, recipient, and transport before
    approving the call. A credit note already marked sent is not sent again. Peppol requires a
    successful credit-note-specific recipient capability check and never falls back to email.
    """
    return await ctx.request_context.lifespan_context.service.send_credit_note(
        credit_note_id,
        transport=transport,
    )


@mcp.tool()
async def send_invoice(
    invoice_id: Annotated[int, Field(gt=0)],
    transport: InvoiceDeliveryMethod,
    ctx: Context[AppContext],
) -> InvoiceSendStatus:
    """Send one existing outgoing invoice by email or Peppol.

    This is an external side effect. Review the invoice, recipient, and transport before approving
    the call. An invoice already marked sent is not sent again. Peppol requires a successful
    recipient capability check and never falls back to email.
    """
    return await ctx.request_context.lifespan_context.service.send_invoice(
        invoice_id,
        transport=transport,
    )
