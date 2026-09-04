from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from mcp_server_billit.config import BillitConfig, BillitEnvironment
from mcp_server_billit.errors import BillitSafetyError, BillitVerificationError
from mcp_server_billit.models import (
    CreateCustomer,
    CreateInvoiceInput,
    CreateInvoiceLine,
    InvoiceDeliveryMethod,
)
from mcp_server_billit.service import BillitService


class FakeClient:
    def __init__(self, payload: dict[str, Any], *, config: BillitConfig | None = None) -> None:
        self.payload = payload
        self.config = config or BillitConfig(api_key="key", party_id=1)
        self.patch_calls = 0
        self.create_calls = 0
        self.send_calls: list[tuple[int, InvoiceDeliveryMethod]] = []
        self.peppol_checks: list[str] = []
        self.peppol_response: dict[str, Any] = {
            "Registered": True,
            "DocumentTypes": ["BISv3Invoice"],
        }

    async def get_invoice_raw(self, _invoice_id: int) -> dict[str, Any]:
        return deepcopy(self.payload)

    async def find_invoices_by_payment_reference_raw(
        self, payment_reference: str, *, max_results: int
    ) -> dict[str, Any]:
        assert payment_reference == "4319"
        assert max_results == 3
        return {"Items": [deepcopy(self.payload)]}

    async def list_unpaid_invoices_raw(self, *, max_results: int) -> dict[str, Any]:
        assert max_results == 10
        return {"Items": [deepcopy(self.payload)]}

    async def search_customers_raw(self, customer_name: str, *, max_results: int) -> dict[str, Any]:
        assert customer_name == "exam"
        assert max_results == 100
        return {
            "Items": [
                {"PartyID": 588708, "Name": "Éxample Customer"},
                {"PartyID": 999, "Name": "Unrelated Company"},
            ]
        }

    async def find_invoices_by_customer_ids_raw(
        self, customer_ids: list[int], *, max_results: int
    ) -> dict[str, Any]:
        assert customer_ids == [588708]
        assert max_results == 25
        return {"Items": [deepcopy(self.payload)]}

    async def get_peppol_participant_raw(self, identifier: str) -> dict[str, Any]:
        self.peppol_checks.append(identifier)
        return deepcopy(self.peppol_response)

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

    async def send_invoice(
        self,
        invoice_id: int,
        *,
        transport: InvoiceDeliveryMethod,
    ) -> None:
        self.send_calls.append((invoice_id, transport))
        self.payload["IsSent"] = True
        self.payload["CurrentDocumentDeliveryDetails"] = {"IsDocumentDelivered": True}


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
async def test_list_unpaid_invoices_is_read_only_and_compact(
    invoice_payload: dict[str, Any],
) -> None:
    invoice_payload["CounterParty"] = {"DisplayName": "Example Customer"}
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.list_unpaid_invoices()

    assert result.returned_count == 1
    assert result.max_results == 10
    assert result.has_more is False
    assert result.invoices[0].invoice_id == 1194146
    assert client.patch_calls == 0
    assert client.create_calls == 0
    assert client.send_calls == []


@pytest.mark.asyncio
async def test_list_unpaid_invoices_accepts_one_hundred_and_rejects_more(
    invoice_payload: dict[str, Any],
) -> None:
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    async def accept_one_hundred(*, max_results: int) -> dict[str, Any]:
        assert max_results == 100
        return {"Items": []}

    client.list_unpaid_invoices_raw = accept_one_hundred  # type: ignore[method-assign]
    result = await service.list_unpaid_invoices(max_results=100)

    assert result.max_results == 100
    with pytest.raises(ValueError, match="between 1 and 100"):
        await service.list_unpaid_invoices(max_results=101)


@pytest.mark.asyncio
async def test_find_invoices_by_partial_customer_name_is_verified_locally(
    invoice_payload: dict[str, Any],
) -> None:
    invoice_payload["CounterParty"] = {"DisplayName": "Éxample Customer"}
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.find_invoices_by_customer_name("  exam  ", max_results=25)

    assert result.found is True
    assert result.query == "exam"
    assert result.matched_customer_count == 1
    assert result.invoices[0].customer == "Éxample Customer"
    assert client.send_calls == []


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


@pytest.mark.asyncio
async def test_send_invoice_by_email_is_verified(invoice_payload: dict[str, Any]) -> None:
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.send_invoice(1194146, transport=InvoiceDeliveryMethod.EMAIL)

    assert result.sent is True
    assert result.already_sent is False
    assert result.delivery_confirmed is True
    assert result.requested_transport is InvoiceDeliveryMethod.EMAIL
    assert client.send_calls == [(1194146, InvoiceDeliveryMethod.EMAIL)]
    assert client.peppol_checks == []


