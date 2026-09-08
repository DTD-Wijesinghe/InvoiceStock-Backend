from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import patch
from decimal import Decimal
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import engine, SessionLocal, User
from app.services import money
from app.agents import settings


def key():
    return str(uuid4())


def product(c, sku='TEA-001', stock='10'):
    r = c.post('/api/products', json={'name':'Tea', 'sku':sku, 'cost_price':'100.00','sell_price':'150.15','reorder_level':'5'})
    assert r.status_code == 200, r.text
    p = r.json()
    if Decimal(stock):
        r = c.post(f'/api/products/{p["id"]}/adjust', json={'qty':stock,'reason':'Opening stock','approved':True,'request_key':key()})
        assert r.status_code == 200, r.text
    return p


def draft(c, p, qty='2', **extras):
    return c.post('/api/documents', json={'items':[{'product_id':p['id'],'qty':qty}], 'request_key':key(), **extras})


def stock(c, pid):
    return Decimal(next(p['stock'] for p in c.get('/api/products').json() if p['id']==pid))


def test_decimal_total_approve_and_retry(client):
    p = product(client)
    d = draft(client,p,discount='0.10').json()
    assert Decimal(d['total']) == Decimal('300.20')
    assert stock(client,p['id']) == 10
    for _ in range(2):
        r = client.post(f'/api/documents/{d["id"]}/approve',json={'approved':True})
        assert r.status_code == 200, r.text
    assert stock(client,p['id']) == 8
    assert len(client.get('/api/movements').json()) == 2


def test_transaction_rollback_on_insufficient_stock(client):
    first = product(client,'FIRST', '10')
    second = product(client,'SECOND', '1')
    r = client.post('/api/documents',json={'items':[{'product_id':first['id'],'qty':'3'},{'product_id':second['id'],'qty':'2'}],'request_key':key()})
    d = r.json()
    r = client.post(f'/api/documents/{d["id"]}/approve',json={'approved':True})
    assert r.status_code == 409
    assert stock(client,first['id']) == 10
    assert stock(client,second['id']) == 1
    assert client.get(f'/api/documents/{d["id"]}').json()['status'] == 'draft'


def test_tenant_isolation(client):
    p = product(client)
    other = TestClient(app)
    other.post('/api/auth/register',json={'name':'Other Owner','business_name':'Other Shop','email':'other@example.com','password':'StrongPass123!','confirm_password':'StrongPass123!'})
    assert other.get('/api/products').json() == []
    assert draft(other,p).status_code == 404
    assert other.post(f'/api/products/{p["id"]}/adjust',json={'qty':'2','reason':'Bad access','approved':True,'request_key':key()}).status_code == 404


def test_roles_and_approval_required(client):
    p = product(client)
    d = draft(client,p).json()
    assert client.post(f'/api/documents/{d["id"]}/approve',json={}).status_code == 422
    for role in ['staff','viewer']:
        r=client.post('/api/members',json={'name':role,'email':role+'@example.com','password':'StrongPass123!','role':role})
        assert r.status_code == 200, r.text
        member=TestClient(app)
        member.post('/api/auth/login',json={'email':role+'@example.com','password':'StrongPass123!'})
        assert member.post(f'/api/documents/{d["id"]}/approve',json={'approved':True}).status_code == 403
        assert draft(member,p).status_code == (200 if role=='staff' else 403)


def test_purchase_receiving_and_void(client):
    p=product(client,stock='0')
    supplier=client.post('/api/contacts',json={'kind':'supplier','name':'Tea Supplier'}).json()
    d=draft(client,p,'7',kind='purchase',contact_id=supplier['id']).json()
    for _ in range(2):
        assert client.post(f'/api/documents/{d["id"]}/approve',json={'approved':True}).status_code==200
    assert stock(client,p['id'])==7
    assert client.post(f'/api/documents/{d["id"]}/void',json={'approved':True}).status_code==200
    assert stock(client,p['id'])==0


def test_idempotency_payload_conflict(client):
    p=product(client)
    request_key=key()
    a=draft(client,p,request_key=request_key)
    b=draft(client,p,request_key=request_key)
    assert a.json()['id']==b.json()['id']
    assert draft(client,p,'3',request_key=request_key).status_code==409


def test_payment_retry_and_overpayment(client):
    p=product(client)
    d=draft(client,p).json()
    client.post(f'/api/documents/{d["id"]}/approve',json={'approved':True})
    payload={'amount':'100','approved':True,'request_key':key()}
    for _ in range(2):
        assert client.post(f'/api/documents/{d["id"]}/payments',json=payload).status_code==200
    assert Decimal(client.get(f'/api/documents/{d["id"]}').json()['paid'])==100
    assert client.post(f'/api/documents/{d["id"]}/payments',json={'amount':'1000','approved':True,'request_key':key()}).status_code==422
    assert client.post(f'/api/documents/{d["id"]}/void',json={'approved':True}).status_code==409


