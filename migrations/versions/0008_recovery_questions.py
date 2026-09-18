"""Hashed recovery questions for password recovery without SMS or SMTP."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'


def upgrade():
    for name in ('recovery_question_1', 'recovery_question_2', 'recovery_question_3'):
        op.add_column('users', sa.Column(name, sa.String(40), nullable=False, server_default=''))
    for name in ('recovery_answer_1_hash', 'recovery_answer_2_hash', 'recovery_answer_3_hash'):
        op.add_column('users', sa.Column(name, sa.String(300), nullable=False, server_default=''))


def downgrade():
    raise RuntimeError('Restore a reviewed backup instead of deleting recovery-question data.')
