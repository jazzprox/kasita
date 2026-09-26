"""receipt store name, line names and how a line was matched

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('receipts', sa.Column('store_name', sa.String(length=120), nullable=True))
    op.add_column('receipt_lines', sa.Column('name', sa.String(length=255), nullable=True))
    op.add_column('receipt_lines', sa.Column('matched_by', sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column('receipt_lines', 'matched_by')
    op.drop_column('receipt_lines', 'name')
    op.drop_column('receipts', 'store_name')
