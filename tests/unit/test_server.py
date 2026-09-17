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
        "find_supplier_invoices_by_number",
        "find_supplier_invoices_by_supplier_name",
        "get_invoice",
        "get_supplier_invoice",
        "list_supplier_credit_notes",
        "list_supplier_invoices",
        "list_unpaid_invoices",
        "mark_invoice_paid",
        "mark_invoice_sent",
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

    mark_invoice_sent = next(tool for tool in tools if tool.name == "mark_invoice_sent")
    assert "does not email" in (mark_invoice_sent.description or "").lower()
    assert "without delivering" in (mark_invoice_sent.description or "").lower()

    send_credit = next(tool for tool in tools if tool.name == "send_credit_note")
    assert "external side effect" in (send_credit.description or "").lower()
    assert "credit-note-specific" in (send_credit.description or "").lower()

    supplier_list = next(tool for tool in tools if tool.name == "list_supplier_invoices")
    assert "read-only" in (supplier_list.description or "").lower()
    assert "unpaid_only" in (supplier_list.description or "")

    supplier_get = next(tool for tool in tools if tool.name == "get_supplier_invoice")
    assert "raw billit data" in (supplier_get.description or "").lower()

    supplier_name = next(
        tool for tool in tools if tool.name == "find_supplier_invoices_by_supplier_name"
    )
    assert "partial" in (supplier_name.description or "").lower()

    supplier_number = next(
        tool for tool in tools if tool.name == "find_supplier_invoices_by_number"
    )
    assert "exact" in (supplier_number.description or "").lower()

    supplier_credits = next(tool for tool in tools if tool.name == "list_supplier_credit_notes")
    assert "read-only" in (supplier_credits.description or "").lower()
