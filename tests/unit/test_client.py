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
        assert request.url.params["$top"] == "100"
        return httpx.Response(200, json={"Items": []})

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        result = await client.list_unpaid_invoices_raw(max_results=100)

    assert result == {"Items": []}


@pytest.mark.asyncio
async def test_customer_search_and_invoice_lookup_use_fixed_filters() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert request.url.path == "/v1/parties"
            assert request.url.params["$filter"] == "PartyType eq 'Customer'"
            assert request.url.params["fullTextSearch"] == "Naos"
            assert request.url.params["$top"] == "100"
            return httpx.Response(200, json={"Items": [{"PartyID": 12, "Name": "Naos"}]})
        assert request.url.path == "/v1/orders"
        assert request.url.params["$filter"] == (
            "OrderType eq 'Invoice' and OrderDirection eq 'Income' "
            "and (CounterParty/PartyID eq 12 or CounterParty/PartyID eq 34)"
        )
        assert request.url.params["$orderby"] == "OrderDate desc,OrderID desc"
        assert request.url.params["$top"] == "25"
        return httpx.Response(200, json={"Items": []})

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        customers = await client.search_customers_raw("Naos")
        invoices = await client.find_invoices_by_customer_ids_raw([12, 34], max_results=25)

    assert customers["Items"][0]["PartyID"] == 12
    assert invoices == {"Items": []}


@pytest.mark.asyncio
async def test_empty_customer_ids_do_not_make_an_http_request() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("No request should be made for an empty customer-ID set")

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        result = await client.find_invoices_by_customer_ids_raw([], max_results=10)

    assert result == {"Items": []}


@pytest.mark.asyncio
async def test_peppol_participant_lookup_encodes_identifier() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/peppol/participantInformation/9925:BE0123456789"
        return httpx.Response(
            200,
            json={"Registered": True, "DocumentTypes": ["BISv3Invoice"]},
        )

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        result = await client.get_peppol_participant_raw("9925:BE0123456789")

    assert result["Registered"] is True


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
async def test_create_credit_note_posts_order_with_idempotency_key() -> None:
    payload = {
        "OrderType": "CreditNote",
        "OrderDirection": "Income",
        "AboutInvoiceNumber": "INV-1",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/orders"
        assert request.headers["Idempotent-Key"] == "credit-attempt-1"
        assert json.loads(request.content) == payload
        return httpx.Response(200, json=654)

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        order_id = await client.create_credit_note_raw(
            payload,
            idempotency_key="credit-attempt-1",
        )

    assert order_id == 654


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
async def test_mark_order_sent_only_patches_is_sent() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/v1/orders/7"
        assert json.loads(request.content) == {"IsSent": True}
        return httpx.Response(200)

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        await client.mark_order_sent(7)


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
async def test_send_credit_note_uses_strict_peppol_transport() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/orders/commands/send"
        assert request.headers["StrictTransportType"] == "true"
        assert json.loads(request.content) == {
            "Transporttype": "Peppol",
            "OrderIDs": [654],
        }
        return httpx.Response(200)

    async with BillitClient(config(), transport=httpx.MockTransport(handler)) as client:
        await client.send_credit_note(654, transport=InvoiceDeliveryMethod.PEPPOL)


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
