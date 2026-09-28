from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------
class LoginIn(BaseModel):
    email: str
    password: str
    device: str = ""


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)
    device: str = ""


class AcceptInviteIn(BaseModel):
    token: str
    # only needed when the invitee has no account yet
    email: str | None = None
    name: str | None = None
    password: str | None = Field(default=None, min_length=10)


class UserOut(ORM):
    id: str
    email: str
    name: str
    is_admin: bool


# --- households ---------------------------------------------------------------
class HouseholdIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(default="XCG", min_length=3, max_length=3)


class HouseholdPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class HouseholdOut(ORM):
    id: str
    name: str
    currency: str
    role: str | None = None


class MemberOut(BaseModel):
    user_id: str
    name: str
    email: str
    role: str


class InviteOut(BaseModel):
    token: str
    url: str
    expires_at: datetime


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ApiKeyOut(ORM):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str  # shown once


# --- locations / stores ------------------------------------------------------
class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    is_freezer: bool = False


class LocationOut(ORM):
    id: str
    name: str
    is_freezer: bool


class StoreIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    payee_match: str | None = None


class StoreOut(ORM):
    id: str
    name: str
    payee_match: str | None


# --- products ---------------------------------------------------------------
class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = None
    category: str | None = None
    unit: str = "pcs"
    image_url: str | None = None
    default_location_id: str | None = None
    min_stock: Decimal = Decimal(0)
    shelf_life_days: int | None = None
    notes: str | None = None
    barcodes: list[str] = []


class ProductPatch(BaseModel):
    name: str | None = None
    brand: str | None = None
    category: str | None = None
    unit: str | None = None
    image_url: str | None = None
    default_location_id: str | None = None
    min_stock: Decimal | None = None
    shelf_life_days: int | None = None
    notes: str | None = None
    archived: bool | None = None


class ProductOut(ORM):
    id: str
    name: str
    brand: str | None
    category: str | None
    unit: str
    image_url: str | None
    default_location_id: str | None
    min_stock: Decimal
    shelf_life_days: int | None
    notes: str | None
    archived: bool
    barcodes: list[str] = []
    in_stock: Decimal = Decimal(0)
    next_best_before: date | None = None


class BarcodeLookupOut(BaseModel):
    barcode: str
    product: ProductOut | None  # already in this household
    found: bool                 # the public databases know it
    source: str | None = None
    name: str | None = None
    brand: str | None = None
    quantity_text: str | None = None
    image_url: str | None = None
    categories: str | None = None  # the database's own text, e.g. "Colas, Sodas"
    category: str | None = None    # Kasita's category: the product's own, else a guess
    brand_hint: str | None = None  # unknown barcode: the maker, from its company prefix


# --- stock ------------------------------------------------------------------
class PurchaseIn(BaseModel):
    product_id: str
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    best_before: date | None = None
    location_id: str | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    store_id: str | None = None
    purchased_at: date | None = None


class ConsumeIn(BaseModel):
    product_id: str
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    spoiled: bool = False  # thrown away rather than used


class OpenIn(BaseModel):
    product_id: str


class StockEntryOut(ORM):
    id: str
    quantity: Decimal
    best_before: date | None
    opened_at: date | None
    purchased_at: date
    unit_price: Decimal | None
    location_id: str | None
    store_id: str | None
    event_id: str | None = None  # set on a fresh purchase, for undo


class UndoIn(BaseModel):
    event_ids: list[str] = Field(min_length=1, max_length=50)


class StockProductOut(BaseModel):
    product: ProductOut
    total: Decimal
    entries: list[StockEntryOut]


class StockEventOut(ORM):
    id: str
    product_id: str
    kind: str
    quantity: Decimal
    unit_price: Decimal | None
    store_id: str | None
    at: datetime


class PricePoint(BaseModel):
    at: datetime
    unit_price: Decimal
    quantity: Decimal
    store_id: str | None
    store_name: str | None


# --- shopping ----------------------------------------------------------------
class ShoppingIn(BaseModel):
    name: str | None = None
    product_id: str | None = None
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    note: str | None = None


class ShoppingPatch(BaseModel):
    name: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    note: str | None = None
    done: bool | None = None


class ShoppingOut(ORM):
    id: str
    name: str
    product_id: str | None
    category: str | None = None  # the product's, or guessed from a free-text name
    quantity: Decimal
    note: str | None
    auto: bool
    done: bool
    created_at: datetime


# --- receipts -------------------------------------------------------------------
class ReceiptLineOut(ORM):
    id: str
    position: int
    raw_text: str
    name: str | None
    quantity: Decimal
    unit_price: Decimal | None
    line_total: Decimal | None
    product_id: str | None
    product_name: str | None = None
    skip: bool
    matched_by: str | None


class ReceiptOut(BaseModel):
    id: str
    status: str  # new | parsed | confirmed | failed
    error: str | None
    store_id: str | None
    store_name: str | None
    purchased_on: date | None
    total: Decimal | None
    currency: str | None
    created_at: datetime
    securo_transaction_id: str | None = None
    line_count: int = 0
    lines_total: Decimal | None = None  # sum of the lines, to compare with `total`
    lines: list[ReceiptLineOut] | None = None


class ReceiptPatch(BaseModel):
    store_id: str | None = None
    purchased_on: date | None = None
    total: Decimal | None = None


class ReceiptLineIn(BaseModel):
    raw_text: str = Field(min_length=1, max_length=255)
    name: str | None = None
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = None
    product_id: str | None = None
    skip: bool = False


class ReceiptLinePatch(BaseModel):
    name: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = None
    product_id: str | None = None
    clear_product: bool = False  # unlink the product (a new one is created on confirm)
    skip: bool | None = None


class ConfirmIn(BaseModel):
    create_missing: bool = True  # lines without a product become new products
    location_id: str | None = None


class ConfirmOut(BaseModel):
    added: int
    created_products: int
    skipped: int


# --- integrations ---------------------------------------------------------------
class DeviceCodeOut(BaseModel):
    user_code: str
    verification_url: str
    interval: int
    expires_at: int


class ChatGPTStatus(BaseModel):
    connected: bool
    email: str | None = None
    plan: str | None = None
    model: str | None = None
    connected_at: int | None = None
    pending: DeviceCodeOut | None = None


class ModelIn(BaseModel):
    model: str = Field(min_length=1, max_length=80)


class SecuroStatus(BaseModel):
    connected: bool
    url: str | None = None
    email: str | None = None


class SecuroConnectIn(BaseModel):
    url: str = Field(default="https://fin.jazzproxy.com", min_length=8, max_length=200)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class SecuroCandidate(BaseModel):
    id: str
    date: str | None
    description: str | None
    amount: str
    currency: str | None
    notes: str | None
    attachment_count: int
    score: int


class SecuroLinkIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=64)
    attach_photo: bool = True
    add_note: bool = True
