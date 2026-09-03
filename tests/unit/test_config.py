from __future__ import annotations

import pytest

from mcp_server_billit.config import (
    BillitConfig,
    BillitConfigurationError,
    BillitEnvironment,
)


def test_defaults_to_sandbox_and_redacts_secret() -> None:
    config = BillitConfig.from_env({"BILLIT_API_KEY": "super-secret", "BILLIT_PARTY_ID": "123"})

    assert config.environment is BillitEnvironment.SANDBOX
    assert config.base_url == "https://api.sandbox.billit.be"
    assert config.allow_production_writes is False
    assert "super-secret" not in repr(config)


def test_production_and_write_opt_in_are_explicit() -> None:
    config = BillitConfig.from_env(
        {
            "BILLIT_API_KEY": "key",
            "BILLIT_PARTY_ID": "456",
            "BILLIT_ENV": "production",
            "BILLIT_ALLOW_PRODUCTION_WRITES": "true",
        }
    )

    assert config.environment is BillitEnvironment.PRODUCTION
    assert config.base_url == "https://api.billit.be"
    assert config.allow_production_writes is True


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"BILLIT_API_KEY": "key"},
        {"BILLIT_PARTY_ID": "1"},
        {"BILLIT_API_KEY": "key", "BILLIT_PARTY_ID": "zero"},
    ],
)
def test_invalid_environment_is_actionable(environment: dict[str, str]) -> None:
    with pytest.raises(BillitConfigurationError):
        BillitConfig.from_env(environment)
