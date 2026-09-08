"""Optional isolated SQLite preview. This is not the PostgreSQL deployment."""
import os
import secrets
from pathlib import Path
from datetime import timedelta
from decimal import Decimal

os.environ['DATABASE_URL']='sqlite:///demo_invoicestock.db'
os.environ['JWT_SECRET']=secrets.token_urlsafe(48)
os.environ['DEMO_MODE']='true'
from app.db import Base, engine, SessionLocal, Business, User, Product, Contact, Document, Expense, now
from app.main import hasher
from app.schemas import DocumentInput
from app.services import create_document, finalize
from sqlalchemy import select, inspect, text


def seed():
    Base.metadata.create_all(engine)
    # Additive upgrade of this isolated demo only; PostgreSQL uses Alembic.
    if 'language' not in {c['name'] for c in inspect(engine).get_columns('user_preferences')}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE user_preferences ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'en'"))
    with SessionLocal.begin() as db:
        if not db.scalar(select(User).where(User.email=='admin@demo.local')):
            platform=Business(name='Demo platform administration')
            db.add(platform);db.flush()
            db.add(User(business_id=platform.id,name='Demo Administrator',email='admin@demo.local',password_hash=hasher.hash('DemoAdmin123!'),role='platform_admin'))
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email=='demo@example.com')):
            return
        b=Business(name='Ceylon Corner',address='Colombo, Sri Lanka')
        db.add(b);db.flush()
        u=User(business_id=b.id,name='Demo Owner',email='demo@example.com',password_hash=hasher.hash('DemoOnly123!'),role='owner')
        db.add(u);db.flush()
        customer=Contact(business_id=b.id,kind='customer',name='Nimal',phone='077 000 0000')
        supplier=Contact(business_id=b.id,kind='supplier',name='Lanka Wholesale')
        db.add_all([customer,supplier]);db.flush()
        products=[]
        for sku,name,category,cost,price,stock,reorder in [
            ('TEA-001','Ceylon black tea · 200g','Beverages',420,650,28,10),
            ('RICE-001','Samba rice · 1kg','Pantry',185,240,60,15),
            ('SOAP-001','Coconut soap','Household',95,150,8,10),
            ('MILK-001','Fresh milk · 1L','Dairy',390,520,12,8),
            ('BISC-001','Cream crackers','Snacks',180,250,25,10),
            ('SUGAR-001','White sugar · 1kg','Pantry',220,280,6,10)]:
            p=Product(business_id=b.id,sku=sku,name=name,category=category,cost_price=Decimal(cost),sell_price=Decimal(price),stock=0,reorder_level=reorder)
            db.add(p);db.flush();products.append(p)
            po=create_document(db,u,DocumentInput(kind='purchase',contact_id=supplier.id,items=[{'product_id':p.id,'qty':str(stock+25)}],request_key='demo-opening-'+sku))
            finalize(db,u,po.id)
        for day in range(6,-1,-1):
            doc=create_document(db,u,DocumentInput(contact_id=customer.id,items=[{'product_id':products[day%6].id,'qty':str(3+day)},{'product_id':products[1].id,'qty':'2'}],request_key='demo-sale-'+str(day)))
            finalize(db,u,doc.id)
            doc.finalized_at=now()-timedelta(days=day)
            doc.created_at=doc.finalized_at
            doc.paid=doc.total if day%2==0 else Decimal(0)
        # Two low-stock examples with auditable adjustment entries.
        from app.db import Movement
        for p in [products[2],products[5]]:
            delta=Decimal(4)-p.stock
            p.stock=4
            db.add(Movement(business_id=b.id,product_id=p.id,qty=delta,reason='Demo opening correction'))
        db.add(Expense(business_id=b.id,category='Transport',amount=Decimal('1800'),date=str(now().date()),note='Sample delivery expense'))
    print('Isolated DEMO ready. Email: demo@example.com | Password: DemoOnly123!')


if __name__=='__main__':
    seed()
    import uvicorn
    uvicorn.run('app.main:app',host='127.0.0.1',port=8000)
