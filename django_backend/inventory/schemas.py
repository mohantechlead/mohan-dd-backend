from ninja import Schema
from typing import List, Optional
import uuid
from datetime import date

# Item schema sent from React
class GrnItemCreateSchema(Schema):
    item_name: str
    quantity: int
    unit_measurement: str
    bags: str
    internal_code: str
   

# Main GRN creation schema
class GrnCreateSchema(Schema):
    supplier_name: str
    grn_no: str
    plate_no: str
    purchase_no: str
    date: date
    ECD_no: str
    transporter_name: str
    storekeeper_name: str 
    items: List[GrnItemCreateSchema]

# Response schema
class GrnItemSchema(Schema):
    item_id: uuid.UUID
    item_name: str
    quantity: int
    

class GrnDetailSchema(Schema):
    id: uuid.UUID
    supplier_name: str
    grn_no: str
    plate_no: str
    purchase_no: str
    items: List[GrnItemSchema]

class GRNListSchema(Schema):
    supplier_name: str
    grn_no: str
    purchase_no: str
    items: List[GrnItemSchema]

#double
class GRNDetailSchema(Schema):
    supplier_name: str
    grn_no: str
    plate_no: str
    purchase_no: str
    items: List[GrnItemSchema]

# DN Schemas

class DnItemCreateSchema(Schema):
    item_name: str
    quantity: int
    unit_measurement: str
    internal_code: str
    bags: float

# Main DN creation schema
class DnCreateSchema(Schema):
    customer_name: str
    dn_no: str
    plate_no: str
    sales_no: str
    date: date
    ECD_no: str
    invoice_no: str
    gatepass_no: str
    despathcher_name: str
    receiver_name: str
    receiver_phone: str
    authorized_by: str
    items: List[DnItemCreateSchema]

# Response schema
class DnItemSchema(Schema):
    item_name: str
    quantity: int
    
class DnDetailSchema(Schema):
    customer_name: str
    dn_no: str
    sales_no: str
    items: Optional[List[DnItemSchema]] = []

class ItemCreateSchema(Schema):
    item_name: str
    hscode: str
    internal_code: str

class ItemSchema(Schema):
    item_name: str
    hscode: str
    internal_code: str
    
class StockSchema(Schema):
    item_name: str
    hscode: Optional[str]
    internal_code: Optional[str]
    quantity: Optional[float]
    unit_measurement: Optional[str]
    package: Optional[float]
 
