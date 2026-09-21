"""Add external object-storage metadata while keeping safe database fallback."""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'


def upgrade():
    op.add_column('businesses', sa.Column('logo_storage_provider', sa.String(20), nullable=False, server_default=''))
    op.add_column('businesses', sa.Column('logo_storage_key', sa.String(300), nullable=False, server_default=''))
    op.alter_column('bank_transfers', 'file_data', existing_type=sa.LargeBinary(), nullable=True)
    op.add_column('bank_transfers', sa.Column('storage_provider', sa.String(20), nullable=False, server_default=''))
    op.add_column('bank_transfers', sa.Column('storage_key', sa.String(300), nullable=False, server_default=''))
    op.add_column('backup_records', sa.Column('storage_provider', sa.String(20), nullable=False, server_default=''))
    op.add_column('backup_records', sa.Column('storage_key', sa.String(300), nullable=False, server_default=''))
    op.add_column('backup_records', sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    raise RuntimeError('Restore a reviewed backup instead of deleting object-storage metadata.')
