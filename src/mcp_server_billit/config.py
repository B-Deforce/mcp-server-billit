"""Environment-only configuration for the Billit API client."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class BillitEnvironment(StrEnum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


BASE_URLS: dict[BillitEnvironment, str] = {
    BillitEnvironment.SANDBOX: "https://api.sandbox.billit.be",
    BillitEnvironment.PRODUCTION: "https://api.billit.be",
}


class BillitConfigurationError(ValueError):
    """Raised when required Billit environment configuration is missing or invalid."""


class BillitConfig(BaseModel):
    """Validated configuration whose repr never reveals the API key."""

    model_config = ConfigDict(frozen=True)

    api_key: SecretStr
    party_id: int = Field(gt=0)
    environment: BillitEnvironment = BillitEnvironment.SANDBOX
    allow_production_writes: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    get_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.25, ge=0, le=10)

    @property
    def base_url(self) -> str:
        """Return a trusted Billit host selected by the environment enum."""
        return BASE_URLS[self.environment]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> BillitConfig:
        """Load Billit credentials without accepting an arbitrary credential destination."""
        values = os.environ if environ is None else environ
        missing = [
            name
            for name in ("BILLIT_API_KEY", "BILLIT_PARTY_ID")
            if not values.get(name, "").strip()
        ]
        if missing:
            joined = ", ".join(missing)
            raise BillitConfigurationError(f"Missing required environment variable(s): {joined}")

        try:
            return cls.model_validate(
                {
                    "api_key": values["BILLIT_API_KEY"],
                    "party_id": values["BILLIT_PARTY_ID"],
                    "environment": values.get("BILLIT_ENV", "sandbox").strip().lower(),
                    "allow_production_writes": _parse_bool(
                        values.get("BILLIT_ALLOW_PRODUCTION_WRITES", "false")
                    ),
                }
            )
        except (ValidationError, ValueError) as exc:
            raise BillitConfigurationError(f"Invalid Billit configuration: {exc}") from None


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError("BILLIT_ALLOW_PRODUCTION_WRITES must be true or false")
