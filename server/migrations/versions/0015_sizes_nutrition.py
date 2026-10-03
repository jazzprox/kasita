"""pack sizes, nutrition, imported recipes

Products get a pack size (g / ml / pcs) for prices per kg / l / piece; the barcode
cache keeps Open Food Facts' Nutri-Score, NOVA group and per-100 g values; recipes remember the
page they were imported from and each ingredient's amount as written ("2 cups").

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('barcode_cache', schema=None) as batch_op:
        batch_op.add_column(sa.Column('nutriscore', sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column('nova', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('nutrients', sa.JSON(), nullable=True))
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('size_amount', sa.Numeric(precision=12, scale=3), nullable=True))
        batch_op.add_column(sa.Column('size_unit', sa.String(length=8), nullable=True))
    with op.batch_alter_table('recipes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_url', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('servings', sa.String(length=40), nullable=True))
    with op.batch_alter_table('recipe_ingredients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('amount', sa.String(length=60), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('recipe_ingredients', schema=None) as batch_op:
        batch_op.drop_column('amount')
    with op.batch_alter_table('recipes', schema=None) as batch_op:
        batch_op.drop_column('servings')
        batch_op.drop_column('source_url')
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('size_unit')
        batch_op.drop_column('size_amount')
    with op.batch_alter_table('barcode_cache', schema=None) as batch_op:
        batch_op.drop_column('nutrients')
        batch_op.drop_column('nova')
        batch_op.drop_column('nutriscore')
