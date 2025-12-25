from ninja import Schema, Field
from datetime import datetime
import uuid
from typing import Optional

# ---------- USER SCHEMAS ----------
class UserSchema(Schema):
    id: int
    username: str
    email: str | None = None

# ---------- PARTNER SCHEMAS ----------
class CustomerCreateSchema(Schema):
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tin_number: str | None = None
    partner_type: str
   
class CustomerListSchema(Schema):
    id: uuid.UUID = Field(alias="partnerid")
    name: str
    email: str | None
    phone: str | None
    address: str | None
    partner_type: str
    tin_number: str

class CustomerDetailSchema(Schema):
    name: str
    email: str | None
    phone: str | None
    address: str | None
    tin_number: str | None 
    partner_type: str

class SupplierCreateSchema(Schema):
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tin_number: str | None = None
    partner_type: str
   
class SupplierListSchema(Schema):
    id: uuid.UUID = Field(alias="partnerid")
    name: str
    email: str | None
    phone: str | None
    address: str | None
    partner_type: str
    tin_number: str

class SupplierDetailSchema(Schema):
    name: str
    email: str | None
    phone: str | None
    address: str | None
    tin_number: str | None 
    partner_type: str
