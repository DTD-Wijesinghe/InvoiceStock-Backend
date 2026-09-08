"""Subscriptions, verified hosted checkout, customer payment reporting and workspace support."""
import calendar
import hashlib
import hmac
import json
import math
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import (Business, User, Product, Contact, Document, DocumentItem, Movement, Expense, Audit, AgentRun,
                 Subscription, BillingOrder, CustomerPayment, Notification, Preference, Feedback, BackupRecord, settings, now)
from .schemas import Input
from .services import serialize, tenant_lock, get, audit


PRICE = Decimal('3500.00')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def next_month(value):
    year = value.year + (value.month == 12)
    month = value.month % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def subscription(db, user):
    sub = db.scalar(select(Subscription).where(Subscription.business_id == user.business_id))
    if not sub:
        b = tenant_lock(db, user)
        sub = db.scalar(select(Subscription).where(Subscription.business_id == user.business_id))
        if not sub:
            sub = Subscription(business_id=user.business_id, trial_ends_at=utc(b.created_at) + timedelta(days=30))
            db.add(sub)
            db.flush()
    return sub


def access_status(db, user):
    sub = subscription(db, user)
    trial_end = utc(sub.trial_ends_at)
    paid_end = utc(sub.paid_until)
    active_until = max(trial_end, paid_end or trial_end)
    state = 'suspended' if sub.suspended else 'active' if paid_end and paid_end > now() else 'trial' if trial_end > now() else 'expired'
    return {'state': state, 'blocked': state in ('expired', 'suspended'), 'price': str(PRICE), 'currency': 'LKR',
            'trial_ends_at': trial_end.isoformat(), 'paid_until': paid_end.isoformat() if paid_end else None,
            'days_remaining': max(0, math.ceil((active_until - now()).total_seconds() / 86400)),
            'gateway_configured': bool(settings.payhere_merchant_id and settings.payhere_merchant_secret),
            'sandbox': settings.payhere_sandbox}


def allowed_when_locked(path):
    return path == '/api/me' or path.startswith(('/api/billing', '/api/notifications', '/api/onboarding', '/api/help', '/api/feedback', '/api/backups', '/api/about', '/api/security'))


def notify(db, user, event_key, title, message, target='Overview', severity='info'):
    existing = db.scalar(select(Notification).where(Notification.business_id == user.business_id, Notification.user_id == user.id, Notification.event_key == event_key))
    if not existing:
        db.add(Notification(business_id=user.business_id, user_id=user.id, event_key=event_key, title=title, message=message, target=target, severity=severity))


def sync_notifications(db, user):
    tenant_lock(db, user)
    state = access_status(db, user)
    notify(db, user, 'welcome', 'Welcome to InvoiceStock', 'Your 30-day trial includes the business workspace. Take the optional tour to get started.', 'Overview')
    if state['blocked']:
        notify(db, user, 'access-' + state['state'], 'Your subscription needs attention', 'Business features are locked. The owner can renew for LKR 3,500 per month. Data export stays available.', 'Billing', 'warning')
    elif state['days_remaining'] <= 7:
        notify(db, user, 'renew-' + str(date.today()), 'Your access renews soon', f'{state["days_remaining"]} days remain. Visit Billing to keep your workspace available.', 'Billing', 'warning')
    if not state['blocked']:
        for p in db.scalars(select(Product).where(Product.business_id == user.business_id, Product.active == True, Product.stock <= Product.reorder_level).limit(30)):
            notify(db, user, f'stock-{p.id}-{date.today()}', f'Low stock: {p.name}', f'{p.stock} {p.unit} available; reorder level {p.reorder_level}. Review before placing a purchase.', 'Inventory', 'warning')
    db.flush()


def preference(db, user):
    pref = db.scalar(select(Preference).where(Preference.user_id == user.id, Preference.business_id == user.business_id))
    if not pref:
        tenant_lock(db, user)
        pref = db.scalar(select(Preference).where(Preference.user_id == user.id))
        if not pref:
            pref = Preference(business_id=user.business_id, user_id=user.id)
            db.add(pref)
            db.flush()
    return pref


