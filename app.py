import os
from io import BytesIO
from math import ceil
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from uuid import uuid4

from dotenv import load_dotenv

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    session,
    send_file,
)
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)

from flask_wtf.csrf import CSRFProtect

from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from extensions import db

from models import (
    Product,
    ProductImage,
    Admin,
    Order,
    OrderItem,
    ShopSettings,
    WilayaDeliveryFee,
)


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

app = Flask(__name__)

# Behind Caddy/nginx: trust the proxy's X-Forwarded-* headers so that
# url_for, redirects and secure cookies see the real scheme and host.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Set FLASK_DEBUG=1 in your local .env only. Never on the server.
DEBUG_MODE = os.environ.get("FLASK_DEBUG") == "1"

# Render/PostgreSQL may provide DATABASE_URL as postgres://... .
# SQLAlchemy expects the modern postgresql:// scheme.
database_url = os.environ.get("DATABASE_URL", "sqlite:///shop.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]

# Session cookie hardening (Secure cookies need HTTPS, so they are
# switched off automatically in local debug mode).
app.config["SESSION_COOKIE_SECURE"] = not DEBUG_MODE
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_SECURE"] = not DEBUG_MODE
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"

# Maximum size of one request
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# ============================================================
# EXTENSIONS
# ============================================================

db.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "admin_entry"


# ============================================================
# LOGIN MANAGER
# ============================================================

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(Admin, int(user_id))
    except (ValueError, TypeError):
        return None


# ============================================================
# ADMIN PATH
# ============================================================

ADMIN_PATH = os.environ["ADMIN_PATH"]


# ============================================================
# IMAGE UPLOAD CONFIGURATION
# ============================================================

# By default, product images stay in the project for local development.
# In production, set UPLOAD_FOLDER to a persistent mounted directory
# (or replace this local storage with object storage such as S3/R2).
upload_folder_env = os.environ.get("UPLOAD_FOLDER")

if upload_folder_env:
    UPLOAD_FOLDER = Path(upload_folder_env).expanduser().resolve()
else:
    UPLOAD_FOLDER = (
        Path(app.static_folder)
        / "images"
        / "products"
    )

UPLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

MAX_PRODUCT_IMAGES = 8


# ============================================================
# PRODUCT CATEGORIES
#
# Single source of truth for the fixed category list. Used by
# the admin product form (to choose a category) and by the
# storefront (to build the category filter). Edit this list to
# add, rename or remove categories shop-wide.
# ============================================================

PRODUCT_CATEGORIES = [
    "Clothing",
    "Electronics",
    "Home & Living",
    "Beauty",
    "Other",
]


# ============================================================
# ALGERIAN WILAYAS (PROVINCES)
#
# The official 1-58 numbering, used for the checkout province
# selector and as the per-province delivery fee list in admin
# settings. Single source of truth — nothing about this list is
# hardcoded anywhere else.
# ============================================================

ALGERIA_WILAYAS = [
    (1, "Adrar"), (2, "Chlef"), (3, "Laghouat"), (4, "Oum El Bouaghi"),
    (5, "Batna"), (6, "Béjaïa"), (7, "Biskra"), (8, "Béchar"),
    (9, "Blida"), (10, "Bouira"), (11, "Tamanrasset"), (12, "Tébessa"),
    (13, "Tlemcen"), (14, "Tiaret"), (15, "Tizi Ouzou"), (16, "Alger"),
    (17, "Djelfa"), (18, "Jijel"), (19, "Sétif"), (20, "Saïda"),
    (21, "Skikda"), (22, "Sidi Bel Abbès"), (23, "Annaba"), (24, "Guelma"),
    (25, "Constantine"), (26, "Médéa"), (27, "Mostaganem"), (28, "M'Sila"),
    (29, "Mascara"), (30, "Ouargla"), (31, "Oran"), (32, "El Bayadh"),
    (33, "Illizi"), (34, "Bordj Bou Arréridj"), (35, "Boumerdès"), (36, "El Tarf"),
    (37, "Tindouf"), (38, "Tissemsilt"), (39, "El Oued"), (40, "Khenchela"),
    (41, "Souk Ahras"), (42, "Tipaza"), (43, "Mila"), (44, "Aïn Defla"),
    (45, "Naâma"), (46, "Aïn Témouchent"), (47, "Ghardaïa"), (48, "Relizane"),
    (49, "Timimoun"), (50, "Bordj Badji Mokhtar"), (51, "Ouled Djellal"), (52, "Béni Abbès"),
    (53, "In Salah"), (54, "In Guezzam"), (55, "Touggourt"), (56, "Djanet"),
    (57, "El M'Ghair"), (58, "El Meniaa"),
]

ALGERIA_WILAYA_NAMES = dict(ALGERIA_WILAYAS)


# ============================================================
# OFFER / PROMOTION (SOLDE) DISCOUNT TYPES
# ============================================================

OFFER_DISCOUNT_TYPES = {
    "percentage",
    "fixed_price",
}


# ============================================================
# STOREFRONT PAGINATION
# ============================================================

PRODUCTS_PER_PAGE = 12


# ============================================================
# CART
#
# The cart lives in the signed session cookie as a plain
# {product_id_str: quantity} mapping. Nothing about a cart is
# persisted server-side until checkout turns it into a real
# Order + OrderItem rows.
# ============================================================

CART_SESSION_KEY = "cart"


# ============================================================
# SHOP SETTINGS HELPER
# ============================================================

def get_shop_settings():
    """Return the singleton shop settings row, creating it if missing."""
    settings = db.session.get(ShopSettings, 1)
    if settings is None:
        settings = ShopSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    return settings


def refresh_offer(product):
    """Expire a product offer automatically when its end time is reached."""
    if (
        getattr(product, "offer_active", False)
        and product.offer_ends_at is not None
        and datetime.utcnow() >= product.offer_ends_at
    ):
        product.offer_active = False
        product.offer_ends_at = None
        product.price = product.regular_price
        db.session.commit()

    return product


def get_cart_raw():
    """The raw {product_id_str: quantity} mapping stored in the session."""
    return session.get(CART_SESSION_KEY, {})


def get_cart_items():
    """
    Load the cart's products from the database, refresh any active
    offers, clamp quantities to available stock, and silently drop
    anything that no longer exists or sold out since it was added.

    Returns (items, subtotal). Each item is a dict with product,
    quantity, unit_price and line_total.
    """

    raw_cart = dict(get_cart_raw())

    items = []
    subtotal = Decimal("0.00")
    changed = False

    for product_id_str in list(raw_cart.keys()):

        try:
            product_id = int(product_id_str)
            quantity = int(raw_cart[product_id_str])
        except (TypeError, ValueError):
            del raw_cart[product_id_str]
            changed = True
            continue

        product = db.session.get(Product, product_id)

        if (
            product is None
            or product.is_sold
            or product.stock <= 0
        ):
            del raw_cart[product_id_str]
            changed = True
            continue

        refresh_offer(product)

        clamped_quantity = max(0, min(quantity, product.stock))

        if clamped_quantity <= 0:
            del raw_cart[product_id_str]
            changed = True
            continue

        if clamped_quantity != quantity:
            raw_cart[product_id_str] = clamped_quantity
            changed = True

        unit_price = Decimal(str(product.price))
        line_total = unit_price * clamped_quantity

        items.append({
            "product": product,
            "quantity": clamped_quantity,
            "unit_price": unit_price,
            "line_total": line_total,
        })

        subtotal += line_total

    if changed:
        session[CART_SESSION_KEY] = raw_cart
        session.modified = True

    return items, subtotal


def get_cart_count():
    """Total item count across the cart, for the navbar badge."""
    total = 0
    for value in get_cart_raw().values():
        try:
            total += int(value)
        except (TypeError, ValueError):
            pass
    return total


def ensure_wilaya_fees_seeded():
    """
    Make sure every wilaya has a delivery-fee row. Runs lazily
    (like get_shop_settings' singleton) rather than requiring a
    separate seed script — newly added wilayas just appear with
    the shop's current flat delivery fee as their starting price.
    """

    existing_codes = {
        row.wilaya_code
        for row in WilayaDeliveryFee.query.with_entities(
            WilayaDeliveryFee.wilaya_code
        ).all()
    }

    shop_settings = get_shop_settings()
    default_fee = shop_settings.delivery_fee

    created = False

    for code, name in ALGERIA_WILAYAS:

        if code not in existing_codes:

            db.session.add(
                WilayaDeliveryFee(
                    wilaya_code=code,
                    wilaya_name=name,
                    fee=default_fee,
                )
            )

            created = True

    if created:
        db.session.commit()


def calculate_delivery_fee(shop_settings, subtotal, wilaya_code=None):
    """
    Delivery fee for a given province. Falls back to the shop's
    flat delivery fee if no province was given/found (kept so any
    older code path without a province still works).
    """

    if not shop_settings.delivery_enabled:
        return Decimal("0.00")

    configured_fee = Decimal(str(shop_settings.delivery_fee))

    if wilaya_code is not None:

        fee_row = WilayaDeliveryFee.query.filter_by(
            wilaya_code=wilaya_code
        ).first()

        if fee_row is not None:
            configured_fee = Decimal(str(fee_row.fee))

    free_threshold = shop_settings.free_delivery_threshold

    if (
        configured_fee > 0
        and free_threshold is not None
        and subtotal >= Decimal(str(free_threshold))
    ):
        return Decimal("0.00")

    return configured_fee


def build_invoice_pdf(order, shop_settings):
    """Render a downloadable PDF bill for a single order."""

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Title"],
        fontSize=20,
        spaceAfter=2,
    )

    normal = styles["Normal"]

    elements = []

    elements.append(Paragraph(shop_settings.shop_name, title_style))
    elements.append(Paragraph("Invoice", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    meta_table = Table(
        [
            ["Invoice #", str(order.id)],
            ["Date", order.created_at.strftime("%Y-%m-%d %H:%M")],
            ["Status", order.status.capitalize()],
        ],
        colWidths=[40 * mm, 60 * mm],
    )

    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#40453f")),
    ]))

    elements.append(meta_table)
    elements.append(Spacer(1, 12))

    bill_to = [
        Paragraph("<b>Bill to</b>", normal),
        Paragraph(order.customer_name, normal),
        Paragraph(order.phone, normal),
    ]

    if order.wilaya_name:
        bill_to.append(Paragraph(order.wilaya_name, normal))

    if order.address:
        bill_to.append(Paragraph(order.address, normal))

    shop_info = [
        Paragraph("<b>From</b>", normal),
        Paragraph(shop_settings.shop_name, normal),
    ]

    if shop_settings.shop_phone:
        shop_info.append(Paragraph(shop_settings.shop_phone, normal))

    if shop_settings.shop_address:
        shop_info.append(Paragraph(shop_settings.shop_address, normal))

    info_table = Table(
        [[bill_to, shop_info]],
        colWidths=[95 * mm, 65 * mm],
    )

    elements.append(info_table)
    elements.append(Spacer(1, 16))

    items_data = [["Product", "Unit price", "Qty", "Subtotal"]]

    for item in order.items:

        product_name = (
            item.product.name
            if item.product
            else "Deleted product"
        )

        items_data.append([
            product_name,
            f"{item.price:,.0f} DA",
            str(item.quantity),
            f"{(item.price * item.quantity):,.0f} DA",
        ])

    items_table = Table(
        items_data,
        colWidths=[80 * mm, 30 * mm, 20 * mm, 30 * mm],
    )

    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1C2321")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DCD3C0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    elements.append(items_table)
    elements.append(Spacer(1, 10))

    subtotal = order.total - order.delivery_fee

    delivery_label = "Delivery"

    if order.wilaya_name:
        delivery_label = f"Delivery ({order.wilaya_name})"

    totals_table = Table(
        [
            ["Subtotal", f"{subtotal:,.0f} DA"],
            [delivery_label, f"{order.delivery_fee:,.0f} DA"],
            ["Total", f"{order.total:,.0f} DA"],
        ],
        colWidths=[130 * mm, 30 * mm],
    )

    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1C2321")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, -1), (-1, -1), 8),
    ]))

    elements.append(totals_table)
    elements.append(Spacer(1, 20))

    elements.append(
        Paragraph("Payment method: Cash on delivery", normal)
    )

    doc.build(elements)

    buffer.seek(0)

    return buffer


