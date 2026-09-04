"""Mapping between Billit's PascalCase order shape and small public models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import (
    CreateInvoiceInput,
    CustomerView,
    FileReference,
    InvoiceAddress,
    InvoiceDeliveryMethod,
    InvoiceLineView,
    InvoiceReferenceMatch,
    InvoiceReferenceSearchResult,
    InvoiceSendStatus,
    InvoiceView,
    PaymentStatus,
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


def invoice_send_status_from_billit(
    data: dict[str, Any],
    *,
    transport: InvoiceDeliveryMethod,
    already_sent: bool,
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
