import os
from pathlib import Path
import pytest

# SQLite is only a fast test backend. PostgreSQL suite: set TEST_DATABASE_URL.
os.environ['DATABASE_URL'] = os.environ.get('TEST_DATABASE_URL', 'sqlite:///test_invoicestock.db')
os.environ['JWT_SECRET'] = 'test-only-secret-not-for-production-1234567890123456789'
from app.db import Base, engine
from app.main import app, attempts
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_database():
    if not (engine.url.database.endswith('test') or engine.url.database == 'test_invoicestock.db'):
        raise RuntimeError('Refusing to clear a non-test database')
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    attempts.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        r = c.post('/api/auth/register', json={'name':'Test Owner','business_name':'Test Shop','email':'test@example.com','password':'StrongPass123!','confirm_password':'StrongPass123!'})
        assert r.status_code == 200, r.text
        yield c