@app.context_processor
def inject_cart_count():
    """Makes `cart_count` available in every template for the navbar badge."""
    return {"cart_count": get_cart_count()}


# ============================================================
# DEVELOPMENT DATABASE
# ============================================================

# Keep this during development.
# Flask-Migrate should be used for future schema changes.

# ============================================================
# PUBLIC STOREFRONT
# ============================================================

@app.route("/")
def home():

    search_query = request.args.get("q", "").strip()
    selected_category = request.args.get("category", "").strip()
    sale_only = request.args.get("sale") == "1"

    products_query = Product.query

    if search_query:

        like_pattern = f"%{search_query}%"

        products_query = products_query.filter(
            db.or_(
                Product.name.ilike(like_pattern),
                Product.description.ilike(like_pattern),
            )
        )

    # Only accept known categories. An unknown/tampered value in
    # the query string is treated as "no filter" rather than
    # producing an empty result set.
    if selected_category not in PRODUCT_CATEGORIES:
        selected_category = ""

    if selected_category:
        products_query = products_query.filter_by(
            category=selected_category
        )

    if sale_only:
        products_query = products_query.filter_by(
            offer_active=True
        )

    total_matching = products_query.count()

    total_pages = max(
        1,
        ceil(total_matching / PRODUCTS_PER_PAGE)
    )

    page = request.args.get("page", 1, type=int) or 1
    page = max(1, min(page, total_pages))

    products = (
        products_query
        .order_by(Product.created_at.desc())
        .offset((page - 1) * PRODUCTS_PER_PAGE)
        .limit(PRODUCTS_PER_PAGE)
        .all()
    )

    for product in products:
        refresh_offer(product)

    shop_settings = get_shop_settings()

    # --------------------------------------------------------
    # HERO / TOOLBAR CONTEXT
    #
    # Counted separately from `products` above since that list
    # may already be narrowed down by search/category/sale.
    # --------------------------------------------------------

    total_products_count = Product.query.count()

    products_on_offer = (
        Product.query
        .filter_by(offer_active=True)
        .all()
    )

    for product in products_on_offer:
        refresh_offer(product)

    active_offers_count = sum(
        1
        for product in products_on_offer
        if product.offer_active
    )

    hero_products = (
        Product.query
        .filter(Product.images.any())
        .order_by(Product.created_at.desc())
        .limit(3)
        .all()
    )

    return render_template(
        "index.html",
        products=products,
        shop_settings=shop_settings,
        categories=PRODUCT_CATEGORIES,
        search_query=search_query,
        selected_category=selected_category,
        sale_only=sale_only,
        total_products_count=total_products_count,
        active_offers_count=active_offers_count,
        hero_products=hero_products,
        page=page,
        total_pages=total_pages,
        total_matching=total_matching,
    )


# ============================================================
# PUBLIC PRODUCT DETAIL
# ============================================================

