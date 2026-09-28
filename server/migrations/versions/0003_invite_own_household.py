"""invites can create a household of the invitee's own

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('invites', sa.Column('own_household', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('invites', 'own_household')
