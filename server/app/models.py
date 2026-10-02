"""Data model.

Everything a household owns hangs off `household_id`; a user can belong to
several households. Barcode lookups from the public product databases are
cached globally (`BarcodeCache`) because they are the same for everyone,
while `Product` rows are per household: your own names, categories and
minimum stock, and products no database knows (local store brands).

Stock is a list of entries ("2 x milk, bought Tuesday, best before 3 Oct"),
not a single counter, so each purchase keeps its own expiry date and price.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


Money = Numeric(12, 2)
Qty = Numeric(12, 3)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Household(Base):
    __tablename__ = "households"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="XCG")
    # ntfy topic for this household's digests (expiry, weekly, freezer). None = no digests.
    ntfy_topic: Mapped[str | None] = mapped_column(String(64))
    grocery_budget: Mapped[Decimal | None] = mapped_column(Money)  # per calendar month; None = no budget
    budget_alerted: Mapped[str | None] = mapped_column(String(16))  # last alert sent, e.g. "2026-10:80"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    members: Mapped[list["Membership"]] = relationship(back_populates="household", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "household_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner | member
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="memberships")
    household: Mapped[Household] = relationship(back_populates="members")


class Invite(Base):
    """One-time invite. Kasita has no open sign-up: an invite either adds someone to this
    household, or (own_household) lets them create an account with a household of their own."""
    __tablename__ = "invites"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # True: the invitee gets an account and a new household of their own, not a seat in this one
    own_household: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device: Mapped[str] = mapped_column(String(120), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Base):
    """Long-lived key for scripts, n8n and agents; scoped to one household."""
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(120))
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # e.g. the widget


class BarcodeCache(Base):
    """What the public product databases said about a barcode (shared by all households)."""
    __tablename__ = "barcode_cache"
    barcode: Mapped[str] = mapped_column(String(32), primary_key=True)
    found: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str | None] = mapped_column(String(32))  # openfoodfacts | openproductsfacts | openbeautyfacts
    name: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    quantity_text: Mapped[str | None] = mapped_column(String(64))  # "1.5 l", "12 rolls"
    image_url: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("household_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    is_freezer: Mapped[bool] = mapped_column(Boolean, default=False)


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("household_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # text that appears in bank/card transactions for this store, e.g. "MANGUSA"
    payee_match: Mapped[str | None] = mapped_column(String(120))
    # store profile, read from receipts ("CAS CORAWEG 78", "Tel: 7374534", "CRIB NUMBER: 102768456")
    # or typed by the user. Receipts only fill what is empty; they never overwrite.
    address: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    crib: Mapped[str | None] = mapped_column(String(40))  # tax / registration number (CRIB, KvK, RNC...), digits
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    location_source: Mapped[str | None] = mapped_column(String(12))  # manual | geocoded


class GeocodeCache(Base):
    """What Nominatim answered for a search (found or not), so the same address is asked once."""
    __tablename__ = "geocode_cache"
    query: Mapped[str] = mapped_column(String(400), primary_key=True)
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    label: Mapped[str | None] = mapped_column(String(400))  # Nominatim's display_name
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(24), default="pcs")  # what one unit of stock means
    image_url: Mapped[str | None] = mapped_column(Text)
    # the picture a product database gave; kept when you replace it, so it can be restored
    db_image_url: Mapped[str | None] = mapped_column(Text)
    default_location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    min_stock: Mapped[Decimal] = mapped_column(Qty, default=0)  # below this it goes on the shopping list
    shelf_life_days: Mapped[int | None]  # default best-before offset when none is entered
    open_days: Mapped[int | None]  # keeps this many days once opened (milk 5, salsa 14...)
    notes: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    barcodes: Mapped[list["ProductBarcode"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class ProductBarcode(Base):
    __tablename__ = "product_barcodes"
    __table_args__ = (UniqueConstraint("household_id", "barcode"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    barcode: Mapped[str] = mapped_column(String(32))

    product: Mapped[Product] = relationship(back_populates="barcodes")


class StockEntry(Base):
    """One batch of a product at home. Consuming reduces `quantity`; 0 = used up."""
    __tablename__ = "stock_entries"
    __table_args__ = (Index("ix_stock_household_product", "household_id", "product_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    best_before: Mapped[date | None] = mapped_column(Date)
    opened_at: Mapped[date | None] = mapped_column(Date)
    frozen_at: Mapped[date | None] = mapped_column(Date)  # when it went into a freezer location
    purchased_at: Mapped[date] = mapped_column(Date, default=lambda: date.today())
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    receipt_line_id: Mapped[str | None] = mapped_column(ForeignKey("receipt_lines.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StockEvent(Base):
    """Append-only history: purchase, consume, open, spoil, adjust. Powers undo and statistics."""
    __tablename__ = "stock_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str | None] = mapped_column(ForeignKey("stock_entries.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))  # free text when there is no product
    quantity: Mapped[Decimal] = mapped_column(Qty, default=1)
    note: Mapped[str | None] = mapped_column(String(255))
    auto: Mapped[bool] = mapped_column(Boolean, default=False)  # added because stock ran low
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped["Product | None"] = relationship(lazy="joined")

    @property
    def category(self) -> str | None:
        """For grouping the list: the product's category, else a guess from the typed name."""
        from .services.categories import guess
        return (self.product.category if self.product else None) or guess(self.name)


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    purchased_on: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(String(3))
    store_name: Mapped[str | None] = mapped_column(String(120))  # as printed, before it is matched to a Store
    image_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | parsed | confirmed | failed
    error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSON)  # what the AI returned, kept for debugging
    securo_transaction_id: Mapped[str | None] = mapped_column(String(64))
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # when it was booked: spending-only lines count in the reports from then, like stock purchases do
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["ReceiptLine"]] = relationship(back_populates="receipt", cascade="all, delete-orphan",
                                                      order_by="ReceiptLine.position")


