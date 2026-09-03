"""Typed and secret-safe Billit errors."""

from __future__ import annotations

from typing import Any


class BillitError(RuntimeError):
    """Base error for all Billit client and service failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        description: str | None = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.description = description
        self.response_body = response_body


class BillitValidationError(BillitError):
    """Billit rejected a request or its business data."""


class BillitAuthenticationError(BillitError):
    """Billit rejected the credentials or access scope."""


class BillitNotFoundError(BillitError):
    """The requested Billit resource does not exist or is inaccessible."""


class BillitRateLimitError(BillitError):
    """Billit asked the client to slow down."""


class BillitServerError(BillitError):
    """Billit returned a server-side failure."""


class BillitTransportError(BillitError):
    """The client could not establish or complete an HTTP exchange."""


class BillitAmbiguousWriteError(BillitTransportError):
    """A write may have succeeded despite a missing response."""

    def __init__(self, operation: str, idempotency_key: str | None = None) -> None:
        suffix = f" Idempotency key: {idempotency_key}." if idempotency_key else ""
        super().__init__(
            f"The Billit {operation} request ended without a definitive response."
            f" Check Billit before retrying to avoid a duplicate or repeated write.{suffix}"
        )
        self.operation = operation
        self.idempotency_key = idempotency_key


class BillitSafetyError(BillitError):
    """A local safety rule prevented a consequential Billit operation."""


class BillitVerificationError(BillitError):
    """Billit accepted a write but the resulting state could not be verified."""
