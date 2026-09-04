from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx
import pytest

from mcp_server_billit.client import BillitClient
from mcp_server_billit.config import BillitConfig
from mcp_server_billit.errors import BillitAmbiguousWriteError, BillitValidationError
from mcp_server_billit.models import InvoiceDeliveryMethod


def config(**overrides: Any) -> BillitConfig:
    values: dict[str, Any] = {"api_key": "secret-key", "party_id": 123, "get_retries": 0}
    values.update(overrides)
    return BillitConfig(**values)


@pytest.mark.asyncio
async def test_get_uses_plural_path_and_required_headers(
    invoice_payload: dict[str, Any],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/orders/1194146"
        assert request.headers["ApiKey"] == "secret-key"
        assert request.headers["PartyID"] == "123"
        return httpx.Response(200, json=invoice_payload)

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        invoice = await client.get_invoice_raw(1194146)

    assert invoice["OrderNumber"] == "QS-244SC"


@pytest.mark.asyncio
async def test_get_retries_transient_status_and_respects_retry_after(
    invoice_payload: dict[str, Any],
) -> None:
    calls = 0
    delays: list[float] = []

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.1"})
        return httpx.Response(200, json=invoice_payload)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with BillitClient(
        config(get_retries=1), transport=httpx.MockTransport(handler), sleep=record_sleep
    ) as client:
        await client.get_invoice_raw(1194146)

    assert calls == 2
    assert delays == [0.1]


@pytest.mark.asyncio
async def test_payment_reference_search_uses_safe_fixed_odata_filter() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/orders"
        assert request.url.params["$filter"] == (
            "OrderType eq 'Invoice' and OrderDirection eq 'Income' "
            "and PaymentReference eq 'O''Brien'"
        )
        assert request.url.params["$top"] == "7"
        return httpx.Response(200, json={"Items": []})

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        result = await client.find_invoices_by_payment_reference_raw("O'Brien", max_results=7)

    assert result == {"Items": []}


@pytest.mark.asyncio
async def test_unpaid_search_uses_fixed_filter_sort_and_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/orders"
        assert request.url.params["$filter"] == (
            "OrderType eq 'Invoice' and OrderDirection eq 'Income' and Paid eq false"
        )
        assert request.url.params["$orderby"] == "ExpiryDate asc,OrderID asc"
        assert request.url.params["$top"] == "50"
        return httpx.Response(200, json={"Items": []})

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        result = await client.list_unpaid_invoices_raw(max_results=50)

    assert result == {"Items": []}


@pytest.mark.asyncio
async def test_validation_error_is_typed_and_secret_safe(
    validation_error_payload: dict[str, Any],
) -> None:
    leaked = {**validation_error_payload, "ApiKey": "secret-key"}

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=leaked)

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BillitValidationError) as caught:
            await client.get_invoice_raw(1)

    error = caught.value
    assert error.code == "InvalidVatPercentage"
    assert error.response_body["ApiKey"] == "********"
    assert "secret-key" not in repr(error)


@pytest.mark.asyncio
async def test_create_sends_idempotency_key_and_never_retries() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["Idempotent-Key"] == "attempt-123"
        assert request.url.path == "/v1/orders"
        raise httpx.ReadTimeout("unknown outcome", request=request)

    async with BillitClient(
        config(get_retries=5), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(BillitAmbiguousWriteError, match="Check Billit") as caught:
            await client.create_invoice_raw({}, idempotency_key="attempt-123")

    assert calls == 1
    assert caught.value.idempotency_key == "attempt-123"


@pytest.mark.asyncio
async def test_mark_paid_serializes_datetime_and_method() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert request.method == "PATCH"
        assert request.url.path == "/v1/orders/7"
        assert '"Paid":true' in body
        assert '"PaidDate":"2026-09-03T12:30:00"' in body
        return httpx.Response(200)

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        await client.mark_invoice_paid(7, paid_at=datetime(2026, 9, 3, 12, 30))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "billit_transport", "strict_transport"),
    [
        (InvoiceDeliveryMethod.EMAIL, "SMTP", None),
        (InvoiceDeliveryMethod.PEPPOL, "Peppol", "true"),
    ],
)
async def test_send_invoice_uses_explicit_transport(
    transport: InvoiceDeliveryMethod,
    billit_transport: str,
    strict_transport: str | None,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/orders/commands/send"
        assert json.loads(request.content) == {
            "Transporttype": billit_transport,
            "OrderIDs": [7],
        }
        assert request.headers.get("StrictTransportType") == strict_transport
        return httpx.Response(200)

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        await client.send_invoice(7, transport=transport)


@pytest.mark.asyncio
async def test_send_invoice_never_retries_an_unknown_outcome() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("unknown outcome", request=request)

    async with BillitClient(
        config(get_retries=5), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(BillitAmbiguousWriteError, match="Check Billit"):
            await client.send_invoice(7, transport=InvoiceDeliveryMethod.EMAIL)

    assert calls == 1
