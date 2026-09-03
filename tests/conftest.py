from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def invoice_payload() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "invoice.json"
    value: dict[str, Any] = json.loads(path.read_text())
    return value


@pytest.fixture
def validation_error_payload() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "validation_error.json"
    value: dict[str, Any] = json.loads(path.read_text())
    return value
