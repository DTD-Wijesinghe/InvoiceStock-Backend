"""Add document creator attribution for quotation workflow."""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'


def upgrade():
    op.add_column('documents', sa.Column('created_by_name', sa.String(120), nullable=False, server_default=''))


def downgrade():
    raise RuntimeError('Restore a reviewed backup instead of deleting document attribution history.')
