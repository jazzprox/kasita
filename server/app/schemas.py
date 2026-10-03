from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

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
    grocery_budget: Decimal | None = Field(default=None, ge=0)  # 0 clears it
    ntfy_topic: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")  # "" clears it


class HouseholdOut(ORM):
    id: str
    name: str
    currency: str
    role: str | None = None
    grocery_budget: Decimal | None = None
    ntfy_topic: str | None = None


class MemberOut(BaseModel):
    user_id: str
    name: str
    email: str
    role: str


class InviteIn(BaseModel):
    own_household: bool = False  # True: they get their own household instead of joining this one


class InviteOut(BaseModel):
    token: str
    url: str
    expires_at: datetime
    own_household: bool = False


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    read_only: bool = False  # can look, never change (any member may create one; full keys are owner-only)


class ApiKeyOut(ORM):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    read_only: bool = False


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
    address: str | None = None
    phone: str | None = None
    crib: str | None = None  # tax / registration number (CRIB, KvK, RNC...)
    lat: float | None = None
    lon: float | None = None
    location_source: str | None = None  # manual | geocoded
    kind: str | None = None  # minimarket | supermarket | other, as set by the user (None = not set)
    kind_guess: str = "other"  # what Kasita assumes: `kind`, else a guess from the name


class StorePatch(BaseModel):
    """Edit a store. Setting lat/lon pins it by hand (it is then never geocoded again);
    both null removes the pin."""
    name: str | None = Field(default=None, min_length=1, max_length=120)
    payee_match: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    crib: str | None = Field(default=None, max_length=40)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    kind: Literal["minimarket", "supermarket", "other"] | None = None  # null = guess from the name


class HomeIn(BaseModel):
    """Home on the map, for the travel stat. Both null clears it."""
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


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
    open_days: int | None = Field(default=None, ge=1, le=365)
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
    open_days: int | None = Field(default=None, ge=1, le=365)
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
    shareable: bool = False  # has a barcode no database knows: can be given to Open Food Facts
    open_days: int | None = None
    runs_out_in_days: float | None = None  # from how fast it gets used; None = not enough history
    photo_source: str | None = None  # "yours" (taken in Kasita) | "database" (came with the barcode) | None
    can_restore_photo: bool = False  # a database photo was replaced and can be put back


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
    frozen_at: date | None = None
    event_id: str | None = None  # set on a fresh purchase, for undo


class EntryPatch(BaseModel):
    best_before: date | None = None
    location_id: str | None = None


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
    at: datetime  # when it was booked
    on: date | None = None  # the day it was bought (the receipt's date)
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
    # with done=true: when it was ticked (a phone that was offline sends its own time), the phone's
    # calendar day, and the store you said you're in. Used to learn each store's walking order.
    ticked_at: datetime | None = None
    local_day: date | None = None
    store_id: str | None = None


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
    product_image_url: str | None = None
    skip: bool
    matched_by: str | None  # alias | guess | user | scan
    department: bool = False  # a shop department ("COMESTIBELS"): scan the pack to say what it was
    spending_only: bool = False  # counts in spending, no product or stock
    spending_category: str | None = None
    suggested_category: str | None = None  # default for spending only, from the department's words


class ReceiptOut(BaseModel):
    id: str
    status: str  # new | parsed | confirmed | failed
    error: str | None
    store_id: str | None
    store_name: str | None
    purchased_on: date | None
    purchased_time: time | None = None
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
    spending_only: bool = False
    spending_category: str | None = Field(default=None, max_length=80)


class ReceiptLinePatch(BaseModel):
    name: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = None
    product_id: str | None = None
    clear_product: bool = False  # unlink the product (a new one is created on confirm)
    skip: bool | None = None
    spending_only: bool | None = None
    spending_category: str | None = Field(default=None, max_length=80)
    department: bool | None = None  # False: "this is a real product name", remembered like any other


class ReceiptScanIn(BaseModel):
    barcode: str | None = None     # scanned code: the household's product, or one made from the databases
    product_id: str | None = None  # or a product chosen/created in the app (after an unknown barcode)


class ReceiptMoveIn(BaseModel):
    to_line_id: str


class ReceiptScanOut(BaseModel):
    status: str  # known | created | linked | unknown (lookup says what is known) | no_line (nothing open)
    product: ProductOut | None = None
    line_id: str | None = None
    reason: str | None = None  # why this line was chosen, e.g. "same price as last time"
    lookup: BarcodeLookupOut | None = None
    receipt: ReceiptOut


class ConfirmIn(BaseModel):
    create_missing: bool = True  # lines without a product become new products
    location_id: str | None = None


class ConfirmOut(BaseModel):
    added: int
    created_products: int
    skipped: int
    spending_only: int = 0


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


class BillLine(BaseModel):
    service: str = Field(min_length=1, max_length=40)
    amount: Decimal


class BillOut(BaseModel):
    id: str
    status: str  # reading | read | linked | failed
    error: str | None
    biller: str | None
    lines: list[BillLine]
    total: Decimal | None
    currency: str | None
    period: str | None
    bill_date: date | None
    due_date: date | None
    account_ref: str | None
    securo_transaction_id: str | None
    created_at: datetime
    has_photo: bool = False


class BillPatch(BaseModel):
    biller: str | None = Field(default=None, max_length=120)
    lines: list[BillLine] | None = None
    total: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period: str | None = Field(default=None, max_length=60)
    bill_date: date | None = None
    due_date: date | None = None
    account_ref: str | None = Field(default=None, max_length=60)


class BillsIn(BaseModel):
    bill_ids: list[str] = Field(min_length=1, max_length=20)


class BillsLinkIn(BillsIn):
    transaction_id: str = Field(min_length=1, max_length=64)
    attach_photos: bool = True
    set_category: bool = True
    add_note: bool = True


class BillsRecordIn(BillsIn):
    account_id: str = Field(min_length=1, max_length=64)
    date: date
    description: str | None = Field(default=None, max_length=200)


class BillsBooked(BaseModel):
    transaction_id: str
    note: str
    skipped: list[str] = []
    bills: list[BillOut]


class SecuroAccount(BaseModel):
    id: str
    name: str
    type: str | None = None
    currency: str | None = None


class CookIn(BaseModel):
    note: str | None = Field(default=None, max_length=200)