@pytest.mark.asyncio
async def test_peppol_capability_check_is_read_only(invoice_payload: dict[str, Any]) -> None:
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.check_peppol_recipient(1194146)

    assert result.registered is True
    assert result.can_receive_invoices is True
    assert result.checked_identifier == "BE0123456789"
    assert client.peppol_checks == ["BE0123456789"]
    assert client.send_calls == []


@pytest.mark.asyncio
async def test_peppol_send_returns_the_successful_preflight(
    invoice_payload: dict[str, Any],
) -> None:
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.send_invoice(1194146, transport=InvoiceDeliveryMethod.PEPPOL)

    assert result.sent is True
    assert result.peppol_capability is not None
    assert result.peppol_capability.can_receive_invoices is True
    assert client.send_calls == [(1194146, InvoiceDeliveryMethod.PEPPOL)]


@pytest.mark.asyncio
async def test_peppol_send_requires_invoice_capability(invoice_payload: dict[str, Any]) -> None:
    client = FakeClient(invoice_payload)
    client.peppol_response = {"Registered": True, "DocumentTypes": ["BISv3CreditNote"]}
    service = BillitService(client)  # type: ignore[arg-type]

    with pytest.raises(BillitSafetyError, match="invoice-capable document type"):
        await service.send_invoice(1194146, transport=InvoiceDeliveryMethod.PEPPOL)

    assert client.peppol_checks == ["BE0123456789"]
    assert client.send_calls == []


@pytest.mark.asyncio
async def test_peppol_send_requires_customer_identifier(invoice_payload: dict[str, Any]) -> None:
    invoice_payload["Customer"].pop("VATNumber")
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    with pytest.raises(BillitSafetyError, match="no customer VAT or Peppol identifier"):
        await service.send_invoice(1194146, transport=InvoiceDeliveryMethod.PEPPOL)

    assert client.peppol_checks == []
    assert client.send_calls == []


@pytest.mark.asyncio
async def test_peppol_check_uses_a_scheme_identifier_when_vat_is_missing(
    invoice_payload: dict[str, Any],
) -> None:
    invoice_payload["Customer"].pop("VATNumber")
    invoice_payload["Customer"]["Identifiers"] = [
        {"Identifier": "5430003799999", "SchemeID": "0088"}
    ]
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.check_peppol_recipient(1194146)

    assert result.checked_identifier == "0088:5430003799999"
    assert client.peppol_checks == ["0088:5430003799999"]


@pytest.mark.asyncio
async def test_already_sent_invoice_is_not_sent_again(invoice_payload: dict[str, Any]) -> None:
    invoice_payload["IsSent"] = True
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    result = await service.send_invoice(1194146, transport=InvoiceDeliveryMethod.PEPPOL)

    assert result.sent is True
    assert result.already_sent is True
    assert client.send_calls == []


@pytest.mark.asyncio
async def test_email_send_requires_customer_email(invoice_payload: dict[str, Any]) -> None:
    invoice_payload["Customer"].pop("Email")
    client = FakeClient(invoice_payload)
    service = BillitService(client)  # type: ignore[arg-type]

    with pytest.raises(BillitSafetyError, match="no customer email"):
        await service.send_invoice(1194146, transport=InvoiceDeliveryMethod.EMAIL)

    assert client.send_calls == []


@pytest.mark.asyncio
async def test_production_send_requires_second_opt_in(invoice_payload: dict[str, Any]) -> None:
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
        await service.send_invoice(1194146, transport=InvoiceDeliveryMethod.EMAIL)

    assert client.send_calls == []


@pytest.mark.asyncio
async def test_send_invoice_requires_verifiable_sent_state(invoice_payload: dict[str, Any]) -> None:
    client = FakeClient(invoice_payload)

    async def do_not_update(
        _invoice_id: int,
        *,
        transport: InvoiceDeliveryMethod,
    ) -> None:
        client.send_calls.append((1194146, transport))

    client.send_invoice = do_not_update  # type: ignore[method-assign]
    service = BillitService(client)  # type: ignore[arg-type]

    with pytest.raises(BillitVerificationError, match="Check Billit before retrying"):
        await service.send_invoice(1194146, transport=InvoiceDeliveryMethod.PEPPOL)
