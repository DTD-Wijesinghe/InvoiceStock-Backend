from datetime import timedelta
from typing import Annotated
from collections import defaultdict, deque
from threading import Lock
import time
import hashlib
import secrets
import jwt
from pwdlib import PasswordHash
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import ValidationError
from .db import session, settings, User, Business, Product, Contact, Document, Expense, Movement, Audit, AgentRun, CustomerPayment, AuthSession, AccountState, now
from .schemas import Register, Login, ProductInput, ContactInput, DocumentInput, Approval, Adjustment, Payment, ExpenseInput, BusinessInput, MemberInput, AgentInput
from .services import serialize, get, audit, once, document_view, create_document, finalize, void_document, report, tenant_lock
from .agents import run_agent
from .saas import access_status, allowed_when_locked, subscription, notify, install_routes, utc
from .admin import install_admin_routes


app = FastAPI(title='InvoiceStock AI', version='0.2.0', description='Tenant-scoped invoicing, inventory, and approval-based agents.', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin, 'http://127.0.0.1:5173'], allow_credentials=True,
                   allow_methods=['GET', 'POST', 'PUT'], allow_headers=['Content-Type', 'Authorization'])
DB = Annotated[Session, Depends(session)]
hasher = PasswordHash.recommended()
attempts = defaultdict(deque)
attempt_lock = Lock()


@app.middleware('http')
async def security_headers(request, call_next):
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH') and request.headers.get('origin') not in (None, settings.frontend_origin, 'http://127.0.0.1:5173'):
        return JSONResponse(status_code=403, content={'detail': 'Origin not allowed'})
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://sandbox.payhere.lk https://www.payhere.lk"
    if settings.frontend_origin.startswith('https://'):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


@app.exception_handler(IntegrityError)
async def integrity_handler(request, exc):
    return JSONResponse(status_code=409, content={'detail': 'Duplicate record or database constraint conflict'})


@app.exception_handler(ValidationError)
async def proposal_validation_handler(request, exc):
    return JSONResponse(status_code=422, content={'detail': 'The proposed data failed validation. Check the requested items and quantities.'})


def current_user(request: Request, db: DB):
    token = request.cookies.get('session')
    if not token:
        raise HTTPException(401, 'Please sign in')
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=['HS256'], options={'require': ['exp', 'sub', 'jti']})
        user = db.get(User, claims['sub'])
    except jwt.InvalidTokenError:
        raise HTTPException(401, 'Session expired; sign in again')
    if not user:
        raise HTTPException(401, 'Account not found')
    active = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash == hashlib.sha256(claims['jti'].encode()).hexdigest()))
    if not active or utc(active.expires_at) <= now():
        raise HTTPException(401, 'Session revoked. Please sign in again.')
    request.state.session_id = active.id
    account = db.scalar(select(AccountState).where(AccountState.user_id == user.id))
    if account and account.disabled:
        raise HTTPException(403, 'This account is disabled. Contact the administrator.')
    if user.role == 'platform_admin':
        if request.url.path == '/api/me' or request.url.path.startswith(('/api/admin', '/api/about', '/api/security')):
            return user
        raise HTTPException(403, 'Use the platform administration workspace')
    if not allowed_when_locked(request.url.path) and access_status(db, user)['blocked']:
        raise HTTPException(402, 'Your trial or subscription has expired. Renew in Billing to unlock your business workspace.')
    return user


Actor = Annotated[User, Depends(current_user)]


def write(user, owner=False):
    if user.role == 'viewer' or (owner and user.role != 'owner'):
        raise HTTPException(403, 'Owner approval required' if owner else 'Read-only account')


def throttle(request):
    address = request.client.host if request.client else 'local'
    with attempt_lock:
        hits = attempts[address]
        cutoff = time.monotonic() - 60
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= 15:
            raise HTTPException(429, 'Too many attempts. Try again in a minute.')
        hits.append(time.monotonic())


def sign_in(response, user, db, remember=False):
    lifetime = 2592000 if remember else 28800
    jti = secrets.token_urlsafe(32)
    expires_at = now() + timedelta(seconds=lifetime)
    db.add(AuthSession(business_id=user.business_id, user_id=user.id, token_hash=hashlib.sha256(jti.encode()).hexdigest(), expires_at=expires_at))
    db.flush()
    token = jwt.encode({'sub': user.id, 'exp': expires_at, 'jti': jti}, settings.jwt_secret, algorithm='HS256')
    response.set_cookie('session', token, httponly=True, samesite='lax', secure=settings.frontend_origin.startswith('https'), max_age=lifetime if remember else None)
    return serialize(user)


@app.get('/health')
def health(db: DB):
    db.execute(text('SELECT 1'))
    return {'status': 'ok', 'database': db.bind.dialect.name, 'demo_mode': settings.demo_mode}


