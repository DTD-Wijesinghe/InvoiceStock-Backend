from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


Money = Decimal


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, validate_default=True)


class Register(Input):
    name: str = Field(min_length=2, max_length=120)
    business_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)

    @model_validator(mode='after')
    def matching_passwords(self):
        if self.password != self.confirm_password:
            raise ValueError('Passwords do not match')
        return self


class Login(Input):
    email: str
    password: str
    remember_me: bool = False


class ProductInput(Input):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=150)
    barcode: str = Field(default='', max_length=100)
    category: str = Field(default='General', max_length=80)
    unit: str = Field(default='pcs', max_length=20)
    cost_price: Money = Field(default=0, ge=0, max_digits=14, decimal_places=2)
    sell_price: Money = Field(default=0, ge=0, max_digits=14, decimal_places=2)
    reorder_level: Decimal = Field(default=5, ge=0, max_digits=14, decimal_places=3)
    active: bool = True


class ContactInput(Input):
    kind: Literal['customer', 'supplier']
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default='', max_length=40)
    email: str = Field(default='', max_length=254)
    address: str = Field(default='', max_length=300)


class ItemInput(Input):
    product_id: str
    qty: Decimal = Field(gt=0, le=1000000, decimal_places=3)


class DocumentInput(Input):
    kind: Literal['invoice', 'purchase'] = 'invoice'
    contact_id: str | None = None
    items: list[ItemInput] = Field(min_length=1, max_length=100)
    discount: Money = Field(default=0, ge=0, max_digits=14, decimal_places=2)
    tax: Money = Field(default=0, ge=0, max_digits=14, decimal_places=2)
    note: str = Field(default='', max_length=1000)
    request_key: str = Field(min_length=8, max_length=100)


class Approval(Input):
    approved: Literal[True]


class Adjustment(Approval):
    qty: Decimal = Field(ge=-1000000, le=1000000, decimal_places=3)
    reason: str = Field(min_length=3, max_length=300)
    request_key: str = Field(min_length=8, max_length=100)


class Payment(Approval):
    amount: Money = Field(gt=0, max_digits=14, decimal_places=2)
    request_key: str = Field(min_length=8, max_length=100)
    method: Literal['cash', 'card', 'bank_transfer', 'cheque', 'mobile_wallet', 'other'] = 'cash'
    reference: str = Field(default='', max_length=100)


class ExpenseInput(Input):
    category: str = Field(min_length=1, max_length=80)
    amount: Money = Field(gt=0, max_digits=14, decimal_places=2)
    date: date
    note: str = Field(default='', max_length=500)
    document_reference: str = Field(default='', max_length=300)


class BusinessInput(Input):
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(default='', max_length=300)
    invoice_prefix: str = Field(default='INV', min_length=1, max_length=12, pattern=r'^[A-Za-z0-9-]+$')


class MemberInput(Input):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=10, max_length=128)
    role: Literal['staff', 'viewer']


class AgentInput(Input):
    agent_type: Literal['inventory', 'finance', 'operations']
    message: str = Field(default='', max_length=2000)
    request_key: str = Field(min_length=8, max_length=100)