@app.route("/product/<int:product_id>")
def product_detail(product_id):

    product = db.get_or_404(
        Product,
        product_id
    )

    refresh_offer(product)
    shop_settings = get_shop_settings()

    ensure_wilaya_fees_seeded()

    wilaya_fees = {
        row.wilaya_code: float(row.fee)
        for row in WilayaDeliveryFee.query.order_by(
            WilayaDeliveryFee.wilaya_code
        ).all()
    }

    return render_template(
        "product.html",
        product=product,
        shop_settings=shop_settings,
        wilayas=ALGERIA_WILAYAS,
        wilaya_fees=wilaya_fees,
    )


# ============================================================
# CUSTOMER CREATE ORDER
# ============================================================

@app.route(
    "/product/<int:product_id>/order",
    methods=["POST"]
)
def create_order(product_id):

    product = db.get_or_404(
        Product,
        product_id
    )

    shop_settings = get_shop_settings()
    refresh_offer(product)

    if not shop_settings.allow_orders:
        flash(
            "New orders are temporarily unavailable.",
            "error"
        )
        return redirect(
            url_for(
                "product_detail",
                product_id=product.id
            )
        )

    # --------------------------------------------------------
    # CUSTOMER INFORMATION
    # --------------------------------------------------------

    customer_name = request.form.get(
        "customer_name",
        ""
    ).strip()

    phone = request.form.get(
        "phone",
        ""
    ).strip()

    address = request.form.get(
        "address",
        ""
    ).strip()

    wilaya_code_raw = request.form.get(
        "wilaya_code",
        ""
    ).strip()

    latitude_raw = request.form.get(
        "latitude",
        ""
    ).strip()

    longitude_raw = request.form.get(
        "longitude",
        ""
    ).strip()

    quantity_raw = request.form.get(
        "quantity",
        ""
    ).strip()

    errors = []


    # --------------------------------------------------------
    # NAME VALIDATION
    # --------------------------------------------------------

    if not customer_name:

        errors.append(
            "Please enter your name."
        )

    elif len(customer_name) > 150:

        errors.append(
            "Your name is too long."
        )


    # --------------------------------------------------------
    # PHONE VALIDATION
    # --------------------------------------------------------

    if not phone:

        errors.append(
            "Please enter your phone number."
        )

    elif len(phone) > 30:

        errors.append(
            "Your phone number is too long."
        )


    # --------------------------------------------------------
    # PROVINCE (WILAYA)
    # --------------------------------------------------------

    wilaya_code = None

    try:
        wilaya_code = int(wilaya_code_raw)
    except (TypeError, ValueError):
        wilaya_code = None

    if wilaya_code not in ALGERIA_WILAYA_NAMES:

        errors.append(
            "Please select your province (wilaya)."
        )

        wilaya_code = None


    # --------------------------------------------------------
    # DELIVERY LOCATION
    #
    # Address OR GPS location.
    # Both are not required.
    # --------------------------------------------------------

    latitude = None
    longitude = None

    if latitude_raw or longitude_raw:

        if not latitude_raw or not longitude_raw:

            errors.append(
                "Your location information is incomplete."
            )

        else:

            try:

                latitude = float(
                    latitude_raw
                )

                longitude = float(
                    longitude_raw
                )

            except (ValueError, TypeError):

                errors.append(
                    "The provided location is invalid."
                )

            else:

                if not -90 <= latitude <= 90:

                    errors.append(
                        "The latitude value is invalid."
                    )

                if not -180 <= longitude <= 180:

                    errors.append(
                        "The longitude value is invalid."
                    )


    has_address = bool(address)

    has_location = (
        latitude is not None
        and longitude is not None
    )

    if not has_address and not has_location:

        errors.append(
            "Please enter a delivery address "
            "or use your current location."
        )


    # --------------------------------------------------------
    # ADDRESS LENGTH
    # --------------------------------------------------------

    if len(address) > 1000:

        errors.append(
            "The delivery address is too long."
        )


    # --------------------------------------------------------
    # QUANTITY
    # --------------------------------------------------------

    quantity = None

    try:

        quantity = int(
            quantity_raw
        )

        if quantity <= 0:

            errors.append(
                "Quantity must be greater than zero."
            )

    except (ValueError, TypeError):

        errors.append(
            "Please provide a valid quantity."
        )


    # --------------------------------------------------------
    # PRODUCT AVAILABILITY
    # --------------------------------------------------------

    if product.stock <= 0:

        errors.append(
            "This product is currently out of stock."
        )

    elif (
        quantity is not None
        and quantity > product.stock
    ):

        errors.append(
            f"Only {product.stock} item(s) "
            f"are currently available."
        )


    # --------------------------------------------------------
    # VALIDATION FAILURE
    # --------------------------------------------------------

    if errors:

        for error in errors:

            flash(
                error,
                "error"
            )

        return redirect(
            url_for(
                "product_detail",
                product_id=product.id
            )
        )


    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    unit_price = Decimal(
        str(product.price)
    )

    subtotal = (
        unit_price
        * quantity
    )

    delivery_fee = calculate_delivery_fee(
        shop_settings,
        subtotal,
        wilaya_code
    )

    total = subtotal + delivery_fee


    # --------------------------------------------------------
    # CREATE ORDER
    # --------------------------------------------------------

    order = Order(
        customer_name=customer_name,
        phone=phone,
        address=address,
        wilaya_code=wilaya_code,
        wilaya_name=ALGERIA_WILAYA_NAMES.get(wilaya_code),
        latitude=latitude,
        longitude=longitude,
        status="pending",
        payment_method="cash_on_delivery",
        delivery_fee=delivery_fee,
        total=total,
    )

    db.session.add(order)

    db.session.flush()


    # --------------------------------------------------------
    # CREATE ORDER ITEM
    # --------------------------------------------------------

    order_item = OrderItem(
        order=order,
        product=product,
        quantity=quantity,
        price=unit_price,
    )

    db.session.add(
        order_item
    )


    # --------------------------------------------------------
    # UPDATE STOCK
    # --------------------------------------------------------

    product.stock -= quantity

    if product.stock == 0:

        product.is_sold = True


    # --------------------------------------------------------
    # SAVE ORDER
    # --------------------------------------------------------

    try:

        db.session.commit()

    except Exception:

        db.session.rollback()

        flash(
            "Something went wrong while "
            "creating your order. Please try again.",
            "error"
        )

        return redirect(
            url_for(
                "product_detail",
                product_id=product.id
            )
        )


    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    return redirect(
        url_for(
            "order_confirmation",
            token=order.public_token
        )
    )


# ============================================================
# CART: ADD ITEM
# ============================================================

@app.route(
    "/cart/add/<int:product_id>",
    methods=["POST"]
)
def add_to_cart(product_id):

    product = db.get_or_404(
        Product,
        product_id
    )

    refresh_offer(product)

    if product.is_sold or product.stock <= 0:

        flash(
            "This product is currently out of stock.",
            "error"
        )

        return redirect(
            url_for(
                "product_detail",
                product_id=product.id
            )
        )

    quantity_raw = request.form.get(
        "quantity",
        "1"
    ).strip()

    try:
        quantity = int(quantity_raw)
    except (TypeError, ValueError):
        quantity = 1

    if quantity <= 0:
        quantity = 1

    raw_cart = dict(get_cart_raw())
    key = str(product.id)
    current_quantity = int(raw_cart.get(key, 0) or 0)

    raw_cart[key] = min(
        current_quantity + quantity,
        product.stock
    )

    session[CART_SESSION_KEY] = raw_cart
    session.modified = True

    flash(
        f"{product.name} added to your cart.",
        "success"
    )

    destination = request.referrer

    if not destination:
        destination = url_for(
            "product_detail",
            product_id=product.id
        )

    return redirect(destination)


