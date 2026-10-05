"""add shop settings and delivery fee

Revision ID: 7f3d9a1b2c44
Revises: 74801a08360d
Create Date: 2026-09-19 16:20:00

"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f3d9a1b2c44"
down_revision = "74801a08360d"
branch_labels = None
depends_on = None


def upgrade():
    # --------------------------------------------------------
    # Add delivery fee to existing orders as nullable first,
    # populate historical orders with zero, then make it
    # non-nullable.
    # --------------------------------------------------------
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "delivery_fee",
                sa.Numeric(precision=10, scale=2),
                nullable=True,
            )
        )

    op.execute(
        sa.text(
            "UPDATE orders SET delivery_fee = 0 WHERE delivery_fee IS NULL"
        )
    )

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.alter_column(
            "delivery_fee",
            existing_type=sa.Numeric(precision=10, scale=2),
            nullable=False,
        )

    # --------------------------------------------------------
    # Create singleton shop settings table.
    # --------------------------------------------------------
    op.create_table(
        "shop_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_name", sa.String(length=150), nullable=False),
        sa.Column("shop_description", sa.Text(), nullable=True),
        sa.Column("shop_phone", sa.String(length=30), nullable=True),
        sa.Column("shop_email", sa.String(length=254), nullable=True),
        sa.Column("shop_address", sa.Text(), nullable=True),
        sa.Column("delivery_enabled", sa.Boolean(), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "free_delivery_threshold",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
        ),
        sa.Column("allow_orders", sa.Boolean(), nullable=False),
        sa.Column("default_offer_duration_days", sa.Integer(), nullable=False),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Seed the singleton configuration row.
    shop_settings_table = sa.table(
        "shop_settings",
        sa.column("id", sa.Integer()),
        sa.column("shop_name", sa.String()),
        sa.column("shop_description", sa.Text()),
        sa.column("shop_phone", sa.String()),
        sa.column("shop_email", sa.String()),
        sa.column("shop_address", sa.Text()),
        sa.column("delivery_enabled", sa.Boolean()),
        sa.column("delivery_fee", sa.Numeric()),
        sa.column("free_delivery_threshold", sa.Numeric()),
        sa.column("allow_orders", sa.Boolean()),
        sa.column("default_offer_duration_days", sa.Integer()),
        sa.column("low_stock_threshold", sa.Integer()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )

    now = datetime.utcnow()

    op.bulk_insert(
        shop_settings_table,
        [
            {
                "id": 1,
                "shop_name": "My Shop",
                "shop_description": None,
                "shop_phone": None,
                "shop_email": None,
                "shop_address": None,
                "delivery_enabled": True,
                "delivery_fee": 0,
                "free_delivery_threshold": None,
                "allow_orders": True,
                "default_offer_duration_days": 7,
                "low_stock_threshold": 5,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade():
    op.drop_table("shop_settings")

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_column("delivery_fee")
