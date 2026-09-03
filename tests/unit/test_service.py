from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from mcp_server_billit.config import BillitConfig, BillitEnvironment
from mcp_server_billit.errors import BillitSafetyError
from mcp_server_billit.models import CreateCustomer, CreateInvoiceInput, CreateInvoiceLine
from mcp_server_billit.service import BillitService


class FakeClient:
    def __init__(self, payload: dict[str, Any], *, config: BillitConfig | None = None) -> None:
        self.payload = payload
        self.config = config or BillitConfig(api_key="key", party_id=1)
        self.patch_calls = 0
        self.create_calls = 0

    async def get_invoice_raw(self, _invoice_id: int) -> dict[str, Any]:
        return deepcopy(self.payload)

    async def find_invoices_by_payment_reference_raw(
        self, payment_reference: str, *, max_results: int
    ) -> dict[str, Any]:
        assert payment_reference == "4319"
        assert max_results == 3
        return {"Items": [deepcopy(self.payload)]}

    async def mark_invoice_paid(self, invoice_id: int, **_kwargs: Any) -> None:
        self.patch_calls += 1
        assert invoice_id == int(self.payload["OrderID"])
        self.payload["Paid"] = True
        self.payload["PaidDate"] = "2026-09-03T12:30:00"

    async def create_invoice_raw(self, payload: dict[str, Any], *, idempotency_key: str) -> int:
        self.create_calls += 1
        assert payload["OrderType"] == "Invoice"
        assert idempotency_key
        return 987


@pytest.mark.asyncio
async def test_already_paid_invoice_is_idempotent(invoice_payload: dict[str, Any]) -> None:
    invoice_payload["Paid"] = True
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.mark_invoice_paid(1194146, paid_at=datetime(2026, 9, 3, 12, 30))

    assert result.already_paid is True
    assert client.patch_calls == 0


@pytest.mark.asyncio
async def test_find_by_payment_reference_is_read_only_and_compact(
    invoice_payload: dict[str, Any],
) -> None:
    invoice_payload["PaymentReference"] = "4319"
    invoice_payload["CounterParty"] = {"DisplayName": "Example Customer"}
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.find_invoices_by_payment_reference(" 4319 ", max_results=3)

    assert result.found is True
    assert result.matches[0].payment_reference == "4319"
    assert client.patch_calls == 0
    assert client.create_calls == 0


@pytest.mark.asyncio
async def test_non_sales_order_is_never_patched(invoice_payload: dict[str, Any]) -> None:
    invoice_payload["OrderDirection"] = "Cost"
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    with pytest.raises(BillitSafetyError, match="not an outgoing sales invoice"):
        await service.mark_invoice_paid(1194146, paid_at=datetime(2026, 9, 3, 12, 30))

    assert client.patch_calls == 0


@pytest.mark.asyncio
async def test_mark_paid_is_verified(invoice_payload: dict[str, Any]) -> None:
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.mark_invoice_paid(1194146, paid_at=datetime(2026, 9, 3, 12, 30))

    assert result.paid is True
    assert result.already_paid is False
    assert client.patch_calls == 1


@pytest.mark.asyncio
async def test_production_write_requires_second_opt_in(invoice_payload: dict[str, Any]) -> None:
    client = FakeClient(
        invoice_payload,
        config=BillitConfig(
            api_key="key",
            party_id=1,
            environment=BillitEnvironment.PRODUCTION,
            allow_production_writes=False,
        ),
    )
    service = BillitService(client)  # type: ignore[arg-type]

    with pytest.raises(BillitSafetyError, match="Production writes are disabled"):
        await service.mark_invoice_paid(1194146, paid_at=datetime(2026, 9, 3, 12, 30))


@pytest.mark.asyncio
async def test_create_invoice_does_not_send(invoice_payload: dict[str, Any]) -> None:
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]
    invoice = CreateInvoiceInput(
        invoice_number="INV-1",
        issue_date=date(2026, 9, 3),
        due_date=date(2026, 10, 3),
        customer=CreateCustomer(name="Customer"),
        lines=[
            CreateInvoiceLine(
                description="Work",
                quantity=Decimal("1"),
                unit_price_excl=Decimal("100"),
                vat_percentage=Decimal("21"),
            )
        ],
    )

    created = await service.create_invoice(invoice, idempotency_key="stable-attempt")

    assert created.invoice_id == 987
    assert created.sent is False
    assert created.idempotency_key == "stable-attempt"
    assert client.create_calls == 1
