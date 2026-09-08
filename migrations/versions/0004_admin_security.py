"""Revocable login sessions, managed account access, and user language."""
from alembic import op
from pathlib import Path
revision='0004'
down_revision='0003'

def upgrade():
    op.execute("ALTER TABLE user_preferences ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'en'")
    schema=Path(__file__).resolve().parents[1]/'sql'/'schema_v3.sql'
    op.get_bind().exec_driver_sql(schema.read_text(encoding='utf-8'))
    for table in ('auth_sessions','account_states'):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        for role in ('anon','authenticated'):
            op.execute(f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='{role}') THEN REVOKE ALL ON TABLE \"{table}\" FROM {role}; END IF; END $$;")

def downgrade():raise RuntimeError('Review a backup restore instead of deleting security records.')