# ============================================================
# CART: VIEW
# ============================================================

@app.route("/cart")
def view_cart():

    items, subtotal = get_cart_items()
    shop_settings = get_shop_settings()

    ensure_wilaya_fees_seeded()

    wilaya_fees = {
        row.wilaya_code: float(row.fee)
        for row in WilayaDeliveryFee.query.order_by(
            WilayaDeliveryFee.wilaya_code
        ).all()
    }

    return render_template(
        "cart.html",
        items=items,
        subtotal=subtotal,
        shop_settings=shop_settings,
        wilayas=ALGERIA_WILAYAS,
        wilaya_fees=wilaya_fees,
    )


# ============================================================
# CART: UPDATE QUANTITIES
# ============================================================

@app.route(
    "/cart/update",
    methods=["POST"]
)
def update_cart():

    raw_cart = dict(get_cart_raw())

    for field_name, raw_value in request.form.items():

        if not field_name.startswith("qty_"):
            continue

        product_id_str = field_name[len("qty_"):]

        if product_id_str not in raw_cart:
            continue

        try:
            quantity = int(raw_value)
        except (TypeError, ValueError):
            continue

        if quantity <= 0:
            del raw_cart[product_id_str]
        else:
            raw_cart[product_id_str] = quantity

    session[CART_SESSION_KEY] = raw_cart
    session.modified = True

    flash(
        "Cart updated.",
        "success"
    )

    return redirect(
        url_for("view_cart")
    )


# ============================================================
# CART: REMOVE ITEM
# ============================================================

@app.route(
    "/cart/remove/<int:product_id>",
    methods=["POST"]
)
def remove_from_cart(product_id):

    raw_cart = dict(get_cart_raw())
    raw_cart.pop(str(product_id), None)

    session[CART_SESSION_KEY] = raw_cart
    session.modified = True

    flash(
        "Item removed from your cart.",
        "success"
    )

    return redirect(
        url_for("view_cart")
    )


# ============================================================
# CART: CHECKOUT
#
# Turns the current cart into a single Order with one OrderItem
# per line — the same schema create_order() above uses for a
# single-product purchase.
# ============================================================

@app.route(
    "/cart/checkout",
    methods=["POST"]
)
def checkout():

    shop_settings = get_shop_settings()

    if not shop_settings.allow_orders:

        flash(
            "New orders are temporarily unavailable.",
            "error"
        )

        return redirect(
            url_for("view_cart")
        )

    items, subtotal = get_cart_items()

    if not items:

        flash(
            "Your cart is empty.",
            "error"
        )

        return redirect(
            url_for("view_cart")
        )


    # --------------------------------------------------------
    # CUSTOMER INFORMATION
    # (same rules as the single-product checkout above)
    # --------------------------------------------------------

    customer_name = request.form.get(
        "customer_name",
        ""
    ).strip()

    phone = request.form.get(
        "phone",
        ""
    ).strip()

    address = request.form.get(
        "address",
        ""
    ).strip()

    wilaya_code_raw = request.form.get(
        "wilaya_code",
        ""
    ).strip()

    latitude_raw = request.form.get(
        "latitude",
        ""
    ).strip()

    longitude_raw = request.form.get(
        "longitude",
        ""
    ).strip()

    errors = []

    if not customer_name:

        errors.append(
            "Please enter your name."
        )

    elif len(customer_name) > 150:

        errors.append(
            "Your name is too long."
        )

    if not phone:

        errors.append(
            "Please enter your phone number."
        )

    elif len(phone) > 30:

        errors.append(
            "Your phone number is too long."
        )

    wilaya_code = None

    try:
        wilaya_code = int(wilaya_code_raw)
    except (TypeError, ValueError):
        wilaya_code = None

    if wilaya_code not in ALGERIA_WILAYA_NAMES:

        errors.append(
            "Please select your province (wilaya)."
        )

        wilaya_code = None

    latitude = None
    longitude = None

    if latitude_raw or longitude_raw:

        if not latitude_raw or not longitude_raw:

            errors.append(
                "Your location information is incomplete."
            )

        else:

            try:

                latitude = float(latitude_raw)
                longitude = float(longitude_raw)

            except (ValueError, TypeError):

                errors.append(
                    "The provided location is invalid."
                )

            else:

                if not -90 <= latitude <= 90:

                    errors.append(
                        "The latitude value is invalid."
                    )

                if not -180 <= longitude <= 180:

                    errors.append(
                        "The longitude value is invalid."
                    )

    has_address = bool(address)

    has_location = (
        latitude is not None
        and longitude is not None
    )

    if not has_address and not has_location:

        errors.append(
            "Please enter a delivery address "
            "or use your current location."
        )

    if len(address) > 1000:

        errors.append(
            "The delivery address is too long."
        )


    # --------------------------------------------------------
    # RE-CHECK STOCK
    #
    # Stock may have moved between loading the cart page and
    # submitting this form.
    # --------------------------------------------------------

    for item in items:

        if item["quantity"] > item["product"].stock:

            errors.append(
                f"Only {item['product'].stock} of "
                f"\"{item['product'].name}\" left in stock."
            )


    if errors:

        for error in errors:

            flash(error, "error")

        return redirect(
            url_for("view_cart")
        )


    # --------------------------------------------------------
    # CREATE ORDER + ORDER ITEMS
    # --------------------------------------------------------

    delivery_fee = calculate_delivery_fee(
        shop_settings,
        subtotal,
        wilaya_code
    )

    total = subtotal + delivery_fee

    order = Order(
        customer_name=customer_name,
        phone=phone,
        address=address,
        wilaya_code=wilaya_code,
        wilaya_name=ALGERIA_WILAYA_NAMES.get(wilaya_code),
        latitude=latitude,
        longitude=longitude,
        status="pending",
        payment_method="cash_on_delivery",
        delivery_fee=delivery_fee,
        total=total,
    )

    db.session.add(order)
    db.session.flush()

    for item in items:

        product = item["product"]

        order_item = OrderItem(
            order=order,
            product=product,
            quantity=item["quantity"],
            price=item["unit_price"],
        )

        db.session.add(order_item)

        product.stock -= item["quantity"]

        if product.stock == 0:
            product.is_sold = True

    try:

        db.session.commit()

    except Exception:

        db.session.rollback()

        flash(
            "Something went wrong while creating "
            "your order. Please try again.",
            "error"
        )

        return redirect(
            url_for("view_cart")
        )

    session[CART_SESSION_KEY] = {}
    session.modified = True

    return redirect(
        url_for(
            "order_confirmation",
            token=order.public_token
        )
    )


# ============================================================
# CUSTOMER ORDER CONFIRMATION
# ============================================================

@app.route("/order/<token>")
def order_confirmation(token):

    order = (
        Order.query
        .filter_by(
            public_token=token
        )
        .first_or_404()
    )

    return render_template(
        "order_confirmation.html",
        order=order
    )


# ============================================================
# CUSTOMER INVOICE DOWNLOAD
# ============================================================