def test_agent_draft_and_hallucinations(client):
    p=product(client)
    client.post('/api/contacts',json={'kind':'customer','name':'Nimal'})
    payload={'agent_type':'operations','message':'Create a draft invoice for Nimal with 2 TEA-001','request_key':key()}
    response=client.post('/api/agents/run',json=payload)
    assert response.status_code==200,response.text
    assert response.json()['status']=='pending_approval'
    assert stock(client,p['id'])==10
    assert client.post('/api/agents/run',json=payload).json()['id']==response.json()['id']
    assert client.post('/api/agents/run',json={**payload,'message':'invoice for Nimal with 2 FAKE-SKU','request_key':key()}).status_code==422
    assert client.post('/api/agents/run',json={**payload,'message':'invoice for Nimal with 200 TEA-001','request_key':key()}).status_code==409


def test_provider_failure_fallback(client):
    product(client)
    client.post('/api/contacts',json={'kind':'customer','name':'Nimal'})
    with patch.object(settings,'ai_model','test-model'), patch('app.agents.model_proposal',side_effect=httpx.ReadTimeout('timeout')):
        r=client.post('/api/agents/run',json={'agent_type':'operations','message':'invoice for Nimal with 1 TEA-001','request_key':key()})
        assert r.status_code==200,r.text
        assert r.json()['result']['mode']=='provider_unavailable_local_fallback'


def test_model_proposal_validation_and_tenant_scope(client):
    p=product(client)
    customer=client.post('/api/contacts',json={'kind':'customer','name':'Nimal'}).json()
    payload={'agent_type':'operations','message':'Draft requested','request_key':key()}
    with patch.object(settings,'ai_model','test-model'), patch('app.agents.model_proposal',return_value={'contact_id':customer['id'],'items':[{'product_id':p['id'],'qty':'2'}]}):
        r=client.post('/api/agents/run',json=payload)
        assert r.status_code==200,r.text
        assert r.json()['result']['mode']=='model_assisted'
        assert stock(client,p['id'])==10
        assert client.post('/api/agents/run',json={**payload,'message':'Changed request'}).status_code==409
    with patch.object(settings,'ai_model','test-model'), patch('app.agents.model_proposal',return_value={'contact_id':customer['id'],'items':[{'product_id':p['id'],'qty':'-2'}]}):
        assert client.post('/api/agents/run',json={**payload,'request_key':key()}).status_code==422
    with patch.object(settings,'ai_model','test-model'), patch('app.agents.model_proposal',return_value={'contact_id':customer['id'],'items':[{'product_id':'invented-id','qty':'2'}]}):
        assert client.post('/api/agents/run',json={**payload,'request_key':key()}).status_code==409


def test_ambiguous_customer_and_negative_stock(client):
    p=product(client)
    for _ in range(2):
        client.post('/api/contacts',json={'kind':'customer','name':'Nimal'})
    assert client.post('/api/agents/run',json={'agent_type':'operations','message':'invoice for Nimal with 2 TEA-001','request_key':key()}).status_code==422
    assert client.post('/api/products/'+p['id']+'/adjust',json={'qty':'-20','reason':'Invalid adjustment','approved':True,'request_key':key()}).status_code==422
    assert stock(client,p['id'])==10


def test_inventory_finance_evidence(client):
    p=product(client,stock='2')
    inventory=client.post('/api/agents/run',json={'agent_type':'inventory','request_key':key()}).json()
    assert inventory['result']['recommendations'][0]['suggested_qty']=='8'
    d=draft(client,p,'1').json()
    client.post(f'/api/documents/{d["id"]}/approve',json={'approved':True})
    finance=client.post('/api/agents/run',json={'agent_type':'finance','request_key':key()}).json()
    assert Decimal(finance['result']['evidence']['gross_profit'])==Decimal('50.15')


def test_duplicate_line_stock_validation(client):
    p=product(client,stock='3')
    d=client.post('/api/documents',json={'items':[{'product_id':p['id'],'qty':'2'},{'product_id':p['id'],'qty':'2'}],'request_key':key()}).json()
    assert client.post(f'/api/documents/{d["id"]}/approve',json={'approved':True}).status_code==409
    assert stock(client,p['id'])==3


def test_money_rounding():
    assert money(Decimal('10.005'))==Decimal('10.01')


@pytest.mark.skipif(engine.dialect.name!='postgresql',reason='Requires real PostgreSQL row locks')
def test_postgres_concurrent_finalization(client):
    p=product(client,stock='3')
    ds=[draft(client,p,'2').json() for _ in range(2)]
    cookies=dict(client.cookies)
    def approve(d):
        c=TestClient(app)
        c.cookies.update(cookies)
        return c.post(f'/api/documents/{d["id"]}/approve',json={'approved':True}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(approve,ds))
    assert sorted(results)==[200,409]
    assert stock(client,p['id'])==1
