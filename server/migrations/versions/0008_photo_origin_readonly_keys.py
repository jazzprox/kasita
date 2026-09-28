"""remember a product's database photo; read-only API keys (the home-screen widget)

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products', sa.Column('db_image_url', sa.Text(), nullable=True))
    op.add_column('api_keys', sa.Column('read_only', sa.Boolean(), nullable=False, server_default=sa.false()))
    # pictures that are links to a product database (not photos taken in Kasita) are database photos
    op.execute("UPDATE products SET db_image_url = image_url "
               "WHERE image_url IS NOT NULL AND image_url NOT LIKE '%/api/product-images/%'")


def downgrade() -> None:
    op.drop_column('api_keys', 'read_only')
    op.drop_column('products', 'db_image_url')
