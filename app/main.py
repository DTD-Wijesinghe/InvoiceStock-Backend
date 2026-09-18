from datetime import timedelta
from typing import Annotated
from collections import defaultdict, deque
from threading import Lock
import time
import hashlib
import hmac
import secrets
import smtplib
from decimal import Decimal
from email.message import EmailMessage
import jwt
from pwdlib import PasswordHash
from fastapi import FastAPI, Depends, HTTPException, Request, Response, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response as RawResponse
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import ValidationError
from .db import session, settings, User, Business, Product, Contact, Document, Expense, Movement, Audit, AgentRun, CustomerPayment, AuthSession, AccountState, PasswordReset, now
from .schemas import Register, Login, ForgotPassword, ResetPassword, EmailCodeInput, EmailOnlyInput, ProductInput, ContactInput, DocumentInput, Approval, Adjustment, Payment, ExpenseInput, BusinessInput, MemberInput, AgentInput
from .services import serialize, get, audit, once, document_view, document_summary, create_document, finalize, void_document, report, tenant_lock
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
    feature = request_feature(request.url.path)
    if feature and not can_access(user, feature):
        raise HTTPException(403, 'This feature is not enabled for your account. Ask your company administrator.')
    if not allowed_when_locked(request.url.path) and access_status(db, user)['blocked']:
        raise HTTPException(402, 'Your trial or subscription has expired. Renew in Billing to unlock your business workspace.')
    return user


Actor = Annotated[User, Depends(current_user)]

FEATURE_PATHS = {
    '/api/products': 'products', '/api/contacts': 'customers', '/api/documents': 'invoices',
    '/api/expenses': 'expenses', '/api/movements': 'inventory', '/api/reports': 'reports',
    '/api/agents': 'ai_assistant', '/api/notifications': 'notifications', '/api/backup': 'backups',
    '/api/feedback': 'feedback', '/api/settings': 'settings',
}

def request_feature(path):
    for prefix, feature in FEATURE_PATHS.items():
        if path == prefix or path.startswith(prefix + '/'):
            return feature
    return None

def is_company_admin(user):
    return user.role in ('owner', 'company_admin')

def can_access(user, feature):
    if feature == 'overview':
        return is_company_admin(user)
    return is_company_admin(user) or feature in (user.permissions or [])


def write(user, owner=False):
    if user.role == 'viewer' or (owner and not is_company_admin(user)):
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


def send_reset_email(recipient, code):
    if not (settings.smtp_host and settings.smtp_from):
        raise RuntimeError('Email delivery is not configured')
    message = EmailMessage()
    message['Subject'] = 'InvoiceStock password reset code'
    message['From'] = settings.smtp_from
    message['To'] = recipient
    message.set_content(f'Your InvoiceStock password reset code is {code}. It expires in 15 minutes. If you did not request this, ignore this email.')
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def send_verification_email(recipient, code):
    if not (settings.smtp_host and settings.smtp_from):
        raise RuntimeError('Email delivery is not configured')
    message = EmailMessage()
    message['Subject'] = 'Verify your InvoiceStock email'
    message['From'] = settings.smtp_from
    message['To'] = recipient
    message.set_content(f'Your InvoiceStock email verification code is {code}. It expires in 15 minutes. If you did not create this account, ignore this email.')
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def issue_email_code(db, user, purpose='email_verification'):
    code = f'{secrets.randbelow(1000000):06d}'
    db.add(PasswordReset(business_id=user.business_id, user_id=user.id, token_hash=hashlib.sha256(code.encode()).hexdigest(), expires_at=now() + timedelta(minutes=15), purpose=purpose))
    db.flush()
    return code


@app.get('/health')
def health(db: DB):
    db.execute(text('SELECT 1'))
    return {'status': 'ok', 'database': db.bind.dialect.name, 'demo_mode': settings.demo_mode}


@app.post('/api/auth/register')
def register(data: Register, response: Response, request: Request, db: DB, background: BackgroundTasks):
    throttle(request)
    email = data.email.lower().strip()
    if not (settings.smtp_host and settings.smtp_from):
        raise HTTPException(503, 'Email verification is not configured. The administrator must configure SMTP before registration.')
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, 'This email is already registered. Sign in or use Forgot password.')
    business = Business(name=data.business_name)
    db.add(business)
    db.flush()
    user = User(business_id=business.id, email=email, name=data.name, password_hash=hasher.hash(data.password), role='company_admin', permissions=[], email_verified=False)
    db.add(user)
    db.flush()
    code = issue_email_code(db, user)
    background.add_task(send_verification_email, email, code)
    subscription(db, user)
    notify(db, user, 'welcome', 'Your 30-day free trial starts now', 'Welcome! Take the optional tour and set up your first product. After your trial, the Business plan is LKR 3,500 per month.', 'Overview', 'success')
    return {'verification_required': True, 'email': email, 'message': 'Verification code sent. Enter it to activate your company administrator account.'}


