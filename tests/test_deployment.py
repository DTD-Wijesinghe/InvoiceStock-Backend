from pathlib import Path
import pytest
from app.deployment import database_url

def test_supabase_driver_tls_and_encoded_password():
    url=database_url('postgresql://postgres.example:p%40ss%23word@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres')
    assert url.drivername=='postgresql+psycopg'
    assert url.password=='p@ss#word'
    assert url.query['sslmode']=='require'
    assert url.port==5432
    assert 'p@ss' not in str(url)

def test_placeholder_database_password_rejected():
    with pytest.raises(ValueError,match='real database password'):
        database_url('postgresql://postgres.example:[YOUR-PASSWORD]@pooler.supabase.com:5432/postgres')

def test_migration_sql_is_inside_repository():
    from importlib.util import spec_from_file_location, module_from_spec
    from unittest.mock import patch, MagicMock
    versions=Path(__file__).resolve().parents[1]/'migrations/versions'
    ddl=[]
    for name in ('0001_initial.py','0002_saas.py','0004_admin_security.py'):
        # Resolve by revision prefix to allow descriptive filenames.
        path=next(versions.glob(name[:4]+'*.py'))
        spec=spec_from_file_location('migration_'+name[:4],path)
        module=module_from_spec(spec);spec.loader.exec_module(module)
        bind=MagicMock()
        bind.exec_driver_sql.side_effect=lambda value: ddl.append(value)
        with patch.object(module.op,'get_bind',return_value=bind),patch.object(module.op,'execute'):
            module.upgrade()
    assert len(ddl)==3
    assert 'CREATE TABLE businesses' in ddl[0]
    assert 'CREATE TABLE subscriptions' in ddl[1]
    assert 'CREATE TABLE auth_sessions' in ddl[2]
