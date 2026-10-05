import secrets
from datetime import datetime

from flask_login import UserMixin

from extensions import db


# ============================================================
# ADMIN
# ============================================================

class Admin(UserMixin, db.Model):
    __tablename__ = "admins"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    def __repr__(self):
        return f"<Admin {self.username}>"


# ============================================================
# SHOP SETTINGS
# ============================================================

class ShopSettings(db.Model):
    __tablename__ = "shop_settings"

    # Singleton row. The application uses id=1.
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # --------------------------------------------------------
    # SHOP INFORMATION
    # --------------------------------------------------------

    shop_name = db.Column(
        db.String(150),
        nullable=False,
        default="My Shop"
    )

    shop_description = db.Column(
        db.Text,
        nullable=True
    )

    shop_phone = db.Column(
        db.String(30),
        nullable=True
    )

    shop_email = db.Column(
        db.String(254),
        nullable=True
    )

    shop_address = db.Column(
        db.Text,
        nullable=True
    )

    # --------------------------------------------------------
    # DELIVERY
    # --------------------------------------------------------

    delivery_enabled = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    delivery_fee = db.Column(
        db.Numeric(10, 2),
        nullable=False,
        default=0
    )

    free_delivery_threshold = db.Column(
        db.Numeric(10, 2),
        nullable=True
    )

    # --------------------------------------------------------
    # ORDERS
    # --------------------------------------------------------

    allow_orders = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    # --------------------------------------------------------
    # OFFERS
    # --------------------------------------------------------

    default_offer_duration_days = db.Column(
        db.Integer,
        nullable=False,
        default=7
    )

    # --------------------------------------------------------
    # INVENTORY
    # --------------------------------------------------------

    low_stock_threshold = db.Column(
        db.Integer,
        nullable=False,
        default=5
    )

    # --------------------------------------------------------
    # TIMESTAMPS
    # --------------------------------------------------------

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    def __repr__(self):
        return f"<ShopSettings {self.id}>"


# ============================================================
# WILAYA DELIVERY FEE
# ============================================================

class WilayaDeliveryFee(db.Model):
    __tablename__ = "wilaya_delivery_fees"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # 1-58, matches the official Algerian wilaya numbering.
    wilaya_code = db.Column(
        db.Integer,
        unique=True,
        nullable=False
    )

    wilaya_name = db.Column(
        db.String(60),
        nullable=False
    )

    fee = db.Column(
        db.Numeric(10, 2),
        nullable=False,
        default=0
    )

    def __repr__(self):
        return f"<WilayaDeliveryFee {self.wilaya_code} {self.wilaya_name}>"


# ============================================================
# PRODUCT
# ============================================================

class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(150),
        nullable=False
    )

    # One of the values in app.PRODUCT_CATEGORIES.
    # Kept as a plain string (rather than a separate table) since
    # the category list is a short, admin-curated set.
    category = db.Column(
        db.String(50),
        nullable=True
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    # Current selling price.
    # For an active offer, this is the discounted price.
    price = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    # Original non-discounted price.
    regular_price = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    stock = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    # --------------------------------------------------------
    # OFFER
    # --------------------------------------------------------

    offer_active = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    offer_ends_at = db.Column(
        db.DateTime,
        nullable=True
    )

    # Kept for compatibility with the existing database.
    # Availability is now determined by stock and this field
    # is no longer used as the offer flag.
    is_sold = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    images = db.relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan"
    )

    order_items = db.relationship(
        "OrderItem",
        back_populates="product"
    )

    def __repr__(self):
        return f"<Product {self.name}>"


# ============================================================
# PRODUCT IMAGE
# ============================================================

class ProductImage(db.Model):
    __tablename__ = "product_images"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    filename = db.Column(
        db.String(255),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False
    )

    product = db.relationship(
        "Product",
        back_populates="images"
    )

    def __repr__(self):
        return f"<ProductImage {self.filename}>"


# ============================================================
# ORDER
# ============================================================

class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    public_token = db.Column(
        db.String(64),
        unique=True,
        nullable=False,
        default=lambda: secrets.token_urlsafe(32)
    )

    customer_name = db.Column(
        db.String(150),
        nullable=False
    )

    phone = db.Column(
        db.String(30),
        nullable=False
    )

    address = db.Column(
        db.Text,
        nullable=False
    )

    # The Algerian province (wilaya) selected at checkout. Stored
    # denormalized (code + name) so historic orders and invoices
    # keep showing the right province even if fees change later.
    wilaya_code = db.Column(
        db.Integer,
        nullable=True
    )

    wilaya_name = db.Column(
        db.String(60),
        nullable=True
    )

    latitude = db.Column(
        db.Float,
        nullable=True
    )

    longitude = db.Column(
        db.Float,
        nullable=True
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="pending"
    )

    payment_method = db.Column(
        db.String(30),
        nullable=False,
        default="cash_on_delivery"
    )

    # Delivery fee captured at the time the order was placed.
    delivery_fee = db.Column(
        db.Numeric(10, 2),
        nullable=False,
        default=0
    )

    total = db.Column(
        db.Numeric(10, 2),
        nullable=False,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    items = db.relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Order #{self.id}>"


# ============================================================
# ORDER ITEM
# ============================================================

class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("orders.id"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        nullable=False
    )

    # Actual unit price paid when this order was placed.
    price = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    order = db.relationship(
        "Order",
        back_populates="items"
    )

    product = db.relationship(
        "Product",
        back_populates="order_items"
    )

    def __repr__(self):
        return (
            f"<OrderItem "
            f"order={self.order_id} "
            f"product={self.product_id}>"
        )