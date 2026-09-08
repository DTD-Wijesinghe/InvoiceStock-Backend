from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db import SessionLocal, Subscription, BillingOrder, settings, now
from app.main import app
from app.saas import md5, next_month
from .test_workflows import product, draft, stock


def expire(client):
    bid=client.get('/api/me').json()['user']['business_id']
    with SessionLocal.begin() as db:
        s=db.scalar(select(Subscription).where(Subscription.business_id==bid))
        s.trial_ends_at=now()-timedelta(days=1)
    return bid


def checkout(client):
    return client.post('/api/billing/checkout',json={'phone':'0771234567','address':'12 Test Road','city':'Colombo','request_key':str(uuid4())})


def notification(order,status='2',amount='3500.00',payment_id='pay-001'):
    f={'merchant_id':'merchant-test','order_id':order,'payment_id':payment_id,'payhere_amount':amount,'payhere_currency':'LKR','status_code':status}
    f['md5sig']=md5(''.join(f[k] for k in ['merchant_id','order_id','payhere_amount','payhere_currency','status_code'])+md5('merchant-secret-test'))
    return f


def test_password_confirmation_required_and_must_match():
    c=TestClient(app)
    data={'name':'Owner','business_name':'New Business','email':'new@example.com','password':'StrongPass123!'}
    assert c.post('/api/auth/register',json=data).status_code==422
    assert c.post('/api/auth/register',json={**data,'confirm_password':'Different123!'}).status_code==422
    assert c.post('/api/auth/register',json={**data,'confirm_password':data['password']}).status_code==200
    assert c.get('/api/me').json()['subscription']['days_remaining']==30


def test_remember_me_cookie(client):
    r=client.post('/api/auth/login',json={'email':'test@example.com','password':'StrongPass123!','remember_me':True})
    assert 'Max-Age=2592000' in r.headers['set-cookie']
    assert 'HttpOnly' in r.headers['set-cookie']
    r=client.post('/api/auth/login',json={'email':'test@example.com','password':'StrongPass123!','remember_me':False})
    assert 'Max-Age=' not in r.headers['set-cookie']


def test_expired_trial_blocks_reads_and_writes_but_keeps_billing_and_export(client):
    product(client)
    expire(client)
    assert client.get('/api/me').json()['subscription']['blocked'] is True
    assert client.get('/api/products').status_code==402
    assert client.post('/api/products',json={'name':'Blocked','sku':'BLOCK'}).status_code==402
    assert client.post('/api/agents/run',json={'agent_type':'inventory','request_key':str(uuid4())}).status_code==402
    assert client.get('/api/billing').status_code==200
    assert client.get('/api/backups/export').status_code==200
    assert client.get('/api/notifications').status_code==200


def test_checkout_unconfigured_is_not_fake_success(client):
    with patch.object(settings,'payhere_merchant_id',''),patch.object(settings,'payhere_merchant_secret',''):
        assert checkout(client).status_code==503


def test_verified_payment_activates_once_and_wrong_amount_rejected(client):
    expire(client)
    with patch.object(settings,'payhere_merchant_id','merchant-test'),patch.object(settings,'payhere_merchant_secret','merchant-secret-test'),patch.object(settings,'public_url','https://shop.example.com'):
        r=checkout(client)
        assert r.status_code==200,r.text
        assert r.json()['fields']['amount']=='3500.00'
        assert 'merchant-secret-test' not in r.text
        order=r.json()['fields']['order_id']
        wrong=notification(order,amount='1.00')
        assert client.post('/api/billing/payhere/notify',data=wrong).status_code==400
        assert client.get('/api/me').json()['subscription']['blocked'] is True
        valid=notification(order)
        assert client.post('/api/billing/payhere/notify',data=valid).status_code==200
        until=client.get('/api/me').json()['subscription']['paid_until']
        assert client.get('/api/products').status_code==200
        assert client.post('/api/billing/payhere/notify',data=valid).status_code==200
        assert client.get('/api/me').json()['subscription']['paid_until']==until
        assert client.post('/api/billing/payhere/notify',data=notification(order,status='-3')).status_code==200
        assert client.get('/api/products').status_code==402
        assert client.post('/api/billing/payhere/notify',data=valid).status_code==200
        assert client.get('/api/me').json()['subscription']['state']=='suspended'


