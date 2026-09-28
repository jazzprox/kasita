"""monthly grocery budget per household, and which budget alert was sent last

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('households', sa.Column('grocery_budget', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('households', sa.Column('budget_alerted', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('households', 'budget_alerted')
    op.drop_column('households', 'grocery_budget')
