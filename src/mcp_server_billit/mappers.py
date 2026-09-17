"""Mapping between Billit's PascalCase order shape and small public models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import (
    CreatedCreditNote,
    CreateInvoiceInput,
    CreditNoteSendStatus,
    CreditNoteStatus,
    CustomerInvoiceSearchResult,
    CustomerView,
    FileReference,
    InvoiceAddress,
    InvoiceDeliveryMethod,
    InvoiceLineView,
    InvoiceReferenceMatch,
    InvoiceReferenceSearchResult,
    InvoiceSendStatus,
    InvoiceStatus,
    InvoiceView,
    PaymentStatus,
    PeppolDocumentType,
    PeppolRecipientCapability,
    SupplierDocumentList,
    SupplierDocumentSummary,
    SupplierDocumentView,
    SupplierInvoiceSearchResult,
    SupplierView,
    UnpaidInvoiceList,
)


def invoice_from_billit(data: dict[str, Any], *, include_raw: bool = False) -> InvoiceView:
    lines_data = data.get("OrderLines") or data.get("Orderlines") or []
    customer_data = data.get("Customer")
    pdf_data = data.get("OrderPDF")

    return InvoiceView(
        invoice_id=int(data["OrderID"]),
        invoice_number=_string(data.get("OrderNumber")),
        order_type=_string(data.get("OrderType")),
        order_direction=_string(data.get("OrderDirection")),
        issue_date=_datetime(data.get("OrderDate")),
        due_date=_datetime(data.get("ExpiryDate")),
        currency=_string(data.get("Currency")),
        customer=_customer(customer_data) if isinstance(customer_data, dict) else None,
        lines=[_line(line) for line in lines_data if isinstance(line, dict)],
        total_excl=_decimal(data.get("TotalExcl")),
        total_vat=_decimal(data.get("TotalVAT")),
        total_incl=_decimal(data.get("TotalIncl")),
        amount_to_pay=_decimal(data.get("ToPay")),
        paid=bool(data.get("Paid", False)),
        paid_at=_datetime(data.get("PaidDate")),
        payment_method=_string(data.get("PaymentMethod")),
        sent=bool(data.get("IsSent", False)),
        created_at=_datetime(data.get("Created")),
        modified_at=_datetime(data.get("LastModified")),
        pdf=_file_reference(pdf_data) if isinstance(pdf_data, dict) else None,
        delivery=data.get("CurrentDocumentDeliveryDetails")
        if isinstance(data.get("CurrentDocumentDeliveryDetails"), dict)
        else None,
        raw=data if include_raw else None,
    )


def payment_status_from_billit(data: dict[str, Any], *, already_paid: bool) -> PaymentStatus:
    return PaymentStatus(
        invoice_id=int(data["OrderID"]),
        paid=bool(data.get("Paid", False)),
        paid_at=_datetime(data.get("PaidDate")),
        payment_method=_string(data.get("PaymentMethod")),
        already_paid=already_paid,
    )


def invoice_status_from_billit(
    data: dict[str, Any],
    *,
    already_sent: bool = False,
) -> InvoiceStatus:
    return InvoiceStatus(
        invoice_id=int(data["OrderID"]),
        invoice_number=_string(data.get("OrderNumber")),
        paid=bool(data.get("Paid", False)),
        sent=bool(data.get("IsSent", False)),
        already_sent=already_sent,
    )


def reference_search_from_billit(data: dict[str, Any]) -> InvoiceReferenceSearchResult:
    matches = _invoice_summaries(data)
    return InvoiceReferenceSearchResult(found=bool(matches), matches=matches)


def unpaid_invoices_from_billit(
    data: dict[str, Any],
    *,
    max_results: int,
) -> UnpaidInvoiceList:
    invoices = _invoice_summaries(data)
    next_page = data.get("NextPageLink") or data.get("nextPageLink")
    return UnpaidInvoiceList(
        returned_count=len(invoices),
        max_results=max_results,
        has_more=bool(next_page),
        invoices=invoices,
    )


def customer_invoice_search_from_billit(
    data: dict[str, Any],
    *,
    query: str,
    matched_customer_count: int,
    max_results: int,
    customer_results_have_more: bool,
) -> CustomerInvoiceSearchResult:
    invoices = _invoice_summaries(data)
    next_page = data.get("NextPageLink") or data.get("nextPageLink")
    return CustomerInvoiceSearchResult(
        query=query,
        found=bool(invoices),
        matched_customer_count=matched_customer_count,
        returned_count=len(invoices),
        max_results=max_results,
        has_more=customer_results_have_more or bool(next_page),
        invoices=invoices,
    )


def supplier_document_from_billit(
    data: dict[str, Any],
    *,
    include_raw: bool = False,
) -> SupplierDocumentView:
    supplier_data = data.get("Supplier")
    if not isinstance(supplier_data, dict):
        supplier_data = data.get("CounterParty")
    lines_data = data.get("OrderLines") or data.get("Orderlines") or []
    attachments_data = data.get("Attachments") or []
    summary = _supplier_document_summary(data)

    return SupplierDocumentView(
        **summary.model_dump(),
        supplier_details=_supplier(supplier_data) if isinstance(supplier_data, dict) else None,
        payment_reference=_string(data.get("PaymentReference")),
        purchase_order_reference=_string(data.get("Reference")),
        comments=_string(data.get("Comments")),
        delivery_date=_datetime(data.get("DeliveryDate")),
        period_from=_datetime(data.get("PeriodFrom")),
        period_till=_datetime(data.get("PeriodTill")),
        created_at=_datetime(data.get("Created")),
        modified_at=_datetime(data.get("LastModified")),
        lines=[_line(line) for line in lines_data if isinstance(line, dict)],
        attachments=[_file_reference(item) for item in attachments_data if isinstance(item, dict)],
        raw=data if include_raw else None,
    )


def supplier_documents_from_billit(
    data: dict[str, Any],
    *,
    max_results: int,
) -> SupplierDocumentList:
    documents = _supplier_document_summaries(data)
    next_page = data.get("NextPageLink") or data.get("nextPageLink")
    return SupplierDocumentList(
        returned_count=len(documents),
        max_results=max_results,
        has_more=bool(next_page),
        documents=documents,
    )


def supplier_invoice_search_from_billit(
    data: dict[str, Any],
    *,
    query: str,
    max_results: int,
    matched_supplier_count: int | None = None,
    supplier_results_have_more: bool = False,
) -> SupplierInvoiceSearchResult:
    documents = _supplier_document_summaries(data)
    next_page = data.get("NextPageLink") or data.get("nextPageLink")
    return SupplierInvoiceSearchResult(
        query=query,
        found=bool(documents),
        matched_supplier_count=matched_supplier_count,
        returned_count=len(documents),
        max_results=max_results,
        has_more=supplier_results_have_more or bool(next_page),
        documents=documents,
    )


def peppol_capability_from_billit(
    data: dict[str, Any],
    *,
    invoice_id: int,
    customer: str | None,
    checked_identifier: str,
    required_document_type: PeppolDocumentType = PeppolDocumentType.INVOICE,
) -> PeppolRecipientCapability:
    registered = _boolean(data.get("Registered"))
    document_types = _document_types(data)
    can_receive_invoices = registered and any(
        _is_invoice_document(value) for value in document_types
    )
    can_receive_credit_notes = registered and any(
        _is_credit_note_document(value) for value in document_types
    )
    can_receive_required_document = {
        PeppolDocumentType.INVOICE: can_receive_invoices,
        PeppolDocumentType.CREDIT_NOTE: can_receive_credit_notes,
    }[required_document_type]
    if not registered:
        reason = "Billit reports that this identifier is not registered on Peppol."
    elif not can_receive_required_document:
        label = "invoice" if required_document_type is PeppolDocumentType.INVOICE else "credit-note"
        reason = (
            f"The Peppol participant is registered, but Billit did not report a {label}-capable "
            "document type."
        )
    else:
        label = (
            "invoices" if required_document_type is PeppolDocumentType.INVOICE else "credit notes"
        )
        reason = f"Billit reports that this Peppol participant can receive {label}."
    return PeppolRecipientCapability(
        invoice_id=invoice_id,
        customer=customer,
        checked_identifier=checked_identifier,
        registered=registered,
        required_document_type=required_document_type,
        can_receive_required_document=can_receive_required_document,
        can_receive_invoices=can_receive_invoices,
        can_receive_credit_notes=can_receive_credit_notes,
        document_types=document_types,
        reason=reason,
    )


def invoice_send_status_from_billit(
    data: dict[str, Any],
    *,
    transport: InvoiceDeliveryMethod,
    already_sent: bool,
    peppol_capability: PeppolRecipientCapability | None = None,
) -> InvoiceSendStatus:
    delivery = data.get("CurrentDocumentDeliveryDetails")
    delivered = delivery.get("IsDocumentDelivered") if isinstance(delivery, dict) else None
    return InvoiceSendStatus(
        invoice_id=int(data["OrderID"]),
        invoice_number=_string(data.get("OrderNumber")),
        requested_transport=transport,
        sent=bool(data.get("IsSent", False)),
        already_sent=already_sent,
        delivery_confirmed=delivered if isinstance(delivered, bool) else None,
        peppol_capability=peppol_capability,
    )


def credit_note_from_invoice_to_billit(
    invoice: dict[str, Any],
    *,
    credit_note_number: str,
    issue_date: date,
    due_date: date | None,
    reason: str | None,
) -> dict[str, Any]:
    invoice_number = _string(invoice.get("OrderNumber"))
    customer = invoice.get("Customer")
    if not isinstance(customer, dict):
        customer = invoice.get("CounterParty")
    customer_id = _integer(invoice.get("CustomerID"))
    if customer_id is None and isinstance(customer, dict):
        customer_id = _integer(customer.get("PartyID") or customer.get("CustomerID"))
    lines = invoice.get("OrderLines") or invoice.get("Orderlines") or []

    if not invoice_number:
        raise ValueError("The source invoice has no OrderNumber.")
    if customer_id is None:
        raise ValueError("The source invoice has no reusable customer PartyID.")
    if not isinstance(lines, list) or not lines:
        raise ValueError("The source invoice has no order lines to credit.")

    mapped_lines = [_credit_note_line(line) for line in lines if isinstance(line, dict)]
    if len(mapped_lines) != len(lines):
        raise ValueError("The source invoice contains an unsupported order-line value.")

    payload: dict[str, Any] = {
        "OrderType": "CreditNote",
        "OrderDirection": "Income",
        "OrderNumber": credit_note_number,
        "OrderDate": issue_date.isoformat(),
        "ExpiryDate": (due_date or issue_date).isoformat(),
        "CustomerID": customer_id,
        "OrderLines": mapped_lines,
        "Currency": _string(invoice.get("Currency")) or "EUR",
        "AboutInvoiceNumber": invoice_number,
    }
    if reason:
        payload["Comments"] = reason
    return payload


def credit_note_status_from_billit(
    data: dict[str, Any],
    *,
    already_paid: bool = False,
    already_sent: bool = False,
) -> CreditNoteStatus:
    return CreditNoteStatus(
        credit_note_id=int(data["OrderID"]),
        credit_note_number=_string(data.get("OrderNumber")),
        source_invoice_number=_string(data.get("AboutInvoiceNumber")),
        paid=bool(data.get("Paid", False)),
        paid_at=_datetime(data.get("PaidDate")),
        sent=bool(data.get("IsSent", False)),
        already_paid=already_paid,
        already_sent=already_sent,
    )


def created_credit_note_from_billit(
    data: dict[str, Any],
    *,
    source_invoice_id: int,
    idempotency_key: str,
) -> CreatedCreditNote:
    status = credit_note_status_from_billit(data)
    return CreatedCreditNote(
        **status.model_dump(),
        source_invoice_id=source_invoice_id,
        total=_decimal(data.get("TotalIncl")),
        currency=_string(data.get("Currency")),
        idempotency_key=idempotency_key,
    )


def credit_note_send_status_from_billit(
    data: dict[str, Any],
    *,
    transport: InvoiceDeliveryMethod,
    already_sent: bool,
    peppol_capability: PeppolRecipientCapability | None = None,
) -> CreditNoteSendStatus:
    delivery = data.get("CurrentDocumentDeliveryDetails")
    delivered = delivery.get("IsDocumentDelivered") if isinstance(delivery, dict) else None
    return CreditNoteSendStatus(
        credit_note_id=int(data["OrderID"]),
        credit_note_number=_string(data.get("OrderNumber")),
        source_invoice_number=_string(data.get("AboutInvoiceNumber")),
        requested_transport=transport,
        sent=bool(data.get("IsSent", False)),
        already_sent=already_sent,
        delivery_confirmed=delivered if isinstance(delivered, bool) else None,
        peppol_capability=peppol_capability,
    )


def _invoice_summaries(data: dict[str, Any]) -> list[InvoiceReferenceMatch]:
    items = data.get("Items") or data.get("items") or data.get("value") or []
    matches: list[InvoiceReferenceMatch] = []
    for item in items:
        if not isinstance(item, dict) or item.get("OrderID") is None:
            continue
        counterparty = item.get("CounterParty")
        if not isinstance(counterparty, dict):
            counterparty = item.get("Customer")
        matches.append(
            InvoiceReferenceMatch(
                invoice_id=int(item["OrderID"]),
                payment_reference=_string(item.get("PaymentReference")),
                customer=_party_display_name(counterparty),
                invoice_number=_string(item.get("OrderNumber")),
                issue_date=_datetime(item.get("OrderDate")),
                due_date=_datetime(item.get("ExpiryDate")),
                paid=bool(item.get("Paid", False)),
                sent=bool(item.get("IsSent", False)),
                amount_remaining=_decimal(item.get("ToPay")),
                billit_status=_string(item.get("OrderStatus")),
                overdue=bool(item.get("Overdue", False)),
                days_overdue=_integer(item.get("DaysOverdue")),
                total=_decimal(item.get("TotalIncl")),
                currency=_string(item.get("Currency")),
            )
        )
    return matches


def _supplier_document_summaries(data: dict[str, Any]) -> list[SupplierDocumentSummary]:
    items = data.get("Items") or data.get("items") or data.get("value") or []
    if not isinstance(items, list):
        return []
    return [
        _supplier_document_summary(item)
        for item in items
        if isinstance(item, dict) and item.get("OrderID") is not None
    ]


def _supplier_document_summary(data: dict[str, Any]) -> SupplierDocumentSummary:
    supplier_data = data.get("Supplier")
    if not isinstance(supplier_data, dict):
        supplier_data = data.get("CounterParty")
    pdf_data = data.get("OrderPDF")
    attachments_data = data.get("Attachments") or []
    attachment_count = len(attachments_data) if isinstance(attachments_data, list) else 0
    return SupplierDocumentSummary(
        order_id=int(data["OrderID"]),
        document_type=_string(data.get("OrderType")),
        supplier=_party_display_name(supplier_data),
        document_number=_string(data.get("OrderNumber")),
        issue_date=_datetime(data.get("OrderDate")),
        due_date=_datetime(data.get("ExpiryDate")),
        total=_decimal(data.get("TotalIncl")),
        currency=_string(data.get("Currency")),
        paid=bool(data.get("Paid", False)),
        amount_to_pay=_decimal(data.get("ToPay")),
        billit_status=_string(data.get("OrderStatus")),
        overdue=bool(data.get("Overdue", False)),
        days_overdue=_integer(data.get("DaysOverdue")),
        approval_status=_string(data.get("ApprovalStatus")),
        external_provider=_string(data.get("ExternalProvider")),
        pdf=_file_reference(pdf_data) if isinstance(pdf_data, dict) else None,
        attachment_count=attachment_count,
    )


def create_invoice_to_billit(invoice: CreateInvoiceInput) -> dict[str, Any]:
    customer: dict[str, Any] = {
        "Name": invoice.customer.name,
        "PartyType": "Customer",
    }
    if invoice.customer.vat_number:
        customer["VATNumber"] = invoice.customer.vat_number
    if invoice.customer.email:
        customer["Email"] = invoice.customer.email
    if invoice.customer.address:
        address = invoice.customer.address
        mapped_address: dict[str, Any] = {
            "AddressType": "InvoiceAddress",
            "Street": address.street,
            "StreetNumber": address.street_number,
            "Zipcode": address.zipcode,
            "City": address.city,
            "CountryCode": address.country_code,
        }
        if address.box:
            mapped_address["Box"] = address.box
        customer["Addresses"] = [mapped_address]

    payload: dict[str, Any] = {
        "OrderType": "Invoice",
        "OrderDirection": "Income",
        "OrderNumber": invoice.invoice_number,
        "OrderDate": invoice.issue_date.isoformat(),
        "ExpiryDate": invoice.due_date.isoformat(),
        "Currency": invoice.currency,
        "Customer": customer,
        "OrderLines": [
            {
                "Description": line.description,
                "Quantity": float(line.quantity),
                "UnitPriceExcl": float(line.unit_price_excl),
                "VATPercentage": float(line.vat_percentage),
                **({"Reference": line.reference} if line.reference else {}),
            }
            for line in invoice.lines
        ],
    }

    optional_fields = {
        "PaymentReference": invoice.payment_reference,
        "Reference": invoice.purchase_order_reference,
        "OrderTitle": invoice.buyer_reference,
        "DeliveryDate": invoice.delivery_date.isoformat() if invoice.delivery_date else None,
    }
    payload.update({key: value for key, value in optional_fields.items() if value is not None})
    return payload


def _customer(data: dict[str, Any]) -> CustomerView:
    addresses = data.get("Addresses") or []
    selected: dict[str, Any] | None = None
    for address in addresses:
        if isinstance(address, dict) and address.get("AddressType") == "InvoiceAddress":
            selected = address
            break
    if selected is None and addresses and isinstance(addresses[0], dict):
        selected = addresses[0]

    if selected is None and any(
        data.get(key) for key in ("Street", "StreetNumber", "Zipcode", "City", "CountryCode")
    ):
        selected = data

    return CustomerView(
        customer_id=_integer(data.get("PartyID") or data.get("CustomerID")),
        name=_string(data.get("Name")),
        vat_number=_string(data.get("VATNumber")),
        email=_string(data.get("Email")),
        address=_address(selected) if selected else None,
    )


def _supplier(data: dict[str, Any]) -> SupplierView:
    addresses = data.get("Addresses") or []
    selected: dict[str, Any] | None = None
    for address in addresses:
        if isinstance(address, dict) and address.get("AddressType") == "InvoiceAddress":
            selected = address
            break
    if selected is None and addresses and isinstance(addresses[0], dict):
        selected = addresses[0]
    if selected is None and any(
        data.get(key) for key in ("Street", "StreetNumber", "Zipcode", "City", "CountryCode")
    ):
        selected = data

    iban = _string(data.get("IBAN"))
    bic = _string(data.get("BIC"))
    bank_accounts = data.get("BankAccounts") or []
    if isinstance(bank_accounts, list):
        for account in bank_accounts:
            if not isinstance(account, dict):
                continue
            iban = iban or _string(account.get("IBAN"))
            bic = bic or _string(account.get("BIC"))
            if iban and bic:
                break

    return SupplierView(
        supplier_id=_integer(data.get("PartyID") or data.get("SupplierID")),
        name=_string(data.get("DisplayName") or data.get("Name")),
        vat_number=_string(data.get("VATNumber")),
        email=_string(data.get("Email")),
        iban=iban,
        bic=bic,
        address=_address(selected) if selected else None,
    )


def _address(data: dict[str, Any]) -> InvoiceAddress:
    return InvoiceAddress(
        name=_string(data.get("Name")),
        street=_string(data.get("Street")),
        street_number=_string(data.get("StreetNumber")),
        box=_string(data.get("Box")),
        zipcode=_string(data.get("Zipcode")),
        city=_string(data.get("City")),
        country_code=_string(data.get("CountryCode")),
    )


def _line(data: dict[str, Any]) -> InvoiceLineView:
    return InvoiceLineView(
        description=_string(data.get("Description")),
        quantity=_decimal(data.get("Quantity")),
        unit_price_excl=_decimal(data.get("UnitPriceExcl")),
        vat_percentage=_decimal(data.get("VATPercentage")),
        total_excl=_decimal(data.get("TotalExcl")),
        total_vat=_decimal(data.get("TotalVAT")),
        total_incl=_decimal(data.get("TotalIncl")),
        reference=_string(data.get("Reference")),
    )


def _credit_note_line(data: dict[str, Any]) -> dict[str, Any]:
    required = ("Quantity", "UnitPriceExcl", "Description", "VATPercentage")
    if any(data.get(key) is None for key in required):
        raise ValueError("A source invoice line is missing credit-note fields.")
    quantity = _decimal(data.get("Quantity"))
    unit_price = _decimal(data.get("UnitPriceExcl"))
    if quantity is None or unit_price is None or quantity < 0 or unit_price < 0:
        raise ValueError("Negative or invalid source invoice lines cannot be credited safely.")

    mapped = {key: data[key] for key in required}
    optional = (
        "Code",
        "Reference",
        "DescriptionExtended",
        "VentilationCode",
        "ProductID",
        "Unit",
        "CustomFields",
        "AnalyticCostBearer",
        "AnalyticCostCenter",
        "ReductionPercentage",
        "AllowanceChargeIndicator",
        "ExternalSequence",
    )
    mapped.update({key: data[key] for key in optional if data.get(key) is not None})
    return mapped


def _file_reference(data: dict[str, Any]) -> FileReference:
    return FileReference(
        file_id=_string(data.get("FileID")),
        filename=_string(data.get("FileName")),
        mime_type=_string(data.get("MimeType")),
    )


def _party_display_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return _string(value.get("DisplayName") or value.get("Name"))


def _datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> str | None:
    return str(value) if value is not None and value != "" else None


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _document_types(data: dict[str, Any]) -> list[str]:
    values: list[str] = []
    raw_types = data.get("DocumentTypes") or []
    if isinstance(raw_types, str):
        raw_types = [raw_types]
    if isinstance(raw_types, list):
        for item in raw_types:
            value = _document_type_value(item)
            if value:
                values.append(value)

    service_details = data.get("ServiceDetails") or []
    if isinstance(service_details, dict):
        service_details = [service_details]
    if isinstance(service_details, list):
        for detail in service_details:
            if not isinstance(detail, dict):
                continue
            for key in ("DocumentType", "DocumentTypeIdentifier", "DocumentTypeID"):
                value = _document_type_value(detail.get(key))
                if value:
                    values.append(value)

    return list(dict.fromkeys(values))


def _document_type_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("Name", "Identifier", "Value", "DocumentType"):
            nested = _string(value.get(key))
            if nested:
                return nested
    return None


def _is_invoice_document(value: str) -> bool:
    normalized = value.casefold().replace("-", "").replace("_", "")
    return normalized.endswith("invoice") and "selfbilling" not in normalized


def _is_credit_note_document(value: str) -> bool:
    normalized = value.casefold().replace("-", "").replace("_", "")
    return normalized.endswith("creditnote") and "selfbilling" not in normalized
