from __future__ import annotations

import pytest

from mcp_server_billit.server import mcp


@pytest.mark.asyncio
async def test_server_advertises_only_the_intended_tools() -> None:
    tools = await mcp.list_tools()
    assert {tool.name for tool in tools} == {
        "create_invoice",
        "find_invoices_by_payment_reference",
        "get_invoice",
        "list_unpaid_invoices",
        "mark_invoice_paid",
        "send_invoice",
    }

    create = next(tool for tool in tools if tool.name == "create_invoice")
    assert "send" in (create.description or "").lower()

    unpaid = next(tool for tool in tools if tool.name == "list_unpaid_invoices")
    assert "read-only" in (unpaid.description or "").lower()

    send = next(tool for tool in tools if tool.name == "send_invoice")
    assert "external side effect" in (send.description or "").lower()
