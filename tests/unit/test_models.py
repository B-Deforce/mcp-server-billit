from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from mcp_server_billit.models import CreateCustomer, CreateInvoiceInput, CreateInvoiceLine


def test_due_date_cannot_precede_issue_date() -> None:
    with pytest.raises(ValidationError, match="due_date"):
        CreateInvoiceInput(
            invoice_number="INV-1",
            issue_date=date(2026, 9, 2),
            due_date=date(2026, 9, 1),
            customer=CreateCustomer(name="Customer"),
            lines=[
                CreateInvoiceLine(
                    description="Work",
                    quantity=Decimal("1"),
                    unit_price_excl=Decimal("10"),
                    vat_percentage=Decimal("21"),
                )
            ],
        )


def test_currency_is_normalized_before_pattern_validation() -> None:
    invoice = CreateInvoiceInput(
        invoice_number="INV-1",
        issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 30),
        currency="eur",
        customer=CreateCustomer(name="Customer"),
        lines=[
            CreateInvoiceLine(
                description="Work",
                quantity=Decimal("1"),
                unit_price_excl=Decimal("10"),
                vat_percentage=Decimal("21"),
            )
        ],
    )
    assert invoice.currency == "EUR"
