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
    invoice_send_status_from_billit,
    payment_status_from_billit,
    reference_search_from_billit,
    unpaid_invoices_from_billit,
)
from .models import (
    CreatedInvoice,
    CreateInvoiceInput,
    InvoiceDeliveryMethod,
    InvoiceReferenceSearchResult,
    InvoiceSendStatus,
    InvoiceView,
    PaymentMethod,
    PaymentStatus,
    UnpaidInvoiceList,
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

    async def list_unpaid_invoices(self, *, max_results: int = 10) -> UnpaidInvoiceList:
        if not 1 <= max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")
        raw = await self.client.list_unpaid_invoices_raw(max_results=max_results)
        return unpaid_invoices_from_billit(raw, max_results=max_results)

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
        self._ensure_outgoing_sales_invoice(current, invoice_id, operation="payment")
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

    async def send_invoice(
        self,
        invoice_id: int,
        *,
        transport: InvoiceDeliveryMethod,
    ) -> InvoiceSendStatus:
        self._ensure_write_allowed()
        current = await self.client.get_invoice_raw(invoice_id)
        self._ensure_outgoing_sales_invoice(current, invoice_id, operation="delivery")

        if bool(current.get("IsSent", False)):
            return invoice_send_status_from_billit(
                current,
                transport=transport,
                already_sent=True,
            )

        if transport is InvoiceDeliveryMethod.EMAIL:
            customer = current.get("Customer")
            email = customer.get("Email") if isinstance(customer, dict) else None
            if not isinstance(email, str) or not email.strip():
                raise BillitSafetyError(
                    f"Invoice {invoice_id} has no customer email address; nothing was sent."
                )

        await self.client.send_invoice(invoice_id, transport=transport)
        updated = await self.client.get_invoice_raw(invoice_id)
        if not bool(updated.get("IsSent", False)):
            raise BillitVerificationError(
                f"Billit accepted the send command for invoice {invoice_id}, but IsSent=true "
                "was not visible during verification. Check Billit before retrying."
            )
        return invoice_send_status_from_billit(
            updated,
            transport=transport,
            already_sent=False,
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

    @staticmethod
    def _ensure_outgoing_sales_invoice(
        invoice: dict[str, object],
        invoice_id: int,
        *,
        operation: str,
    ) -> None:
        order_type = str(invoice.get("OrderType", "")).lower()
        order_direction = str(invoice.get("OrderDirection", "")).lower()
        if order_type != "invoice" or order_direction != "income":
            raise BillitSafetyError(
                f"Order {invoice_id} is not an outgoing sales invoice; "
                f"no {operation} action was taken."
            )
