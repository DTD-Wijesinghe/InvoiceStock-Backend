"""Add email verification for company admins and employees."""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'

def upgrade():
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=True, server_default=sa.true()))
    op.add_column('users', sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET email_verified = TRUE WHERE email_verified IS NULL")
    op.add_column('password_resets', sa.Column('purpose', sa.String(30), nullable=False, server_default='password_reset'))

def downgrade():
    raise RuntimeError('Restore a reviewed backup instead of deleting email verification history.')
