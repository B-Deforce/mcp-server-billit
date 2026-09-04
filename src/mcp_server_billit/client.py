"""Async HTTP client for the intentionally small Billit surface."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from .config import BillitConfig
from .errors import (
    BillitAmbiguousWriteError,
    BillitAuthenticationError,
    BillitError,
    BillitNotFoundError,
    BillitRateLimitError,
    BillitServerError,
    BillitTransportError,
    BillitValidationError,
)
from .models import InvoiceDeliveryMethod, PaymentMethod

Sleep = Callable[[float], Awaitable[None]]


class BillitClient:
    """Reusable async Billit client with GET-only automatic retries."""

    def __init__(
        self,
        config: BillitConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            headers={
                "ApiKey": config.api_key.get_secret_value(),
                "PartyID": str(config.party_id),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(
                config.timeout_seconds, connect=min(10.0, config.timeout_seconds)
            ),
            transport=transport,
        )

    @classmethod
    def from_env(cls) -> BillitClient:
        return cls(BillitConfig.from_env())

    async def __aenter__(self) -> BillitClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_invoice_raw(self, invoice_id: int) -> dict[str, Any]:
        response = await self._get_with_retries(f"/v1/orders/{invoice_id}")
        value = self._json(response)
        if not isinstance(value, dict):
            raise BillitServerError("Billit returned an unexpected invoice response shape.")
        return value

    async def find_invoices_by_payment_reference_raw(
        self,
        payment_reference: str,
        *,
        max_results: int = 10,
    ) -> dict[str, Any]:
        escaped_reference = payment_reference.replace("'", "''")
        odata_filter = (
            "OrderType eq 'Invoice' and OrderDirection eq 'Income' "
            f"and PaymentReference eq '{escaped_reference}'"
        )
        response = await self._get_with_retries(
            "/v1/orders",
            params={"$filter": odata_filter, "$top": str(max_results)},
        )
        value = self._json(response)
        if not isinstance(value, dict):
            raise BillitServerError("Billit returned an unexpected invoice-search response shape.")
        return value

    async def list_unpaid_invoices_raw(self, *, max_results: int = 10) -> dict[str, Any]:
        odata_filter = "OrderType eq 'Invoice' and OrderDirection eq 'Income' and Paid eq false"
        response = await self._get_with_retries(
            "/v1/orders",
            params={
                "$filter": odata_filter,
                "$orderby": "ExpiryDate asc,OrderID asc",
                "$top": str(max_results),
            },
        )
        value = self._json(response)
        if not isinstance(value, dict):
            raise BillitServerError("Billit returned an unexpected unpaid-invoice response shape.")
        return value

    async def search_customers_raw(
        self,
        customer_name: str,
        *,
        max_results: int = 100,
    ) -> dict[str, Any]:
        response = await self._get_with_retries(
            "/v1/parties",
            params={
                "$filter": "PartyType eq 'Customer'",
                "fullTextSearch": customer_name,
                "$top": str(max_results),
            },
        )
        value = self._json(response)
        if not isinstance(value, dict):
            raise BillitServerError("Billit returned an unexpected customer-search response shape.")
        return value

    async def find_invoices_by_customer_ids_raw(
        self,
        customer_ids: list[int],
        *,
        max_results: int = 10,
    ) -> dict[str, Any]:
        if not customer_ids:
            return {"Items": []}
        customer_filter = " or ".join(
            f"CounterParty/PartyID eq {customer_id}" for customer_id in customer_ids
        )
        odata_filter = (
            f"OrderType eq 'Invoice' and OrderDirection eq 'Income' and ({customer_filter})"
        )
        response = await self._get_with_retries(
            "/v1/orders",
            params={
                "$filter": odata_filter,
                "$orderby": "OrderDate desc,OrderID desc",
                "$top": str(max_results),
            },
        )
        value = self._json(response)
        if not isinstance(value, dict):
            raise BillitServerError(
                "Billit returned an unexpected customer-invoice response shape."
            )
        return value

    async def get_peppol_participant_raw(self, identifier: str) -> dict[str, Any]:
        encoded_identifier = quote(identifier, safe="")
        response = await self._get_with_retries(
            f"/v1/peppol/participantInformation/{encoded_identifier}"
        )
        value = self._json(response)
        if not isinstance(value, dict):
            raise BillitServerError(
                "Billit returned an unexpected Peppol participant response shape."
            )
        return value

    async def mark_invoice_paid(
        self,
        invoice_id: int,
        *,
        paid_at: datetime,
        internal_info: str | None = None,
        payment_method: PaymentMethod | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "Paid": True,
            "PaidDate": paid_at.isoformat(timespec="seconds"),
        }
        if internal_info:
            payload["InternalInfo"] = internal_info
        if payment_method:
            payload["PaymentMethod"] = payment_method.value

        await self._write(
            "PATCH",
            f"/v1/orders/{invoice_id}",
            operation="mark-paid",
            json_body=payload,
        )

    async def create_invoice_raw(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> int:
        response = await self._write(
            "POST",
            "/v1/orders",
            operation="create-invoice",
            json_body=payload,
            headers={"Idempotent-Key": idempotency_key},
            idempotency_key=idempotency_key,
        )
        value = self._json(response)
        if isinstance(value, dict):
            value = value.get("OrderID") or value.get("orderID") or value.get("id")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise BillitServerError(
                "Billit returned an unexpected create-invoice response."
            ) from None

    async def send_invoice(
        self,
        invoice_id: int,
        *,
        transport: InvoiceDeliveryMethod,
    ) -> None:
        billit_transport = {
            InvoiceDeliveryMethod.EMAIL: "SMTP",
            InvoiceDeliveryMethod.PEPPOL: "Peppol",
        }[transport]
        headers = (
            {"StrictTransportType": "true"} if transport is InvoiceDeliveryMethod.PEPPOL else None
        )
        await self._write(
            "POST",
            "/v1/orders/commands/send",
            operation=f"send-invoice-{transport.value}",
            json_body={"Transporttype": billit_transport, "OrderIDs": [invoice_id]},
            headers=headers,
        )

    async def _get_with_retries(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        for attempt in range(self.config.get_retries + 1):
            try:
                response = await self._http.get(path, params=params)
            except httpx.RequestError:
                if attempt >= self.config.get_retries:
                    raise BillitTransportError(
                        "Could not complete the Billit request after retrying."
                    ) from None
                await self._sleep(self.config.retry_backoff_seconds * (2**attempt))
                continue

            transient = response.status_code == 429 or 500 <= response.status_code < 600
            if transient and attempt < self.config.get_retries:
                await self._sleep(self._retry_delay(response, attempt))
                continue

            self._raise_for_response(response)
            return response

        raise AssertionError("retry loop exited unexpectedly")

    async def _write(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(method, path, json=json_body, headers=headers)
        except httpx.RequestError:
            raise BillitAmbiguousWriteError(operation, idempotency_key) from None
        self._raise_for_response(response)
        return response

    def _raise_for_response(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        body = self._safe_response_body(response)
        code, description = _extract_error_details(body)
        detail = f" {description}" if description else ""
        message = f"Billit request failed with HTTP {response.status_code}.{detail}".strip()
        kwargs = {
            "status_code": response.status_code,
            "code": code,
            "description": description,
            "response_body": body,
        }

        if response.status_code in {400, 409, 422}:
            raise BillitValidationError(message, **kwargs)
        if response.status_code in {401, 403}:
            raise BillitAuthenticationError(message, **kwargs)
        if response.status_code == 404:
            raise BillitNotFoundError(message, **kwargs)
        if response.status_code == 429:
            raise BillitRateLimitError(message, **kwargs)
        if 500 <= response.status_code < 600:
            raise BillitServerError(message, **kwargs)
        raise BillitError(message, **kwargs)

    def _safe_response_body(self, response: httpx.Response) -> Any:
        try:
            body: Any = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = response.text[:1000]
        return _redact(body, secret=self.config.api_key.get_secret_value())

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except ValueError:
                pass
        return float(self.config.retry_backoff_seconds) * (2.0**attempt)

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except json.JSONDecodeError:
            text = response.text.strip().strip('"')
            return text


def _extract_error_details(body: Any) -> tuple[str | None, str | None]:
    if not isinstance(body, dict):
        return None, str(body)[:500] if body else None
    code = body.get("Code") or body.get("code")
    description = (
        body.get("Description")
        or body.get("description")
        or body.get("Message")
        or body.get("message")
    )
    return (
        str(code) if code is not None else None,
        str(description)[:500] if description is not None else None,
    )


def _redact(value: Any, *, secret: str) -> Any:
    sensitive = {"apikey", "api_key", "authorization", "secret", "token"}
    if isinstance(value, dict):
        return {
            key: "********" if key.lower() in sensitive else _redact(item, secret=secret)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, secret=secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "********")[:1000]
    return value