def test_forged_callback_and_return_url_do_not_unlock(client):
    expire(client)
    with patch.object(settings,'payhere_merchant_id','merchant-test'),patch.object(settings,'payhere_merchant_secret','merchant-secret-test'),patch.object(settings,'public_url','https://shop.example.com'):
        order=checkout(client).json()['fields']['order_id']
        data=notification(order)
        data['md5sig']='FAKE'
        assert client.post('/api/billing/payhere/notify',data=data).status_code==400
        client.get('/?billing=return')
        assert client.get('/api/me').json()['subscription']['blocked'] is True


def test_payment_methods_reports_and_retry(client):
    p=product(client)
    d=draft(client,p).json()
    client.post('/api/documents/'+d['id']+'/approve',json={'approved':True})
    cash={'amount':'100.00','method':'cash','approved':True,'request_key':str(uuid4())}
    for _ in range(2):
        assert client.post('/api/documents/'+d['id']+'/payments',json=cash).status_code==200
    card={'amount':'150.00','method':'card','reference':'RECEIPT-1','approved':True,'request_key':str(uuid4())}
    assert client.post('/api/documents/'+d['id']+'/payments',json=card).status_code==200
    r=client.get('/api/reports/payment-methods').json()
    assert Decimal(r['total'])==250
    methods={m['method']:m for m in r['methods']}
    assert methods['cash']['count']==1
    assert Decimal(methods['card']['share'])==60
    assert Decimal(r['unclassified_legacy_paid'])==0
    assert client.get('/api/reports/payment-methods?start=2026-12-01&end=2026-01-01').status_code==422


def test_notification_read_status_is_per_account(client):
    product(client,stock='2')
    a=client.get('/api/notifications').json()
    b=client.get('/api/notifications').json()
    assert len(a)==len(b)
    assert any('Low stock' in n['title'] for n in a)
    client.post('/api/notifications/all/read')
    assert all(n['read_at'] for n in client.get('/api/notifications').json())
    client.post('/api/members',json={'name':'Viewer','email':'viewer@example.com','password':'StrongPass123!','role':'viewer'})
    other=TestClient(app)
    other.post('/api/auth/login',json={'email':'viewer@example.com','password':'StrongPass123!'})
    rows=other.get('/api/notifications').json()
    assert any(not n['read_at'] for n in rows)
    other.post('/api/notifications/'+a[0]['id']+'/read')
    assert all(n['user_id']!=a[0]['user_id'] for n in rows)


def test_feedback_onboarding_and_help(client):
    assert client.get('/api/onboarding').json()['tour_completed'] is False
    assert client.post('/api/onboarding',json={'completed':True}).json()['tour_completed'] is True
    f=client.post('/api/feedback',json={'category':'suggestion','rating':5,'message':'Please add receipt templates.'})
    assert f.status_code==200,f.text
    assert len(client.get('/api/feedback').json())==1
    h=client.post('/api/help',json={'message':'How do I record a card payment?'}).json()
    assert h['target']=='Reports'
    assert 'does not charge' in h['answer']


def test_export_excludes_credentials_and_other_tenants(client):
    p=product(client)
    result=client.get('/api/backups/export')
    assert result.status_code==200
    assert 'attachment;' in result.headers['content-disposition']
    data=result.json()
    assert data['tables']['products'][0]['id']==p['id']
    assert 'password_hash' not in result.text
    assert 'jwt_secret' not in result.text
    assert len(client.get('/api/backups').json()['records'])==1


def test_backup_reporting_requires_secret(client):
    assert client.post('/api/internal/backup-status',json={'status':'complete'}).status_code==403
    with patch.object(settings,'backup_webhook_secret','x'*48):
        for _ in range(2):
            assert client.post('/api/internal/backup-status',json={'status':'complete'},headers={'x-backup-key':'x'*48}).status_code==200
    rows=client.get('/api/backups').json()['records']
    assert len(rows)==1
    assert rows[0]['kind']=='scheduled'


def test_month_end_renewal():
    from datetime import datetime, timezone
    assert next_month(datetime(2026,1,31,tzinfo=timezone.utc)).day==28
