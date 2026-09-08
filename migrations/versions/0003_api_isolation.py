"""Deny Supabase Data API roles direct access; application connects server-side."""
from alembic import op
revision = '0003'
down_revision = '0002'
TABLES = ('businesses', 'users', 'products', 'contacts', 'documents', 'document_items', 'inventory_movements', 'expenses', 'audit_logs', 'agent_runs', 'action_keys', 'subscriptions', 'billing_orders', 'customer_payments', 'notifications', 'user_preferences', 'feedback', 'backup_records')


def upgrade():
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        for role in ('anon', 'authenticated'):
            op.execute(f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN REVOKE ALL ON TABLE \"{table}\" FROM {role}; END IF; END $$;")


def downgrade():
    raise RuntimeError('Review Data API permissions manually before changing isolation.')
