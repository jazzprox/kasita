"""products keep N days once opened; batches remember when they were frozen

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products', sa.Column('open_days', sa.Integer(), nullable=True))
    op.add_column('stock_entries', sa.Column('frozen_at', sa.Date(), nullable=True))
    # batches already sitting in a freezer: count from when they were bought
    op.execute("""UPDATE stock_entries SET frozen_at = purchased_at
                  WHERE location_id IN (SELECT id FROM locations WHERE is_freezer)""")


def downgrade() -> None:
    op.drop_column('stock_entries', 'frozen_at')
    op.drop_column('products', 'open_days')
