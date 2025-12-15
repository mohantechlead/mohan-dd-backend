from ninja import Schema, Field
from datetime import datetime
import uuid


# ---------- USER SCHEMAS ----------
class UserSchema(Schema):
    id: int
    username: str
    email: str | None = None

# ---------- PARTNER SCHEMAS ----------
class PartnerIn(Schema):
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tin_number: str | None = None
    partner_type: str

class PartnerListSchema(Schema):
    id: uuid.UUID = Field(alias="partnerid")
    name: str
    email: str | None
    phone: str | None
    address: str | None
    partner_type: str

class PartnerDetailSchema(Schema):
    id: uuid.UUID = Field(alias="partnerid")
    name: str
    email: str | None
    phone: str | None
    address: str | None
    tin_number: str | None 
    partner_type: str
    created_at: datetime
    updated_at: datetime
