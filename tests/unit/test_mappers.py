from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from mcp_server_billit.mappers import (
    create_invoice_to_billit,
    customer_invoice_search_from_billit,
    invoice_from_billit,
    peppol_capability_from_billit,
    reference_search_from_billit,
    unpaid_invoices_from_billit,
)
from mcp_server_billit.models import (
    CreateCustomer,
    CreateInvoiceAddress,
    CreateInvoiceInput,
    CreateInvoiceLine,
)


def test_invoice_mapping_is_normalized_and_raw_is_opt_in(
    invoice_payload: dict[str, Any],
) -> None:
    invoice = invoice_from_billit(invoice_payload)

    assert invoice.invoice_id == 1194146
    assert invoice.invoice_number == "QS-244SC"
    assert invoice.customer is not None
    assert invoice.customer.name == "Example Customer"
    assert invoice.customer.address is not None
    assert invoice.customer.address.city == "Ghent"
    assert invoice.lines[0].total_incl == Decimal("242")
    assert invoice.total_vat == Decimal("42")
    assert invoice.pdf is not None
    assert invoice.pdf.filename == "QS-244SC.pdf"
    assert invoice.raw is None

    assert invoice_from_billit(invoice_payload, include_raw=True).raw == invoice_payload


def test_create_mapping_fixes_sales_invoice_fields() -> None:
    invoice = CreateInvoiceInput(
        invoice_number="INV-2026-001",
        issue_date=date(2026, 9, 3),
        due_date=date(2026, 10, 3),
        customer=CreateCustomer(
            name="Example Customer",
            vat_number="BE0123456789",
            address=CreateInvoiceAddress(
                street="Example Street",
                street_number="1",
                zipcode="1000",
                city="Brussels",
                country_code="BE",
            ),
        ),
        lines=[
            CreateInvoiceLine(
                description="Consulting",
                quantity=Decimal("1"),
                unit_price_excl=Decimal("100.00"),
                vat_percentage=Decimal("21"),
            )
        ],
        purchase_order_reference="PO-42",
    )

    payload = create_invoice_to_billit(invoice)

    assert payload["OrderType"] == "Invoice"
    assert payload["OrderDirection"] == "Income"
    assert payload["Customer"]["PartyType"] == "Customer"
    assert payload["Customer"]["Addresses"][0]["AddressType"] == "InvoiceAddress"
    assert payload["OrderLines"][0]["UnitPriceExcl"] == 100.0
    assert payload["Reference"] == "PO-42"
    assert "IsSent" not in payload


def test_payment_reference_search_mapping_returns_compact_matches() -> None:
    result = reference_search_from_billit(
        {
            "Items": [
                {
                    "OrderID": 139602588,
                    "PaymentReference": "4319",
                    "CounterParty": {"DisplayName": "Example Customer"},
                    "OrderNumber": "2730",
                    "OrderDate": "2026-08-01T00:00:00",
                    "ExpiryDate": "2026-08-31T00:00:00",
                    "Paid": True,
                    "IsSent": True,
                    "ToPay": 0,
                    "OrderStatus": "Paid",
                    "Overdue": False,
                    "DaysOverdue": 0,
                    "TotalIncl": 160,
                    "Currency": "EUR",
                }
            ]
        }
    )

    assert result.found is True
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.invoice_id == 139602588
    assert match.payment_reference == "4319"
    assert match.customer == "Example Customer"
    assert match.invoice_number == "2730"
    assert match.paid is True
    assert match.sent is True
    assert match.issue_date is not None
    assert match.due_date is not None
    assert match.days_overdue == 0
    assert match.amount_remaining == Decimal("0")
    assert match.total == Decimal("160")


def test_payment_reference_search_mapping_handles_no_matches() -> None:
    result = reference_search_from_billit({"Items": []})
    assert result.found is False
    assert result.matches == []


def test_unpaid_invoice_mapping_returns_count_and_summaries(
    invoice_payload: dict[str, Any],
) -> None:
    invoice_payload["CounterParty"] = {"DisplayName": "Example Customer"}
    result = unpaid_invoices_from_billit(
        {"Items": [invoice_payload], "NextPageLink": "https://example.test/next"},
        max_results=10,
    )

    assert result.returned_count == 1
    assert result.max_results == 10
    assert result.has_more is True
    assert result.invoices[0].invoice_id == 1194146
    assert result.invoices[0].customer == "Example Customer"
    assert result.invoices[0].amount_remaining == Decimal("242")
    assert result.invoices[0].sent is False


def test_customer_invoice_search_mapping_reports_counts(invoice_payload: dict[str, Any]) -> None:
    invoice_payload["CounterParty"] = {"DisplayName": "Naos"}
    result = customer_invoice_search_from_billit(
        {"Items": [invoice_payload]},
        query="nao",
        matched_customer_count=1,
        max_results=25,
        customer_results_have_more=False,
    )

    assert result.query == "nao"
    assert result.found is True
    assert result.matched_customer_count == 1
    assert result.returned_count == 1
    assert result.invoices[0].customer == "Naos"


def test_peppol_capability_requires_registration_and_invoice_document() -> None:
    capable = peppol_capability_from_billit(
        {
            "Registered": True,
            "DocumentTypes": ["BISv3Invoice", "BISv3CreditNote"],
        },
        invoice_id=7,
        customer="Naos",
        checked_identifier="BE0123456789",
    )
    self_billing_only = peppol_capability_from_billit(
        {
            "Registered": "true",
            "ServiceDetails": [{"DocumentType": {"Identifier": "BISv3InvoiceSelfBilling"}}],
        },
        invoice_id=7,
        customer="Naos",
        checked_identifier="BE0123456789",
    )
    response_only = peppol_capability_from_billit(
        {"Registered": True, "DocumentTypes": ["BISv3InvoiceResponse"]},
        invoice_id=7,
        customer="Naos",
        checked_identifier="BE0123456789",
    )

    assert capable.registered is True
    assert capable.can_receive_invoices is True
    assert self_billing_only.registered is True
    assert self_billing_only.can_receive_invoices is False
    assert response_only.can_receive_invoices is False
