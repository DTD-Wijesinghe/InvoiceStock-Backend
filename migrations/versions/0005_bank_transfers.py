"""Manual bank-transfer subscription payments and receipt review."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'


def upgrade():
    op.create_table(
        'bank_transfers',
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False, server_default='3500'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='LKR'),
        sa.Column('transfer_reference', sa.String(120), nullable=False, server_default=''),
        sa.Column('submitted_transfer_date', sa.String(10), nullable=False, server_default=''),
        sa.Column('file_name', sa.String(180), nullable=False),
        sa.Column('content_type', sa.String(80), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('file_data', sa.LargeBinary(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('review_note', sa.String(500), nullable=False, server_default=''),
        sa.Column('reviewed_by', sa.String(36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('business_id', sa.String(36), nullable=False),
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.UniqueConstraint('business_id', 'file_hash'),
    )
    op.create_index('ix_bank_transfers_business_id', 'bank_transfers', ['business_id'])
    op.create_index('ix_bank_transfers_user_id', 'bank_transfers', ['user_id'])


def downgrade():
    raise RuntimeError('Restore a reviewed backup instead of deleting payment evidence.')