@app.route("/order/<token>/invoice")
def order_invoice(token):

    order = (
        Order.query
        .filter_by(
            public_token=token
        )
        .first_or_404()
    )

    shop_settings = get_shop_settings()

    pdf_buffer = build_invoice_pdf(
        order,
        shop_settings
    )

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"invoice-{order.id}.pdf",
    )


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route(
    f"/{ADMIN_PATH}",
    methods=["GET", "POST"]
)
def admin_entry():

    if current_user.is_authenticated:

        return redirect(
            url_for("admin_dashboard")
        )


    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )


        admin = (
            Admin.query
            .filter_by(
                username=username
            )
            .first()
        )


        if admin is None:

            flash(
                "Invalid username or password.",
                "error"
            )

            return render_template(
                "admin_login.html"
            )


        if not check_password_hash(
            admin.password_hash,
            password
        ):

            flash(
                "Invalid username or password.",
                "error"
            )

            return render_template(
                "admin_login.html"
            )


        login_user(admin)

        return redirect(
            url_for(
                "admin_dashboard"
            )
        )


    return render_template(
        "admin_login.html"
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/dashboard"
)
@login_required
def admin_dashboard():

    shop_settings = get_shop_settings()

    # --------------------------------------------------------
    # PRODUCTS
    # --------------------------------------------------------

    total_products = (
        Product.query.count()
    )


    total_stock = sum(
        product.stock
        for product in Product.query.all()
        if not product.is_sold
    )


    sold_products = (
        Product.query
        .filter_by(
            is_sold=True
        )
        .count()
    )


    # --------------------------------------------------------
    # LOW STOCK
    # --------------------------------------------------------

    low_stock_products = (
        Product.query
        .filter(
            Product.stock > 0,
            Product.stock <= shop_settings.low_stock_threshold,
            Product.stock > 0
        )
        .order_by(
            Product.stock.asc()
        )
        .all()
    )


    # --------------------------------------------------------
    # ORDERS
    # --------------------------------------------------------

    total_orders = (
        Order.query.count()
    )


    pending_orders = (
        Order.query
        .filter_by(
            status="pending"
        )
        .count()
    )


    # --------------------------------------------------------
    # EXPECTED REVENUE
    #
    # Pending + confirmed
    # --------------------------------------------------------

    active_orders = (
        Order.query
        .filter(
            Order.status.in_([
                "pending",
                "confirmed",
            ])
        )
        .all()
    )


    expected_revenue = sum(
        (
            Decimal(str(order.total))
            for order in active_orders
        ),
        Decimal("0")
    )


    # --------------------------------------------------------
    # COMPLETED REVENUE
    #
    # Delivered only
    # --------------------------------------------------------

    delivered_orders = (
        Order.query
        .filter_by(
            status="delivered"
        )
        .all()
    )


    completed_revenue = sum(
        (
            Decimal(str(order.total))
            for order in delivered_orders
        ),
        Decimal("0")
    )


    # --------------------------------------------------------
    # TOP 5 DEMANDED PRODUCTS
    #
    # Cancelled orders excluded.
    # Ranked by quantity.
    # --------------------------------------------------------

    valid_order_items = (
        db.session.query(
            OrderItem.product_id,
            db.func.sum(
                OrderItem.quantity
            ).label(
                "total_quantity"
            )
        )
        .join(
            Order,
            Order.id == OrderItem.order_id
        )
        .filter(
            Order.status != "cancelled"
        )
        .group_by(
            OrderItem.product_id
        )
        .order_by(
            db.func.sum(
                OrderItem.quantity
            ).desc()
        )
        .limit(5)
        .all()
    )


    top_demanded_products = []


    for product_id, total_quantity in valid_order_items:

        product = db.session.get(
            Product,
            product_id
        )

        if product is None:
            continue


        top_demanded_products.append({
            "product": product,
            "quantity": total_quantity,
        })


    # --------------------------------------------------------
    # RECENT ORDERS
    # --------------------------------------------------------

    recent_orders = (
        Order.query
        .order_by(
            Order.created_at.desc()
        )
        .limit(5)
        .all()
    )


    # --------------------------------------------------------
    # RECENT PRODUCTS
    # --------------------------------------------------------

    recent_products = (
        Product.query
        .order_by(
            Product.created_at.desc()
        )
        .limit(5)
        .all()
    )


    return render_template(
        "admin_dashboard.html",

        total_products=total_products,
        total_stock=total_stock,
        sold_products=sold_products,

        low_stock=len(
            low_stock_products
        ),

        low_stock_products=low_stock_products,

        total_orders=total_orders,
        pending_orders=pending_orders,

        expected_revenue=expected_revenue,
        completed_revenue=completed_revenue,

        top_demanded_products=(
            top_demanded_products
        ),

        recent_orders=recent_orders,
        recent_products=recent_products,
        shop_settings=shop_settings,
    )


# ============================================================
# ADMIN PRODUCTS
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/products"
)
@login_required
def admin_products():

    products = (
        Product.query
        .order_by(
            Product.created_at.desc()
        )
        .all()
    )

    return render_template(
        "admin_products.html",
        products=products
    )


