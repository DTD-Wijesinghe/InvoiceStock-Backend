from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app, hasher
from app.db import SessionLocal, User, Business


def admin_client():
    with SessionLocal.begin() as db:
        business=Business(name='Platform')
        db.add(business)
        db.flush()
        db.add(User(business_id=business.id,name='Admin',email='admin@test.local',password_hash=hasher.hash('AdminStrong123!'),role='platform_admin'))
    admin=TestClient(app)
    assert admin.post('/api/auth/login',json={'email':'admin@test.local','password':'AdminStrong123!'}).status_code==200
    return admin


def test_public_registration_cannot_choose_admin(client):
    assert client.get('/api/admin/overview').status_code==403
    assert client.post('/api/auth/register',json={'name':'Escalate','business_name':'Shop','email':'escalate@test.local','password':'StrongPass123!','confirm_password':'StrongPass123!','role':'platform_admin'}).status_code==422


def test_admin_separate_workspace_and_disable_revokes_sessions(client):
    uid=client.get('/api/me').json()['user']['id']
    admin=admin_client()
    assert admin.get('/api/me').json()['user']['role']=='platform_admin'
    assert admin.get('/api/admin/overview').status_code==200
    assert admin.get('/api/products').status_code==403
    assert admin.post('/api/admin/users/'+uid+'/access',json={'disabled':True,'reason':'Requested access review'}).status_code==200
    assert client.get('/api/me').status_code==401
    assert client.post('/api/auth/login',json={'email':'test@example.com','password':'StrongPass123!'}).status_code==403
    assert admin.post('/api/admin/users/'+uid+'/access',json={'disabled':False,'reason':'Access review complete'}).status_code==200
    assert client.get('/api/me').status_code==401
    assert client.post('/api/auth/login',json={'email':'test@example.com','password':'StrongPass123!'}).status_code==200
    assert len(admin.get('/api/admin/audit').json())==2


def test_logout_invalidates_copied_cookie(client):
    copy=TestClient(app)
    copy.cookies.update(client.cookies)
    assert copy.get('/api/me').status_code==200
    assert client.post('/api/auth/logout').status_code==200
    assert copy.get('/api/me').status_code==401


def test_language_persistence_and_about(client):
    assert client.post('/api/onboarding/language',json={'language':'si'}).status_code==200
    assert client.get('/api/onboarding').json()['language']=='si'
    assert client.post('/api/onboarding/language',json={'language':'ta'}).status_code==200
    assert client.get('/api/onboarding').json()['language']=='ta'
    assert client.post('/api/onboarding/language',json={'language':'xx'}).status_code==422
    info=client.get('/api/about').json()
    assert info['developer']=='D.T.D.Wijesinghe'
    assert info['version']=='0.2.0'