@app.post('/api/auth/login')
def login(data: Login, response: Response, request: Request, db: DB, background: BackgroundTasks):
    throttle(request)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if not user or not hasher.verify(data.password, user.password_hash):
        raise HTTPException(401, 'Invalid email or password')
    if not user.email_verified:
        if settings.smtp_host and settings.smtp_from:
            code = issue_email_code(db, user)
            background.add_task(send_verification_email, user.email, code)
        raise HTTPException(403, 'Verify your email before signing in. Check your inbox for the six-digit code.')
    account = db.scalar(select(AccountState).where(AccountState.user_id == user.id))
    if account and account.disabled:
        raise HTTPException(403, 'This account is disabled. Contact the administrator.')
    return sign_in(response, user, db, data.remember_me)


@app.post('/api/auth/forgot-password')
def forgot_password(data: ForgotPassword, request: Request, db: DB, background: BackgroundTasks):
    throttle(request)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if user and settings.smtp_host and settings.smtp_from:
        code = f'{secrets.randbelow(1000000):06d}'
        reset = PasswordReset(business_id=user.business_id, user_id=user.id, token_hash=hashlib.sha256(code.encode()).hexdigest(), expires_at=now() + timedelta(minutes=15), purpose='password_reset')
        db.add(reset)
        db.flush()
        background.add_task(send_reset_email, user.email, code)
    return {'message': 'If that email belongs to an account, a password reset code has been sent.'}


@app.post('/api/auth/verify-email')
def verify_email(data: EmailCodeInput, response: Response, request: Request, db: DB):
    throttle(request)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if not user:
        raise HTTPException(400, 'Invalid or expired verification code')
    reset = db.scalar(select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.purpose == 'email_verification', PasswordReset.used_at.is_(None)).order_by(PasswordReset.created_at.desc()))
    if not reset or utc(reset.expires_at) <= now() or reset.attempts >= 5 or not hmac.compare_digest(reset.token_hash, hashlib.sha256(data.code.encode()).hexdigest()):
        if reset: reset.attempts += 1
        raise HTTPException(400, 'Invalid or expired verification code')
    reset.used_at = now()
    user.email_verified = True
    user.verified_at = now()
    return sign_in(response, user, db)


@app.post('/api/auth/resend-verification')
def resend_verification(data: EmailOnlyInput, request: Request, db: DB, background: BackgroundTasks):
    throttle(request)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if user and not user.email_verified and settings.smtp_host and settings.smtp_from:
        code = issue_email_code(db, user)
        background.add_task(send_verification_email, user.email, code)
    return {'message': 'If the account needs verification, a new code has been sent.'}


@app.post('/api/auth/reset-password')
def reset_password(data: ResetPassword, request: Request, db: DB):
    throttle(request)
    user = db.scalar(select(User).where(User.email == data.email.lower().strip()))
    if not user:
        raise HTTPException(400, 'Invalid or expired reset code')
    reset = db.scalar(select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.purpose == 'password_reset', PasswordReset.used_at.is_(None)).order_by(PasswordReset.created_at.desc()))
    if not reset or utc(reset.expires_at) <= now() or reset.attempts >= 5:
        raise HTTPException(400, 'Invalid or expired reset code')
    reset.attempts += 1
    if not hmac.compare_digest(reset.token_hash, hashlib.sha256(data.code.encode()).hexdigest()):
        raise HTTPException(400, 'Invalid or expired reset code')
    reset.used_at = now()
    user.password_hash = hasher.hash(data.password)
    for active in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
        db.delete(active)
    return {'message': 'Password changed. Please sign in again.'}


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


@app.get('/api/business/logo')
def business_logo(user: Actor, db: DB):
    business = db.get(Business, user.business_id)
    if not business or not business.logo_data:
        raise HTTPException(404, 'Company logo has not been uploaded')
    return RawResponse(content=business.logo_data, media_type=business.logo_content_type or 'image/png', headers={'Cache-Control': 'no-cache'})


