import hashlib
import json
from datetime import timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, func
from .db import Business, Product, Contact, Document, DocumentItem, Movement, Audit, ActionKey, Expense, now


def money(value):
    return Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def serialize(obj):
    return {c.name: (str(v) if isinstance(v, Decimal) else v.isoformat() if hasattr(v, 'isoformat') else v)
            for c in obj.__table__.columns if c.name != 'password_hash' for v in [getattr(obj, c.name)]}


def get(db, model, entity_id, user, lock=False):
    q = select(model).where(model.id == entity_id, model.business_id == user.business_id)
    result = db.scalar(q.with_for_update() if lock else q)
    if not result:
        raise HTTPException(404, 'Record not found')
    return result


def audit(db, user, action, entity_id, before=None, after=None):
    db.add(Audit(business_id=user.business_id, actor=user.id, action=action, entity_id=entity_id,
                 before=before or {}, after=after or {}))


def tenant_lock(db, user):
    return db.scalar(select(Business).where(Business.id == user.business_id).with_for_update())


def once(db, user, key, payload):
    tenant_lock(db, user)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    prior = db.scalar(select(ActionKey).where(ActionKey.business_id == user.business_id, ActionKey.key == key))
    if prior:
        if prior.fingerprint != digest:
            raise HTTPException(409, 'Request key was already used for a different action')
        return False
    db.add(ActionKey(business_id=user.business_id, key=key, fingerprint=digest))
    db.flush()
    return True


def document_view(db, doc):
    result = serialize(doc)
    result['items'] = [serialize(i) for i in db.scalars(select(DocumentItem).where(DocumentItem.document_id == doc.id))]
    return result


def create_document(db, user, data):
    if not once(db, user, data.request_key, {'action': 'draft', **data.model_dump()}):
        return db.scalar(select(Document).where(Document.business_id == user.business_id, Document.request_key == data.request_key))
    if data.contact_id:
        contact = get(db, Contact, data.contact_id, user)
        if contact.kind != ('customer' if data.kind == 'invoice' else 'supplier'):
            raise HTTPException(422, 'Wrong contact type')
    if data.kind == 'purchase' and not data.contact_id:
        raise HTTPException(422, 'Select a supplier')
    quantities = {}
    for item in data.items:
        quantities[item.product_id] = quantities.get(item.product_id, Decimal(0)) + item.qty
    lines = []
    for pid, qty in sorted(quantities.items()):
        p = get(db, Product, pid, user)
        if not p.active:
            raise HTTPException(409, f'{p.name} is inactive')
        price = p.sell_price if data.kind == 'invoice' else p.cost_price
        lines.append(dict(product_id=p.id, name=p.name, qty=qty, unit_price=price, cost_snapshot=p.cost_price, line_total=money(qty * price)))
    subtotal = sum((x['line_total'] for x in lines), Decimal(0))
    if data.discount > subtotal:
        raise HTTPException(422, 'Discount cannot exceed subtotal')
    doc = Document(business_id=user.business_id, kind=data.kind, contact_id=data.contact_id,
                   request_key=data.request_key, subtotal=subtotal, discount=data.discount,
                   tax=data.tax, total=money(subtotal - data.discount + data.tax), note=data.note)
    db.add(doc)
    db.flush()
    db.add_all([DocumentItem(business_id=user.business_id, document_id=doc.id, **line) for line in lines])
    audit(db, user, 'draft_created', doc.id, after=serialize(doc))
    db.flush()
    return doc


def finalize(db, user, doc_id):
    business = tenant_lock(db, user)
    doc = get(db, Document, doc_id, user, True)
    if doc.status in ('final', 'received'):
        return doc
    if doc.status != 'draft':
        raise HTTPException(409, 'Only a draft can be finalized')
    before = serialize(doc)
    items = list(db.scalars(select(DocumentItem).where(DocumentItem.document_id == doc.id).order_by(DocumentItem.product_id)))
    for item in items:
        p = get(db, Product, item.product_id, user, True)
        if not p.active:
            raise HTTPException(409, f'{p.name} is inactive')
        change = -item.qty if doc.kind == 'invoice' else item.qty
        if p.stock + change < 0:
            raise HTTPException(409, f'Insufficient stock for {p.name}: available {p.stock}')
        previous = serialize(p)
        if doc.kind == 'invoice':
            item.cost_snapshot = p.cost_price
        else:
            p.cost_price = money((p.stock * p.cost_price + item.qty * item.unit_price) / (p.stock + item.qty))
        p.stock += change
        db.add(Movement(business_id=user.business_id, product_id=p.id, qty=change, reason=doc.kind, reference_id=doc.id))
        audit(db, user, 'stock_' + doc.kind, p.id, previous, serialize(p))
    doc.number = f'{business.invoice_prefix if doc.kind == "invoice" else "PO"}-{business.next_invoice:06d}'
    business.next_invoice += 1
    doc.status = 'final' if doc.kind == 'invoice' else 'received'
    doc.finalized_at = now()
    audit(db, user, 'document_approved', doc.id, before, serialize(doc))
    db.flush()
    return doc