class CheckoutInput(Input):
    request_key: str = Field(min_length=8, max_length=100)
    phone: str = Field(min_length=9, max_length=25, pattern=r'^\+?[0-9 ()-]+$')
    address: str = Field(min_length=4, max_length=200)
    city: str = Field(min_length=2, max_length=80)


class FeedbackInput(Input):
    category: Literal['suggestion', 'bug', 'question', 'compliment'] = 'suggestion'
    rating: int = Field(ge=1, le=5)
    message: str = Field(min_length=10, max_length=3000)


class HelpInput(Input):
    message: str = Field(min_length=1, max_length=1000)


class TourInput(Input):
    completed: bool


class LanguageInput(Input):
    language: Literal['en','si','ta']


class BackupStatusInput(Input):
    status: Literal['complete', 'failed']


HELP = [
    ('invoice sale sell', 'Create an invoice', 'Open Invoices → New invoice. Choose a customer and products, enter quantities, and create a draft. Review the exact totals. An owner must approve before stock is deducted.', 'Invoices'),
    ('stock inventory product barcode sku', 'Manage your stock', 'Add products with a unique SKU and prices. Products begin with zero stock. Use Inventory → Adjust for an opening quantity with a reason, or receive a purchase. Only owners approve stock changes.', 'Inventory'),
    ('purchase supplier receive reorder', 'Receive a purchase', 'Create a supplier in Suppliers, then create a purchase draft. Review its products and costs. Approve & receive adds stock. The inventory agent can suggest reorder quantities.', 'Purchases'),
    ('payment cash card bank cheque wallet balance', 'Record customer payments', 'Open a final invoice, enter the amount received, and choose cash, card, bank transfer, cheque, mobile wallet, or other. Add a receipt reference if useful. Reports separates counts and amounts by payment method. This records a payment; it does not charge a customer card.', 'Reports'),
    ('trial subscription renew price billing paid block', 'Your plan and trial', 'Every new business starts with 30 days free. After that, renew at LKR 3,500 per month in Billing. Business features are locked when access expires, while billing and data export remain available. Monthly renewals are manual; there are no automatic charges.', 'Billing'),
    ('backup restore export data', 'Keep a copy of your data', 'Open Backups to download your business JSON export. Daily encrypted PostgreSQL backups run through the deployment workflow once the hosting administrator configures its secrets. Restore to a separate test database first; restoring is an administrator operation.', 'Backups'),
    ('agent ai assistant draft', 'Use your assistants', 'Inventory and finance assistants show verified business evidence. The invoice assistant accepts commands like “Create a draft invoice for Nimal with 2 TEA-001”. Use real names and SKUs. All financial and stock approvals remain with the owner.', 'AI Assistant'),
    ('tour guide help start', 'Take a guided tour', 'Choose the Take a tour button here to walk through the main areas. You can skip the tour or replay it whenever you like.', 'Overview'),
    ('notification alert bell', 'Stay informed', 'The bell opens your notification inbox. It shows welcome, low stock, trial expiry, and billing updates. Open a notification to visit its screen; read status is saved for your account.', 'Notifications'),
    ('feedback problem bug contact', 'Share feedback', 'Open Feedback to send a suggestion, bug report, question, or compliment. Feedback is saved in your business workspace. External support email delivery is not connected.', 'Feedback'),
]


def md5(value):
    # Required by PayHere's published signature protocol, not for password hashing.
    return hashlib.md5(value.encode()).hexdigest().upper()


