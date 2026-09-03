"""Business and safety rules around the raw Billit client."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from .client import BillitClient
from .config import BillitEnvironment
from .errors import BillitSafetyError, BillitVerificationError
from .mappers import (
    create_invoice_to_billit,
    invoice_from_billit,
    payment_status_from_billit,
    reference_search_from_billit,
)
from .models import (
    CreatedInvoice,
    CreateInvoiceInput,
    InvoiceReferenceSearchResult,
    InvoiceView,
    PaymentMethod,
    PaymentStatus,
)


class BillitService:
    def __init__(self, client: BillitClient) -> None:
        self.client = client

    async def get_invoice(self, invoice_id: int, *, include_raw: bool = False) -> InvoiceView:
        raw = await self.client.get_invoice_raw(invoice_id)
        return invoice_from_billit(raw, include_raw=include_raw)

    async def find_invoices_by_payment_reference(
        self,
        payment_reference: str,
        *,
        max_results: int = 10,
    ) -> InvoiceReferenceSearchResult:
        reference = payment_reference.strip()
        if not reference:
            raise ValueError("payment_reference must not be empty")
        raw = await self.client.find_invoices_by_payment_reference_raw(
            reference,
            max_results=max_results,
        )
        return reference_search_from_billit(raw)

    async def mark_invoice_paid(
        self,
        invoice_id: int,
        *,
        paid_at: datetime,
        note: str | None = None,
        payment_method: PaymentMethod | None = None,
    ) -> PaymentStatus:
        self._ensure_write_allowed()
        current = await self.client.get_invoice_raw(invoice_id)
        order_type = str(current.get("OrderType", "")).lower()
        order_direction = str(current.get("OrderDirection", "")).lower()
        if order_type != "invoice" or order_direction != "income":
            raise BillitSafetyError(
                f"Order {invoice_id} is not an outgoing sales invoice; "
                "no payment state was changed."
            )
        if bool(current.get("Paid", False)):
            return payment_status_from_billit(current, already_paid=True)

        await self.client.mark_invoice_paid(
            invoice_id,
            paid_at=paid_at,
            internal_info=note,
            payment_method=payment_method,
        )
        updated = await self.client.get_invoice_raw(invoice_id)
        if not bool(updated.get("Paid", False)):
            raise BillitVerificationError(
                f"Billit accepted the update for invoice {invoice_id}, but Paid=true "
                "was not visible during verification. Check Billit before retrying."
            )
        return payment_status_from_billit(updated, already_paid=False)

    async def create_invoice(
        self,
        invoice: CreateInvoiceInput,
        *,
        idempotency_key: str | None = None,
    ) -> CreatedInvoice:
        self._ensure_write_allowed()
        key = idempotency_key or str(uuid4())
        invoice_id = await self.client.create_invoice_raw(
            create_invoice_to_billit(invoice),
            idempotency_key=key,
        )
        return CreatedInvoice(
            invoice_id=invoice_id,
            invoice_number=invoice.invoice_number,
            idempotency_key=key,
            sent=False,
        )

    def _ensure_write_allowed(self) -> None:
        config = self.client.config
        if (
            config.environment is BillitEnvironment.PRODUCTION
            and not config.allow_production_writes
        ):
            raise BillitSafetyError(
                "Production writes are disabled. Set BILLIT_ALLOW_PRODUCTION_WRITES=true only "
                "after reviewing the invoice and operation."
            )
