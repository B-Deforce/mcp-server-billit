"""Context-efficient public models for Billit invoice operations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaymentMethod(StrEnum):
    WIRED = "Wired"
    VISA = "Visa"
    BANCONTACT = "Bancontact"
    CASH = "Contant"
    DIRECT_DEBIT = "Domiciliation"
    ONLINE = "Online"
    OTHER = "Other"
    PRIVATE_ACCOUNT = "PrivateAccount"


class InvoiceDeliveryMethod(StrEnum):
    EMAIL = "email"
    PEPPOL = "peppol"


class InvoiceAddress(APIModel):
    name: str | None = None
    street: str | None = None
    street_number: str | None = None
    box: str | None = None
    zipcode: str | None = None
    city: str | None = None
    country_code: str | None = None


class CustomerView(APIModel):
    customer_id: int | None = None
    name: str | None = None
    vat_number: str | None = None
    email: str | None = None
    address: InvoiceAddress | None = None


class InvoiceLineView(APIModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price_excl: Decimal | None = None
    vat_percentage: Decimal | None = None
    total_excl: Decimal | None = None
    total_vat: Decimal | None = None
    total_incl: Decimal | None = None
    reference: str | None = None


class FileReference(APIModel):
    file_id: str | None = None
    filename: str | None = None
    mime_type: str | None = None


class InvoiceView(APIModel):
    invoice_id: int
    invoice_number: str | None = None
    order_type: str | None = None
    order_direction: str | None = None
    issue_date: datetime | None = None
    due_date: datetime | None = None
    currency: str | None = None
    customer: CustomerView | None = None
    lines: list[InvoiceLineView] = Field(default_factory=list)
    total_excl: Decimal | None = None
    total_vat: Decimal | None = None
    total_incl: Decimal | None = None
    amount_to_pay: Decimal | None = None
    paid: bool = False
    paid_at: datetime | None = None
    payment_method: str | None = None
    sent: bool = False
    created_at: datetime | None = None
    modified_at: datetime | None = None
    pdf: FileReference | None = None
    delivery: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


class InvoiceReferenceMatch(APIModel):
    invoice_id: int
    payment_reference: str | None = None
    customer: str | None = None
    invoice_number: str | None = None
    issue_date: datetime | None = None
    due_date: datetime | None = None
    paid: bool = False
    sent: bool = False
    amount_remaining: Decimal | None = None
    billit_status: str | None = None
    overdue: bool = False
    days_overdue: int | None = None
    total: Decimal | None = None
    currency: str | None = None


class InvoiceReferenceSearchResult(APIModel):
    found: bool
    matches: list[InvoiceReferenceMatch] = Field(default_factory=list)


class CustomerInvoiceSearchResult(APIModel):
    query: str
    found: bool
    matched_customer_count: int
    returned_count: int
    max_results: int
    has_more: bool
    invoices: list[InvoiceReferenceMatch] = Field(default_factory=list)


class UnpaidInvoiceList(APIModel):
    returned_count: int
    max_results: int
    has_more: bool
    invoices: list[InvoiceReferenceMatch] = Field(default_factory=list)


class PaymentStatus(APIModel):
    invoice_id: int
    paid: bool
    paid_at: datetime | None = None
    payment_method: str | None = None
    already_paid: bool = False


class InvoiceSendStatus(APIModel):
    invoice_id: int
    invoice_number: str | None = None
    requested_transport: InvoiceDeliveryMethod
    sent: bool
    already_sent: bool = False
    delivery_confirmed: bool | None = None
    peppol_capability: PeppolRecipientCapability | None = None


class PeppolRecipientCapability(APIModel):
    invoice_id: int
    customer: str | None = None
    checked_identifier: str
    registered: bool
    can_receive_invoices: bool
    document_types: list[str] = Field(default_factory=list)
    reason: str


class CreateInvoiceLine(APIModel):
    description: str = Field(min_length=1, max_length=1000)
    quantity: Decimal = Field(gt=0)
    unit_price_excl: Decimal = Field(ge=0)
    vat_percentage: Decimal = Field(ge=0, le=100)
    reference: str | None = Field(default=None, max_length=250)


class CreateInvoiceAddress(APIModel):
    street: str = Field(min_length=1, max_length=250)
    street_number: str = Field(min_length=1, max_length=50)
    zipcode: str = Field(min_length=1, max_length=30)
    city: str = Field(min_length=1, max_length=150)
    country_code: str = Field(min_length=2, max_length=2)
    box: str | None = Field(default=None, max_length=50)

    @field_validator("country_code", mode="before")
    @classmethod
    def uppercase_country_code(cls, value: object) -> str:
        return str(value).upper()


class CreateCustomer(APIModel):
    name: str = Field(min_length=1, max_length=250)
    vat_number: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=320)
    address: CreateInvoiceAddress | None = None


class CreateInvoiceInput(APIModel):
    invoice_number: str = Field(min_length=1, max_length=100)
    issue_date: date
    due_date: date
    customer: CreateCustomer
    lines: list[CreateInvoiceLine] = Field(min_length=1, max_length=500)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    payment_reference: str | None = Field(default=None, max_length=250)
    purchase_order_reference: str | None = Field(default=None, max_length=250)
    buyer_reference: str | None = Field(default=None, max_length=250)
    delivery_date: date | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def uppercase_currency(cls, value: object) -> str:
        return str(value).upper()

    @model_validator(mode="after")
    def validate_dates(self) -> CreateInvoiceInput:
        if self.due_date < self.issue_date:
            raise ValueError("due_date must be on or after issue_date")
        return self


class CreatedInvoice(APIModel):
    invoice_id: int
    invoice_number: str
    idempotency_key: str
    sent: bool = False
