"""Add owner-configurable stock range targets."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'


def upgrade():
    op.add_column('products', sa.Column('max_stock_level', sa.Numeric(14, 3), nullable=True))


def downgrade():
    op.drop_column('products', 'max_stock_level')