def verify_payment(db, form):
    if not settings.payhere_merchant_secret or not settings.payhere_merchant_id:
        raise HTTPException(503, 'Payment gateway is not configured')
    required = ['merchant_id', 'order_id', 'payment_id', 'payhere_amount', 'payhere_currency', 'status_code', 'md5sig']
    if any(not form.get(k) or len(form[k]) > 200 for k in required):
        raise HTTPException(400, 'Incomplete notification')
    signature = md5(''.join(form[k] for k in ['merchant_id', 'order_id', 'payhere_amount', 'payhere_currency', 'status_code']) + md5(settings.payhere_merchant_secret))
    if form['merchant_id'] != settings.payhere_merchant_id or not hmac.compare_digest(signature, form['md5sig'].upper()):
        raise HTTPException(400, 'Invalid payment signature')
    order = db.scalar(select(BillingOrder).where(BillingOrder.id == form['order_id']))
    if not order:
        raise HTTPException(404, 'Unknown billing order')
    owner = db.scalar(select(User).where(User.business_id == order.business_id, User.role == 'owner'))
    tenant_lock(db, owner)
    db.refresh(order, with_for_update=True)
    try:
        amount = Decimal(form['payhere_amount'])
        if not amount.is_finite() or amount != order.amount or form['payhere_currency'] != order.currency:
            raise HTTPException(400, 'Payment amount or currency does not match')
    except InvalidOperation:
        raise HTTPException(400, 'Invalid amount')
    status = form['status_code']
    if status not in ('2', '0', '-1', '-2', '-3'):
        raise HTTPException(400, 'Unknown payment status')
    sub = subscription(db, owner)
    if status == '-3':
        if order.payment_id and order.payment_id != form['payment_id']:
            raise HTTPException(400, 'Payment reference does not match')
        order.status = 'chargedback'
        sub.suspended = True
        notify(db, owner, 'chargeback-' + order.id, 'Payment disputed', 'Access is suspended following a verified chargeback. Contact the service administrator.', 'Billing', 'warning')
    elif status == '2' and order.status not in ('paid', 'chargedback'):
        if db.scalar(select(BillingOrder).where(BillingOrder.payment_id == form['payment_id'], BillingOrder.id != order.id)):
            raise HTTPException(409, 'Payment already belongs to another order')
        start = max(now(), utc(sub.trial_ends_at), utc(sub.paid_until) or now())
        sub.paid_until = next_month(start)
        order.status = 'paid'
        order.payment_id = form['payment_id']
        order.paid_at = now()
        order.access_until = sub.paid_until
        notify(db, owner, 'paid-' + order.id, 'Subscription payment confirmed', f'LKR 3,500 received. Access is paid through {sub.paid_until.date()}.', 'Billing', 'success')
        audit(db, owner, 'subscription_payment_verified', order.id, after={'amount': str(order.amount), 'access_until': sub.paid_until.isoformat()})
    elif order.status not in ('paid', 'chargedback'):
        order.status = {'0': 'pending', '-1': 'cancelled', '-2': 'failed'}[status]
    db.flush()
    return {'received': True}