def void_document(db, user, doc_id):
    tenant_lock(db, user)
    doc = get(db, Document, doc_id, user, True)
    if doc.status == 'void':
        return doc
    before = serialize(doc)
    if doc.paid > 0:
        raise HTTPException(409, 'Paid invoices require a separate refund workflow; automatic refund is not supported')
    if doc.status in ('final', 'received'):
        for item in db.scalars(select(DocumentItem).where(DocumentItem.document_id == doc.id).order_by(DocumentItem.product_id)):
            p = get(db, Product, item.product_id, user, True)
            delta = item.qty if doc.kind == 'invoice' else -item.qty
            if p.stock + delta < 0:
                raise HTTPException(409, 'Cannot reverse purchase: stock has already been sold')
            previous = serialize(p)
            remaining = p.stock + delta
            if doc.kind == 'invoice':
                p.cost_price = money((p.stock * p.cost_price + item.qty * item.cost_snapshot) / remaining)
            elif remaining > 0:
                value = p.stock * p.cost_price - item.qty * item.unit_price
                if value < 0:
                    raise HTTPException(409, 'Cannot reverse this purchase without a manual valuation review')
                p.cost_price = money(value / remaining)
            p.stock += delta
            db.add(Movement(business_id=user.business_id, product_id=p.id, qty=delta, reason='void ' + doc.kind, reference_id=doc.id))
            audit(db, user, 'stock_reversed', p.id, previous, serialize(p))
    doc.status = 'void'
    audit(db, user, 'document_voided', doc.id, before, serialize(doc))
    db.flush()
    return doc


def report(db, user):
    bid = user.business_id
    invoices = list(db.scalars(select(Document).where(Document.business_id == bid, Document.kind == 'invoice', Document.status == 'final')))
    expenses = list(db.scalars(select(Expense).where(Expense.business_id == bid, Expense.voided == False)))
    products = list(db.scalars(select(Product).where(Product.business_id == bid)))
    today = now().astimezone(ZoneInfo('Asia/Colombo')).date()
    recent_start = today - timedelta(days=6)
    prior_start = today - timedelta(days=13)
    date_of = lambda d: (d.finalized_at if d.finalized_at.tzinfo else d.finalized_at.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo('Asia/Colombo')).date()
    revenue = sum((d.subtotal - d.discount for d in invoices), Decimal(0))
    cost = db.scalar(select(func.coalesce(func.sum(DocumentItem.qty * DocumentItem.cost_snapshot), 0)).join(Document, Document.id == DocumentItem.document_id).where(Document.business_id == bid, Document.kind == 'invoice', Document.status == 'final'))
    recent = sum((d.total for d in invoices if date_of(d) >= recent_start), Decimal(0))
    prior = sum((d.total for d in invoices if prior_start <= date_of(d) < recent_start), Decimal(0))
    expense_total = sum((e.amount for e in expenses), Decimal(0))
    sales = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        sales.append({'date': str(day), 'total': str(sum((d.total for d in invoices if date_of(d) == day), Decimal(0)))})
    leaders = db.execute(select(Product.name, func.sum(DocumentItem.qty), func.sum(DocumentItem.line_total)).join(DocumentItem, Product.id == DocumentItem.product_id).join(Document, Document.id == DocumentItem.document_id).where(Document.business_id == bid, Document.kind == 'invoice', Document.status == 'final').group_by(Product.id).order_by(func.sum(DocumentItem.line_total).desc()).limit(10)).all()
    return {'revenue': str(money(revenue)), 'gross_profit': str(money(revenue - cost)), 'expenses': str(money(expense_total)),
            'net_estimate': str(money(revenue - cost - expense_total)), 'today_sales': str(sum((d.total for d in invoices if date_of(d) == today), Decimal(0))),
            'receivables': str(sum((d.total - d.paid for d in invoices), Decimal(0))),
            'stock_value': str(money(sum((p.stock * p.cost_price for p in products), Decimal(0)))),
            'low_stock': [serialize(p) for p in products if p.active and p.stock <= p.reorder_level],
            'recent_week': str(recent), 'previous_week': str(prior),
            'change_percent': str(money((recent - prior) / prior * 100)) if prior else None,
            'daily_sales': sales, 'top_products': [{'name': n, 'qty': str(q), 'sales': str(t)} for n, q, t in leaders],
            'invoice_count': len(invoices), 'product_count': len(products)}