class ReceiptLine(Base):
    __tablename__ = "receipt_lines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    receipt_id: Mapped[str] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int]
    raw_text: Mapped[str] = mapped_column(String(255))  # exactly as printed, e.g. "GSC TOILET PPR 12R"
    name: Mapped[str | None] = mapped_column(String(255))  # readable, e.g. "Toilet paper 12 rolls"
    quantity: Mapped[Decimal] = mapped_column(Qty, default=1)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    line_total: Mapped[Decimal | None] = mapped_column(Money)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    skip: Mapped[bool] = mapped_column(Boolean, default=False)  # not a stock item (bag fee, deposit...)
    matched_by: Mapped[str | None] = mapped_column(String(8))  # alias | guess | user | scan
    # a shop department ("COMESTIBELS", "FRUTA / BERDURA"), not a product: never remembered as an alias
    department: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # counts in spending under `spending_category`, but creates no product and no stock
    spending_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    spending_category: Mapped[str | None] = mapped_column(String(80))

    receipt: Mapped[Receipt] = relationship(back_populates="lines")


class ReceiptAlias(Base):
    """Learned mapping: this store prints this text for this product. Makes the next receipt automatic."""
    __tablename__ = "receipt_aliases"
    __table_args__ = (UniqueConstraint("household_id", "store_id", "text_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    text_key: Mapped[str] = mapped_column(String(255))  # normalised receipt text
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))


class ReceiptDepartment(Base):
    """Learned: at this store, this receipt text is a department (it was linked to different
    products on different lines), so it is never auto-linked from memory."""
    __tablename__ = "receipt_departments"
    __table_args__ = (UniqueConstraint("household_id", "store_id", "text_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    store_id: Mapped[str | None] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    text_key: Mapped[str] = mapped_column(String(255))  # normalised receipt text


class Integration(Base):
    """Per-household connection settings (ChatGPT sign-in for receipts, Securo)."""
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("household_id", "kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # chatgpt | securo
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # tokens are encrypted before they get here
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)



class Recipe(Base):
    """A saved meal: from a 'What can I cook?' idea or typed in."""
    __tablename__ = "recipes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    minutes: Mapped[int | None]
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="recipe", cascade="all, delete-orphan",
                                                                 order_by="RecipeIngredient.position")


class RecipeIngredient(Base):
    """One thing a recipe needs: one of the household's products, or just a name (bought when needed)."""
    __tablename__ = "recipe_ingredients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(default=0)
    name: Mapped[str] = mapped_column(String(160))
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    quantity: Mapped[Decimal] = mapped_column(Qty, default=1)  # in the product's unit; what 'Cooked it' takes

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")


class MealPlan(Base):
    """What's for dinner on a day (one planned meal per day)."""
    __tablename__ = "meal_plan"
    __table_args__ = (UniqueConstraint("household_id", "day"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    recipe_id: Mapped[str | None] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(160))  # "leftovers", "eating out"...



class Bill(Base):
    """A household bill (water, electricity, internet...) photographed in Kasita and booked in Securo.
    Not part of the pantry: it only reads the bill and links it to the payment in the finance app."""
    __tablename__ = "bills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="reading")  # reading | read | linked | failed
    error: Mapped[str | None] = mapped_column(Text)
    biller: Mapped[str | None] = mapped_column(String(120))            # Aqualectra, Flow, Selikor...
    lines: Mapped[list] = mapped_column(JSON, default=list)             # [{"service": "water", "amount": "50.98"}]
    total: Mapped[Decimal | None] = mapped_column(Money)                # amount due on this bill
    currency: Mapped[str | None] = mapped_column(String(3))
    period: Mapped[str | None] = mapped_column(String(60))              # "September 2026"
    bill_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    account_ref: Mapped[str | None] = mapped_column(String(60))         # customer / account number
    image_path: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSON)
    securo_transaction_id: Mapped[str | None] = mapped_column(String(64))
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