def install_routes(app, auth, db_dependency, write):
    Actor = Annotated[User, Depends(auth)]
    DB = Annotated[Session, Depends(db_dependency)]

    @app.post('/api/internal/backup-status')
    def backup_status(data: BackupStatusInput, request: Request, db: DB):
        secret = settings.backup_webhook_secret
        if len(secret) < 32 or not hmac.compare_digest(request.headers.get('x-backup-key', ''), secret):
            raise HTTPException(403, 'Invalid backup reporting credential')
        for owner in db.scalars(select(User).where(User.role == 'owner')):
            tenant_lock(db, owner)
            day_start = now().replace(hour=0, minute=0, second=0, microsecond=0)
            prior = db.scalar(select(BackupRecord).where(BackupRecord.business_id == owner.business_id, BackupRecord.kind == 'scheduled', BackupRecord.created_at >= day_start, BackupRecord.status == data.status))
            if not prior:
                db.add(BackupRecord(business_id=owner.business_id, actor='backup-workflow', kind='scheduled', status=data.status))
                notify(db, owner, f'backup-{date.today()}-{data.status}', 'Daily backup ' + ('completed' if data.status == 'complete' else 'failed'),
                       'The external backup workflow reported ' + data.status + '. Review the workflow run and verify restore readiness.', 'Backups', 'success' if data.status == 'complete' else 'warning')
        return {'recorded': True}

    @app.get('/api/billing')
    def billing(user: Actor, db: DB):
        return {'subscription': access_status(db, user), 'orders': [serialize(o) for o in db.scalars(select(BillingOrder).where(BillingOrder.business_id == user.business_id).order_by(BillingOrder.created_at.desc()).limit(50))]}

    @app.post('/api/billing/checkout')
    def checkout(data: CheckoutInput, user: Actor, db: DB):
        write(user, True)
        if not settings.payhere_merchant_id or not settings.payhere_merchant_secret:
            raise HTTPException(503, 'Payments are not connected yet. The service administrator must configure PayHere.')
        if not settings.public_url.startswith('https://'):
            raise HTTPException(503, 'PayHere needs the deployed public HTTPS address for verified callbacks')
        tenant_lock(db, user)
        if subscription(db, user).suspended:
            raise HTTPException(403, 'Contact the service administrator to resolve the payment dispute')
        order = db.scalar(select(BillingOrder).where(BillingOrder.business_id == user.business_id, BillingOrder.request_key == data.request_key))
        if not order:
            order = BillingOrder(business_id=user.business_id, request_key=data.request_key)
            db.add(order)
            db.flush()
        if order.status == 'paid':
            raise HTTPException(409, 'This order is already paid')
        secret_hash = md5(settings.payhere_merchant_secret)
        amount = f'{order.amount:.2f}'
        fields = {'merchant_id': settings.payhere_merchant_id, 'order_id': order.id, 'amount': amount, 'currency': 'LKR',
                  'hash': md5(settings.payhere_merchant_id + order.id + amount + 'LKR' + secret_hash),
                  'return_url': settings.public_url + '/?billing=return', 'cancel_url': settings.public_url + '/?billing=cancel',
                  'notify_url': (settings.backend_public_url or settings.public_url) + '/api/billing/payhere/notify', 'items': 'InvoiceStock Business - one month',
                  'first_name': user.name.split()[0], 'last_name': ' '.join(user.name.split()[1:]) or user.name,
                  'email': user.email, 'phone': data.phone, 'address': data.address, 'city': data.city, 'country': 'Sri Lanka'}
        return {'action': 'https://sandbox.payhere.lk/pay/checkout' if settings.payhere_sandbox else 'https://www.payhere.lk/pay/checkout', 'fields': fields}

    @app.post('/api/billing/payhere/notify')
    async def webhook(request: Request, db: DB):
        body = await request.body()
        if len(body) > 16384:
            raise HTTPException(413, 'Notification too large')
        try:
            values = parse_qs(body.decode('utf-8'), strict_parsing=True, max_num_fields=50)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, 'Invalid notification encoding')
        if any(len(v) != 1 for v in values.values()):
            raise HTTPException(400, 'Duplicate fields')
        return verify_payment(db, {k: v[0] for k, v in values.items()})

    @app.get('/api/notifications')
    def notifications(user: Actor, db: DB):
        sync_notifications(db, user)
        return [serialize(n) for n in db.scalars(select(Notification).where(Notification.business_id == user.business_id, Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100))]

    @app.post('/api/notifications/{nid}/read')
    def mark_read(nid: str, user: Actor, db: DB):
        items = select(Notification).where(Notification.business_id == user.business_id, Notification.user_id == user.id)
        if nid != 'all':
            items = items.where(Notification.id == nid)
        for n in db.scalars(items):
            n.read_at = now()
        return {'ok': True}

    @app.get('/api/onboarding')
    def onboarding(user: Actor, db: DB):
        return serialize(preference(db, user))

    @app.post('/api/onboarding')
    def onboarding_done(data: TourInput, user: Actor, db: DB):
        p = preference(db, user)
        p.tour_completed = data.completed
        return serialize(p)

    @app.post('/api/onboarding/language')
    def language(data: LanguageInput, user: Actor, db: DB):
        p = preference(db, user)
        p.language = data.language
        return {'language': p.language}

    @app.get('/api/feedback')
    def feedback_list(user: Actor, db: DB):
        return [serialize(f) for f in db.scalars(select(Feedback).where(Feedback.business_id == user.business_id, Feedback.user_id == user.id).order_by(Feedback.created_at.desc()).limit(50))]

    @app.post('/api/feedback')
    def feedback_create(data: FeedbackInput, user: Actor, db: DB):
        count = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.user_id == user.id, Feedback.created_at >= now() - timedelta(days=1)))
        if count >= 10:
            raise HTTPException(429, 'Daily feedback limit reached')
        f = Feedback(business_id=user.business_id, user_id=user.id, **data.model_dump())
        db.add(f)
        db.flush()
        notify(db, user, 'feedback-' + f.id, 'Thank you for your feedback', 'Your feedback is saved. You can review it in Feedback.', 'Feedback', 'success')
        return serialize(f)

    @app.post('/api/help')
    def help_answer(data: HelpInput, user: Actor):
        words = set(data.message.lower().replace('?', '').split())
        ranked = sorted(HELP, key=lambda item: len(words & set(item[0].split())), reverse=True)
        best = ranked[0]
        if not (words & set(best[0].split())):
            return {'answer': 'I can guide you through invoices, stock, customer payments, reports, subscriptions, backups, and the AI agents. What would you like help with?', 'target': None, 'source': 'Product help guide'}
        return {'answer': best[2], 'target': best[3], 'source': 'Product help guide', 'title': best[1]}

    @app.get('/api/reports/payment-methods')
    def payment_methods(user: Actor, db: DB, start: date | None = None, end: date | None = None):
        if start and end and start > end:
            raise HTTPException(422, 'Start date must precede end date')
        q = select(CustomerPayment.method, func.count(), func.sum(CustomerPayment.amount)).where(CustomerPayment.business_id == user.business_id)
        if start:
            q = q.where(CustomerPayment.created_at >= datetime.combine(start, datetime.min.time(), timezone.utc))
        if end:
            q = q.where(CustomerPayment.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc))
        rows = db.execute(q.group_by(CustomerPayment.method)).all()
        total = sum((amount for _, _, amount in rows), Decimal(0))
        return {'total': str(total), 'methods': [{'method': method, 'count': count, 'amount': str(amount), 'share': str((amount / total * 100).quantize(Decimal('.1'))) if total else '0'} for method, count, amount in rows],
                'unclassified_legacy_paid': str(db.scalar(select(func.coalesce(func.sum(Document.paid), 0)).where(Document.business_id == user.business_id, Document.kind == 'invoice', Document.status == 'final')) - db.scalar(select(func.coalesce(func.sum(CustomerPayment.amount), 0)).where(CustomerPayment.business_id == user.business_id)))}

    @app.get('/api/backups')
    def backups(user: Actor, db: DB):
        write(user, True)
        return {'records': [serialize(b) for b in db.scalars(select(BackupRecord).where(BackupRecord.business_id == user.business_id).order_by(BackupRecord.created_at.desc()).limit(30))], 'daily_schedule': '01:00 UTC / 06:30 Sri Lanka', 'scheduler': 'External encrypted PostgreSQL workflow; requires administrator setup'}

    @app.get('/api/backups/export')
    def export(user: Actor, db: DB):
        write(user, True)
        tenant_lock(db, user)
        tables = [Product, Contact, Document, DocumentItem, Movement, Expense, CustomerPayment, Audit, AgentRun, Subscription, BillingOrder, Feedback]
        payload = {'format': 'invoicestock-business-export', 'version': 2, 'exported_at': now().isoformat(), 'business': serialize(db.get(Business, user.business_id)),
                   'tables': {model.__tablename__: [serialize(row) for row in db.scalars(select(model).where(model.business_id == user.business_id))] for model in tables}}
        db.add(BackupRecord(business_id=user.business_id, actor=user.id))
        audit(db, user, 'business_data_exported', user.business_id)
        return Response(json.dumps(payload, indent=2), media_type='application/json', headers={'Content-Disposition': f'attachment; filename="invoicestock-{date.today()}.json"'})
