"""One-time password reset codes."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'


def upgrade():
    op.create_table(
        'password_resets',
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('business_id', sa.String(36), nullable=False),
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_password_resets_business_id', 'password_resets', ['business_id'])
    op.create_index('ix_password_resets_user_id', 'password_resets', ['user_id'])


def downgrade():
    raise RuntimeError('Restore a reviewed backup instead of deleting password-reset records.')
