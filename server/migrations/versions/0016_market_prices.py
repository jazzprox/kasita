"""market prices

Prices a shop publishes online (Mangusa Hypermarket's web shop), matched to products by barcode,
with a history of changes.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'market_prices',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('retailer', sa.String(length=24), nullable=False),
        sa.Column('sku', sa.String(length=24), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('regular_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('on_sale', sa.Boolean(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('in_stock', sa.Boolean(), nullable=False),
        sa.Column('pack_note', sa.String(length=60), nullable=True),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=160), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('retailer', 'sku'),
    )
    with op.batch_alter_table('market_prices', schema=None) as batch_op:
        batch_op.create_index('ix_market_sku', ['sku'], unique=False)
    op.create_table(
        'market_price_changes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('retailer', sa.String(length=24), nullable=False),
        sa.Column('sku', sa.String(length=24), nullable=False),
        sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('on_sale', sa.Boolean(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('market_price_changes', schema=None) as batch_op:
        batch_op.create_index('ix_market_change_sku', ['retailer', 'sku', 'at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('market_price_changes', schema=None) as batch_op:
        batch_op.drop_index('ix_market_change_sku')
    op.drop_table('market_price_changes')
    with op.batch_alter_table('market_prices', schema=None) as batch_op:
        batch_op.drop_index('ix_market_sku')
    op.drop_table('market_prices')
