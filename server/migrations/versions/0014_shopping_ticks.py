"""shopping ticks

Every item ticked off the shopping list, with when and (once known) in which store: the
list learns the order you walk each store in.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'shopping_ticks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('household_id', sa.String(length=36), nullable=False),
        sa.Column('item_id', sa.String(length=36), nullable=False),
        sa.Column('product_id', sa.String(length=36), nullable=True),
        sa.Column('name_key', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=80), nullable=True),
        sa.Column('ticked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('local_day', sa.Date(), nullable=False),
        sa.Column('store_id', sa.String(length=36), nullable=True),
        sa.Column('store_source', sa.String(length=8), nullable=True),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('shopping_ticks', schema=None) as batch_op:
        batch_op.create_index('ix_ticks_household_day', ['household_id', 'local_day'], unique=False)
        batch_op.create_index(batch_op.f('ix_shopping_ticks_item_id'), ['item_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('shopping_ticks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_shopping_ticks_item_id'))
        batch_op.drop_index('ix_ticks_household_day')
    op.drop_table('shopping_ticks')
