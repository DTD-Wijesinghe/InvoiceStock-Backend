"""Trial, billing, payment methods, notifications, feedback and backup records."""
from pathlib import Path
from alembic import op
revision = '0002'
down_revision = '0001'


def upgrade():
    schema = Path(__file__).resolve().parents[3] / 'database' / 'schema_v2.sql'
    op.get_bind().exec_driver_sql(schema.read_text(encoding='utf-8'))


def downgrade():
    raise RuntimeError('Restore a reviewed backup instead of dropping business data.')
