"""add product offers

Revision ID: 74801a08360d
Revises:
Create Date: 2026-09-13 21:22:06.801112

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "74801a08360d"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():

    # --------------------------------------------------------
    # STEP 1
    # Add the new columns temporarily as nullable.
    #
    # This is necessary because the database already contains
    # existing products.
    # --------------------------------------------------------

    with op.batch_alter_table(
        "products",
        schema=None
    ) as batch_op:

        batch_op.add_column(
            sa.Column(
                "regular_price",
                sa.Numeric(
                    precision=10,
                    scale=2
                ),
                nullable=True
            )
        )

        batch_op.add_column(
            sa.Column(
                "offer_active",
                sa.Boolean(),
                nullable=True
            )
        )

        batch_op.add_column(
            sa.Column(
                "offer_ends_at",
                sa.DateTime(),
                nullable=True
            )
        )


    # --------------------------------------------------------
    # STEP 2
    # Populate the new columns for existing products.
    #
    # Existing price becomes the original/regular price.
    # Existing products do not start with an offer.
    # --------------------------------------------------------

    op.execute(
        sa.text(
            """
            UPDATE products
            SET
                regular_price = price,
                offer_active = 0
            WHERE
                regular_price IS NULL
                OR offer_active IS NULL
            """
        )
    )


    # --------------------------------------------------------
    # STEP 3
    # Now that every existing product has values,
    # make the required columns non-nullable.
    # --------------------------------------------------------

    with op.batch_alter_table(
        "products",
        schema=None
    ) as batch_op:

        batch_op.alter_column(
            "regular_price",
            existing_type=sa.Numeric(
                precision=10,
                scale=2
            ),
            nullable=False
        )

        batch_op.alter_column(
            "offer_active",
            existing_type=sa.Boolean(),
            nullable=False
        )


def downgrade():

    with op.batch_alter_table(
        "products",
        schema=None
    ) as batch_op:

        batch_op.drop_column(
            "offer_ends_at"
        )

        batch_op.drop_column(
            "offer_active"
        )

        batch_op.drop_column(
            "regular_price"
        )