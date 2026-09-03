from __future__ import annotations

import os

import pytest

from mcp_server_billit.client import BillitClient
from mcp_server_billit.config import BillitConfig, BillitEnvironment


@pytest.mark.asyncio
async def test_get_known_sandbox_invoice() -> None:
    invoice_id = os.getenv("BILLIT_TEST_INVOICE_ID")
    if not invoice_id:
        pytest.skip("BILLIT_TEST_INVOICE_ID is not configured")

    config = BillitConfig.from_env()
    if config.environment is not BillitEnvironment.SANDBOX:
        pytest.fail("Live integration tests may only run with BILLIT_ENV=sandbox")

    async with BillitClient(config) as client:
        invoice = await client.get_invoice_raw(int(invoice_id))

    assert int(invoice["OrderID"]) == int(invoice_id)
