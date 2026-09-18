"""Add company-admin roles, employee permissions, and company branding."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'

def upgrade():
    op.add_column('users', sa.Column('permissions', sa.JSON(), nullable=True))
    op.add_column('businesses', sa.Column('logo_data', sa.LargeBinary(), nullable=True))
    op.add_column('businesses', sa.Column('logo_content_type', sa.String(80), nullable=False, server_default=''))

def downgrade():
    raise RuntimeError('Restore a reviewed backup instead of deleting company permissions or branding.')