# ============================================================
# ADMIN ADD PRODUCT
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/products/add",
    methods=["GET", "POST"]
)
@login_required
def admin_add_product():

    if request.method == "GET":

        return render_template(
            "admin_add_product.html",
            categories=PRODUCT_CATEGORIES
        )


    # --------------------------------------------------------
    # BASIC DATA
    # --------------------------------------------------------

    name = request.form.get(
        "name",
        ""
    ).strip()

    category = request.form.get(
        "category",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    price_raw = request.form.get(
        "price",
        ""
    ).strip()

    stock_raw = request.form.get(
        "stock",
        ""
    ).strip()

    # Legacy field retained only for compatibility with the old
    # schema. Stock is now the source of truth for availability.
    is_sold = False

    image_files = request.files.getlist(
        "images"
    )

    errors = []


    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    if not name:

        errors.append(
            "Product name is required."
        )

    elif len(name) > 150:

        errors.append(
            "Product name is too long."
        )


    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    if category and category not in PRODUCT_CATEGORIES:

        errors.append(
            "Please choose a valid category."
        )


    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    if len(description) > 5000:

        errors.append(
            "Description is too long."
        )


    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price = None

    try:

        price = Decimal(
            price_raw
        )

        if not price.is_finite():

            errors.append(
                "Please provide a valid price."
            )

        elif price < 0:

            errors.append(
                "Price cannot be negative."
            )

        elif price.as_tuple().exponent < -2:

            errors.append(
                "Price can have at most "
                "two decimal places."
            )

    except (
        InvalidOperation,
        ValueError
    ):

        errors.append(
            "Please provide a valid price."
        )


    # --------------------------------------------------------
    # STOCK
    # --------------------------------------------------------

    stock = None

    try:

        stock = int(
            stock_raw
        )

        if stock < 0:

            errors.append(
                "Stock cannot be negative."
            )

    except (
        ValueError,
        TypeError
    ):

        errors.append(
            "Please provide a valid stock quantity."
        )


    # --------------------------------------------------------
    # IMAGE COUNT
    # --------------------------------------------------------

    if len(image_files) > MAX_PRODUCT_IMAGES:

        errors.append(
            f"You can upload a maximum of "
            f"{MAX_PRODUCT_IMAGES} images."
        )


    # --------------------------------------------------------
    # IMAGE VALIDATION
    # --------------------------------------------------------

    valid_image_files = []

    for image_file in image_files:

        if (
            not image_file
            or not image_file.filename
        ):

            continue


        safe_name = secure_filename(
            image_file.filename
        )

        extension = Path(
            safe_name
        ).suffix.lower()


        if extension not in ALLOWED_IMAGE_EXTENSIONS:

            errors.append(
                f"Unsupported image type: "
                f"{image_file.filename}"
            )

            continue


        valid_image_files.append(
            (
                image_file,
                extension,
            )
        )


    # --------------------------------------------------------
    # VALIDATION FAILURE
    # --------------------------------------------------------

    if errors:

        for error in errors:

            flash(
                error,
                "error"
            )

        return render_template(
            "admin_add_product.html",
            categories=PRODUCT_CATEGORIES
        )


    # --------------------------------------------------------
    # CREATE PRODUCT
    # --------------------------------------------------------

    product = Product(
        name=name,
        category=category or None,
        description=(
            description
            if description
            else None
        ),
        price=price,
        regular_price=price,
        stock=stock,
        offer_active=False,
        offer_ends_at=None,
        is_sold=False,
    )

    db.session.add(
        product
    )

    db.session.flush()


    # --------------------------------------------------------
    # SAVE IMAGES
    # --------------------------------------------------------

    for image_file, extension in valid_image_files:

        filename = (
            f"{uuid4().hex}"
            f"{extension}"
        )

        file_path = (
            UPLOAD_FOLDER
            / filename
        )

        image_file.save(
            file_path
        )


        product_image = ProductImage(
            filename=filename,
            product=product,
        )

        db.session.add(
            product_image
        )


    # --------------------------------------------------------
    # COMMIT
    # --------------------------------------------------------

    try:

        db.session.commit()

    except Exception:

        db.session.rollback()

        flash(
            "Could not create the product.",
            "error"
        )

        return render_template(
            "admin_add_product.html",
            categories=PRODUCT_CATEGORIES
        )


    flash(
        "Product created successfully.",
        "success"
    )


    return redirect(
        url_for(
            "admin_products"
        )
    )

# ============================================================
# ADMIN EDIT PRODUCT
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/products/<int:product_id>/edit",
    methods=["GET", "POST"]
)
@login_required
def admin_edit_product(product_id):

    product = db.get_or_404(
        Product,
        product_id
    )

    refresh_offer(product)

    shop_settings = get_shop_settings()

    # --------------------------------------------------------
    # FORM VALUES
    #
    # `values` is what the template renders in the inputs.
    # On GET it comes from the database, on a failed POST it
    # comes back from the submitted form so the admin does not
    # lose what they typed.
    # --------------------------------------------------------

    if request.method == "GET":

        values = {
            "name": product.name,
            "category": product.category or "",
            "description": product.description or "",
            # The "Price" field always represents the regular
            # (non-discounted) price. When no offer is active,
            # regular_price and price are the same value.
            "price": product.regular_price,
            "stock": product.stock,
            "offer_active": product.offer_active,
            "discount_type": "percentage",
            "discount_value": "",
            "offer_duration_days": (
                shop_settings.default_offer_duration_days
            ),
        }

        return render_template(
            "admin_edit_product.html",
            product=product,
            values=values,
            categories=PRODUCT_CATEGORIES,
            shop_settings=shop_settings,
        )

    # --------------------------------------------------------
    # READ FORM DATA
    # --------------------------------------------------------

    name = request.form.get(
        "name",
        ""
    ).strip()

    category = request.form.get(
        "category",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    price_raw = request.form.get(
        "price",
        ""
    ).strip()

    stock_raw = request.form.get(
        "stock",
        ""
    ).strip()

    # --------------------------------------------------------
    # PROMOTION (SOLDE) FIELDS
    #
    # Nothing here is hard-coded: the discount type, discount
    # amount and duration all come from the form, and the
    # duration defaults to the shop-wide setting only when the
    # admin leaves it blank.
    # --------------------------------------------------------

    offer_active_input = (
        request.form.get("offer_active") == "on"
    )

    discount_type = request.form.get(
        "discount_type",
        "percentage"
    ).strip()

    discount_value_raw = request.form.get(
        "discount_value",
        ""
    ).strip()

    offer_duration_raw = request.form.get(
        "offer_duration_days",
        ""
    ).strip()

    values = {
        "name": name,
        "category": category,
        "description": description,
        "price": price_raw,
        "stock": stock_raw,
        "offer_active": offer_active_input,
        "discount_type": discount_type or "percentage",
        "discount_value": discount_value_raw,
        "offer_duration_days": (
            offer_duration_raw
            or shop_settings.default_offer_duration_days
        ),
    }

    errors = []

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    if not name:

        errors.append(
            "Product name is required."
        )

    elif len(name) > 150:

        errors.append(
            "Product name is too long."
        )

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    if category and category not in PRODUCT_CATEGORIES:

        errors.append(
            "Please choose a valid category."
        )

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    if len(description) > 5000:

        errors.append(
            "Description is too long."
        )

    # --------------------------------------------------------
    # PRICE
    #
    # This is always the regular (non-discounted) price.
    # --------------------------------------------------------

    price = None

    try:

        price = Decimal(price_raw)

        if not price.is_finite():

            errors.append(
                "Please provide a valid price."
            )

        elif price < 0:

            errors.append(
                "Price cannot be negative."
            )

        elif price.as_tuple().exponent < -2:

            errors.append(
                "Price can have at most two decimal places."
            )

    except (InvalidOperation, ValueError):

        errors.append(
            "Please provide a valid price."
        )

    # --------------------------------------------------------
    # PROMOTION VALIDATION
    #
    # Only validated/applied when the admin has switched the
    # promotion on. Turning it off (or leaving it off) simply
    # keeps the product at its regular price.
    # --------------------------------------------------------

    offer_price = None
    offer_duration_days = None

    if offer_active_input:

        if discount_type not in OFFER_DISCOUNT_TYPES:

            errors.append(
                "Please choose a valid discount type."
            )

        try:

            offer_duration_days = int(
                offer_duration_raw
                or shop_settings.default_offer_duration_days
            )

            if not 1 <= offer_duration_days <= 365:

                errors.append(
                    "Promotion duration must be between "
                    "1 and 365 days."
                )

        except (ValueError, TypeError):

            errors.append(
                "Please provide a valid promotion duration."
            )

        discount_value = None

        try:

            discount_value = Decimal(discount_value_raw)

            if not discount_value.is_finite():

                errors.append(
                    "Please provide a valid discount amount."
                )

        except (InvalidOperation, ValueError):

            errors.append(
                "Please provide a valid discount amount."
            )

        # Only compute the offer price once the regular price
        # and the discount amount are both individually valid.
        if (
            price is not None
            and price.is_finite()
            and price >= 0
            and discount_value is not None
            and discount_value.is_finite()
        ):

            if discount_type == "percentage":

                if not 0 < discount_value < 100:

                    errors.append(
                        "Discount percentage must be "
                        "between 1 and 99."
                    )

                else:

                    raw_offer_price = (
                        price
                        * (Decimal("100") - discount_value)
                        / Decimal("100")
                    )

                    offer_price = raw_offer_price.quantize(
                        Decimal("0.01")
                    )

            elif discount_type == "fixed_price":

                if not 0 <= discount_value < price:

                    errors.append(
                        "The sale price must be lower than "
                        "the regular price."
                    )

                else:

                    offer_price = discount_value.quantize(
                        Decimal("0.01")
                    )

    # --------------------------------------------------------
    # STOCK
    # --------------------------------------------------------

    stock = None

    try:

        stock = int(stock_raw)

        if stock < 0:

            errors.append(
                "Stock cannot be negative."
            )

    except (ValueError, TypeError):

        errors.append(
            "Please provide a valid stock quantity."
        )

    # --------------------------------------------------------
    # IMAGES
    # --------------------------------------------------------

    image_files = request.files.getlist("images")

    new_image_files = [
        image_file
        for image_file in image_files
        if image_file
        and image_file.filename
    ]

    current_image_count = len(product.images)

    if (
        current_image_count
        + len(new_image_files)
        > MAX_PRODUCT_IMAGES
    ):

        errors.append(
            f"A product can have a maximum of "
            f"{MAX_PRODUCT_IMAGES} images total."
        )

    valid_image_files = []

    for image_file in new_image_files:

        safe_name = secure_filename(
            image_file.filename
        )

        extension = Path(
            safe_name
        ).suffix.lower()

        if extension not in ALLOWED_IMAGE_EXTENSIONS:

            errors.append(
                f"Unsupported image type: "
                f"{image_file.filename}"
            )

            continue

        valid_image_files.append(
            (
                image_file,
                extension
            )
        )

    # --------------------------------------------------------
    # VALIDATION FAILURE
    # --------------------------------------------------------

    if errors:

        for error in errors:

            flash(
                error,
                "error"
            )

        return render_template(
            "admin_edit_product.html",
            product=product,
            values=values,
            categories=PRODUCT_CATEGORIES,
            shop_settings=shop_settings,
        )

    # --------------------------------------------------------
    # UPDATE PRODUCT
    # --------------------------------------------------------

    product.name = name

    product.category = category or None

    product.description = (
        description
        if description
        else None
    )

    product.stock = stock

    # Availability is based on stock. Keep the old column false
    # because it is no longer used to represent sold-out products.
    product.is_sold = False

    # --------------------------------------------------------
    # PROMOTION (SOLDE)
    #
    # `price` here is always the regular price the admin just
    # entered. When a promotion is active, the actual selling
    # price is the computed offer_price and offer_ends_at is
    # pushed out by the chosen duration; otherwise the product
    # simply sells at its regular price.
    # --------------------------------------------------------

    product.regular_price = price

    if offer_active_input:

        product.offer_active = True
        product.price = offer_price
        product.offer_ends_at = (
            datetime.utcnow()
            + timedelta(days=offer_duration_days)
        )

    else:

        product.offer_active = False
        product.offer_ends_at = None
        product.price = price

    # --------------------------------------------------------
    # SAVE NEW IMAGES
    #
    # Files written to disk are tracked so they can be removed
    # again if anything later in the request fails. Otherwise a
    # failed update leaves orphan files in the upload folder.
    # --------------------------------------------------------

    saved_paths = []

    def discard_saved_images():

        for saved_path in saved_paths:

            try:
                saved_path.unlink(missing_ok=True)

            except OSError:
                pass

    for image_file, extension in valid_image_files:

        filename = (
            f"{uuid4().hex}{extension}"
        )

        file_path = (
            UPLOAD_FOLDER / filename
        )

        try:

            image_file.save(file_path)

            saved_paths.append(file_path)

        except Exception:

            db.session.rollback()

            discard_saved_images()

            flash(
                "Could not save one of the images.",
                "error"
            )

            return render_template(
                "admin_edit_product.html",
                product=product,
                values=values,
                categories=PRODUCT_CATEGORIES,
                shop_settings=shop_settings,
            )

        product_image = ProductImage(
            filename=filename,
            product=product
        )

        db.session.add(
            product_image
        )

    # --------------------------------------------------------
    # COMMIT CHANGES
    # --------------------------------------------------------

    try:

        db.session.commit()

    except Exception as exc:

        db.session.rollback()

        discard_saved_images()

        app.logger.exception(
            "PRODUCT UPDATE ERROR: %r",
            exc
        )

        flash(
            "Could not update the product.",
            "error"
        )

        return render_template(
            "admin_edit_product.html",
            product=product,
            values=values,
            categories=PRODUCT_CATEGORIES,
            shop_settings=shop_settings,
        )

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    flash(
        "Product updated successfully.",
        "success"
    )

    return redirect(
        url_for(
            "admin_products"
        )
    )

# ============================================================
# ADMIN DELETE PRODUCT IMAGE
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/products/<int:product_id>/images/<int:image_id>/delete",
    methods=["POST"]
)
@login_required
def admin_delete_product_image(
    product_id,
    image_id
):

    product = db.get_or_404(
        Product,
        product_id
    )

    image = db.get_or_404(
        ProductImage,
        image_id
    )


    # Make sure the image actually belongs
    # to this product.
    if image.product_id != product.id:

        flash(
            "Invalid product image.",
            "error"
        )

        return redirect(
            url_for(
                "admin_edit_product",
                product_id=product.id
            )
        )


    image_path = (
        UPLOAD_FOLDER
        / image.filename
    )


    try:

        db.session.delete(
            image
        )

        db.session.commit()

    except Exception:

        db.session.rollback()

        flash(
            "Could not delete the image.",
            "error"
        )

        return redirect(
            url_for(
                "admin_edit_product",
                product_id=product.id
            )
        )


    # Delete the physical file after the DB
    # operation has succeeded.
    try:

        if image_path.is_file():

            image_path.unlink()

    except OSError:

        # Database deletion already succeeded.
        # The orphaned physical file can be
        # cleaned later.
        pass


    flash(
        "Image deleted successfully.",
        "success"
    )


    return redirect(
        url_for(
            "admin_edit_product",
            product_id=product.id
        )
    )