@app.post('/api/auth/register')
def register(data: Register, response: Response, request: Request, db: DB):
    throttle(request)
    business = Business(name=data.business_name)
    db.add(business)
    db.flush()
    user = User(business_id=business.id, email=data.email.lower(), name=data.name, password_hash=hasher.hash(data.password), role='owner')
    db.add(user)
    db.flush()
    subscription(db, user)
    notify(db, user, 'welcome', 'Your 30-day free trial starts now', 'Welcome! Take the optional tour and set up your first product. After your trial, the Business plan is LKR 3,500 per month.', 'Overview', 'success')
    return sign_in(response, user, db)


@app.post('/api/auth/login')
def login(data: Login, response: Response, request: Request, db: DB):
    throttle(request)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if not user or not hasher.verify(data.password, user.password_hash):
        raise HTTPException(401, 'Invalid email or password')
    account = db.scalar(select(AccountState).where(AccountState.user_id == user.id))
    if account and account.disabled:
        raise HTTPException(403, 'This account is disabled. Contact the administrator.')
    return sign_in(response, user, db, data.remember_me)


@app.post('/api/auth/logout')
def logout(response: Response, request: Request, db: DB):
    try:
        claims = jwt.decode(request.cookies.get('session', ''), settings.jwt_secret, algorithms=['HS256'])
        active = db.scalar(select(AuthSession).where(AuthSession.token_hash == hashlib.sha256(claims.get('jti', '').encode()).hexdigest()))
        if active: db.delete(active)
    except jwt.InvalidTokenError:
        pass
    response.delete_cookie('session')
    return {'ok': True}


@app.get('/api/me')
def me(user: Actor, db: DB):
    return {'user': serialize(user), 'business': serialize(db.get(Business, user.business_id)), 'ai_model_configured': bool(settings.ai_model), 'demo_mode': settings.demo_mode, 'subscription': None if user.role == 'platform_admin' else access_status(db, user)}


@app.get('/api/products')
def products(user: Actor, db: DB):
    return [serialize(p) for p in db.scalars(select(Product).where(Product.business_id == user.business_id).order_by(Product.name))]


@app.post('/api/products')
def new_product(data: ProductInput, user: Actor, db: DB):
    write(user)
    p = Product(business_id=user.business_id, **data.model_dump())
    db.add(p)
    db.flush()
    audit(db, user, 'product_created', p.id, after=serialize(p))
    return serialize(p)


@app.put('/api/products/{pid}')
def edit_product(pid: str, data: ProductInput, user: Actor, db: DB):
    write(user)
    tenant_lock(db, user)
    p = get(db, Product, pid, user, True)
    before = serialize(p)
    for key, value in data.model_dump().items():
        setattr(p, key, value)
    audit(db, user, 'product_updated', p.id, before, serialize(p))
    return serialize(p)


@app.post('/api/products/{pid}/adjust')
def adjust(pid: str, data: Adjustment, user: Actor, db: DB):
    write(user, True)
    if not once(db, user, data.request_key, {'action': 'adjust', 'id': pid, **data.model_dump()}):
        return serialize(get(db, Product, pid, user))
    p = get(db, Product, pid, user, True)
    if data.qty == 0 or p.stock + data.qty < 0:
        raise HTTPException(422, 'Adjustment must be nonzero and cannot create negative stock')
    before = serialize(p)
    p.stock += data.qty
    db.add(Movement(business_id=user.business_id, product_id=p.id, qty=data.qty, reason=data.reason, reference_id=data.request_key))
    audit(db, user, 'stock_adjusted', p.id, before, serialize(p))
    return serialize(p)


@app.get('/api/movements')
def movements(user: Actor, db: DB):
    return [serialize(m) for m in db.scalars(select(Movement).where(Movement.business_id == user.business_id).order_by(Movement.created_at.desc()).limit(500))]


@app.get('/api/contacts')
def contacts(user: Actor, db: DB):
    return [serialize(c) for c in db.scalars(select(Contact).where(Contact.business_id == user.business_id).order_by(Contact.name))]


@app.post('/api/contacts')
def new_contact(data: ContactInput, user: Actor, db: DB):
    write(user)
    contact = Contact(business_id=user.business_id, **data.model_dump())
    db.add(contact)
    db.flush()
    audit(db, user, 'contact_created', contact.id, after=serialize(contact))
    return serialize(contact)


@app.put('/api/contacts/{cid}')
def edit_contact(cid: str, data: ContactInput, user: Actor, db: DB):
    write(user)
    c = get(db, Contact, cid, user, True)
    if data.kind != c.kind:
        raise HTTPException(422, 'Contact type cannot change')
    before = serialize(c)
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    audit(db, user, 'contact_updated', c.id, before, serialize(c))
    return serialize(c)


@app.get('/api/documents')
def documents(user: Actor, db: DB):
    return [serialize(d) for d in db.scalars(select(Document).where(Document.business_id == user.business_id).order_by(Document.created_at.desc()).limit(500))]


@app.post('/api/documents')
def draft(data: DocumentInput, user: Actor, db: DB):
    write(user)
    return document_view(db, create_document(db, user, data))


@app.get('/api/documents/{did}')
def detail(did: str, user: Actor, db: DB):
    return document_view(db, get(db, Document, did, user))


