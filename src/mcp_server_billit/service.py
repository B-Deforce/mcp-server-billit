"""Business and safety rules around the raw Billit client."""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from uuid import uuid4

from .client import BillitClient
from .config import BillitEnvironment
from .errors import BillitSafetyError, BillitVerificationError
from .mappers import (
    create_invoice_to_billit,
    created_credit_note_from_billit,
    credit_note_from_invoice_to_billit,
    credit_note_send_status_from_billit,
    credit_note_status_from_billit,
    customer_invoice_search_from_billit,
    invoice_from_billit,
    invoice_send_status_from_billit,
    payment_status_from_billit,
    peppol_capability_from_billit,
    reference_search_from_billit,
    unpaid_invoices_from_billit,
)
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
    PeppolDocumentType,
    PeppolRecipientCapability,
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
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")
        raw = await self.client.list_unpaid_invoices_raw(max_results=max_results)
        return unpaid_invoices_from_billit(raw, max_results=max_results)

    async def find_invoices_by_customer_name(
        self,
        customer_name: str,
        *,
        max_results: int = 10,
    ) -> CustomerInvoiceSearchResult:
        query = customer_name.strip()
        if not query:
            raise ValueError("customer_name must not be empty")
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")

        customer_data = await self.client.search_customers_raw(query, max_results=100)
        normalized_query = _normalize_name(query)
        matched_ids: list[int] = []
        for party in _items(customer_data):
            party_id = _party_id(party)
            names = _party_names(party)
            if party_id is not None and any(
                normalized_query in _normalize_name(name) for name in names
            ):
                matched_ids.append(party_id)
        matched_ids = list(dict.fromkeys(matched_ids))

        invoices = await self.client.find_invoices_by_customer_ids_raw(
            matched_ids,
            max_results=max_results,
        )
        customer_results_have_more = bool(
            customer_data.get("NextPageLink") or customer_data.get("nextPageLink")
        )
        return customer_invoice_search_from_billit(
            invoices,
            query=query,
            matched_customer_count=len(matched_ids),
            max_results=max_results,
            customer_results_have_more=customer_results_have_more,
        )

    async def check_peppol_recipient(self, invoice_id: int) -> PeppolRecipientCapability:
        current = await self.client.get_invoice_raw(invoice_id)
        self._ensure_outgoing_sales_invoice(current, invoice_id, operation="Peppol check")
        return await self._check_peppol_for_order(
            current,
            invoice_id,
            required_document_type=PeppolDocumentType.INVOICE,
        )

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

    async def create_credit_note_from_invoice(
        self,
        invoice_id: int,
        *,
        credit_note_number: str,
        issue_date: date,
        due_date: date | None = None,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> CreatedCreditNote:
        self._ensure_write_allowed()
        number = credit_note_number.strip()
        if not number:
            raise ValueError("credit_note_number must not be empty")
        if due_date is not None and due_date < issue_date:
            raise ValueError("due_date must be on or after issue_date")

        source = await self.client.get_invoice_raw(invoice_id)
        self._ensure_outgoing_sales_invoice(source, invoice_id, operation="credit-note creation")
        key = idempotency_key or str(uuid4())
        try:
            payload = credit_note_from_invoice_to_billit(
                source,
                credit_note_number=number,
                issue_date=issue_date,
                due_date=due_date,
                reason=reason.strip() if reason and reason.strip() else None,
            )
        except ValueError as error:
            raise BillitSafetyError(
                f"Invoice {invoice_id} cannot be converted safely: {error} Nothing was created."
            ) from error

        credit_note_id = await self.client.create_credit_note_raw(
            payload,
            idempotency_key=key,
        )
        created = await self.client.get_invoice_raw(credit_note_id)
        self._ensure_outgoing_credit_note(created, credit_note_id, operation="verification")
        if str(created.get("OrderNumber", "")) != number or str(
            created.get("AboutInvoiceNumber", "")
        ) != str(source.get("OrderNumber", "")):
            raise BillitVerificationError(
                f"Billit created order {credit_note_id}, but its credit-note number or source "
                "invoice link could not be verified. Inspect Billit before retrying."
            )
        return created_credit_note_from_billit(
            created,
            source_invoice_id=invoice_id,
            idempotency_key=key,
        )

    async def mark_credit_note_paid(
        self,
        credit_note_id: int,
        *,
        paid_at: datetime,
        note: str | None = None,
        payment_method: PaymentMethod | None = None,
    ) -> CreditNoteStatus:
        self._ensure_write_allowed()
        current = await self.client.get_invoice_raw(credit_note_id)
        self._ensure_outgoing_credit_note(current, credit_note_id, operation="payment")
        if bool(current.get("Paid", False)):
            return credit_note_status_from_billit(current, already_paid=True)

        await self.client.mark_invoice_paid(
            credit_note_id,
            paid_at=paid_at,
            internal_info=note,
            payment_method=payment_method,
        )
        updated = await self.client.get_invoice_raw(credit_note_id)
        if not bool(updated.get("Paid", False)):
            raise BillitVerificationError(
                f"Billit accepted the update for credit note {credit_note_id}, but Paid=true "
                "was not visible during verification. Check Billit before retrying."
            )
        return credit_note_status_from_billit(updated)

    async def mark_credit_note_sent(self, credit_note_id: int) -> CreditNoteStatus:
        self._ensure_write_allowed()
        current = await self.client.get_invoice_raw(credit_note_id)
        self._ensure_outgoing_credit_note(current, credit_note_id, operation="sent-status update")
        if bool(current.get("IsSent", False)):
            return credit_note_status_from_billit(current, already_sent=True)

        await self.client.mark_order_sent(credit_note_id)
        updated = await self.client.get_invoice_raw(credit_note_id)
        if not bool(updated.get("IsSent", False)):
            raise BillitVerificationError(
                f"Billit accepted the update for credit note {credit_note_id}, but IsSent=true "
                "was not visible during verification. Check Billit before retrying."
            )
        return credit_note_status_from_billit(updated)

    async def send_credit_note(
        self,
        credit_note_id: int,
        *,
        transport: InvoiceDeliveryMethod,
    ) -> CreditNoteSendStatus:
        self._ensure_write_allowed()
        current = await self.client.get_invoice_raw(credit_note_id)
        self._ensure_outgoing_credit_note(current, credit_note_id, operation="delivery")

        if bool(current.get("IsSent", False)):
            return credit_note_send_status_from_billit(
                current,
                transport=transport,
                already_sent=True,
            )

        if transport is InvoiceDeliveryMethod.EMAIL:
            self._ensure_customer_email(current, credit_note_id, label="Credit note")

        peppol_capability = None
        if transport is InvoiceDeliveryMethod.PEPPOL:
            peppol_capability = await self._check_peppol_for_order(
                current,
                credit_note_id,
                required_document_type=PeppolDocumentType.CREDIT_NOTE,
            )
            if not peppol_capability.can_receive_required_document:
                raise BillitSafetyError(
                    f"Credit note {credit_note_id} was not sent: {peppol_capability.reason}"
                )

        await self.client.send_credit_note(credit_note_id, transport=transport)
        updated = await self.client.get_invoice_raw(credit_note_id)
        if not bool(updated.get("IsSent", False)):
            raise BillitVerificationError(
                f"Billit accepted the send command for credit note {credit_note_id}, but "
                "IsSent=true was not visible during verification. Check Billit before retrying."
            )
        return credit_note_send_status_from_billit(
            updated,
            transport=transport,
            already_sent=False,
            peppol_capability=peppol_capability,
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
            self._ensure_customer_email(current, invoice_id, label="Invoice")

        peppol_capability = None
        if transport is InvoiceDeliveryMethod.PEPPOL:
            peppol_capability = await self._check_peppol_for_order(
                current,
                invoice_id,
                required_document_type=PeppolDocumentType.INVOICE,
            )
            if not peppol_capability.can_receive_required_document:
                raise BillitSafetyError(
                    f"Invoice {invoice_id} was not sent: {peppol_capability.reason}"
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
            peppol_capability=peppol_capability,
        )

    async def _check_peppol_for_order(
        self,
        order: dict[str, object],
        order_id: int,
        *,
        required_document_type: PeppolDocumentType,
    ) -> PeppolRecipientCapability:
        customer = order.get("Customer")
        if not isinstance(customer, dict):
            customer = order.get("CounterParty")
        if not isinstance(customer, dict):
            raise BillitSafetyError(
                f"Order {order_id} has no customer data for a Peppol capability check."
            )

        identifiers = _peppol_identifiers(customer)
        if not identifiers:
            raise BillitSafetyError(
                f"Order {order_id} has no customer VAT or Peppol identifier; nothing was sent."
            )
        customer_name = next(iter(_party_names(customer)), None)
        fallback: PeppolRecipientCapability | None = None
        for identifier in identifiers:
            raw = await self.client.get_peppol_participant_raw(identifier)
            capability = peppol_capability_from_billit(
                raw,
                invoice_id=order_id,
                customer=customer_name,
                checked_identifier=identifier,
                required_document_type=required_document_type,
            )
            if capability.can_receive_required_document:
                return capability
            if fallback is None or capability.registered:
                fallback = capability
        assert fallback is not None
        return fallback

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

    @staticmethod
    def _ensure_outgoing_credit_note(
        order: dict[str, object],
        order_id: int,
        *,
        operation: str,
    ) -> None:
        order_type = str(order.get("OrderType", "")).lower()
        order_direction = str(order.get("OrderDirection", "")).lower()
        if order_type != "creditnote" or order_direction != "income":
            raise BillitSafetyError(
                f"Order {order_id} is not an outgoing sales credit note; "
                f"no {operation} action was taken."
            )

    @staticmethod
    def _ensure_customer_email(
        order: dict[str, object],
        order_id: int,
        *,
        label: str,
    ) -> None:
        customer = order.get("Customer")
        if not isinstance(customer, dict):
            customer = order.get("CounterParty")
        email = customer.get("Email") if isinstance(customer, dict) else None
        if not isinstance(email, str) or not email.strip():
            raise BillitSafetyError(
                f"{label} {order_id} has no customer email address; nothing was sent."
            )


def _items(data: dict[str, object]) -> list[dict[str, object]]:
    raw_items = data.get("Items") or data.get("items") or data.get("value") or []
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _party_id(party: dict[str, object]) -> int | None:
    value = party.get("PartyID") or party.get("CustomerID")
    try:
        return int(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _party_names(party: dict[str, object]) -> list[str]:
    values = [party.get("DisplayName"), party.get("Name"), party.get("CommercialName")]
    return [str(value).strip() for value in values if value is not None and str(value).strip()]


def _normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def _peppol_identifiers(customer: dict[str, object]) -> list[str]:
    identifiers: list[str] = []
    for key in ("VATNumber", "EnterpriseNumber", "CompanyNumber", "CBE"):
        value = customer.get(key)
        if value is not None and str(value).strip():
            identifiers.append(str(value).strip())

    raw_identifiers = customer.get("Identifiers") or []
    if isinstance(raw_identifiers, list):
        for item in raw_identifiers:
            if isinstance(item, str) and item.strip():
                identifiers.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            value = item.get("Identifier") or item.get("Value")
            if value is None or not str(value).strip():
                continue
            identifier = str(value).strip()
            scheme = item.get("SchemeID") or item.get("Scheme")
            if scheme is not None and str(scheme).strip() and ":" not in identifier:
                identifier = f"{str(scheme).strip()}:{identifier}"
            identifiers.append(identifier)
    return list(dict.fromkeys(identifiers))
