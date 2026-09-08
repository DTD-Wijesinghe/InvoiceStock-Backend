"""Initial PostgreSQL schema for InvoiceStock AI."""
from alembic import op
from pathlib import Path
revision = '0001'
down_revision = None


def upgrade():
    # Frozen baseline DDL; subsequent schema changes require a new migration.
    schema = Path(__file__).resolve().parents[3] / 'database' / 'schema.sql'
    op.get_bind().exec_driver_sql(schema.read_text(encoding='utf-8'))


def downgrade():
    raise RuntimeError('Destructive downgrade disabled. Restore a reviewed backup instead.')