@app.post('/api/documents/{did}/approve')
def approve(did: str, data: Approval, user: Actor, db: DB):
    write(user, True)
    doc = finalize(db, user, did)
    for run in db.scalars(select(AgentRun).where(AgentRun.business_id == user.business_id, AgentRun.status == 'pending_approval')):
        if run.result.get('document', {}).get('id') == did:
            run.status = 'approved'
    return document_view(db, doc)


@app.post('/api/documents/{did}/void')
def void(did: str, data: Approval, user: Actor, db: DB):
    write(user, True)
    return document_view(db, void_document(db, user, did))


@app.post('/api/documents/{did}/payments')
def payment(did: str, data: Payment, user: Actor, db: DB):
    write(user, True)
    if not once(db, user, data.request_key, {'action': 'payment', 'id': did, **data.model_dump()}):
        return serialize(get(db, Document, did, user))
    doc = get(db, Document, did, user, True)
    if doc.status != 'final' or doc.kind != 'invoice':
        raise HTTPException(409, 'Only final invoices accept payments')
    if doc.paid + data.amount > doc.total:
        raise HTTPException(422, 'Payment exceeds outstanding balance')
    before = serialize(doc)
    doc.paid += data.amount
    db.add(CustomerPayment(business_id=user.business_id, document_id=doc.id, amount=data.amount, method=data.method, reference=data.reference, actor=user.id))
    notify(db, user, 'payment-' + data.request_key, 'Customer payment recorded', f'LKR {data.amount} received by {data.method.replace("_", " ")} for {doc.number}.', 'Invoices', 'success')
    audit(db, user, 'payment_recorded', doc.id, before, serialize(doc))
    return serialize(doc)


@app.get('/api/expenses')
def expenses(user: Actor, db: DB):
    return [serialize(e) for e in db.scalars(select(Expense).where(Expense.business_id == user.business_id).order_by(Expense.date.desc()))]


@app.post('/api/expenses')
def new_expense(data: ExpenseInput, user: Actor, db: DB):
    write(user, True)
    e = Expense(business_id=user.business_id, **{**data.model_dump(), 'date': str(data.date)})
    db.add(e)
    db.flush()
    audit(db, user, 'expense_created', e.id, after=serialize(e))
    return serialize(e)


@app.post('/api/expenses/{eid}/void')
def void_expense(eid: str, data: Approval, user: Actor, db: DB):
    write(user, True)
    e = get(db, Expense, eid, user, True)
    before = serialize(e)
    e.voided = True
    audit(db, user, 'expense_voided', e.id, before, serialize(e))
    return serialize(e)


@app.get('/api/reports')
def reports(user: Actor, db: DB):
    return report(db, user)


@app.put('/api/settings')
def edit_settings(data: BusinessInput, user: Actor, db: DB):
    write(user, True)
    b = tenant_lock(db, user)
    before = serialize(b)
    for k, v in data.model_dump().items():
        setattr(b, k, v)
    audit(db, user, 'settings_updated', b.id, before, serialize(b))
    return serialize(b)


@app.get('/api/members')
def members(user: Actor, db: DB):
    write(user, True)
    return [serialize(u) for u in db.scalars(select(User).where(User.business_id == user.business_id))]


@app.post('/api/members')
def new_member(data: MemberInput, user: Actor, db: DB):
    write(user, True)
    member = User(business_id=user.business_id, name=data.name, email=data.email.lower(), role=data.role, password_hash=hasher.hash(data.password))
    db.add(member)
    db.flush()
    audit(db, user, 'member_created', member.id, after=serialize(member))
    return serialize(member)


@app.get('/api/audit')
def logs(user: Actor, db: DB):
    write(user, True)
    return [serialize(a) for a in db.scalars(select(Audit).where(Audit.business_id == user.business_id).order_by(Audit.created_at.desc()).limit(200))]


@app.get('/api/agents/runs')
def runs(user: Actor, db: DB):
    return [serialize(r) for r in db.scalars(select(AgentRun).where(AgentRun.business_id == user.business_id).order_by(AgentRun.created_at.desc()).limit(50))]


@app.post('/api/agents/run')
def agent(data: AgentInput, user: Actor, db: DB):
    write(user)
    result = run_agent(db, user, data)
    if result['status'] == 'pending_approval':
        for owner in db.scalars(select(User).where(User.business_id == user.business_id, User.role == 'owner')):
            notify(db, owner, 'agent-' + result['id'], 'An AI draft needs your review', 'The invoice agent prepared a draft. Review its customer, quantities and totals before approval.', 'Invoices')
    return result


install_routes(app, current_user, session, write)
install_admin_routes(app, current_user, session)

# Production uses one origin for the UI and API, keeping cookies first-party.
import os
from fastapi.staticfiles import StaticFiles
if os.environ.get('FRONTEND_DIST'):
    app.mount('/', StaticFiles(directory=os.environ['FRONTEND_DIST'], html=True), name='frontend')
