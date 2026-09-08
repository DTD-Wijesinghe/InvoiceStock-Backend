from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from sqlalchemy import create_engine, String, Numeric, ForeignKey, UniqueConstraint, JSON, DateTime, Boolean, Integer, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Settings(BaseSettings):
    database_url: str = 'postgresql+psycopg://invoicestock:change-me@127.0.0.1:55432/invoicestock'
    jwt_secret: str = Field(min_length=32)
    demo_mode: bool = False
    frontend_origin: str = 'http://localhost:5173'
    ai_base_url: str = 'http://127.0.0.1:11434/v1'
    ai_api_key: str = ''
    ai_model: str = ''
    public_url: str = 'http://localhost:5173'
    payhere_merchant_id: str = ''
    payhere_merchant_secret: str = ''
    payhere_sandbox: bool = True
    backup_last_success: str = ''
    backup_webhook_secret: str = ''
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Tenant(Identity):
    business_id: Mapped[str] = mapped_column(ForeignKey('businesses.id'), index=True)


class Business(Identity, Base):
    __tablename__ = 'businesses'
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default='LKR')
    timezone: Mapped[str] = mapped_column(String(60), default='Asia/Colombo')
    invoice_prefix: Mapped[str] = mapped_column(String(12), default='INV')
    address: Mapped[str] = mapped_column(String(300), default='')
    next_invoice: Mapped[int] = mapped_column(Integer, default=1)


class User(Tenant, Base):
    __tablename__ = 'users'
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default='owner')


class Product(Tenant, Base):
    __tablename__ = 'products'
    __table_args__ = (UniqueConstraint('business_id', 'sku'), CheckConstraint('stock >= 0'), CheckConstraint('cost_price >= 0 AND sell_price >= 0'))
    sku: Mapped[str] = mapped_column(String(60))
    barcode: Mapped[str] = mapped_column(String(100), default='')
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(80), default='General')
    unit: Mapped[str] = mapped_column(String(20), default='pcs')
    cost_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sell_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=5)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Contact(Tenant, Base):
    __tablename__ = 'contacts'
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40), default='')
    email: Mapped[str] = mapped_column(String(254), default='')
    address: Mapped[str] = mapped_column(String(300), default='')


class Document(Tenant, Base):
    __tablename__ = 'documents'
    __table_args__ = (UniqueConstraint('business_id', 'number'), UniqueConstraint('business_id', 'request_key'))
    kind: Mapped[str] = mapped_column(String(20))
    contact_id: Mapped[str | None] = mapped_column(ForeignKey('contacts.id'))
    number: Mapped[str | None] = mapped_column(String(40))
    request_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default='draft')
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    note: Mapped[str] = mapped_column(String(1000), default='')
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentItem(Tenant, Base):
    __tablename__ = 'document_items'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'))
    name: Mapped[str] = mapped_column(String(150))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cost_snapshot: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class Movement(Tenant, Base):
    __tablename__ = 'inventory_movements'
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'), index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    reason: Mapped[str] = mapped_column(String(300))
    reference_id: Mapped[str] = mapped_column(String(100), default='')


class Expense(Tenant, Base):
    __tablename__ = 'expenses'
    category: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    date: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(String(500), default='')
    document_reference: Mapped[str] = mapped_column(String(300), default='')
    voided: Mapped[bool] = mapped_column(Boolean, default=False)


class Audit(Tenant, Base):
    __tablename__ = 'audit_logs'
    actor: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(100))
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentRun(Tenant, Base):
    __tablename__ = 'agent_runs'
    agent_type: Mapped[str] = mapped_column(String(30))
    request_key: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint('business_id', 'request_key'),)
    status: Mapped[str] = mapped_column(String(30), default='complete')
    result: Mapped[dict] = mapped_column(JSON)


class ActionKey(Tenant, Base):
    __tablename__ = 'action_keys'
    __table_args__ = (UniqueConstraint('business_id', 'key'),)
    key: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[str] = mapped_column(String(64))


class Subscription(Tenant, Base):
    __tablename__ = 'subscriptions'
    __table_args__ = (UniqueConstraint('business_id'),)
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)


class BillingOrder(Tenant, Base):
    __tablename__ = 'billing_orders'
    __table_args__ = (UniqueConstraint('business_id', 'request_key'),)
    request_key: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=3500)
    currency: Mapped[str] = mapped_column(String(3), default='LKR')
    status: Mapped[str] = mapped_column(String(30), default='pending')
    payment_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerPayment(Tenant, Base):
    __tablename__ = 'customer_payments'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    method: Mapped[str] = mapped_column(String(30))
    reference: Mapped[str] = mapped_column(String(100), default='')
    actor: Mapped[str] = mapped_column(String(36))


class Notification(Tenant, Base):
    __tablename__ = 'notifications'
    __table_args__ = (UniqueConstraint('business_id', 'user_id', 'event_key'),)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    event_key: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(150))
    message: Mapped[str] = mapped_column(String(600))
    severity: Mapped[str] = mapped_column(String(20), default='info')
    target: Mapped[str] = mapped_column(String(40), default='Overview')
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Preference(Tenant, Base):
    __tablename__ = 'user_preferences'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True)
    tour_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(5), default='en', server_default='en')


class Feedback(Tenant, Base):
    __tablename__ = 'feedback'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    category: Mapped[str] = mapped_column(String(30))
    rating: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(3000))
    status: Mapped[str] = mapped_column(String(30), default='received')


class BackupRecord(Tenant, Base):
    __tablename__ = 'backup_records'
    actor: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(30), default='manual_export')
    status: Mapped[str] = mapped_column(String(30), default='complete')


class AuthSession(Tenant, Base):
    __tablename__ = 'auth_sessions'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountState(Tenant, Base):
    __tablename__ = 'account_states'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


def session():
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