# ============================================================
# ADMIN DELETE PRODUCT
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/products/<int:product_id>/delete",
    methods=["POST"]
)
@login_required
def admin_delete_product(product_id):

    product = db.get_or_404(
        Product,
        product_id
    )

    # A product that already appears in past orders can't be
    # removed without breaking that order history — guide the
    # admin toward marking it unavailable instead.
    if product.order_items:

        flash(
            f"\"{product.name}\" is part of existing orders and "
            "can't be deleted. Set its stock to 0 to hide it "
            "from the shop instead.",
            "error"
        )

        return redirect(
            url_for("admin_products")
        )

    image_paths = [
        UPLOAD_FOLDER / image.filename
        for image in product.images
    ]

    try:

        db.session.delete(product)
        db.session.commit()

    except Exception:

        db.session.rollback()

        flash(
            "Could not delete the product.",
            "error"
        )

        return redirect(
            url_for("admin_products")
        )

    for image_path in image_paths:

        try:

            if image_path.is_file():
                image_path.unlink()

        except OSError:
            # Database deletion already succeeded; an orphaned
            # physical file can be cleaned up later.
            pass

    flash(
        f"\"{product.name}\" was deleted.",
        "success"
    )

    return redirect(
        url_for("admin_products")
    )


# ============================================================
# ADMIN SETTINGS
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/settings",
    methods=["GET", "POST"]
)
@login_required
def admin_settings():

    settings = get_shop_settings()

    if request.method == "GET":
        return render_template(
            "admin_settings.html",
            settings=settings
        )

    shop_name = request.form.get("shop_name", "").strip()
    shop_description = request.form.get("shop_description", "").strip()
    shop_phone = request.form.get("shop_phone", "").strip()
    shop_email = request.form.get("shop_email", "").strip()
    shop_address = request.form.get("shop_address", "").strip()

    delivery_enabled = request.form.get("delivery_enabled") == "on"
    allow_orders = request.form.get("allow_orders") == "on"

    delivery_fee_raw = request.form.get("delivery_fee", "").strip()
    free_delivery_raw = request.form.get(
        "free_delivery_threshold",
        ""
    ).strip()
    offer_duration_raw = request.form.get(
        "default_offer_duration_days",
        ""
    ).strip()
    low_stock_raw = request.form.get(
        "low_stock_threshold",
        ""
    ).strip()

    errors = []

    if not shop_name:
        errors.append("Shop name is required.")
    elif len(shop_name) > 150:
        errors.append("Shop name is too long.")

    if len(shop_description) > 5000:
        errors.append("Shop description is too long.")

    if len(shop_phone) > 30:
        errors.append("Shop phone number is too long.")

    if len(shop_email) > 254:
        errors.append("Shop email is too long.")

    if len(shop_address) > 1000:
        errors.append("Shop address is too long.")

    try:
        delivery_fee = Decimal(delivery_fee_raw or "0")
        if not delivery_fee.is_finite() or delivery_fee < 0:
            errors.append("Delivery fee must be zero or greater.")
        elif delivery_fee.as_tuple().exponent < -2:
            errors.append("Delivery fee can have at most two decimal places.")
    except InvalidOperation:
        delivery_fee = Decimal("0")
        errors.append("Please provide a valid delivery fee.")

    free_delivery_threshold = None
    if free_delivery_raw:
        try:
            free_delivery_threshold = Decimal(free_delivery_raw)
            if not free_delivery_threshold.is_finite() or free_delivery_threshold < 0:
                errors.append(
                    "Free delivery threshold must be zero or greater."
                )
            elif free_delivery_threshold.as_tuple().exponent < -2:
                errors.append(
                    "Free delivery threshold can have at most two decimal places."
                )
        except InvalidOperation:
            errors.append("Please provide a valid free delivery threshold.")

    try:
        default_offer_duration_days = int(offer_duration_raw)
        if not 1 <= default_offer_duration_days <= 365:
            errors.append("Offer duration must be between 1 and 365 days.")
    except ValueError:
        default_offer_duration_days = settings.default_offer_duration_days
        errors.append("Please provide a valid offer duration.")

    try:
        low_stock_threshold = int(low_stock_raw)
        if not 0 <= low_stock_threshold <= 1000000:
            errors.append("Low-stock threshold is invalid.")
    except ValueError:
        low_stock_threshold = settings.low_stock_threshold
        errors.append("Please provide a valid low-stock threshold.")

    if errors:
        for error in errors:
            flash(error, "error")
        return render_template(
            "admin_settings.html",
            settings=settings
        )

    settings.shop_name = shop_name
    settings.shop_description = shop_description or None
    settings.shop_phone = shop_phone or None
    settings.shop_email = shop_email or None
    settings.shop_address = shop_address or None

    settings.delivery_enabled = delivery_enabled
    settings.delivery_fee = delivery_fee
    settings.free_delivery_threshold = free_delivery_threshold

    settings.allow_orders = allow_orders
    settings.default_offer_duration_days = default_offer_duration_days
    settings.low_stock_threshold = low_stock_threshold
    settings.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Could not save shop settings.", "error")
        return render_template(
            "admin_settings.html",
            settings=settings
        )

    flash("Settings saved successfully.", "success")

    return redirect(
        url_for("admin_settings")
    )


