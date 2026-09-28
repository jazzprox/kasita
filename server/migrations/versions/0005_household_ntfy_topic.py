"""each household has its own ntfy topic for digests (none = no digests)

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('households', sa.Column('ntfy_topic', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('households', 'ntfy_topic')