@app.post('/api/business/logo')
def upload_business_logo(user: Actor, db: DB, file: UploadFile = File(...)):
    if not is_company_admin(user):
        raise HTTPException(403, 'Only a company administrator can change the logo')
    allowed = {'image/png', 'image/jpeg', 'image/webp', 'image/svg+xml'}
    if file.content_type not in allowed:
        raise HTTPException(415, 'Upload a PNG, JPG, WEBP, or SVG logo')
    content = file.file.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise HTTPException(413, 'Logo must be smaller than 1 MB')
    business = tenant_lock(db, user)
    business.logo_data = content
    business.logo_content_type = file.content_type
    audit(db, user, 'company_logo_updated', business.id, after={'content_type': file.content_type, 'size': len(content)})
    return {'ok': True}


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
    return [document_summary(d) for d in db.scalars(select(Document).where(Document.business_id == user.business_id).order_by(Document.created_at.desc()).limit(500))]


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
    for administrator in db.scalars(select(User).where(User.business_id == user.business_id, User.role.in_(['owner', 'company_admin']), User.id != user.id)):
        notify(db, administrator, 'payment-' + data.request_key, 'Customer payment received', f'LKR {data.amount} was recorded for {doc.number}. Review company receivables.', 'Reports', 'success')
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


@app.get('/api/company/performance')
def company_performance(user: Actor, db: DB):
    if not is_company_admin(user):
        raise HTTPException(403, 'Only a company administrator can view employee performance')
    invoices = list(db.scalars(select(Document).where(Document.business_id == user.business_id, Document.kind == 'invoice', Document.status == 'final')))
    expenses = list(db.scalars(select(Expense).where(Expense.business_id == user.business_id, Expense.voided == False)))
    audits = list(db.scalars(select(Audit).where(Audit.business_id == user.business_id).order_by(Audit.created_at.desc()).limit(5000)))
    employees = []
    for member in db.scalars(select(User).where(User.business_id == user.business_id).order_by(User.name)):
        rows = [a for a in audits if a.actor == member.id]
        sales = [a for a in rows if a.action == 'draft_created' and (a.after or {}).get('kind') == 'invoice']
        approved = [a for a in rows if a.action == 'document_approved' and (a.after or {}).get('kind') == 'invoice']
        payments = [a for a in rows if a.action == 'payment_recorded']
        payment_total = sum((Decimal(str((a.after or {}).get('paid', 0))) - Decimal(str((a.before or {}).get('paid', 0))) for a in payments), Decimal(0))
        employees.append({'id': member.id, 'name': member.name, 'email': member.email, 'email_verified': member.email_verified, 'role': member.role,
                          'sales_created': len(sales), 'invoices_approved': len(approved),
                          'payments_recorded': len(payments), 'payments_received': str(payment_total),
                          'activity_count': len(rows)})
    pending = [d for d in invoices if d.paid < d.total]
    return {'employees': employees, 'invoice_count': len(invoices),
            'pending_receivables': str(sum((d.total - d.paid for d in pending), Decimal(0))),
            'pending_invoice_count': len(pending),
            'payments_received': str(sum((d.paid for d in invoices), Decimal(0))),
            'expenses_total': str(sum((e.amount for e in expenses), Decimal(0)))}


@app.post('/api/members')
def new_member(data: MemberInput, user: Actor, db: DB, background: BackgroundTasks):
    write(user, True)
    if not (settings.smtp_host and settings.smtp_from):
        raise HTTPException(503, 'Email verification is not configured. Configure SMTP before creating employees.')
    email = data.email.lower().strip()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, 'This email is already registered')
    member = User(business_id=user.business_id, name=data.name, email=email, role=data.role, permissions=data.permissions, password_hash=hasher.hash(data.password))
    db.add(member)
    db.flush()
    code = issue_email_code(db, member)
    background.add_task(send_verification_email, member.email, code)
    audit(db, user, 'member_created', member.id, after=serialize(member))
    return {**serialize(member), 'message': 'Employee created. A verification code was sent to the employee email.'}


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
        for owner in db.scalars(select(User).where(User.business_id == user.business_id, User.role.in_(['owner', 'company_admin']))):
            notify(db, owner, 'agent-' + result['id'], 'An AI draft needs your review', 'The invoice agent prepared a draft. Review its customer, quantities and totals before approval.', 'Invoices')
    return result


install_routes(app, current_user, session, write)
install_admin_routes(app, current_user, session)

# Production uses one origin for the UI and API, keeping cookies first-party.
import os
from fastapi.staticfiles import StaticFiles
if os.environ.get('FRONTEND_DIST'):
    app.mount('/', StaticFiles(directory=os.environ['FRONTEND_DIST'], html=True), name='frontend')