# ============================================================
# ADMIN DELIVERY FEES BY PROVINCE
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/settings/delivery-fees",
    methods=["GET", "POST"]
)
@login_required
def admin_delivery_fees():

    ensure_wilaya_fees_seeded()

    if request.method == "POST":

        rows = WilayaDeliveryFee.query.all()

        errors = []

        for row in rows:

            raw_value = request.form.get(
                f"fee_{row.wilaya_code}",
                ""
            ).strip()

            try:

                fee = Decimal(raw_value)

                if not fee.is_finite() or fee < 0:
                    raise InvalidOperation(
                        "Delivery fee must be zero or greater."
                    )

                if fee.as_tuple().exponent < -2:
                    raise InvalidOperation(
                        "Delivery fee can have at most "
                        "two decimal places."
                    )

            except InvalidOperation:

                errors.append(
                    f"Invalid fee for {row.wilaya_name}."
                )

                continue

            row.fee = fee

        if errors:

            db.session.rollback()

            for error in errors:
                flash(error, "error")

        else:

            db.session.commit()

            flash(
                "Delivery fees updated.",
                "success"
            )

        return redirect(
            url_for("admin_delivery_fees")
        )

    wilaya_fees = (
        WilayaDeliveryFee.query
        .order_by(WilayaDeliveryFee.wilaya_code)
        .all()
    )

    return render_template(
        "admin_delivery_fees.html",
        wilaya_fees=wilaya_fees
    )


@app.route(
    f"/{ADMIN_PATH}/settings/password",
    methods=["POST"]
)
@login_required
def admin_change_password():

    current_password = request.form.get(
        "current_password",
        ""
    )

    new_password = request.form.get(
        "new_password",
        ""
    )

    confirm_password = request.form.get(
        "confirm_password",
        ""
    )

    if not check_password_hash(
        current_user.password_hash,
        current_password
    ):
        flash("Current password is incorrect.", "error")
        return redirect(url_for("admin_settings"))

    if len(new_password) < 8:
        flash("New password must contain at least 8 characters.", "error")
        return redirect(url_for("admin_settings"))

    if new_password != confirm_password:
        flash("The new passwords do not match.", "error")
        return redirect(url_for("admin_settings"))

    current_user.password_hash = generate_password_hash(
        new_password
    )

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Could not change the password.", "error")
        return redirect(url_for("admin_settings"))

    flash("Password changed successfully.", "success")

    return redirect(
        url_for("admin_settings")
    )


# ============================================================
# ADMIN ORDERS
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/orders"
)
@login_required
def admin_orders():

    orders = (
        Order.query
        .order_by(
            Order.created_at.desc()
        )
        .all()
    )

    return render_template(
        "admin_orders.html",
        orders=orders
    )


# ============================================================
# ADMIN ORDER DETAILS
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/orders/<int:order_id>"
)
@login_required
def admin_order_detail(order_id):

    order = db.get_or_404(
        Order,
        order_id
    )

    return render_template(
        "admin_order_detail.html",
        order=order
    )


# ============================================================
# ADMIN INVOICE DOWNLOAD
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/orders/<int:order_id>/invoice"
)
@login_required
def admin_order_invoice(order_id):

    order = db.get_or_404(
        Order,
        order_id
    )

    shop_settings = get_shop_settings()

    pdf_buffer = build_invoice_pdf(
        order,
        shop_settings
    )

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"invoice-{order.id}.pdf",
    )


# ============================================================
# ADMIN UPDATE ORDER STATUS
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/orders/<int:order_id>/status",
    methods=["POST"]
)
@login_required
def admin_update_order_status(order_id):

    order = db.get_or_404(
        Order,
        order_id
    )


    new_status = request.form.get(
        "status",
        ""
    ).strip().lower()


    allowed_statuses = {
        "pending",
        "confirmed",
        "delivered",
        "cancelled",
    }


    if new_status not in allowed_statuses:

        flash(
            "Invalid order status.",
            "error"
        )

        return redirect(
            url_for(
                "admin_order_detail",
                order_id=order.id
            )
        )


    order.status = new_status


    try:

        db.session.commit()

        flash(
            "Order status updated successfully.",
            "success"
        )

    except Exception:

        db.session.rollback()

        flash(
            "Could not update the order status.",
            "error"
        )


    return redirect(
        url_for(
            "admin_order_detail",
            order_id=order.id
        )
    )


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.route(
    f"/{ADMIN_PATH}/logout"
)
@login_required
def admin_logout():

    logout_user()

    flash(
        "You have been signed out.",
        "success"
    )

    return redirect(
        url_for(
            "admin_entry"
        )
    )


# ============================================================
# CREATE FIRST ADMIN (CLI)
#
# Usage:  flask create-admin
# Reads ADMIN_USERNAME and ADMIN_PASSWORD from the environment.
# Safe to run on every deploy: it does nothing if an admin
# with that username already exists.
# ============================================================

@app.cli.command("create-admin")
def create_admin_command():
    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")

    if not username or not password:
        print("create-admin: ADMIN_USERNAME / ADMIN_PASSWORD not set, skipping.")
        return

    if len(password) < 8:
        print("create-admin: ADMIN_PASSWORD must have at least 8 characters.")
        return

    existing = Admin.query.filter_by(username=username).first()

    if existing is not None:
        print(f"create-admin: admin '{username}' already exists, nothing to do.")
        return

    db.session.add(
        Admin(
            username=username,
            password_hash=generate_password_hash(password),
        )
    )
    db.session.commit()
    print(f"create-admin: admin '{username}' created.")


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=DEBUG_MODE
    )
