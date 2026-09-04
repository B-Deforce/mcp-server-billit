from __future__ import annotations

import pytest

from mcp_server_billit.server import mcp


@pytest.mark.asyncio
async def test_server_advertises_only_the_intended_tools() -> None:
    tools = await mcp.list_tools()
    assert {tool.name for tool in tools} == {
        "check_peppol_recipient",
        "create_credit_note_from_invoice",
        "create_invoice",
        "find_invoices_by_customer_name",
        "find_invoices_by_payment_reference",
        "get_invoice",
        "list_unpaid_invoices",
        "mark_invoice_paid",
        "mark_credit_note_paid",
        "mark_credit_note_sent",
        "send_credit_note",
        "send_invoice",
    }

    create = next(tool for tool in tools if tool.name == "create_invoice")
    assert "send" in (create.description or "").lower()

    unpaid = next(tool for tool in tools if tool.name == "list_unpaid_invoices")
    assert "read-only" in (unpaid.description or "").lower()

    send = next(tool for tool in tools if tool.name == "send_invoice")
    assert "external side effect" in (send.description or "").lower()

    customer_search = next(tool for tool in tools if tool.name == "find_invoices_by_customer_name")
    assert "partial" in (customer_search.description or "").lower()

    peppol = next(tool for tool in tools if tool.name == "check_peppol_recipient")
    assert "read-only" in (peppol.description or "").lower()

    create_credit = next(tool for tool in tools if tool.name == "create_credit_note_from_invoice")
    assert "full credit" in (create_credit.description or "").lower()
    assert "does not send" in (create_credit.description or "").lower()

    mark_sent = next(tool for tool in tools if tool.name == "mark_credit_note_sent")
    assert "does not email" in (mark_sent.description or "").lower()

    send_credit = next(tool for tool in tools if tool.name == "send_credit_note")
    assert "external side effect" in (send_credit.description or "").lower()
    assert "credit-note-specific" in (send_credit.description or "").lower()
